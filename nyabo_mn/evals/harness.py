"""Deterministic mini-pipeline the evals and the simulator run cases through.

Why a harness and not the real ``agent.pipeline``: the evals must run without a bench
and without network, so the same case gives the same answer on a laptop, in CI and on a
site. Everything here is built from ``nyabo_mn.core`` and ``nyabo_mn.agent`` plus the
seed JSON. The parts that live on the Frappe side are reached through :class:`Adapters`:
``default_adapters()`` wires ``nyabo_mn.rules.guard`` (``require_verified`` /
``is_verified`` take a core ``PatternSpec``, no site needed) and keeps the core fallbacks
for the functions that take site documents or a company (primary-document hook, period
lock, reversal, FX rate); ``site_adapters(company)`` swaps in
``compliance.period.is_locked`` and ``compliance.hooks.require_primary_document`` on a
connected site. A pure-Python run without ``frappe`` importable gets the fallbacks, which
carry the same contract, so a missing dependency never turns into a silently skipped check.

The defences mirror docs/ARCHITECTURE.md §5.3 step 7 and §1.9: a low confidence on
``total`` / ``date`` / ``vat_amount``, a new supplier, an unverified rule, a suspected
injection, a duplicate, a receipt of another company or a foreign-currency receipt all
mark the proposal ``needs_accountant``; when an injection is suspected the model's
account choice and reason are discarded entirely, because the instructed content may
well be exactly what the model returned.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import importlib
import importlib.util
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from nyabo_mn.agent import classify as classify_mod
from nyabo_mn.agent import extract as extract_mod
from nyabo_mn.agent.llm_client import LlmClient, LlmResult
from nyabo_mn.agent.mock_client import DEFAULT_FIXTURES_DIR, MockLlmClient
from nyabo_mn.core import rules_engine as re_
from nyabo_mn.core.models import Citation, ProposedEntry, ProposedLine, RegimeContext
from nyabo_mn.core.money import ZERO, fmt_mnt, quantize, to_decimal, vat_consistent
from nyabo_mn.core.quarantine import find_injection
from nyabo_mn.core.validate import validate_entry
from nyabo_mn.i18n import mn
from nyabo_mn.nyabo.seed import load_seed, seed_path
from nyabo_mn.setup import chart as chart_mod

CONFIDENCE_MIN = 0.7
CONFIDENCE_FIELDS = ("total", "date", "vat_amount")
CASH_METHODS = ("cash",)
# Card, QPay and transfer receipts are NOT credited to the bank here: the statement line
# settles the payable later, and crediting the bank now would double count (D-019). The
# tuple is kept because the card wording and the matching hints still read it.
BANK_METHODS = ("card", "qpay", "transfer")
DEFAULT_SCHEME = "v1"
DEFAULT_EXPENSE_ROLE = "default_expense"

FLAG_LOW_CONFIDENCE = "low_confidence"
FLAG_INJECTION = "injection_suspected"
FLAG_NEW_SUPPLIER = "new_supplier"
FLAG_UNVERIFIED_RULE = "unverified_rule"
FLAG_NO_EBARIMT = "no_ebarimt"
FLAG_DUPLICATE = "duplicate"
FLAG_WRONG_COMPANY = "wrong_company"
FLAG_FOREIGN_CURRENCY = "foreign_currency"
FLAG_SELLER_NOT_VAT_PAYER = "seller_not_vat_payer"
FLAG_VAT_INCONSISTENT = "vat_inconsistent"
FLAG_ENTRY_INVALID = "entry_invalid"
FLAG_LOW_CLASSIFICATION = "low_classification_confidence"
CLASSIFICATION_CONFIDENCE_MIN = 0.5


# --- errors and adapters ----------------------------------------------------------------------


class UnverifiedRuleError(Exception):
	"""Fallback for ``nyabo_mn.rules.guard.UnverifiedRuleError`` when that package is absent."""

	def __init__(self, rule: str):
		super().__init__(f"rule {rule!r} is not verified")
		self.rule = rule
		self.message_mn = mn.MSG_UNVERIFIED_RULE_BLOCKED.format(rule=rule)


class PrimaryDocumentError(Exception):
	"""A posting without a primary document (Law on Accounting art. 13.7)."""

	def __init__(self, message_mn: str | None = None) -> None:
		super().__init__("primary document required")
		self.message_mn = message_mn or mn.MSG_PRIMARY_DOCUMENT_REQUIRED


def fallback_require_verified(pattern: re_.PatternSpec) -> None:
	"""Core-only stand-in for ``rules.guard.require_verified``: refuse an unverified pattern."""
	if not pattern.verified:
		raise UnverifiedRuleError(pattern.pattern_id)


def fallback_is_verified(pattern: re_.PatternSpec) -> bool:
	"""Core-only stand-in for ``rules.guard.is_verified`` (the card check, no simulation bypass)."""
	return bool(pattern.verified)


def require_nyabo_document_complete(fields: Mapping[str, Any]) -> None:
	"""ARCHITECTURE §1.4: a Nyabo-created posting links its proposal, its document and an explanation.

	The compliance hook enforces the primary document (art. 13.7) and the proposal link;
	the explanation is what the pipeline guarantees, so the harness keeps this rule in
	front of both the fallback and the real hook.
	"""
	if fields.get("nyabo_proposal") and not (
		fields.get("source_document") and str(fields.get("nyabo_explanation") or "").strip()
	):
		raise PrimaryDocumentError()


def fallback_require_primary_document(fields: Mapping[str, Any]) -> None:
	"""Core-only stand-in for ``compliance.hooks.require_primary_document``.

	A posting is allowed when it links a Nyabo Document, carries an attachment, or names
	its primary document in ``nyabo_primary_document_ref``; a Nyabo-created document must
	link its proposal *and* carry the explanation (ARCHITECTURE §1.4).
	"""
	require_nyabo_document_complete(fields)
	if fields.get("nyabo_proposal"):
		return
	has_document = bool(fields.get("source_document") or fields.get("has_attachment"))
	has_ref = bool(str(fields.get("nyabo_primary_document_ref") or "").strip())
	if not (has_document or has_ref):
		raise PrimaryDocumentError()


class _DocShim:
	"""The slice of a Frappe document ``compliance.hooks.require_primary_document`` reads.

	``is_new()`` is True so the hook never queries File rows: a case states its attachment
	with ``has_attachment`` and the adapter honours that before calling the hook.
	"""

	def __init__(self, fields: Mapping[str, Any], doctype: str) -> None:
		self._fields = dict(fields)
		self.doctype = doctype
		self.name = None

	def get(self, key: str, default: Any = None) -> Any:
		return self._fields.get(key, default)

	def is_new(self) -> bool:
		return True


def hook_require_primary_document(fields: Mapping[str, Any], doctype: str = "Journal Entry") -> None:
	"""The real ``compliance.hooks.require_primary_document`` on the case's fields."""
	from nyabo_mn.compliance import hooks as compliance_hooks

	require_nyabo_document_complete(fields)
	if fields.get("has_attachment"):
		return  # the case asserts a File row is attached; on a site the hook would find it
	try:
		compliance_hooks.require_primary_document(_DocShim(fields, doctype))
	except Exception as exc:  # noqa: BLE001 - frappe.ValidationError carries the Mongolian text
		raise PrimaryDocumentError(str(exc)) from exc


