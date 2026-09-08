"""Receipt pipeline on the Frappe side (docs/ARCHITECTURE.md §5.3) and question answering (§5.7).

``process_receipt(document_name)`` runs on the ``long`` queue after the Telegram handler
stored the photo as a ``Nyabo Document``. It is the one place where the model's output
(extraction, classification) meets the deterministic parts (regime, rules, posting
patterns, validation) and ends as a ``Nyabo Proposal`` plus a card. The model proposes;
nothing here inserts an accounting document - that is ``agent.post.post_proposal`` after
a tap.

Rules bridge: ``nyabo_mn.rules`` (regime, patterns, guard) is built by another agent in
parallel. Where ARCHITECTURE names the exact call (``rules.regime.posting_context``,
``rules.guard.require_verified`` / ``UnverifiedRuleError``) this module uses it when it
is importable and otherwise falls back to the seed-backed implementation below, which
reads the same DocTypes (``Nyabo Company Settings.regimes``, ``Nyabo Posting Pattern``,
``Nyabo Tax Parameter``) and the same seed JSON. The fallback is not a second rule set:
it is the core engine (``nyabo_mn.core.rules_engine``) fed from the DocType rows.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Any

from nyabo_mn.agent import classify, extract, frappe_log
from nyabo_mn.agent.llm_client import CallRecord, LlmClient, get_client
from nyabo_mn.core import rules_engine
from nyabo_mn.core.models import (
	Citation,
	ProposedEntry,
	Receipt,
	ReceiptVerification,
	RegimeContext,
	SellerInfo,
)
from nyabo_mn.core.money import ZERO, fmt_mnt, quantize
from nyabo_mn.core.quarantine import find_injection
from nyabo_mn.core.validate import validate_entry
from nyabo_mn.i18n import mn
from nyabo_mn.nyabo.seed import load_seed

logger = logging.getLogger("nyabo.agent")

LOW_CONFIDENCE = 0.7
CONFIDENCE_FIELDS = ("total", "date", "vat_amount")
RULE_ORDER = ("supplier_register_no", "supplier_name_pattern", "description_pattern", "amount_band")
FAMILY_EXPENSE = "purchase_expense"
FAMILY_INVENTORY = "purchase_inventory"
FAMILY_FIXED_ASSET = "fixed_asset_acquire"
STOCK_ACCOUNT_TYPES = frozenset({"Stock"})
FIXED_ASSET_ACCOUNT_TYPES = frozenset({"Fixed Asset", "Capital Work in Progress"})
EXPLANATION_MAX = 300
VAT_RATE_KEY = "vat.rate"
FAQ_PATHS = ("config/faq.mn.md", "nyabo/seed/faq.mn.md")

CardSender = Callable[[str], None]


# --- errors ----------------------------------------------------------------------------------


class PipelineError(RuntimeError):
	"""A receipt that cannot become a proposal; ``message_mn`` goes to the sender."""

	def __init__(self, message: str, message_mn: str):
		super().__init__(message)
		self.message_mn = message_mn


try:  # ARCHITECTURE §1.2 names this class; use the real one once nyabo_mn.rules lands.
	from nyabo_mn.rules.guard import UnverifiedRuleError  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only before the rules package exists

	class UnverifiedRuleError(rules_engine.RuleError):  # type: ignore[no-redef]
		"""A Posting Pattern (or other rule) with ``verified = 0`` was about to reach ``insert()``."""


# --- small helpers ---------------------------------------------------------------------------


def _json_default(value: Any) -> Any:
	if isinstance(value, Decimal):
		return str(value)
	if isinstance(value, (dt.date, dt.datetime)):
		return value.isoformat()
	if hasattr(value, "to_dict"):
		return value.to_dict()
	return str(value)


def dumps(value: Any) -> str:
	return json.dumps(value, ensure_ascii=False, default=_json_default)


def loads(value: Any) -> Any:
	if value in (None, ""):
		return None
	if isinstance(value, (dict, list)):
		return value
	return json.loads(value)


def _today(now: dt.datetime | None) -> dt.date:
	"""The site's business date, not UTC's.

	A receipt with no readable date is posted "today", and today in Ulaanbaatar (UTC+8) is
	already tomorrow's date for eight hours of every UTC day: taking the UTC date would post
	a night-time receipt into the previous day - and, on the 1st of a month, into a period
	the accountant may already have closed. ``frappe.utils.today`` is the site's own clock;
	an explicit ``now`` (the caller's, and the tests') still wins.
	"""
	if now is not None:
		return now.date()
	try:
		import frappe

		return dt.date.fromisoformat(str(frappe.utils.today()))
	except Exception:  # noqa: BLE001 - no site (pure-Python callers): fall back to the local clock
		return dt.datetime.now().date()


def _simulation() -> bool:
	import frappe

	try:
		return bool(frappe.flags.get("nyabo_simulation"))
	except Exception:  # noqa: BLE001
		return False


def write_event(
	event_type: str,
	*,
	company: str | None = None,
	ref_doctype: str | None = None,
	ref_name: str | None = None,
	reason: str | None = None,
	payload: Mapping[str, Any] | None = None,
	actor_user: str | None = None,
	actor_telegram_id: str | None = None,
) -> str | None:
	"""Append a ``Nyabo Event``; failures are logged, never raised (audit must not break flows)."""
	import frappe

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Nyabo Event",
				"event_type": event_type,
				"company": company,
				"actor_user": actor_user or frappe.session.user,
				"actor_telegram_id": actor_telegram_id,
				"ref_doctype": ref_doctype,
				"ref_name": ref_name,
				"reason": (reason or "")[:1000] or None,
				"payload_json": dumps(dict(payload)) if payload else None,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc.name
	except Exception as exc:  # noqa: BLE001
		logger.exception("could not write Nyabo Event %s", event_type)
		try:
			from nyabo_mn.log import log_error

			log_error("event.write_failed", exc, event_type=event_type)
		except Exception:  # noqa: BLE001
			pass
		return None


def company_settings(company: str) -> Any | None:
	import frappe

	name = frappe.db.get_value("Nyabo Company Settings", {"company": company}, "name")
	return frappe.get_doc("Nyabo Company Settings", name) if name else None


# --- regime and tax parameters (bridge to nyabo_mn.rules) ---------------------------------------


def regime_context(company: str, on_date: dt.date) -> RegimeContext:
	"""``rules.regime.posting_context`` when available, else the settings' regime table through core."""
	try:
		from nyabo_mn.rules import regime as rules_regime  # type: ignore[import-not-found]
	except ImportError:
		rules_regime = None
	if rules_regime is not None and hasattr(rules_regime, "posting_context"):
		return rules_regime.posting_context(company, on_date)
	settings = company_settings(company)
	history = []
	for row in (settings.get("regimes") if settings else None) or []:
		history.append((row.regime, row.effective_from, row.effective_to))
	return rules_engine.regime_on(history, on_date)


