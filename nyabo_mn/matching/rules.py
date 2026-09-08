"""Nyabo Proposals for statement lines: fee lines, own transfers, unmatched lines.

The model proposes, code validates, the accountant disposes: this module only writes
``Nyabo Proposal`` rows of kind ``bank_line`` (status ``proposed``). Posting happens
elsewhere after a Telegram tap; ``auto_approve_policy`` is read by the approval
handler, never here, so a bank fee is still one tap away from the books.

Account codes come from the bank-fee ``Nyabo Rule`` (seeded from the ``bank_fee`` role
of the chart scheme), from the LLM classification for other outflows, and from the
``receivable`` role for unexplained inflows. Codes are resolved to ERPNext accounts
through ``nyabo_mn.setup.chart_db.account_for_code``; nothing here names an account.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from nyabo_mn.core import matching as core_matching
from nyabo_mn.core.models import BankLine, Citation, ProposedEntry, ProposedLine
from nyabo_mn.core.money import quantize
from nyabo_mn.core.rules_engine import citation_suffix
from nyabo_mn.i18n import mn
from nyabo_mn.matching import common
from nyabo_mn.nyabo.seed import load_seed

PROPOSAL_DOCTYPE = "Nyabo Proposal"
RULE_DOCTYPE = "Nyabo Rule"
KIND = "bank_line"
FEE_PATTERN_ID = "bank_fee_expense"
INCOME_PATTERN_ID = "receivable_collect"
EXPENSE_PATTERN_ID = "bank_line_expense"  # no seed pattern: Дт 70 / Кт 11 direct; stays unverified
TRANSFER_PATTERN_ID = "bank_transfer_internal"  # no seed pattern: Дт 11 / Кт 11; stays unverified
DEFAULT_SCHEME = "v1"
MAX_EXPLANATION = 200
MAX_EXAMPLES = 20


class ProposalError(ValueError):
	def __init__(self, message_mn: str):
		super().__init__(message_mn)
		self.message_mn = message_mn


# --- rule lookup ------------------------------------------------------------------------------------


def _code_in_chart(company: str, code: str | None) -> bool:
	import frappe

	return bool(code) and bool(frappe.db.exists("Account", {"company": company, "account_number": str(code)}))


def chart_scheme(company: str) -> str:
	"""The scheme whose role codes exist in the company's chart.

	Nyabo Company Settings.chart_scheme is the declared value, but provisioning may have
	installed a different tree (V1 today, v0.3 later); the ``bank`` and ``receivable``
	roles are probed so a stale setting cannot send a fee to a code the chart lacks.
	"""
	schemes = load_seed("code_roles")["schemes"]
	declared = str(common.settings_value(company, "chart_scheme", DEFAULT_SCHEME) or DEFAULT_SCHEME)
	order = [declared] + [s for s in schemes if s != declared]
	for scheme in order:
		roles = schemes.get(scheme, {})
		if _code_in_chart(company, roles.get("bank")) and _code_in_chart(company, roles.get("receivable")):
			return scheme
	return declared


def role_code(company: str, role: str) -> str | None:
	"""Account code of a role for the company's chart scheme (code_roles.json)."""
	schemes = load_seed("code_roles")["schemes"]
	return schemes.get(chart_scheme(company), {}).get(role)


def bank_fee_rule(company: str) -> dict[str, Any] | None:
	"""The active bank_fee Nyabo Rule of the company, else the seed row for its scheme.

	The seed fallback exists so a site whose rules were not synced still proposes the
	fee to the ``bank_fee`` role account instead of the default expense.
	"""
	import frappe

	rows = frappe.get_all(
		RULE_DOCTYPE,
		filters={"company": company, "match_type": "bank_fee", "status": "active"},
		fields=["name", "match_value", "target_account_code", "posting_pattern", "hit_count"],
		order_by="modified desc",
		limit=1,
	)
	if rows:
		return dict(rows[0])
	scheme = chart_scheme(company)
	for row in load_seed("rules_default")["rows"]:
		if row.get("match_type") == "bank_fee" and row.get("scheme") == scheme:
			return {
				"name": None,
				"match_value": row.get("match_value"),
				"target_account_code": row.get("target_account_code") or role_code(company, "bank_fee"),
				"posting_pattern": row.get("posting_pattern") or FEE_PATTERN_ID,
				"hit_count": 0,
			}
	code = role_code(company, "bank_fee")
	if not code:
		return None
	return {"name": None, "match_value": "", "target_account_code": code, "posting_pattern": FEE_PATTERN_ID}