def fallback_period_is_closed(closed_periods: Iterable[Mapping[str, Any]], on_date: dt.date) -> bool:
	"""True when ``on_date`` lies inside any (start_date, end_date) row (inclusive, like ERPNext)."""
	for period in closed_periods:
		if period.get("disabled"):
			continue
		start = _date(period.get("start_date"))
		end = _date(period.get("end_date"))
		if start is None or end is None:
			continue
		if start <= on_date <= end:
			return True
	return False


def fallback_reverse_entry(entry: ProposedEntry, posting_date: dt.date, reason: str) -> ProposedEntry:
	"""Debit/credit swapped, same accounts and amounts (what ``make_reverse_journal_entry`` does)."""
	lines = tuple(
		ProposedLine(
			account_code=line.account_code,
			debit=line.credit,
			credit=line.debit,
			description=line.description,
			party_type=line.party_type,
			party=line.party,
		)
		for line in entry.lines
	)
	return dataclasses.replace(
		entry,
		lines=lines,
		posting_date=posting_date,
		explanation=reason,
		warnings=(),
	)


def fallback_rate_on(
	rates: Iterable[Mapping[str, Any]], from_currency: str, to_currency: str, on_date: dt.date
) -> Decimal:
	"""Mongolbank-style lookup: the latest rate dated on or before the transaction date.

	Same rule as ``erpnext.setup.utils.get_exchange_rate`` reading Currency Exchange rows
	(``date <= transaction_date``, newest first). No rate at all is an error, never 1.0.
	"""
	best: tuple[dt.date, Decimal] | None = None
	for row in rates:
		if row.get("from_currency") != from_currency or row.get("to_currency") != to_currency:
			continue
		day = _date(row.get("date"))
		if day is None or day > on_date:
			continue
		if best is None or day > best[0]:
			best = (day, to_decimal(row.get("exchange_rate") or 0))
	if best is None:
		raise LookupError(f"no {from_currency}->{to_currency} rate on or before {on_date.isoformat()}")
	return best[1]


@dataclass(frozen=True)
class Adapters:
	"""The Frappe-side contracts the harness needs, as callables (tests pass fakes).

	``require_verified`` is the posting-time guard (it honours ``frappe.flags.nyabo_simulation``
	exactly like the pipeline); ``is_verified`` is the plain card check that decides
	``needs_accountant`` and never bypasses (ARCHITECTURE §5.3 step 5, D-006).
	"""

	require_verified: Callable[[re_.PatternSpec], None] = fallback_require_verified
	is_verified: Callable[[re_.PatternSpec], bool] = fallback_is_verified
	require_primary_document: Callable[[Mapping[str, Any]], None] = fallback_require_primary_document
	period_is_closed: Callable[[Iterable[Mapping[str, Any]], dt.date], bool] = fallback_period_is_closed
	reverse_entry: Callable[[ProposedEntry, dt.date, str], ProposedEntry] = fallback_reverse_entry
	rate_on: Callable[[Iterable[Mapping[str, Any]], str, str, dt.date], Decimal] = fallback_rate_on
	source: str = "fallback"


SOURCE_MODULES = "nyabo_mn.rules+compliance"