def tax_parameter_rows() -> list[rules_engine.ParameterRow]:
	"""DocType rows when the seed has been synced, else the seed file itself."""
	import frappe

	rows: list[rules_engine.ParameterRow] = []
	if _has_rows("Nyabo Tax Parameter"):
		for row in frappe.get_all(
			"Nyabo Tax Parameter",
			fields=["key", "value_json", "unit", "effective_from", "effective_to", "status", "verified"],
		):
			data = dict(row)
			data["value"] = loads(data.pop("value_json", None))
			rows.append(rules_engine.ParameterRow.from_dict(data))
	if rows:
		return rows
	return [rules_engine.ParameterRow.from_dict(r) for r in load_seed("tax_parameters")["rows"]]


def tax_parameter(key: str, on_date: dt.date, *, allow_unverified: bool = False) -> rules_engine.ParameterRow:
	"""The dated tax-parameter row through ``rules.params`` (which applies ``rules.guard``).

	WHY the bridge and not ``rules_engine.parameter_decimal`` on our own rows (F-09): the
	engine resolves the date but knows nothing about ``verified``, so a rate an admin has
	not checked would silently size the VAT of a proposal that a tap then posts. ``params.get``
	is the one guarded lookup (§1.2); its only bypass is ``frappe.flags.nyabo_simulation``,
	inside ``rules.guard``. Callers that merely build templates or display a value pass
	``allow_unverified=True`` (setup.taxes does, for exactly that reason).
	"""
	try:
		from nyabo_mn.rules import params as rules_params  # type: ignore[import-not-found]
	except ImportError:
		rules_params = None
	if rules_params is not None and hasattr(rules_params, "get"):
		return rules_params.get(key, on_date, allow_unverified=allow_unverified)
	row = rules_engine.resolve_parameter(tax_parameter_rows(), key, on_date)
	if not allow_unverified:
		_require_verified_rule(row, key)
	return row


def vat_rate(on_date: dt.date, *, allow_unverified: bool = False) -> Decimal:
	"""The VAT rate in force on the date, refused when the row is unverified (see ``tax_parameter``)."""
	return tax_parameter(VAT_RATE_KEY, on_date, allow_unverified=allow_unverified).as_decimal()


def _has_rows(doctype: str) -> bool:
	import frappe

	try:
		return frappe.db.count(doctype) > 0
	except Exception:  # noqa: BLE001 - DocType not installed yet
		return False


# --- posting patterns ---------------------------------------------------------------------------


def _pattern_from_doc(doc: Any) -> rules_engine.PatternSpec:
	data = doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)
	data["lines"] = [dict(line) for line in data.get("lines") or []]
	return rules_engine.PatternSpec.from_dict(data)


def load_patterns() -> list[rules_engine.PatternSpec]:
	"""``Nyabo Posting Pattern`` rows (the admin's ``verified`` flags live there), else the seed."""
	import frappe

	if _has_rows("Nyabo Posting Pattern"):
		return [
			_pattern_from_doc(frappe.get_doc("Nyabo Posting Pattern", name))
			for name in frappe.get_all("Nyabo Posting Pattern", pluck="name", order_by="creation asc")
		]
	return [rules_engine.PatternSpec.from_dict(r) for r in load_seed("posting_patterns")["rows"]]


def pattern_by_id(pattern_id: str) -> rules_engine.PatternSpec:
	for pattern in load_patterns():
		if pattern.pattern_id == pattern_id:
			return pattern
	raise rules_engine.NoPatternError(
		f"posting pattern {pattern_id!r} not found",
		mn.MSG_PATTERN_NOT_FOUND.format(document=pattern_id),
	)


def _require_verified_rule(rule: Any, label: str) -> None:
	"""``rules.guard.require_verified`` when the package is importable, else the same check locally.

	One helper for every rule shape (pattern, tax-parameter row) so the guard - and its
	single ``frappe.flags.nyabo_simulation`` bypass - is applied in exactly one way.
	"""
	try:
		from nyabo_mn.rules import guard  # type: ignore[import-not-found]
	except ImportError:
		guard = None
	if guard is not None and hasattr(guard, "require_verified"):
		guard.require_verified(rule)
		return
	if not getattr(rule, "verified", False):
		raise UnverifiedRuleError(
			f"rule {label!r} is not verified",
			mn.MSG_UNVERIFIED_RULE_BLOCKED.format(rule=label),
		)