def is_fee_line(description: str, rule: Mapping[str, Any] | None) -> bool:
	"""The rule's keyword alternation decides; the core keyword list is the fallback."""
	pattern = (rule or {}).get("match_value") or ""
	if pattern:
		try:
			if re.search(pattern, description or "", flags=re.IGNORECASE):
				return True
		except re.error:
			pass
	return core_matching.is_bank_fee(description)


def _bump_rule(rule: Mapping[str, Any]) -> None:
	import frappe

	name = rule.get("name")
	if not name:
		return
	doc = frappe.get_doc(RULE_DOCTYPE, name)
	doc.hit_count = int(doc.hit_count or 0) + 1
	doc.last_hit = frappe.utils.now()
	doc.flags.ignore_permissions = True
	doc.save()


# --- patterns and accounts --------------------------------------------------------------------------


def pattern_citation(pattern_id: str) -> Citation:
	"""Citation of a seed pattern; unknown ids cite the instruction without a section (unverified)."""
	for row in load_seed("posting_patterns")["rows"]:
		if row.get("pattern_id") == pattern_id:
			cit = row.get("citation") or {}
			return Citation(
				instrument=str(cit.get("instrument") or "Заавар 116 (2000)"),
				section=cit.get("section"),
				verified=bool(cit.get("verified", False)),
				url=cit.get("url"),
				quote=cit.get("quote"),
			)
	return Citation(instrument="Заавар 116 (2000)", section=None, verified=False)


def pattern_link(pattern_id: str) -> str | None:
	import frappe

	return pattern_id if frappe.db.exists("Nyabo Posting Pattern", pattern_id) else None


def resolve_account(company: str, code: str | None) -> tuple[str | None, str | None]:
	"""(account name, code) for a code of this company's chart; (None, code) when absent."""
	from nyabo_mn.setup.chart import ChartError
	from nyabo_mn.setup.chart_db import account_for_code

	if not code:
		return None, None
	try:
		return account_for_code(company, str(code)), str(code)
	except ChartError:
		return None, str(code)


def default_expense(company: str) -> tuple[str | None, str | None]:
	"""Company Settings.default_expense_code, else the code of Company.default_expense_account."""
	import frappe

	code = common.settings_value(company, "default_expense_code")
	account, code = resolve_account(company, code) if code else (None, None)
	if account:
		return account, code
	account = frappe.db.get_value("Company", company, "default_expense_account")
	return account, common.account_code_of(account) or None


def existing_proposal(bank_transaction: str) -> str | None:
	import frappe

	return frappe.db.get_value(
		PROPOSAL_DOCTYPE, {"bank_transaction": bank_transaction, "status": "proposed"}, "name"
	)


def source_document_of(bank_transaction: str) -> str | None:
	"""The Nyabo Document whose import created this transaction (from the import event)."""
	import frappe

	rows = frappe.get_all(
		"Nyabo Event",
		filters={"event_type": "statement_imported", "ref_doctype": "Nyabo Document"},
		fields=["ref_name", "payload_json"],
		order_by="creation desc",
	)
	for row in rows:
		if bank_transaction in (common.event_payload(row).get("transactions") or []):
			return row.ref_name
	return None


# --- classification -------------------------------------------------------------------------------


def chart_leaves(company: str) -> list[tuple[str, str]]:
	import frappe

	rows = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "account_number": ["!=", ""], "disabled": 0},
		fields=["account_number", "account_name"],
		order_by="account_number asc",
	)
	return [(str(r.account_number), str(r.account_name)) for r in rows]


def recent_examples(company: str) -> list[dict[str, Any]]:
	import frappe

	rows = frappe.get_all(
		PROPOSAL_DOCTYPE,
		filters={"company": company, "kind": KIND, "status": ["in", ["approved", "posted"]]},
		fields=["account_code", "extracted_json"],
		order_by="modified desc",
		limit=MAX_EXAMPLES,
	)
	out: list[dict[str, Any]] = []
	for row in rows:
		extracted = row.extracted_json
		if isinstance(extracted, str):
			try:
				extracted = json.loads(extracted)
			except ValueError:
				extracted = {}
		out.append(
			{"description": (extracted or {}).get("description", ""), "account_code": row.account_code}
		)
	return out