def site_period_is_closed(company: str) -> Callable[[Iterable[Mapping[str, Any]], dt.date], bool]:
	"""Period lock from the company's own Accounting Period rows (the case's list is ignored).

	``compliance.period.is_locked`` is what the pipeline and the reversal ask; the case's
	``closed_periods`` are expected to have been created on the site by the caller.
	"""

	def _closed(_closed_periods: Iterable[Mapping[str, Any]], on_date: dt.date) -> bool:
		try:
			from nyabo_mn.compliance import period as compliance_period
		except ImportError:
			compliance_period = None
		if compliance_period is not None:
			return bool(compliance_period.is_locked(company, on_date)[0])
		import frappe

		rows = frappe.get_all(
			"Accounting Period",
			filters={"company": company, "disabled": 0},
			fields=["start_date", "end_date"],
		)
		return fallback_period_is_closed([dict(r) for r in rows], on_date)

	return _closed


def site_adapters(company: str) -> Adapters:
	"""Adapters that read the site: real Accounting Periods and the real primary-document hook.

	Reversal and FX stay on the fallbacks even here: ``compliance.reversal.reverse`` needs a
	submitted document and the FX cases carry their own rate rows, while the harness works
	on ``ProposedEntry`` values that are never posted.
	"""
	base = default_adapters()
	require_document = base.require_primary_document
	if importlib.util.find_spec("nyabo_mn.compliance.hooks") is not None:
		require_document = hook_require_primary_document
	return dataclasses.replace(
		base,
		period_is_closed=site_period_is_closed(company),
		require_primary_document=require_document,
		source=f"{base.source}+site",
	)


def default_adapters() -> Adapters:
	"""The real ``nyabo_mn.rules.guard`` when ``frappe`` is importable, else the core fallbacks.

	``guard.require_verified`` / ``guard.is_verified`` accept a core ``PatternSpec`` (an
	object with ``pattern_id`` and ``verified``), so no site is needed. The compliance
	functions take a company or a site document; :func:`site_adapters` wires those.
	"""
	try:
		guard = importlib.import_module("nyabo_mn.rules.guard")
	except ImportError:
		return Adapters()
	return Adapters(
		require_verified=guard.require_verified, is_verified=guard.is_verified, source=SOURCE_MODULES
	)


# --- rules data ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class RulesData:
	parameters: tuple[re_.ParameterRow, ...]
	patterns: tuple[re_.PatternSpec, ...]
	roles: Mapping[str, str | None]
	leaves: Mapping[str, str]  # code -> name
	scheme: str

	def leaf_list(self) -> list[tuple[str, str]]:
		return sorted(self.leaves.items())

	def role_code(self, role: str) -> str | None:
		return self.roles.get(role)

	def vat_rate(self, on_date: dt.date) -> Decimal:
		return re_.parameter_decimal(self.parameters, "vat.rate", on_date)


@lru_cache(maxsize=4)
def load_rules(scheme: str = DEFAULT_SCHEME) -> RulesData:
	"""Seed parameters, patterns, roles and the chart leaves of ``scheme`` (v1 = the draft chart)."""
	parameters = tuple(re_.ParameterRow.from_dict(row) for row in load_seed("tax_parameters")["rows"])
	patterns = tuple(re_.PatternSpec.from_dict(row) for row in load_seed("posting_patterns")["rows"])
	roles = dict(load_seed("code_roles")["schemes"][scheme])
	chart_path = chart_mod.DEFAULT_CHART_PATH if scheme == "v1" else seed_path("chart_v03")
	chart = chart_mod.load_chart(chart_path)
	leaves = {a.number: a.name for a in chart.accounts() if a.number and not a.is_group}
	return RulesData(parameters, patterns, roles, leaves, scheme)


def regime_context(regime: str, on_date: dt.date) -> RegimeContext:
	"""A one-row regime history is enough for a case: the regime named is in force on the date."""
	return re_.regime_on([(regime, None, None)], on_date)


# --- fixtures -----------------------------------------------------------------------------------


def load_fixture(key: str, fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR) -> dict[str, Any]:
	"""``"extract/golden_petrovis_fuel"`` -> the parsed ``tests/fixtures/llm/extract/golden_petrovis_fuel.json``."""
	path = Path(fixtures_dir) / f"{key}.json"
	with path.open(encoding="utf-8") as fh:
		return json.load(fh)


def placeholder_image(key: str) -> bytes:
	"""Deterministic stand-in bytes for a receipt photo; the fixture key decides the model's answer."""
	return b"NYABO-EVAL-IMAGE:" + hashlib.sha256(key.encode("utf-8")).digest()


def script_fixture(
	client: LlmClient, purpose: str, key: str, fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR
) -> None:
	"""Make a MockLlmClient answer ``purpose`` with the fixture; a real client is left alone."""
	if isinstance(client, MockLlmClient):
		client.add(purpose, load_fixture(key, fixtures_dir))


# --- extraction --------------------------------------------------------------------------------


def extract_case(
	client: LlmClient,
	fixture_key: str,
	*,
	company_context: str = "",
	now: dt.datetime | None = None,
	fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
	mime: str = "image/jpeg",
) -> extract_mod.ExtractOutcome:
	"""Run the vision extraction with the fixture as the model's answer."""
	script_fixture(client, extract_mod.PURPOSE, fixture_key, fixtures_dir)
	return extract_mod.extract_receipt_full(
		client,
		placeholder_image(fixture_key),
		mime,
		company_context=company_context,
		now=now or dt.datetime(2026, 9, 8, 9, 0, tzinfo=dt.timezone.utc),
	)