def require_verified(pattern: rules_engine.PatternSpec) -> None:
	"""``rules.guard.require_verified`` when available; refuses an unverified pattern for a real posting."""
	_require_verified_rule(pattern, pattern.pattern_id)


# --- chart, schemes, code resolution ----------------------------------------------------------------


def chart_leaves(company: str) -> list[tuple[str, str]]:
	"""``(code, account_name)`` for every numbered ledger account of the company, sorted by code."""
	import frappe

	rows = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "disabled": 0, "account_number": ["!=", ""]},
		fields=["account_number", "account_name", "account_type", "root_type"],
	)
	return sorted((str(r.account_number), str(r.account_name)) for r in rows)


def account_types(company: str) -> dict[str, tuple[str, str]]:
	import frappe

	rows = frappe.get_all(
		"Account",
		filters={"company": company, "account_number": ["!=", ""]},
		fields=["account_number", "account_type", "root_type", "is_group"],
	)
	return {str(r.account_number): (str(r.account_type or ""), str(r.root_type or "")) for r in rows}


def chart_scheme(company: str, settings: Any | None, leaves: Iterable[str]) -> str:
	"""The settings' scheme when its role codes exist in the chart, else the scheme that does.

	Provisioning installs the V1 draft while the settings default to ``v03``; guessing
	an account from the wrong scheme would post to a code that is not in the chart, so
	the payable role of each scheme is checked against the real leaves.
	"""
	leaf_set = set(leaves)
	schemes = load_seed("code_roles")["schemes"]
	preferred = str((settings.get("chart_scheme") if settings else None) or "v03")
	order = [preferred] + [s for s in ("v03", "v1") if s != preferred]
	for scheme in order:
		roles = schemes.get(scheme)
		if scheme == "accountant" or not roles:
			continue
		if roles.get("payable") in leaf_set:
			return scheme
	return preferred


def role_code(company: str, scheme: str, role: str) -> str | None:
	"""Account code for a ``code_roles.json`` role; the accountant's chart maps through alias rows."""
	import frappe

	schemes = load_seed("code_roles")["schemes"]
	base_scheme = "v03" if scheme == "accountant" else scheme
	code = (schemes.get(base_scheme) or {}).get(role)
	if not code:
		return None
	if scheme == "accountant":
		target = frappe.db.get_value(
			"Nyabo Account Alias",
			{"company": company, "scheme": "accountant", "alias_code": code},
			"target_code",
		)
		return str(target) if target else None
	return str(code)


def make_resolver(
	company: str,
	scheme: str,
	leaves: Iterable[str],
	classified_code: str,
	*,
	primary_selectors: Iterable[str] = (),
	overrides: Mapping[str, str] | None = None,
) -> Callable[[str], str]:
	"""Selector -> account code for ``rules_engine.instantiate``.

	``class:NN`` and the pattern's primary debit line resolve to the classified code (the
	model or the rule chose it); ``role:X`` goes through ``code_roles.json``; a literal
	code is returned as is. ``overrides`` swaps a role (payable -> cash for a cash JE).
	"""
	leaf_set = set(leaves)
	primaries = set(primary_selectors)
	overrides = dict(overrides or {})

	def resolve(selector: str) -> str:
		if selector in primaries or selector.startswith("class:"):
			return classified_code
		if selector.startswith("role:"):
			role = overrides.get(selector[5:], selector[5:])
			code = role_code(company, scheme, role)
			if not code or code not in leaf_set:
				raise PipelineError(
					f"role {role!r} has no leaf account in scheme {scheme!r} for {company}",
					mn.WARN_ACCOUNT_ROLE_MISSING.format(role=role),
				)
			return code
		if selector not in leaf_set:
			raise PipelineError(
				f"account {selector!r} is not a leaf of {company}",
				mn.MSG_ACCOUNT_CODE_INVALID.format(code=selector),
			)
		return selector

	return resolve


def family_for_code(company: str, code: str) -> str:
	"""Which purchase pattern family the chosen account belongs to (by ERPNext account_type)."""
	account_type, _root = account_types(company).get(code, ("", ""))
	if account_type in STOCK_ACCOUNT_TYPES:
		return FAMILY_INVENTORY
	if account_type in FIXED_ASSET_ACCOUNT_TYPES:
		return FAMILY_FIXED_ASSET
	return FAMILY_EXPENSE


def primary_selectors(pattern: rules_engine.PatternSpec) -> list[str]:
	"""The first debit line carrying the document amount: the classified account goes there."""
	for line in pattern.lines:
		if line.side == "debit" and line.amount_kind in ("net", "gross"):
			return [line.selector]
	return []


# --- Nyabo Rule matching -----------------------------------------------------------------------------


def _pattern_hit(pattern: str, *texts: str) -> bool:
	"""Regex when the value compiles, else case-insensitive substring; empty never matches."""
	pattern = (pattern or "").strip()
	if not pattern:
		return False
	try:
		compiled = re.compile(pattern, re.IGNORECASE | re.UNICODE)
	except re.error:
		compiled = None
	for text in texts:
		if not text:
			continue
		if compiled is not None and compiled.search(text):
			return True
		if pattern.lower() in text.lower():
			return True
	return False