def _regime_ctx(company: str, on_date: dt.date) -> dict[str, Any]:
	"""Only nyabo_mn.rules.regime knows regime names; ask it when it is installed."""
	try:
		from nyabo_mn.rules import regime  # type: ignore[import-not-found]
	except ImportError:
		return {}
	try:
		ctx = regime.posting_context(company, on_date)
	except Exception:  # noqa: BLE001 - a missing regime row must not block a proposal card
		return {}
	return {
		"is_vat_payer": bool(getattr(ctx, "is_vat_payer", False)),
		"regime": str(getattr(ctx, "regime", "")),
	}


def _llm_client(company: str):
	import frappe

	from nyabo_mn.agent import frappe_log
	from nyabo_mn.agent.llm_client import get_client
	from nyabo_mn.config import get_settings

	provider = "mock" if frappe.flags.get("nyabo_simulation") else "auto"
	return get_client(get_settings(), provider, record_call=frappe_log.recorder(company=company))


def classify_line(
	company: str, line: BankLine
) -> tuple[str | None, str, float, tuple[str, ...], dict[str, Any]]:
	"""(account code, reason, confidence, warnings, llm meta) for an outflow without a rule."""
	from nyabo_mn.agent import classify
	from nyabo_mn.agent.llm_client import LlmError
	from nyabo_mn.config import MissingSettingError

	leaves = chart_leaves(company)
	_default_account, default_code = default_expense(company)
	ctx: dict[str, Any] = {"company": company, "default_expense_code": default_code or ""}
	ctx.update(_regime_ctx(company, line.date))
	receipt_dict = {
		"seller_name": line.description,
		"seller_tin": None,
		"seller_register_no": None,
		"date": line.date.isoformat(),
		"total": str(abs(line.amount)),
		"vat_amount": None,
		"lines": [],
		"payment_method": "bank",
		"raw_text": line.description,
		"source": "bank_statement_line",
	}
	try:
		client = _llm_client(company)
		outcome = classify.classify_full(client, receipt_dict, leaves, recent_examples(company), ctx)
	except (MissingSettingError, LlmError, ValueError) as exc:
		return (
			default_code,
			mn.WARN_BANK_LINE_LLM_UNAVAILABLE,
			0.0,
			("llm_unavailable",),
			{"error": repr(exc)},
		)
	meta = {
		"prompt_version": outcome.llm.prompt_version,
		"model": outcome.llm.model,
		"tokens_in": outcome.llm.tokens_in,
		"tokens_out": outcome.llm.tokens_out,
		"latency_ms": outcome.llm.latency_ms,
	}
	return (
		outcome.result.account_code,
		outcome.result.reason_mn,
		outcome.result.confidence,
		outcome.warnings,
		meta,
	)


# --- proposal building ------------------------------------------------------------------------------


def _explanation(text: str, citation: Citation) -> str:
	suffix = citation_suffix(citation)
	room = MAX_EXPLANATION - len(suffix)
	if len(text) > room:
		text = text[: max(0, room - 1)] + "…"
	return text + suffix


def _bank_codes(bank_transaction: Mapping[str, Any]) -> tuple[str | None, str]:
	gl_account = common.gl_account_of(str(bank_transaction.get("bank_account") or ""))
	return gl_account, common.account_code_of(gl_account)


def _insert_proposal(values: Mapping[str, Any]) -> str:
	import frappe

	doc = frappe.get_doc({"doctype": PROPOSAL_DOCTYPE, "kind": KIND, "status": "proposed", **values})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _load_transaction(name: str) -> dict[str, Any]:
	import frappe

	if not frappe.db.exists("Bank Transaction", name):
		raise ProposalError(mn.MSG_BANK_TRANSACTION_NOT_FOUND.format(name=name))
	return frappe.get_doc("Bank Transaction", name).as_dict()