# --- proposal -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposalOutcome:
	"""What the pipeline would put on the card, plus every reason it was held back."""

	receipt: Mapping[str, Any]
	regime: RegimeContext
	account_code: str | None
	vat_treatment: str
	entry: ProposedEntry | None
	explanation: str
	reason_mn: str
	confidence: float
	needs_accountant: bool
	flags: tuple[str, ...]
	problems: tuple[str, ...]
	warnings: tuple[str, ...]
	injection_detected: bool
	injection_fragment: str | None
	duplicate: bool
	wrong_company: bool
	classification_source: str
	llm: tuple[LlmResult, ...] = ()
	pattern_id: str | None = None
	citation: Citation | None = None
	amount_mnt: Decimal | None = None
	document_kind: str | None = None

	def summary(self) -> dict[str, Any]:
		return {
			"account_code": self.account_code,
			"vat_treatment": self.vat_treatment,
			"document_kind": self.document_kind,
			"pattern_id": self.pattern_id,
			"needs_accountant": self.needs_accountant,
			"flags": list(self.flags),
			"duplicate": self.duplicate,
			"wrong_company": self.wrong_company,
			"injection_detected": self.injection_detected,
			"explanation": self.explanation,
			"lines": [
				{"account_code": line.account_code, "debit": str(line.debit), "credit": str(line.credit)}
				for line in (self.entry.lines if self.entry else ())
			],
			"total": str(self.entry.total) if self.entry else None,
			"vat_amount": str(self.entry.vat_amount) if self.entry else None,
			"problems": list(self.problems),
		}


@dataclass(frozen=True)
class Prior:
	"""What the company has already seen: for duplicate detection (sha256, receipt id, or seller+date+total)."""

	file_hashes: frozenset[str] = frozenset()
	receipt_ids: frozenset[str] = frozenset()
	receipts: frozenset[tuple[str, str, str]] = frozenset()  # (seller_tin, date, total)

	@classmethod
	def from_dict(cls, data: Mapping[str, Any] | None) -> Prior:
		data = data or {}
		receipts = set()
		for row in data.get("receipts") or []:
			receipts.add(
				(
					str(row.get("seller_tin") or ""),
					str(row.get("date") or ""),
					str(quantize(to_decimal(row.get("total") or 0))),
				)
			)
		return cls(
			file_hashes=frozenset(str(h) for h in data.get("file_hashes") or []),
			receipt_ids=frozenset(str(r) for r in data.get("receipt_ids") or []),
			receipts=frozenset(receipts),
		)


def is_duplicate(receipt: Mapping[str, Any], file_hash: str | None, prior: Prior) -> bool:
	"""The three dedup keys the receipt flow uses, in the order they are cheap to check."""
	if file_hash and file_hash in prior.file_hashes:
		return True
	receipt_id = receipt.get("receipt_id")
	if receipt_id and str(receipt_id) in prior.receipt_ids:
		return True
	total = receipt.get("total")
	day = receipt.get("date")
	if total is not None and day is not None:
		key = (str(receipt.get("seller_tin") or ""), _date(day).isoformat(), str(quantize(to_decimal(total))))
		if key in prior.receipts:
			return True
	return False


def is_wrong_company(receipt: Mapping[str, Any], company_tin: str | None) -> bool:
	"""A receipt printed for another buyer (TIN on the receipt differs from the company's)."""
	buyer_tin = str(receipt.get("buyer_tin") or "").strip()
	if not buyer_tin or not company_tin:
		return False
	return buyer_tin != str(company_tin).strip()


@dataclass(frozen=True)
class ProposeInput:
	receipt: Mapping[str, Any]
	regime: str
	on_date: dt.date
	company: str = "Тест ХХК"
	classify_fixture: str | None = None
	seller_vat_payer: bool | None = None
	supplier_known: bool = False
	file_hash: str | None = None
	prior: Prior = field(default_factory=Prior)
	company_tin: str | None = None
	currency: str = "MNT"
	fx_rates: tuple[Mapping[str, Any], ...] = ()
	examples: tuple[Mapping[str, Any], ...] = ()
	scheme: str = DEFAULT_SCHEME

	@classmethod
	def from_case(
		cls, input_json: Mapping[str, Any], regime: str, on_date: dt.date, company: str
	) -> ProposeInput:
		receipt = dict(input_json.get("receipt") or {})
		if "date" not in receipt or receipt.get("date") is None:
			receipt["date"] = on_date.isoformat()
		return cls(
			receipt=receipt,
			regime=regime,
			on_date=on_date,
			company=company,
			classify_fixture=input_json.get("classify_fixture"),
			seller_vat_payer=input_json.get("seller_vat_payer"),
			supplier_known=bool(input_json.get("supplier_known", False)),
			file_hash=input_json.get("file_hash"),
			prior=Prior.from_dict(input_json.get("prior")),
			company_tin=input_json.get("company_tin"),
			currency=str(input_json.get("currency") or receipt.get("currency") or "MNT"),
			fx_rates=tuple(input_json.get("fx_rates") or ()),
			examples=tuple(input_json.get("examples") or ()),
			scheme=str(input_json.get("scheme") or DEFAULT_SCHEME),
		)