def match_rule(
	company: str,
	receipt: Receipt,
	*,
	supplier_name: str | None,
	supplier_register_no: str | None,
	total: Decimal | None,
) -> Any | None:
	"""First active ``Nyabo Rule`` in ARCHITECTURE order; bumps ``hit_count``/``last_hit``."""
	import frappe
	from frappe.utils import now_datetime

	rows = frappe.get_all(
		"Nyabo Rule",
		filters={"company": company, "status": "active", "match_type": ["in", list(RULE_ORDER)]},
		fields=[
			"name",
			"match_type",
			"match_value",
			"amount_min",
			"amount_max",
			"target_account_code",
			"vat_treatment",
			"posting_pattern",
			"hit_count",
		],
		order_by="creation asc",
	)
	descriptions = [line.description for line in receipt.lines] + [receipt.raw_text]
	seller_names = [receipt.seller_name, supplier_name or ""]
	register_nos = {receipt.seller_register_no or "", supplier_register_no or ""} - {""}
	for match_type in RULE_ORDER:
		for row in rows:
			if row.match_type != match_type:
				continue
			hit = False
			if match_type == "supplier_register_no":
				hit = (row.match_value or "").strip() in register_nos
			elif match_type == "supplier_name_pattern":
				hit = _pattern_hit(row.match_value, *seller_names)
			elif match_type == "description_pattern":
				hit = _pattern_hit(row.match_value, *descriptions)
			elif match_type == "amount_band" and total is not None:
				low = Decimal(str(row.amount_min or 0))
				high = Decimal(str(row.amount_max or 0))
				hit = low <= total and (high <= 0 or total <= high)
			if hit:
				frappe.db.set_value(
					"Nyabo Rule",
					row.name,
					{"hit_count": int(row.hit_count or 0) + 1, "last_hit": now_datetime()},
				)
				return row
	return None


# --- LLM plumbing -----------------------------------------------------------------------------------


class _CallCollector:
	"""Buffers ``CallRecord`` rows until the proposal exists, then writes them with its name."""

	def __init__(self, company: str):
		self.company = company
		self.records: list[CallRecord] = []

	def __call__(self, record: CallRecord) -> None:
		self.records.append(record)

	def flush(self, proposal: str | None) -> None:
		for record in self.records:
			frappe_log.record(record, company=self.company, proposal=proposal)
		self.records.clear()


def llm_client(settings: Any, collector: _CallCollector) -> LlmClient:
	return get_client(settings, "mock" if _simulation() else "auto", record_call=collector)


def _settings_obj() -> Any:
	from nyabo_mn.config import get_settings

	return get_settings()


def _document_bytes(document: Any) -> tuple[bytes, str]:
	import frappe

	file_name = frappe.db.get_value("File", {"file_url": document.file}, "name")
	if not file_name:
		raise PipelineError(f"file {document.file!r} not found for {document.name}", mn.MSG_EXTRACTION_FAILED)
	content = frappe.get_doc("File", file_name).get_content()
	if isinstance(content, str):
		content = content.encode("utf-8")
	mime = str(document.get("mime_type") or "image/jpeg")
	return content, mime


def send_card(proposal_name: str) -> None:
	"""Hand the proposal to the Telegram layer; a missing handler is logged, not fatal."""
	try:
		from nyabo_mn.telegram.handlers.receipt import send_proposal_card  # type: ignore[import-not-found]
	except ImportError:
		logger.info("telegram receipt handler not available; card for %s not sent", proposal_name)
		return
	try:
		send_proposal_card(proposal_name)
	except Exception as exc:  # noqa: BLE001 - the proposal exists; the card can be resent
		logger.exception("send_proposal_card failed for %s", proposal_name)
		try:
			from nyabo_mn.log import log_error

			log_error("card.send_failed", exc, proposal=proposal_name)
		except Exception:  # noqa: BLE001
			pass


# --- the pipeline ------------------------------------------------------------------------------------


def _confidence_warnings(receipt: Receipt, printed_vat: Decimal) -> list[str]:
	out: list[str] = []
	for field in CONFIDENCE_FIELDS:
		if field == "vat_amount" and printed_vat <= ZERO:
			continue
		confidence = receipt.confidence_of(field)
		if confidence < LOW_CONFIDENCE:
			out.append(
				mn.WARN_LOW_CONFIDENCE.format(
					field=mn.FIELD_LABELS.get(field, field), confidence=int(round(confidence * 100))
				)
			)
	return out


def _qr_vision_mismatch(qr_data: str | None, receipt: Receipt) -> bool:
	"""The QR payload is opaque (ARCHITECTURE §2): nothing in it can be compared with the
	vision fields today, so no mismatch is ever asserted. Kept as the single place to
	extend when the payload format is documented."""
	del qr_data, receipt
	return False


def decide_vat_treatment(
	proposed: str,
	*,
	ctx: RegimeContext,
	printed_vat: Decimal,
	seller_vat_payer: bool | None,
) -> tuple[str, list[str]]:
	"""Deterministic VAT treatment: the regime and the seller override the model.

	Non-VAT companies never withhold (Заавар 116: VAT into cost). A receipt without a
	printed VAT line has nothing to withhold. A seller the registry says is not a VAT
	payer cannot have charged VAT, so the printed amount stays in the expense with a
	warning for the accountant. A VAT payer with VAT printed by a VAT-payer seller
	withholds: the model's "in_expense" is not honoured because the non-deductible
	categories are a pending 2027 rule (``vat.input_deduction_categories``), not a
	judgement the model may make; only ``exempt`` / ``zero`` survive.
	"""
	warnings: list[str] = []
	if not ctx.input_vat_recoverable:
		return ("in_expense" if printed_vat > ZERO else "none"), warnings
	if printed_vat <= ZERO:
		return ("none" if proposed in ("withheld", "in_expense", "none") else proposed), warnings
	if seller_vat_payer is False:
		warnings.append(mn.WARN_SELLER_NOT_VAT_PAYER)
		return "in_expense", warnings
	if proposed in ("exempt", "zero"):
		return proposed, warnings
	return "withheld", warnings