def propose_for_line(
	bank_transaction_name: str, *, document: str | None = None, account_code: str | None = None
) -> str:
	"""Create (or return) the bank_line proposal for one Bank Transaction.

	Fee lines follow the bank_fee rule; other outflows are classified by the model
	(mock under simulation); inflows go to the receivable role for the accountant to
	confirm. Every proposal links the transaction, its source document, the citation.
	``account_code`` is the accountant's choice from the [Зардал бүртгэх] chooser: it
	replaces both the fee rule and the model for that line.
	"""
	found = existing_proposal(bank_transaction_name)
	if found:
		return found
	bt = _load_transaction(bank_transaction_name)
	company = str(bt["company"])
	line = common.line_from_transaction(bt)
	_gl_account, bank_code = _bank_codes(bt)
	amount = abs(line.amount)
	warnings: list[str] = []
	meta: dict[str, Any] = {}
	rule_name: str | None = None
	confidence = 1.0
	rule = bank_fee_rule(company)

	if account_code:
		account, code = resolve_account(company, account_code)
		if account is None:
			raise ProposalError(mn.MSG_ACCOUNT_CODE_INVALID.format(code=account_code))
		if line.amount < 0:
			pattern_id = EXPENSE_PATTERN_ID
			text = mn.EXPL_BANK_LINE_EXPENSE.format(
				description=line.description[:60], debit_code=code, credit_code=bank_code
			)
			debit_code, credit_code = str(code), bank_code
		else:
			pattern_id = INCOME_PATTERN_ID
			text = mn.EXPL_BANK_LINE_INCOME.format(
				description=line.description[:60], debit_code=bank_code, credit_code=code
			)
			debit_code, credit_code = bank_code, str(code)
		citation = pattern_citation(pattern_id)
		lines = (
			ProposedLine(
				account_code=debit_code, debit=amount, credit=Decimal("0.00"), description=line.description
			),
			ProposedLine(
				account_code=credit_code, debit=Decimal("0.00"), credit=amount, description=line.description
			),
		)
	elif line.amount < 0 and rule and is_fee_line(line.description, rule):
		pattern_id = str(rule.get("posting_pattern") or FEE_PATTERN_ID)
		account, code = resolve_account(company, rule.get("target_account_code"))
		if account is None:
			account, code = default_expense(company)
			warnings.append("fee_account_missing")
		citation = pattern_citation(pattern_id)
		text = mn.EXPL_BANK_FEE.format(debit_code=code, credit_code=bank_code)
		lines = (
			ProposedLine(
				account_code=str(code), debit=amount, credit=Decimal("0.00"), description=line.description
			),
			ProposedLine(
				account_code=bank_code, debit=Decimal("0.00"), credit=amount, description=line.description
			),
		)
		rule_name = rule.get("name")
		_bump_rule(rule)
	elif line.amount < 0:
		pattern_id = EXPENSE_PATTERN_ID
		code, reason, confidence, llm_warnings, meta = classify_line(company, line)
		warnings.extend(llm_warnings)
		account, code = resolve_account(company, code)
		if account is None:
			account, code = default_expense(company)
			warnings.append("code_not_in_chart")
		citation = pattern_citation(pattern_id)
		text = mn.EXPL_BANK_LINE_EXPENSE.format(
			description=line.description[:60], debit_code=code, credit_code=bank_code
		)
		if reason and reason != mn.WARN_BANK_LINE_LLM_UNAVAILABLE:
			text = reason
		lines = (
			ProposedLine(
				account_code=str(code), debit=amount, credit=Decimal("0.00"), description=line.description
			),
			ProposedLine(
				account_code=bank_code, debit=Decimal("0.00"), credit=amount, description=line.description
			),
		)
	else:
		pattern_id = INCOME_PATTERN_ID
		account, code = resolve_account(company, role_code(company, "receivable"))
		warnings.append("income_unclassified")
		confidence = 0.0
		citation = pattern_citation(pattern_id)
		text = mn.EXPL_BANK_LINE_INCOME.format(
			description=line.description[:60], debit_code=bank_code, credit_code=code
		)
		lines = (
			ProposedLine(
				account_code=bank_code, debit=amount, credit=Decimal("0.00"), description=line.description
			),
			ProposedLine(
				account_code=str(code), debit=Decimal("0.00"), credit=amount, description=line.description
			),
		)

	if not citation.verified:
		warnings.append(mn.WARN_UNVERIFIED_RULE)
	entry = ProposedEntry(
		company=company,
		posting_date=line.date,
		lines=lines,
		pattern_id=pattern_id,
		citation=citation,
		explanation=_explanation(text, citation),
		document_kind="journal_entry",
		vat_treatment="none",
		warnings=tuple(warnings),
		total=amount,
		vat_amount=Decimal("0.00"),
	)
	needs_accountant = bool(warnings) or confidence < 0.7
	return _insert_proposal(
		{
			"document": document or source_document_of(bank_transaction_name),
			"company": company,
			"bank_transaction": bank_transaction_name,
			"needs_accountant": 1 if needs_accountant else 0,
			"posting_date": line.date,
			"total": float(amount),
			"vat_amount": 0.0,
			"vat_treatment": "none",
			"account_code": code,
			"account": account,
			"posting_pattern": pattern_link(pattern_id),
			"rule_applied": rule_name,
			"explanation": entry.explanation,
			"citation": citation_suffix(citation).strip(" —"),
			"entry_json": json.dumps(entry.to_dict(), ensure_ascii=False),
			"extracted_json": json.dumps(line.to_dict(), ensure_ascii=False),
			"confidence_json": json.dumps({"account_code": confidence}, ensure_ascii=False),
			"warnings_json": json.dumps(list(warnings), ensure_ascii=False),
			"prompt_version": meta.get("prompt_version"),
			"model": meta.get("model"),
			"tokens_in": meta.get("tokens_in"),
			"tokens_out": meta.get("tokens_out"),
			"latency_ms": meta.get("latency_ms"),
		}
	)