def propose(
	spec: ProposeInput,
	client: LlmClient | None = None,
	*,
	adapters: Adapters | None = None,
	fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
	defend_injection: bool = True,
) -> ProposalOutcome:
	"""ARCHITECTURE §5.3 steps 3-7 for one extracted receipt under one regime.

	``defend_injection=False`` exists only so a test can plant an injection success and
	prove the metric catches it; production callers never pass it.
	"""
	adapters = adapters or default_adapters()
	rules = load_rules(spec.scheme)
	ctx = regime_context(spec.regime, spec.on_date)
	receipt = _normalise_receipt(spec.receipt)
	flags: list[str] = []
	warnings: list[str] = []
	llm: list[LlmResult] = []

	# Injection scan covers every free-text field the model could have copied from the paper.
	texts = [str(receipt.get("seller_name") or ""), str(receipt.get("notes") or "")]
	texts += [str(line.get("description") or "") for line in receipt.get("lines") or []]
	fragment = receipt.get("injection_fragment") or next(
		(f for f in (find_injection(t) for t in texts) if f), None
	)
	injection = bool(receipt.get("injection_suspected")) or fragment is not None
	if injection:
		flags.append(FLAG_INJECTION)
		warnings.append(mn.WARN_INJECTION_SUSPECTED)

	duplicate = is_duplicate(receipt, spec.file_hash, spec.prior)
	if duplicate:
		flags.append(FLAG_DUPLICATE)
	wrong_company = is_wrong_company(receipt, spec.company_tin)
	if wrong_company:
		flags.append(FLAG_WRONG_COMPANY)

	for name in CONFIDENCE_FIELDS:
		confidence = float((receipt.get("confidence") or {}).get(name, 0.0))
		if confidence < CONFIDENCE_MIN:
			flags.append(f"{FLAG_LOW_CONFIDENCE}:{name}")
			warnings.append(
				mn.WARN_LOW_CONFIDENCE.format(
					field=mn.FIELD_LABELS.get(name, name), confidence=int(confidence * 100)
				)
			)
	if not spec.supplier_known:
		flags.append(FLAG_NEW_SUPPLIER)
		warnings.append(mn.WARN_NEW_SUPPLIER)
	if not receipt.get("receipt_id"):
		flags.append(FLAG_NO_EBARIMT)
		warnings.append(mn.VERIFICATION_RECEIPT_UNCHECKED)

	# Classification: rule-free path (rules DocType is Frappe-side); the model proposes.
	default_code = rules.role_code(DEFAULT_EXPENSE_ROLE) or ""
	classify_ctx = {
		"company": spec.company,
		"regime": ctx.regime.value,
		"is_vat_payer": ctx.is_vat_payer,
		"default_expense_code": default_code,
		"seller_vat_payer": spec.seller_vat_payer,
		"now": dt.datetime.combine(spec.on_date, dt.time(9, 0), tzinfo=dt.timezone.utc),
	}
	account_code = default_code
	reason_mn = mn.AGENT_REASON_UNAVAILABLE
	confidence = 0.0
	vat_treatment = default_vat_treatment(receipt, ctx, spec.seller_vat_payer)
	source = "default"
	if client is not None:
		if spec.classify_fixture:
			script_fixture(client, classify_mod.PURPOSE, spec.classify_fixture, fixtures_dir)
		outcome = classify_mod.classify_full(
			client, receipt, rules.leaf_list(), list(spec.examples), classify_ctx
		)
		llm.append(outcome.llm)
		warnings.extend(outcome.warnings)
		account_code = outcome.result.account_code
		reason_mn = outcome.result.reason_mn
		confidence = outcome.result.confidence
		vat_treatment = outcome.result.vat_treatment
		source = "model"
	if injection and defend_injection:
		# The instructed content may be exactly what came back: drop the model's whole answer.
		account_code = default_code
		reason_mn = mn.AGENT_REASON_UNAVAILABLE
		confidence = 0.0
		vat_treatment = default_vat_treatment(receipt, ctx, spec.seller_vat_payer)
		source = "default"
	elif source == "model" and confidence < CLASSIFICATION_CONFIDENCE_MIN:
		# The prompt asks for < 0.5 when guessing (personal-looking purchases, unknown sellers).
		flags.append(FLAG_LOW_CLASSIFICATION)

	vat_treatment, vat_flags = _settle_vat(
		vat_treatment, receipt, ctx, spec.seller_vat_payer, rules, spec.on_date
	)
	flags.extend(vat_flags)
	warnings.extend(mn.WARN_SELLER_NOT_VAT_PAYER for f in vat_flags if f == FLAG_SELLER_NOT_VAT_PAYER)

	entry: ProposedEntry | None = None
	problems: tuple[str, ...] = ()
	pattern_id: str | None = None
	citation: Citation | None = None
	amount_mnt: Decimal | None = None
	document_kind: str | None = None
	if receipt.get("total") is not None and account_code:
		try:
			entry, amount_mnt = _build_entry(
				spec, receipt, ctx, rules, account_code, vat_treatment, reason_mn, adapters, flags
			)
		except (re_.RuleError, LookupError) as exc:
			problems = (str(getattr(exc, "message_mn", exc)),)
			flags.append(FLAG_ENTRY_INVALID)
		if entry is not None:
			pattern_id = entry.pattern_id
			citation = entry.citation
			document_kind = entry.document_kind
			found = validate_entry(entry, rules.leaves.keys(), rules.vat_rate(spec.on_date))
			if found:
				problems = tuple(found)
				flags.append(FLAG_ENTRY_INVALID)
			pattern = _pattern_by_id(rules, entry.pattern_id)
			refused: Exception | None = None
			try:
				adapters.require_verified(pattern)
			except Exception as exc:  # noqa: BLE001 - any guard error means "hold for the accountant"
				refused = exc
			# The card flag never bypasses (D-006): a simulated posting may pass the guard,
			# the card still says the rule is unverified.
			if refused is not None or not adapters.is_verified(pattern):
				flags.append(FLAG_UNVERIFIED_RULE)
				text = str(getattr(refused, "message_mn", "") or mn.WARN_UNVERIFIED_RULE)
				if text not in warnings:
					warnings.append(text)

	needs_accountant = bool(flags)
	explanation = entry.explanation if entry is not None else reason_mn
	return ProposalOutcome(
		receipt=receipt,
		regime=ctx,
		account_code=account_code or None,
		vat_treatment=vat_treatment,
		entry=entry,
		explanation=explanation,
		reason_mn=reason_mn,
		confidence=confidence,
		needs_accountant=needs_accountant,
		flags=tuple(dict.fromkeys(flags)),
		problems=problems,
		warnings=tuple(dict.fromkeys(warnings)),
		injection_detected=injection,
		injection_fragment=fragment,
		duplicate=duplicate,
		wrong_company=wrong_company,
		classification_source=source,
		llm=tuple(llm),
		pattern_id=pattern_id,
		citation=citation,
		amount_mnt=amount_mnt,
		document_kind=document_kind,
	)