def build_amounts(gross: Decimal, printed_vat: Decimal, treatment: str) -> dict[str, Decimal]:
	"""Amount kinds for the pattern: withheld splits net/vat, everything else books gross."""
	gross = quantize(gross)
	if treatment == "withheld" and printed_vat > ZERO:
		vat = quantize(printed_vat)
		return {"gross": gross, "vat": vat, "net": gross - vat}
	return {"gross": gross, "net": gross}


def build_explanation(reason: str, *, treatment: str, ctx: RegimeContext, vat: Decimal) -> str:
	parts = [reason.strip()] if reason and reason.strip() else []
	if treatment == "withheld":
		parts.append(mn.EXPL_VAT_WITHHELD.format(vat=fmt_mnt(vat)))
	elif not ctx.is_vat_payer and vat > ZERO:
		parts.append(mn.EXPL_NO_VAT_NON_PAYER)
	return " ".join(parts)


def citation_text(citation: Citation) -> str:
	return f"{citation.instrument}, {citation.section or mn.CITATION_SECTION_PENDING}"


def process_receipt(
	document_name: str,
	*,
	client: LlmClient | None = None,
	provider: Any | None = None,
	now: dt.datetime | None = None,
	send: CardSender | None = send_card,
) -> str:
	"""Turn a received ``Nyabo Document`` into a ``Nyabo Proposal`` and send its card.

	Returns the proposal name. Any failure marks the document ``failed`` with the error,
	writes a ``pipeline_failed`` event and re-raises so the job log keeps the traceback.
	"""
	import frappe

	document = frappe.get_doc("Nyabo Document", document_name)
	company = document.company
	collector = _CallCollector(company)
	proposal_name: str | None = None
	try:
		proposal_name = _run(document, collector, client=client, provider=provider, now=now)
		collector.flush(proposal_name)
	except Exception as exc:
		collector.flush(None)
		message = getattr(exc, "message_mn", None) or f"{type(exc).__name__}: {exc}"
		try:
			document.db_set({"status": "failed", "error": str(message)[:1000]})
			write_event(
				"pipeline_failed",
				company=company,
				ref_doctype="Nyabo Document",
				ref_name=document.name,
				reason=str(message)[:500],
				payload={"error_class": type(exc).__name__},
			)
			from nyabo_mn.log import log_error

			log_error("pipeline.failed", exc, document=document.name, company=company)
		except Exception:  # noqa: BLE001 - reporting must not hide the original error
			logger.exception("could not record pipeline failure for %s", document.name)
		raise
	if send is not None:
		send(proposal_name)
	return proposal_name