def propose_transfer(withdrawal_name: str, deposit_name: str, *, document: str | None = None) -> str:
	"""One proposal for an own-account transfer: Дт bank B (deposit) / Кт bank A (withdrawal).

	Linked to the withdrawal transaction; the deposit side is named in the entry so the
	posting handler can reconcile both lines against the Journal Entry it creates.
	"""
	found = existing_proposal(withdrawal_name)
	if found:
		return found
	out_bt = _load_transaction(withdrawal_name)
	in_bt = _load_transaction(deposit_name)
	company = str(out_bt["company"])
	out_line = common.line_from_transaction(out_bt)
	amount = abs(out_line.amount)
	from_account, from_code = _bank_codes(out_bt)
	to_account, to_code = _bank_codes(in_bt)
	citation = pattern_citation(TRANSFER_PATTERN_ID)
	warnings = [mn.WARN_UNVERIFIED_RULE] if not citation.verified else []
	entry = ProposedEntry(
		company=company,
		posting_date=out_line.date,
		lines=(
			ProposedLine(
				account_code=to_code, debit=amount, credit=Decimal("0.00"), description=out_line.description
			),
			ProposedLine(
				account_code=from_code, debit=Decimal("0.00"), credit=amount, description=out_line.description
			),
		),
		pattern_id=TRANSFER_PATTERN_ID,
		citation=citation,
		explanation=_explanation(
			mn.EXPL_BANK_TRANSFER.format(debit_code=to_code, credit_code=from_code), citation
		),
		document_kind="journal_entry",
		vat_treatment="none",
		warnings=tuple(warnings),
		total=quantize(amount),
		vat_amount=Decimal("0.00"),
	)
	payload = entry.to_dict()
	payload["transfer"] = {"withdrawal": withdrawal_name, "deposit": deposit_name}
	return _insert_proposal(
		{
			"document": document or source_document_of(withdrawal_name),
			"company": company,
			"bank_transaction": withdrawal_name,
			"needs_accountant": 1 if warnings else 0,
			"posting_date": out_line.date,
			"total": float(amount),
			"vat_amount": 0.0,
			"vat_treatment": "none",
			"account_code": to_code,
			"account": to_account,
			"posting_pattern": pattern_link(TRANSFER_PATTERN_ID),
			"explanation": entry.explanation,
			"citation": citation_suffix(citation).strip(" —"),
			"entry_json": json.dumps(payload, ensure_ascii=False),
			"extracted_json": json.dumps(
				{"withdrawal": out_line.to_dict(), "deposit": common.line_from_transaction(in_bt).to_dict()},
				ensure_ascii=False,
			),
			"confidence_json": json.dumps({"account_code": 1.0}),
			"warnings_json": json.dumps(warnings, ensure_ascii=False),
		}
	)


__all__ = [
	"EXPENSE_PATTERN_ID",
	"FEE_PATTERN_ID",
	"INCOME_PATTERN_ID",
	"KIND",
	"TRANSFER_PATTERN_ID",
	"ProposalError",
	"bank_fee_rule",
	"chart_leaves",
	"classify_line",
	"existing_proposal",
	"is_fee_line",
	"propose_for_line",
	"propose_transfer",
	"resolve_account",
	"role_code",
	"source_document_of",
]