def default_vat_treatment(
	receipt: Mapping[str, Any], ctx: RegimeContext, seller_vat_payer: bool | None
) -> str:
	"""The treatment code derives without a model: withheld only when every condition holds."""
	if not receipt.get("vat_amount"):
		return "none"
	if ctx.input_vat_recoverable and seller_vat_payer:
		return "withheld"
	return "in_expense"


def _settle_vat(
	treatment: str,
	receipt: Mapping[str, Any],
	ctx: RegimeContext,
	seller_vat_payer: bool | None,
	rules: RulesData,
	on_date: dt.date,
) -> tuple[str, list[str]]:
	"""Deterministic VAT rule on top of the model's answer (docs/mn-rules-reference.md §3)."""
	flags: list[str] = []
	vat = receipt.get("vat_amount")
	if not ctx.input_vat_recoverable and treatment == "withheld":
		treatment = "in_expense" if vat else "none"
	if treatment == "withheld":
		if seller_vat_payer is False:
			flags.append(FLAG_SELLER_NOT_VAT_PAYER)
			treatment = "in_expense" if vat else "none"
		elif not vat:
			treatment = "none"
		elif receipt.get("total") is not None and not vat_consistent(
			receipt["total"], vat, rules.vat_rate(on_date)
		):
			flags.append(FLAG_VAT_INCONSISTENT)
	return treatment, flags


def _build_entry(
	spec: ProposeInput,
	receipt: Mapping[str, Any],
	ctx: RegimeContext,
	rules: RulesData,
	account_code: str,
	vat_treatment: str,
	reason_mn: str,
	adapters: Adapters,
	flags: list[str],
) -> tuple[ProposedEntry, Decimal]:
	gross = quantize(to_decimal(receipt["total"]))
	if spec.currency != "MNT":
		flags.append(FLAG_FOREIGN_CURRENCY)
		rate = adapters.rate_on(spec.fx_rates, spec.currency, "MNT", spec.on_date)
		gross = quantize(gross * rate)
	amounts: dict[str, Decimal] = {"gross": gross}
	if vat_treatment == "withheld":
		vat = quantize(to_decimal(receipt.get("vat_amount") or 0))
		amounts["vat"] = vat
		amounts["net"] = gross - vat
	else:
		amounts["net"] = gross

	pattern = re_.select_pattern(rules.patterns, "purchase_invoice", ctx, {"family": "purchase_expense"})
	# A Purchase Invoice always credits the supplier (ERPNext's credit_to). A Journal Entry
	# credits cash only for a cash receipt; card/QPay/transfer keep the payable so the bank
	# statement can settle it (D-019). agent.pipeline.propose does exactly this, and the
	# simulator must show what the pipeline would post.
	if vat_treatment != "withheld":
		pattern = _apply_alternatives(pattern, _conditions(receipt))

	def resolve(selector: str) -> str:
		if selector.startswith("role:"):
			code = rules.role_code(selector[5:])
			if code is None:
				raise re_.MissingAmountError(selector, mn.MSG_ACCOUNT_UNKNOWN.format(account=selector))
			return code
		if selector.startswith("class:"):
			return account_code
		return selector

	entry = re_.instantiate(
		pattern,
		amounts,
		resolve,
		company=spec.company,
		posting_date=spec.on_date,
		explanation="",
		vat_treatment=vat_treatment,  # type: ignore[arg-type]
		supplier=str(receipt.get("seller_name") or "") or None,
		description=str((receipt.get("lines") or [{}])[0].get("description") or "")
		if receipt.get("lines")
		else "",
	)
	# The model's one line, then the VAT sentence code owns, then the citation (§1.4).
	parts = [reason_mn.strip()]
	if vat_treatment == "withheld":
		parts.append(mn.EXPL_VAT_WITHHELD.format(vat=fmt_mnt(amounts["vat"])))
	elif not ctx.input_vat_recoverable and receipt.get("vat_amount"):
		parts.append(mn.EXPL_NO_VAT_NON_PAYER)
	explanation = " ".join(p for p in parts if p) + re_.citation_suffix(pattern.citation)
	return dataclasses.replace(entry, explanation=explanation), gross


def _conditions(receipt: Mapping[str, Any]) -> set[str]:
	"""Only a cash receipt swaps the credit line; see D-019 for why card/QPay/transfer do not."""
	method = str(receipt.get("payment_method") or "unknown")
	if method in CASH_METHODS:
		return {"paid_in_cash"}
	return set()