def _run(
	document: Any,
	collector: _CallCollector,
	*,
	client: LlmClient | None,
	provider: Any | None,
	now: dt.datetime | None,
) -> str:
	import frappe

	from nyabo_mn.agent import few_shot
	from nyabo_mn.agent import supplier as supplier_mod
	from nyabo_mn.ebarimt import get_provider, qr

	company = document.company
	settings_row = company_settings(company)
	site_settings = _settings_obj()
	# ``now`` is a UTC timestamp for the call records; the *posting date* must be the site's
	# business date, so ``_today`` is asked only what the caller actually supplied.
	given_now = now
	now = now or dt.datetime.now(dt.timezone.utc)
	warnings: list[str] = []
	needs_accountant = False

	# 1. QR
	image_bytes, mime = _document_bytes(document)
	qr_data = qr.decode(image_bytes)

	# 2. Extraction
	if client is None:
		client = llm_client(site_settings, collector)
	elif getattr(client, "record_call", None) is None and hasattr(client, "record_call"):
		# An injected client (tests, simulator) still logs its calls: "every call writes" (§6).
		client.record_call = collector
	context = (
		f"company: {company}\nscheme: {(settings_row.get('chart_scheme') if settings_row else '') or ''}"
	)
	outcome = extract.extract_receipt_full(client, image_bytes, mime, company_context=context, now=now)
	receipt = outcome.receipt
	document.db_set({"status": "extracted"})

	# Quarantine: instruction-looking text anywhere in what the model read back.
	fragment = outcome.injection_fragment or find_injection(receipt.raw_text)
	if fragment:
		warnings.append(mn.WARN_INJECTION_SUSPECTED)
		needs_accountant = True
		write_event(
			"injection_suspected",
			company=company,
			ref_doctype="Nyabo Document",
			ref_name=document.name,
			reason=fragment[:200],
			payload={"injection_fragment": fragment[:500]},
		)
	if extract.WARN_SELLER_NAME_MISSING in outcome.warnings:
		needs_accountant = True

	# Dates and regime
	posting_date = receipt.date
	if posting_date is None:
		posting_date = _today(given_now)
		warnings.append(mn.MSG_DATE_DEFAULTED_TODAY)
		needs_accountant = True
	ctx = regime_context(company, posting_date)

	# 3. Seller and supplier
	provider = provider or get_provider(site_settings)
	seller_info: SellerInfo = provider.lookup_seller(
		tin=receipt.seller_tin, register_no=receipt.seller_register_no
	)
	verification: ReceiptVerification = provider.verify_receipt(
		qr_data=qr_data, receipt_id=receipt.receipt_id
	)
	supplier_name, supplier_is_new = supplier_mod.match_or_create(company, receipt, seller_info)
	if supplier_is_new:
		warnings.append(mn.WARN_NEW_SUPPLIER)
		needs_accountant = True
	supplier_register_no = frappe.db.get_value("Supplier", supplier_name, "register_no")
	seller_vat_payer = seller_info.vat_payer if seller_info.found else None
	if seller_vat_payer is None and supplier_name and not supplier_is_new:
		checked = frappe.db.get_value("Supplier", supplier_name, ["ebarimt_vat_payer", "ebarimt_checked_at"])
		if checked and checked[1]:
			seller_vat_payer = bool(checked[0])

	# Amounts
	if receipt.total is None or receipt.total <= ZERO:
		raise PipelineError(f"receipt {document.name} has no total", mn.MSG_RECEIPT_AMOUNT_MISSING)
	gross = quantize(receipt.total)
	printed_vat = quantize(receipt.vat_amount) if receipt.vat_amount is not None else ZERO
	confidence_warnings = _confidence_warnings(receipt, printed_vat)
	if _qr_vision_mismatch(qr_data, receipt):
		confidence_warnings.append(mn.WARN_QR_VISION_MISMATCH)
	if confidence_warnings:
		warnings.extend(confidence_warnings)
		needs_accountant = True

	# 4. Rules, else classification
	leaves = chart_leaves(company)
	leaf_codes = [code for code, _name in leaves]
	scheme = chart_scheme(company, settings_row, leaf_codes)
	default_code = str((settings_row.get("default_expense_code") if settings_row else "") or "")
	if default_code not in leaf_codes:
		default_code = role_code(company, scheme, "default_expense") or default_code
	rule = match_rule(
		company,
		receipt,
		supplier_name=supplier_name,
		supplier_register_no=supplier_register_no,
		total=gross,
	)
	llm_meta: dict[str, Any] = {
		"prompt_version": outcome.llm.prompt_version,
		"model": outcome.llm.model,
		"tokens_in": outcome.llm.tokens_in,
		"tokens_out": outcome.llm.tokens_out,
		"latency_ms": outcome.llm.latency_ms,
	}
	if rule is not None:
		code = str(rule.target_account_code)
		proposed_treatment = str(rule.vat_treatment or "none")
		reason = mn.EXPL_RULE_APPLIED.format(rule=rule.name, code=code)
		if code not in leaf_codes:
			warnings.append(mn.MSG_ACCOUNT_CODE_INVALID.format(code=code))
			needs_accountant = True
			code = default_code
	else:
		classification = classify.classify_full(
			client,
			outcome.receipt_dict,
			leaves,
			few_shot.bundle(company),
			{
				"company": company,
				"regime": ctx.regime.value,
				"is_vat_payer": ctx.is_vat_payer,
				"default_expense_code": default_code,
				"seller_vat_payer": seller_vat_payer,
				"now": now,
			},
		)
		code = classification.result.account_code
		proposed_treatment = classification.result.vat_treatment
		reason = classification.result.reason_mn
		if classification.warnings:
			needs_accountant = True
		llm_meta["tokens_in"] += classification.llm.tokens_in
		llm_meta["tokens_out"] += classification.llm.tokens_out
		llm_meta["latency_ms"] += classification.llm.latency_ms
		llm_meta["prompt_version"] = f"{outcome.llm.prompt_version}+{classification.llm.prompt_version}"

	treatment, vat_warnings = decide_vat_treatment(
		proposed_treatment, ctx=ctx, printed_vat=printed_vat, seller_vat_payer=seller_vat_payer
	)
	warnings.extend(vat_warnings)

	# 5. Pattern, entry, validation
	family = family_for_code(company, code)
	hints: dict[str, Any] = {"family": family}
	if rule is not None and rule.posting_pattern:
		hints = {"pattern_id": rule.posting_pattern}
	pattern = rules_engine.select_pattern(load_patterns(), "purchase_invoice", ctx, hints)
	document_kind = (
		"purchase_invoice"
		if treatment == "withheld" and "Purchase Invoice" in pattern.document_types
		else "journal_entry"
	)
	# A cash receipt credits cash whatever the document kind: no bank statement line will ever
	# arrive to settle a payable that was paid over the counter (D-019). The Purchase Invoice
	# books it as ERPNext's paid invoice (``is_paid``) in ``post.build_purchase_invoice``.
	overrides = {"payable": "cash"} if receipt.payment_method == "cash" else {}
	resolver = make_resolver(
		company, scheme, leaf_codes, code, primary_selectors=primary_selectors(pattern), overrides=overrides
	)
	amounts = build_amounts(gross, printed_vat, treatment)
	vat_booked = amounts.get("vat", ZERO)
	description = (
		receipt.lines[0].description
		if receipt.lines and receipt.lines[0].description
		else receipt.seller_name
	)
	entry: ProposedEntry = rules_engine.instantiate(
		pattern,
		amounts,
		resolver,
		company=company,
		posting_date=posting_date,
		explanation=build_explanation(reason, treatment=treatment, ctx=ctx, vat=printed_vat),
		vat_treatment=treatment,  # type: ignore[arg-type]
		document_kind=document_kind,  # type: ignore[arg-type]
		supplier=supplier_name,
		description=description,
		warnings=warnings,
	)
	if not pattern.verified:
		needs_accountant = True
	problems = validate_entry(entry, leaf_codes, vat_rate(posting_date))
	entry_warnings = list(entry.warnings)
	for problem in problems:
		entry_warnings.append(mn.WARN_ENTRY_INVALID.format(problem=problem))
		needs_accountant = True
	entry = ProposedEntry.from_dict(
		{**entry.to_dict(), "warnings": entry_warnings, "vat_amount": str(vat_booked)}
	)

	# 6. Proposal
	from nyabo_mn.setup.chart_db import account_for_code

	proposal = frappe.get_doc(
		{
			"doctype": "Nyabo Proposal",
			"document": document.name,
			"company": company,
			"kind": "receipt",
			"status": "proposed",
			"needs_accountant": 1 if needs_accountant else 0,
			"supplier": supplier_name,
			"supplier_is_new": 1 if supplier_is_new else 0,
			"posting_date": posting_date,
			"total": float(gross),
			"vat_amount": float(vat_booked),
			"vat_treatment": treatment,
			"account_code": code,
			"account": account_for_code(company, code),
			"posting_pattern": pattern.pattern_id
			if frappe.db.exists("Nyabo Posting Pattern", pattern.pattern_id)
			else None,
			"rule_applied": rule.name if rule is not None else None,
			"explanation": entry.explanation[:EXPLANATION_MAX],
			"citation": citation_text(pattern.citation),
			"entry_json": dumps(entry.to_dict()),
			"extracted_json": dumps(outcome.receipt_dict),
			"verification_json": dumps(
				{"seller": seller_info.to_dict(), "receipt": verification.to_dict(), "qr_data": qr_data}
			),
			"confidence_json": dumps(dict(receipt.confidence)),
			"warnings_json": dumps(entry_warnings),
			**llm_meta,
		}
	)
	proposal.flags.ignore_permissions = True
	proposal.insert()
	document.db_set({"status": "proposed"})
	write_event(
		"proposal_created",
		company=company,
		ref_doctype="Nyabo Proposal",
		ref_name=proposal.name,
		payload={
			"document": document.name,
			"needs_accountant": needs_accountant,
			"rule": rule.name if rule else None,
		},
	)
	return proposal.name