def _apply_alternatives(pattern: re_.PatternSpec, conditions: set[str]) -> re_.PatternSpec:
	"""Swap a line for its alternative when the receipt states the condition (cash / card)."""
	if not conditions:
		return pattern
	lines = []
	for line in pattern.lines:
		chosen = next((alt for alt in line.alternatives if alt.when in conditions), None)
		if chosen is None:
			lines.append(line)
			continue
		lines.append(
			dataclasses.replace(line, account_class=chosen.account_class, role=chosen.role, alternatives=())
		)
	return dataclasses.replace(pattern, lines=tuple(lines))


def _pattern_by_id(rules: RulesData, pattern_id: str) -> re_.PatternSpec:
	for pattern in rules.patterns:
		if pattern.pattern_id == pattern_id:
			return pattern
	raise re_.NoPatternError(pattern_id, mn.MSG_PATTERN_NOT_FOUND.format(document=pattern_id))


def _normalise_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
	out = dict(receipt)
	for key in ("total", "vat_amount"):
		if out.get(key) is not None:
			out[key] = quantize(to_decimal(out[key]))
	if out.get("date") is not None:
		out["date"] = _date(out["date"])
	lines = []
	for line in out.get("lines") or []:
		row = dict(line)
		if row.get("amount") is not None:
			row["amount"] = quantize(to_decimal(row["amount"]))
		if row.get("qty") is not None:
			row["qty"] = to_decimal(row["qty"])
		lines.append(row)
	out["lines"] = lines
	return out


# --- corrections, periods, documents, fx ----------------------------------------------------------


@dataclass(frozen=True)
class CorrectionOutcome:
	reversal: ProposedEntry
	new_entry: ProposedEntry | None
	correction_rows: tuple[dict[str, str], ...]
	reversal_in_original_period: bool
	warnings: tuple[str, ...]

	def summary(self) -> dict[str, Any]:
		return {
			"reversal_date": self.reversal.posting_date.isoformat(),
			"reversal_lines": _lines(self.reversal),
			"new_entry_lines": _lines(self.new_entry) if self.new_entry else None,
			"new_entry_date": self.new_entry.posting_date.isoformat() if self.new_entry else None,
			"correction_rows": list(self.correction_rows),
			"reversal_in_original_period": self.reversal_in_original_period,
			"warnings": list(self.warnings),
		}


def correct(
	original: ProposalOutcome,
	spec: ProposeInput,
	correction: Mapping[str, Any],
	*,
	today: dt.date,
	closed_periods: Iterable[Mapping[str, Any]] = (),
	client: LlmClient | None = None,
	adapters: Adapters | None = None,
) -> CorrectionOutcome:
	"""ARCHITECTURE §5.6: reversal first, then a new proposal unless the reason is ``duplicate``."""
	adapters = adapters or default_adapters()
	if original.entry is None:
		raise ValueError("cannot correct a proposal without an entry")
	reason = str(correction.get("reason") or "other")
	reason_text = mn.CORRECT_REASONS.get(reason, mn.CORRECT_OTHER)
	closed = list(closed_periods)
	in_original = not adapters.period_is_closed(closed, original.entry.posting_date)
	reversal_date = original.entry.posting_date if in_original else today
	reversal = adapters.reverse_entry(original.entry, reversal_date, reason_text)
	warnings: list[str] = []
	if not in_original:
		warnings.append(
			mn.MSG_CORRECTION_PERIOD_CLOSED.format(period=original.entry.posting_date.strftime("%Y-%m"))
		)

	rows: list[dict[str, str]] = []
	new_entry: ProposedEntry | None = None
	if reason == "dup":
		rows.append(
			{"field": "reversed", "proposed_value": original.entry.pattern_id, "corrected_value": "duplicate"}
		)
	else:
		field_name = str(correction.get("field") or "")
		corrected = correction.get("corrected_value")
		receipt = dict(spec.receipt)
		# A closed original period moves both the reversal and the new entry to today.
		new_spec = spec if in_original else dataclasses.replace(spec, on_date=today)
		proposed_value: Any = None
		if field_name == "account_code":
			proposed_value = original.account_code
		elif field_name == "total":
			proposed_value = str(original.entry.total)
			receipt["total"] = corrected
			receipt["vat_amount"] = correction.get("corrected_vat", receipt.get("vat_amount"))
			new_spec = dataclasses.replace(new_spec, receipt=receipt)
		elif field_name == "vat_treatment":
			proposed_value = original.vat_treatment
		elif field_name == "posting_date":
			proposed_value = original.entry.posting_date.isoformat()
			new_spec = dataclasses.replace(new_spec, on_date=_date(corrected))
		rows.append(
			{"field": field_name, "proposed_value": str(proposed_value), "corrected_value": str(corrected)}
		)
		new_entry = _rebuild(original, new_spec, field_name, corrected, adapters)
	return CorrectionOutcome(reversal, new_entry, tuple(rows), in_original, tuple(warnings))


def _rebuild(
	original: ProposalOutcome, spec: ProposeInput, field_name: str, corrected: Any, adapters: Adapters
) -> ProposedEntry:
	"""The corrected entry: the original proposal with one value replaced, re-instantiated."""
	rules = load_rules(spec.scheme)
	ctx = regime_context(spec.regime, spec.on_date)
	receipt = _normalise_receipt(spec.receipt)
	account_code = str(corrected) if field_name == "account_code" else (original.account_code or "")
	vat_treatment = str(corrected) if field_name == "vat_treatment" else original.vat_treatment
	if vat_treatment == "withheld" and not ctx.input_vat_recoverable:
		vat_treatment = "in_expense"
	entry, _amount = _build_entry(
		spec, receipt, ctx, rules, account_code, vat_treatment, original.reason_mn, adapters, []
	)
	return entry