# --- questions (ARCHITECTURE §5.7) ----------------------------------------------------------------------

AdminNotifier = Callable[[str, str], None]
# The Telegram layer may set this to push escalations to the admins; see escalate handler.
ADMIN_NOTIFIER: AdminNotifier | None = None


def _find_supplier(name: str) -> str | None:
	import frappe

	from nyabo_mn.core.matching import name_similarity

	if frappe.db.exists("Supplier", name):
		return name
	best: tuple[float, str] | None = None
	for row in frappe.get_all("Supplier", fields=["name", "supplier_name"]):
		score = name_similarity(name, row.supplier_name or row.name)
		if score >= 0.8 and (best is None or score > best[0]):
			best = (score, row.name)
	return best[1] if best else None


def books_handlers(
	company: str, *, today: dt.date | None = None
) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
	"""Read-only handlers for ``agent.questions``; every number is formatted here, never by the model."""
	import frappe
	from erpnext.accounts.utils import get_balance_on

	from nyabo_mn.core import dates
	from nyabo_mn.setup.chart import ChartError
	from nyabo_mn.setup.chart_db import account_for_code

	today = today or dt.date.today()

	def _account(code: str | None) -> str:
		if not code:
			raise ChartError("account_code required")
		return account_for_code(company, str(code).strip(), leaf=False)

	def _books(args: dict[str, Any]) -> dict[str, Any]:
		kind = args.get("query_kind")
		inner = dict(args.get("args") or {})
		try:
			if kind == "balance_on_date":
				account = _account(inner.get("account_code"))
				on = dt.date.fromisoformat(inner["on_date"]) if inner.get("on_date") else today
				balance = Decimal(str(get_balance_on(account, on, company=company) or 0))
				return {
					"account": account,
					"date": on.isoformat(),
					"balance": fmt_mnt(balance),
					"text": mn.MSG_BALANCE_ANSWER.format(
						account=account, date=on.isoformat(), balance=fmt_mnt(balance)
					),
				}
			if kind == "spend_by_account":
				account = _account(inner.get("account_code"))
				period = inner.get("period") or dates.period_of(today)
				start, end = dates.period_bounds(period)
				rows = frappe.get_all(
					"GL Entry",
					filters={
						"company": company,
						"account": account,
						"is_cancelled": 0,
						"posting_date": ["between", [start, end]],
					},
					fields=["debit", "credit"],
				)
				amount = quantize(
					sum((Decimal(str(r.debit or 0)) - Decimal(str(r.credit or 0)) for r in rows), ZERO)
				)
				label = dates.period_label(period)
				return {
					"account": account,
					"period": period,
					"amount": fmt_mnt(amount),
					"text": mn.MSG_SPEND_ANSWER.format(period=label, account=account, amount=fmt_mnt(amount)),
				}
			if kind == "last_entries_for_supplier":
				wanted = str(inner.get("supplier") or "").strip()
				supplier = _find_supplier(wanted) if wanted else None
				if not supplier:
					return {
						"supplier": wanted,
						"entries": [],
						"text": mn.SUPPLIER_NOT_FOUND_ANSWER.format(supplier=wanted),
					}
				rows = frappe.get_all(
					"GL Entry",
					filters={
						"company": company,
						"party_type": "Supplier",
						"party": supplier,
						"is_cancelled": 0,
					},
					fields=["voucher_type", "voucher_no", "posting_date", "debit", "credit"],
					order_by="posting_date desc",
				)
				seen: dict[str, dict[str, Any]] = {}
				for row in rows:
					key = f"{row.voucher_type}:{row.voucher_no}"
					if key in seen:
						continue
					amount = max(Decimal(str(row.debit or 0)), Decimal(str(row.credit or 0)))
					seen[key] = {
						"doctype": row.voucher_type,
						"name": row.voucher_no,
						"date": str(row.posting_date),
						"amount": fmt_mnt(amount),
					}
					if len(seen) >= 5:
						break
				entries = list(seen.values())
				if not entries:
					return {
						"supplier": supplier,
						"entries": [],
						"text": mn.LAST_ENTRIES_NONE.format(supplier=supplier),
					}
				lines = "\n".join(mn.LAST_ENTRY_LINE.format(**e) for e in entries)
				return {
					"supplier": supplier,
					"entries": entries,
					"text": mn.MSG_LAST_ENTRIES_ANSWER.format(supplier=supplier, entries=lines),
				}
			if kind == "unmatched_count":
				count = frappe.db.count(
					"Bank Transaction",
					{"company": company, "docstatus": 1, "status": ["in", ["Unreconciled", "Pending"]]},
				)
				return {"count": count, "text": mn.UNMATCHED_ANSWER.format(count=count)}
			return {"error": "invalid_arguments", "detail": [f"unknown query_kind {kind!r}"]}
		except ChartError as exc:
			return {"error": "unknown_account", "detail": [str(exc)]}
		except ValueError as exc:
			return {"error": "invalid_arguments", "detail": [str(exc)]}

	return {"answer_from_books": _books}