def document_allowed(fields: Mapping[str, Any], adapters: Adapters | None = None) -> tuple[bool, str | None]:
	"""(allowed, message_mn) for a posting described by its custom-field values."""
	adapters = adapters or default_adapters()
	try:
		adapters.require_primary_document(fields)
	except Exception as exc:  # noqa: BLE001 - the hook raises frappe.ValidationError on a site
		return False, str(getattr(exc, "message_mn", exc))
	return True, None


def posting_allowed_in_period(
	closed_periods: Iterable[Mapping[str, Any]], on_date: dt.date, adapters: Adapters | None = None
) -> tuple[bool, str | None]:
	adapters = adapters or default_adapters()
	if adapters.period_is_closed(list(closed_periods), on_date):
		return False, mn.MSG_POSTING_IN_CLOSED_PERIOD.format(
			date=on_date.isoformat(), period=on_date.strftime("%Y-%m")
		)
	return True, None


@dataclass(frozen=True)
class FxOutcome:
	rate: Decimal
	amount_mnt: Decimal
	settlement_rate: Decimal | None
	fx_difference: Decimal | None
	fx_entry: ProposedEntry | None

	def summary(self) -> dict[str, Any]:
		return {
			"rate": str(self.rate),
			"amount_mnt": str(self.amount_mnt),
			"settlement_rate": str(self.settlement_rate) if self.settlement_rate is not None else None,
			"fx_difference": str(self.fx_difference) if self.fx_difference is not None else None,
			"fx_pattern": self.fx_entry.pattern_id if self.fx_entry else None,
			"fx_lines": _lines(self.fx_entry) if self.fx_entry else None,
		}


def convert_fx(
	input_json: Mapping[str, Any],
	regime: str,
	on_date: dt.date,
	*,
	adapters: Adapters | None = None,
	company: str = "Тест ХХК",
) -> FxOutcome:
	"""Mongolbank rate on the transaction date; on settlement the difference goes to fx_gain / fx_loss."""
	adapters = adapters or default_adapters()
	rules = load_rules(str(input_json.get("scheme") or DEFAULT_SCHEME))
	currency = str(input_json.get("currency") or "USD")
	amount = quantize(to_decimal(input_json["amount"]))
	rates = list(input_json.get("fx_rates") or [])
	rate = adapters.rate_on(rates, currency, "MNT", on_date)
	amount_mnt = quantize(amount * rate)
	settlement_rate: Decimal | None = None
	difference: Decimal | None = None
	fx_entry: ProposedEntry | None = None
	settled_on = input_json.get("settled_on")
	if settled_on:
		settlement_day = _date(settled_on)
		settlement_rate = adapters.rate_on(rates, currency, "MNT", settlement_day)
		difference = quantize(amount * settlement_rate) - amount_mnt
		if difference != ZERO:
			ctx = regime_context(regime, settlement_day)
			family = "fx"
			wanted = "fx_loss" if difference > ZERO else "fx_gain"
			pattern = re_.select_pattern(
				rules.patterns, "journal_entry", ctx, {"family": family, "pattern_id": wanted}
			)
			pattern = _apply_alternatives(
				pattern, {"fx_payable"} if input_json.get("side", "payable") == "payable" else set()
			)

			def resolve(selector: str) -> str:
				if selector.startswith("role:"):
					code = rules.role_code(selector[5:])
					if code is None:
						raise re_.MissingAmountError(
							selector, mn.MSG_ACCOUNT_UNKNOWN.format(account=selector)
						)
					return code
				return selector

			fx_entry = re_.instantiate(
				pattern,
				{"fx_difference": abs(difference)},
				resolve,
				company=company,
				posting_date=settlement_day,
				explanation=mn.EXPL_EXPENSE.format(
					what=pattern.name_mn, debit_code=pattern.lines[0].role or "", credit_name=""
				),
			)
	return FxOutcome(rate, amount_mnt, settlement_rate, difference, fx_entry)


# --- helpers -------------------------------------------------------------------------------------


def _date(value: Any) -> dt.date | None:
	if value in (None, ""):
		return None
	if isinstance(value, dt.datetime):
		return value.date()
	if isinstance(value, dt.date):
		return value
	return dt.date.fromisoformat(str(value)[:10])


def _lines(entry: ProposedEntry | None) -> list[dict[str, str]]:
	if entry is None:
		return []
	return [
		{"account_code": line.account_code, "debit": str(line.debit), "credit": str(line.credit)}
		for line in entry.lines
	]


def lines_of(entry: ProposedEntry | None) -> list[dict[str, str]]:
	return _lines(entry)


def date_of(value: Any) -> dt.date | None:
	return _date(value)


__all__ = [
	"Adapters",
	"CorrectionOutcome",
	"FxOutcome",
	"Prior",
	"PrimaryDocumentError",
	"ProposalOutcome",
	"ProposeInput",
	"RulesData",
	"SOURCE_MODULES",
	"UnverifiedRuleError",
	"convert_fx",
	"correct",
	"default_adapters",
	"document_allowed",
	"extract_case",
	"hook_require_primary_document",
	"is_duplicate",
	"is_wrong_company",
	"lines_of",
	"load_fixture",
	"load_rules",
	"placeholder_image",
	"posting_allowed_in_period",
	"propose",
	"regime_context",
	"script_fixture",
]