def load_faq() -> list[tuple[str, str]]:
	"""``(heading, body)`` sections of the FAQ markdown; empty when no file ships yet."""
	import frappe

	for relative in FAQ_PATHS:
		try:
			path = frappe.get_app_path("nyabo_mn", *relative.split("/"))
		except Exception:  # noqa: BLE001
			continue
		try:
			with open(path, encoding="utf-8") as fh:
				text = fh.read()
		except OSError:
			continue
		sections: list[tuple[str, str]] = []
		heading, body = "", []
		for line in text.splitlines():
			if line.startswith("#"):
				if heading or body:
					sections.append((heading, "\n".join(body).strip()))
				heading, body = line.lstrip("#").strip(), []
			else:
				body.append(line)
		if heading or body:
			sections.append((heading, "\n".join(body).strip()))
		return [s for s in sections if s[1]]
	return []


def faq_handler(args: dict[str, Any]) -> dict[str, Any]:
	question = str(args.get("question") or "").lower()
	tokens = {t for t in re.split(r"\W+", question, flags=re.UNICODE) if len(t) > 2}
	best: tuple[int, str, str] | None = None
	for heading, body in load_faq():
		haystack = f"{heading} {body}".lower()
		score = sum(1 for t in tokens if t in haystack)
		if score and (best is None or score > best[0]):
			best = (score, heading, body)
	if best is None:
		return {"found": False, "text": mn.FAQ_NOT_FOUND}
	return {"found": True, "title": best[1], "text": best[2][:1500]}


def escalate_handler(user: str, company: str, question: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
	def _escalate(args: dict[str, Any]) -> dict[str, Any]:
		summary = str(args.get("summary") or "")[:500]
		event = write_event(
			"question_escalated",
			company=company,
			actor_user=user,
			reason=summary,
			payload={"question": question[:500]},
		)
		notified = False
		notifier = ADMIN_NOTIFIER
		if notifier is None:
			try:
				from nyabo_mn.telegram import api as telegram_api  # type: ignore[import-not-found]

				# UNVERIFIED: the Telegram layer's admin notification entry point is not part of the
				# contract yet; only used when it exposes notify_admins(summary, company).
				notifier = getattr(telegram_api, "notify_admins", None)
			except ImportError:
				notifier = None
		if notifier is not None:
			try:
				notifier(summary, company)
				notified = True
			except Exception:  # noqa: BLE001 - the event is the record; notification is best effort
				logger.exception("admin notification failed")
		return {"escalated": True, "event": event, "notified": notified, "text": mn.MSG_ESCALATED}

	return _escalate


def answer_question(
	user: str,
	company: str,
	text: str,
	*,
	client: LlmClient | None = None,
	now: dt.datetime | None = None,
) -> str:
	"""One read-only, tool-using model call; returns the Mongolian sentence for the chat."""
	from nyabo_mn.agent import questions

	now = now or dt.datetime.now(dt.timezone.utc)
	recorder = frappe_log.recorder(company=company)
	if client is None:
		client = get_client(_settings_obj(), "mock" if _simulation() else "auto", record_call=recorder)
	elif getattr(client, "record_call", None) is None and hasattr(client, "record_call"):
		client.record_call = recorder
	handlers = {
		**books_handlers(company, today=now.date()),
		"answer_faq": faq_handler,
		"escalate_to_admin": escalate_handler(user, company, text),
	}
	try:
		ctx = regime_context(company, now.date())
		regime = ctx.regime.value
	except rules_engine.RuleError:
		regime = "unknown"
	outcome = questions.answer(
		client,
		text,
		handlers,
		company_context=f"company: {company}\nregime: {regime}\nuser: {user}",
		now=now,
	)
	if outcome.injection_suspected:
		write_event(
			"injection_suspected",
			company=company,
			actor_user=user,
			reason=(outcome.injection_fragment or "")[:200],
			payload={"source": "question"},
		)
	return outcome.answer.answer_mn


__all__ = [
	"ADMIN_NOTIFIER",
	"CONFIDENCE_FIELDS",
	"FAMILY_EXPENSE",
	"FAMILY_FIXED_ASSET",
	"FAMILY_INVENTORY",
	"LOW_CONFIDENCE",
	"RULE_ORDER",
	"PipelineError",
	"UnverifiedRuleError",
	"answer_question",
	"books_handlers",
	"build_amounts",
	"build_explanation",
	"chart_leaves",
	"chart_scheme",
	"citation_text",
	"company_settings",
	"decide_vat_treatment",
	"dumps",
	"escalate_handler",
	"faq_handler",
	"family_for_code",
	"load_faq",
	"load_patterns",
	"loads",
	"make_resolver",
	"match_rule",
	"pattern_by_id",
	"process_receipt",
	"regime_context",
	"require_verified",
	"role_code",
	"send_card",
	"tax_parameter",
	"tax_parameter_rows",
	"vat_rate",
	"write_event",
]
