"""From an approved proposal to a submitted ERPNext document, and the accountant's other taps.

``post_proposal`` is the only code path that inserts an accounting document from the bot
(docs/ARCHITECTURE.md §5.3 step 6). Before ``insert()`` it checks, in this order: the
approver's right to approve, that the posting pattern is verified (``require_verified``,
principle §1.2), that the company has a regime on the posting date, and that the posting
date is not inside a closed Accounting Period (a Mongolian refusal instead of ERPNext's
English one). Then a Purchase Invoice (input VAT withheld) or a Journal Entry (everything
else), with the audit custom fields, is inserted and submitted.

The other functions are the buttons on the card: change account, reject, list / search
accounts, make a correction proposal after a reversal, confirm a learned rule. Learned
rules (§5.6) are created from two agreeing ``Nyabo Correction`` rows and start as
``pending_confirmation`` - they never post anything until an accountant confirms them.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from nyabo_mn.agent import pipeline
from nyabo_mn.core import dates, rules_engine
from nyabo_mn.core.models import ProposedEntry, ProposedLine
from nyabo_mn.core.money import ZERO
from nyabo_mn.i18n import mn

logger = logging.getLogger("nyabo.agent")

ROLE_ACCOUNTANT = "Nyabo Accountant"
ROLE_ADMIN = "Nyabo Admin"
ROLE_OWNER = "Nyabo Owner"
ROLE_SYSTEM = "System Manager"
POSTABLE_STATUSES = ("proposed", "approved")
ITEM_UOM = "Nos"  # ERPNext's stock UOM default; present on every site's UOM list
LEARN_MIN_CORRECTIONS = 2
TOP_ACCOUNTS_DAYS = 90
SEARCH_LIMIT = 10


class ApprovalError(Exception):
	"""The tap is refused; ``message_mn`` is the reply."""

	def __init__(self, message_mn: str, *, code: str = "refused"):
		super().__init__(message_mn)
		self.message_mn = message_mn
		self.code = code


class ClosedPeriodError(ApprovalError):
	"""The posting date sits inside a closed Accounting Period."""


# --- lookups -------------------------------------------------------------------------------------


def _proposal(name: str) -> Any:
	import frappe

	if not frappe.db.exists("Nyabo Proposal", name):
		raise ApprovalError(mn.MSG_PROPOSAL_NOT_FOUND, code="not_found")
	return frappe.get_doc("Nyabo Proposal", name)


def _entry(proposal: Any) -> ProposedEntry:
	data = pipeline.loads(proposal.entry_json)
	if not data:
		raise ApprovalError(mn.MSG_PROPOSAL_NOT_FOUND, code="no_entry")
	return ProposedEntry.from_dict(data)


def _user_link(user: str) -> Any | None:
	import frappe

	name = frappe.db.get_value("Nyabo User Link", {"user": user, "status": "active"}, "name")
	return frappe.get_doc("Nyabo User Link", name) if name else None


def approver_kind(company: str, user: str) -> str | None:
	"""``accountant`` / ``owner`` / ``None``: who this user is for the company (§5.3 step 7)."""
	import frappe

	settings = pipeline.company_settings(company)
	if settings and settings.get("accountant_user") == user:
		return "accountant"
	roles = set(frappe.get_roles(user))
	if roles & {ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_SYSTEM} or user == "Administrator":
		return "accountant"
	link = _user_link(user)
	if link is not None:
		companies = {row.company for row in (link.get("companies") or [])}
		if not companies or company in companies:
			if link.role in ("Accountant", "Admin"):
				return "accountant"
			if link.role == "Owner":
				return "owner"
	if ROLE_OWNER in roles:
		return "owner"
	return None


def check_can_approve(proposal: Any, user: str) -> None:
	kind = approver_kind(proposal.company, user)
	if kind is None:
		raise ApprovalError(mn.MSG_NO_PERMISSION, code="no_permission")
	if kind == "owner" and int(proposal.needs_accountant or 0):
		raise ApprovalError(mn.MSG_ACCOUNTANT_ONLY, code="accountant_only")


# --- period guard --------------------------------------------------------------------------------


def closed_period_for(company: str, doctype: str, posting_date: dt.date) -> str | None:
	"""Name of the Accounting Period that closes ``doctype`` on the date, or None."""
	import frappe
	from frappe.utils import getdate

	for period in frappe.get_all(
		"Accounting Period",
		filters={"company": company, "disabled": 0},
		fields=["name", "start_date", "end_date"],
	):
		if not (getdate(period.start_date) <= posting_date <= getdate(period.end_date)):
			continue
		closed = frappe.get_all(
			"Closed Document",
			filters={
				"parent": period.name,
				"parenttype": "Accounting Period",
				"document_type": doctype,
				"closed": 1,
			},
		)
		if closed:
			return period.name
	return None


def refuse_if_closed(company: str, doctype: str, posting_date: dt.date) -> None:
	period = closed_period_for(company, doctype, posting_date)
	if period:
		raise ClosedPeriodError(
			mn.MSG_POSTING_IN_CLOSED_PERIOD.format(
				date=posting_date.isoformat(), period=dates.period_label(dates.period_of(posting_date))
			),
			code="closed_period",
		)


# --- document builders -----------------------------------------------------------------------------


def _account_name(company: str, code: str) -> str:
	from nyabo_mn.setup.chart_db import account_for_code

	return account_for_code(company, code)


def _account_type(company: str, code: str) -> str:
	import frappe

	return str(
		frappe.db.get_value("Account", {"company": company, "account_number": code}, "account_type") or ""
	)


def _purchase_tax_template(company: str) -> tuple[str | None, str | None]:
	"""``(template name, account_head)`` of the input-VAT purchase template, if provisioned."""
	import frappe

	from nyabo_mn.setup.taxes import PURCHASE_TEMPLATE_TITLE

	name = frappe.db.get_value(
		"Purchase Taxes and Charges Template", {"company": company, "title": PURCHASE_TEMPLATE_TITLE}, "name"
	)
	if not name:
		return None, None
	template = frappe.get_doc("Purchase Taxes and Charges Template", name)
	rows = template.get("taxes") or []
	return name, (rows[0].account_head if rows else None)


def audit_fields(
	proposal: Any, approver_user: str, extracted: dict[str, Any], verification: dict[str, Any]
) -> dict[str, Any]:
	seller = verification.get("seller") or {}
	receipt_date = extracted.get("date")
	return {
		"ebarimt_receipt_id": extracted.get("receipt_id"),
		"ebarimt_lottery_no": extracted.get("lottery_no"),
		"ebarimt_datetime": f"{receipt_date} 00:00:00" if receipt_date else None,
		"ebarimt_verified": 1 if seller.get("found") else 0,
		"ebarimt_qr_data": verification.get("qr_data"),
		"source_document": proposal.document,
		"nyabo_proposal": proposal.name,
		"nyabo_explanation": proposal.explanation,
		"nyabo_prompt_version": proposal.prompt_version,
		"nyabo_approved_by": approver_user,
	}


def _split_lines(
	company: str, entry: ProposedEntry
) -> tuple[list[ProposedLine], ProposedLine | None, list[ProposedLine]]:
	"""``(debit lines, VAT line, credit lines)``; the VAT line is the debit on a Tax-type account."""
	debits = [line for line in entry.lines if line.debit > ZERO]
	credits = [line for line in entry.lines if line.credit > ZERO]
	vat_line = None
	if entry.vat_treatment == "withheld" and entry.vat_amount > ZERO:
		for line in debits:
			if _account_type(company, line.account_code) == "Tax" and line.debit == entry.vat_amount:
				vat_line = line
				break
	return [line for line in debits if line is not vat_line], vat_line, credits


def build_purchase_invoice(proposal: Any, entry: ProposedEntry, approver_user: str) -> dict[str, Any]:
	import frappe

	company = proposal.company
	if not proposal.supplier:
		raise ApprovalError(mn.MSG_SUPPLIER_REQUIRED_FOR_INVOICE, code="supplier_required")
	extracted = pipeline.loads(proposal.extracted_json) or {}
	verification = pipeline.loads(proposal.verification_json) or {}
	debits, vat_line, _credits = _split_lines(company, entry)
	if not debits:
		raise ApprovalError(mn.MSG_PROPOSAL_NOT_POSTABLE.format(status=proposal.status), code="no_lines")
	lines = extracted.get("lines") or []
	first_description = str(lines[0].get("description") or "") if lines and isinstance(lines[0], dict) else ""
	items = []
	for line in debits:
		items.append(
			{
				"item_name": (line.description or first_description or proposal.supplier)[:140],
				"description": line.description or first_description or proposal.supplier,
				"qty": 1,
				"uom": ITEM_UOM,
				"conversion_factor": 1,
				"rate": float(line.debit),
				"expense_account": _account_name(company, line.account_code),
			}
		)
	taxes: list[dict[str, Any]] = []
	template_name = None
	if vat_line is not None:
		template_name, account_head = _purchase_tax_template(company)
		account_head = account_head or _account_name(company, vat_line.account_code)
		# "Actual" books the VAT printed on the receipt exactly; validate_entry already
		# checked it against the rate within a tögrög (D-002).
		taxes.append(
			{
				"category": "Total",
				"add_deduct_tax": "Add",
				"charge_type": "Actual",
				"account_head": account_head,
				"description": mn.TAX_PURCHASE_VAT_10,
				"tax_amount": float(vat_line.debit),
			}
		)
	currency = frappe.get_cached_value("Company", company, "default_currency") or "MNT"
	doc: dict[str, Any] = {
		"doctype": "Purchase Invoice",
		"company": company,
		"supplier": proposal.supplier,
		"posting_date": entry.posting_date,
		"set_posting_time": 1,
		"due_date": entry.posting_date,
		"currency": currency,
		"conversion_rate": 1,
		"bill_no": extracted.get("receipt_id") or None,
		"bill_date": entry.posting_date if extracted.get("receipt_id") else None,
		"items": items,
		"taxes": taxes,
		"remarks": proposal.explanation,
		**audit_fields(proposal, approver_user, extracted, verification),
	}
	if template_name:
		doc["taxes_and_charges"] = template_name
	return doc


def build_journal_entry(proposal: Any, entry: ProposedEntry, approver_user: str) -> dict[str, Any]:
	company = proposal.company
	extracted = pipeline.loads(proposal.extracted_json) or {}
	verification = pipeline.loads(proposal.verification_json) or {}
	accounts = []
	for line in entry.lines:
		row: dict[str, Any] = {
			"account": _account_name(company, line.account_code),
			"debit_in_account_currency": float(line.debit),
			"credit_in_account_currency": float(line.credit),
			"user_remark": line.description or None,
		}
		if line.party_type and line.party:
			row["party_type"], row["party"] = line.party_type, line.party
		elif proposal.supplier and _account_type(company, line.account_code) == "Payable":
			row["party_type"], row["party"] = "Supplier", proposal.supplier
		accounts.append(row)
	return {
		"doctype": "Journal Entry",
		"voucher_type": "Journal Entry",
		"company": company,
		"posting_date": entry.posting_date,
		"accounts": accounts,
		"user_remark": proposal.explanation,
		"bill_no": extracted.get("receipt_id") or None,
		**audit_fields(proposal, approver_user, extracted, verification),
	}


# --- posting -------------------------------------------------------------------------------------


def post_proposal(
	proposal_name: str, approver_user: str, approver_telegram_id: str | None = None
) -> dict[str, str]:
	"""Insert and submit the ERPNext document for an approved proposal; idempotent."""
	import frappe

	proposal = _proposal(proposal_name)
	if proposal.status == "posted" and proposal.posted_name:
		return {"posted_doctype": proposal.posted_doctype, "posted_name": proposal.posted_name}
	if proposal.status not in POSTABLE_STATUSES:
		raise ApprovalError(mn.MSG_PROPOSAL_ALREADY_DECIDED.format(status=proposal.status), code="decided")

	check_can_approve(proposal, approver_user)
	entry = _entry(proposal)
	pattern = pipeline.pattern_by_id(entry.pattern_id)
	pipeline.require_verified(pattern)
	pipeline.regime_context(proposal.company, entry.posting_date)  # raises MissingRuleError without a regime
	doctype = rules_engine.DOCUMENT_KIND_TO_DOCTYPE[entry.document_kind]
	refuse_if_closed(proposal.company, doctype, entry.posting_date)

	if entry.document_kind == "purchase_invoice":
		payload = build_purchase_invoice(proposal, entry, approver_user)
	else:
		payload = build_journal_entry(proposal, entry, approver_user)

	doc = frappe.get_doc(payload)
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()

	from frappe.utils import now_datetime

	proposal.db_set(
		{
			"status": "posted",
			"approved_by": approver_user,
			"approved_telegram_id": approver_telegram_id,
			"approved_at": now_datetime(),
			"posted_doctype": doc.doctype,
			"posted_name": doc.name,
		}
	)
	if proposal.document and frappe.db.exists("Nyabo Document", proposal.document):
		frappe.db.set_value(
			"Nyabo Document",
			proposal.document,
			{"status": "posted", "posted_doctype": doc.doctype, "posted_name": doc.name},
		)
	pipeline.write_event(
		"proposal_posted",
		company=proposal.company,
		actor_user=approver_user,
		actor_telegram_id=approver_telegram_id,
		ref_doctype=doc.doctype,
		ref_name=doc.name,
		payload={"proposal": proposal.name, "pattern": entry.pattern_id, "total": str(entry.total)},
	)
	from nyabo_mn.agent import few_shot

	few_shot.invalidate(proposal.company)
	return {"posted_doctype": doc.doctype, "posted_name": doc.name}


# --- card buttons: change account, reject ---------------------------------------------------------------


def _leaf_codes(company: str) -> dict[str, str]:
	return dict(pipeline.chart_leaves(company))


def _write_correction(
	proposal: Any,
	*,
	field: str,
	proposed_value: str | None,
	corrected_value: str | None,
	user: str,
	source: str = "edit",
	reason: str | None = None,
	reason_text: str | None = None,
	telegram_id: str | None = None,
) -> Any:
	import frappe

	doc = frappe.get_doc(
		{
			"doctype": "Nyabo Correction",
			"proposal": proposal.name,
			"company": proposal.company,
			"field": field,
			"proposed_value": proposed_value,
			"corrected_value": corrected_value,
			"corrected_by": user,
			"corrected_telegram_id": telegram_id,
			"reason": reason,
			"reason_text": reason_text,
			"source": source,
			"supplier": proposal.supplier,
			"posted_doctype": proposal.posted_doctype,
			"posted_name": proposal.posted_name,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def change_account(proposal_name: str, code: str, user: str, *, telegram_id: str | None = None) -> Any:
	"""Swap the classified account on the proposal; records a ``Nyabo Correction`` (field account_code)."""
	proposal = _proposal(proposal_name)
	if proposal.status not in POSTABLE_STATUSES:
		raise ApprovalError(mn.MSG_PROPOSAL_ALREADY_DECIDED.format(status=proposal.status), code="decided")
	code = str(code).strip()
	leaves = _leaf_codes(proposal.company)
	if code not in leaves:
		raise ApprovalError(mn.MSG_ACCOUNT_CODE_INVALID.format(code=code), code="invalid_account")
	old_code = str(proposal.account_code or "")
	if code == old_code:
		return proposal
	entry = _entry(proposal)
	lines = [
		ProposedLine(**{**line.to_dict(), "account_code": code}) if line.account_code == old_code else line
		for line in entry.lines
	]
	new_entry = ProposedEntry.from_dict({**entry.to_dict(), "lines": [line.to_dict() for line in lines]})
	proposal.db_set(
		{
			"account_code": code,
			"account": _account_name(proposal.company, code),
			"entry_json": pipeline.dumps(new_entry.to_dict()),
		}
	)
	_write_correction(
		proposal,
		field="account_code",
		proposed_value=old_code,
		corrected_value=code,
		user=user,
		telegram_id=telegram_id,
	)
	pipeline.write_event(
		"proposal_account_changed",
		company=proposal.company,
		actor_user=user,
		actor_telegram_id=telegram_id,
		ref_doctype="Nyabo Proposal",
		ref_name=proposal.name,
		payload={"from": old_code, "to": code},
	)
	return proposal


def reject(proposal_name: str, reason_code: str, user: str, *, telegram_id: str | None = None) -> Any:
	import frappe

	proposal = _proposal(proposal_name)
	if proposal.status not in POSTABLE_STATUSES:
		raise ApprovalError(mn.MSG_PROPOSAL_ALREADY_DECIDED.format(status=proposal.status), code="decided")
	reason = mn.REJECT_REASONS.get(reason_code, mn.REJECT_OTHER)
	proposal.db_set({"status": "rejected", "rejection_reason": reason, "approved_by": user})
	if proposal.document and frappe.db.exists("Nyabo Document", proposal.document):
		frappe.db.set_value("Nyabo Document", proposal.document, "status", "rejected")
	_write_correction(
		proposal,
		field="rejected",
		proposed_value=str(proposal.account_code or ""),
		corrected_value=None,
		user=user,
		source="rejection",
		reason=reason_code,
		reason_text=reason,
		telegram_id=telegram_id,
	)
	pipeline.write_event(
		"proposal_rejected",
		company=proposal.company,
		actor_user=user,
		actor_telegram_id=telegram_id,
		ref_doctype="Nyabo Proposal",
		ref_name=proposal.name,
		reason=reason,
	)
	return proposal


# --- account pickers --------------------------------------------------------------------------------------


def top_accounts(company: str, n: int = 6) -> list[tuple[str, str]]:
	"""Most used codes in the last 90 days of approved proposals, then chart defaults, ``n`` total."""
	import frappe

	leaves = _leaf_codes(company)
	since = dt.date.today() - dt.timedelta(days=TOP_ACCOUNTS_DAYS)
	counts: dict[str, int] = {}
	for row in frappe.get_all(
		"Nyabo Proposal",
		filters={"company": company, "status": ["in", ["approved", "posted"]], "modified": [">=", since]},
		fields=["account_code"],
	):
		if row.account_code in leaves:
			counts[row.account_code] = counts.get(row.account_code, 0) + 1
	ordered = [code for code, _c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
	settings = pipeline.company_settings(company)
	default = str((settings.get("default_expense_code") if settings else "") or "")
	if default in leaves and default not in ordered:
		ordered.append(default)
	for code, _name in pipeline.chart_leaves(company):
		if len(ordered) >= n:
			break
		if code not in ordered and _is_expense_leaf(company, code):
			ordered.append(code)
	return [(code, leaves[code]) for code in ordered[:n]]


def _is_expense_leaf(company: str, code: str) -> bool:
	account_type, root_type = pipeline.account_types(company).get(code, ("", ""))
	return root_type == "Expense" and account_type in ("Expense Account", "")


def search_accounts(company: str, query: str) -> list[tuple[str, str]]:
	"""Leaves whose code starts with the query or whose name contains it (case-insensitive)."""
	needle = (query or "").strip().lower()
	if not needle:
		return []
	hits = [
		(code, name)
		for code, name in pipeline.chart_leaves(company)
		if code.startswith(needle) or needle in name.lower()
	]
	return hits[:SEARCH_LIMIT]


# --- corrections after a reversal (§5.6) -------------------------------------------------------------


def make_correction_proposal(original_doctype: str, original_name: str, reason_code: str, user: str) -> str:
	"""A new proposal pre-filled from the original document's Nyabo proposal (kind ``correction``)."""
	import frappe

	original = frappe.get_doc(original_doctype, original_name)
	source_name = original.get("nyabo_proposal")
	if not source_name or not frappe.db.exists("Nyabo Proposal", source_name):
		raise ApprovalError(mn.MSG_CORRECTION_ORIGINAL_NOT_NYABO.format(name=original_name), code="not_nyabo")
	source = frappe.get_doc("Nyabo Proposal", source_name)
	entry = _entry(source)
	reason = mn.CORRECT_REASONS.get(reason_code, mn.CORRECT_OTHER)
	explanation = (mn.EXPL_CORRECTION_PREFIX.format(reason=reason) + (source.explanation or ""))[
		: pipeline.EXPLANATION_MAX
	]
	values = {
		"doctype": "Nyabo Proposal",
		"document": source.document,
		"company": source.company,
		"kind": "correction",
		"status": "proposed",
		"needs_accountant": 1,
		"supplier": source.supplier,
		"supplier_is_new": 0,
		"posting_date": entry.posting_date,
		"total": float(entry.total),
		"vat_amount": float(entry.vat_amount),
		"vat_treatment": source.vat_treatment,
		"account_code": source.account_code,
		"account": source.account,
		"posting_pattern": source.posting_pattern,
		"rule_applied": None,
		"explanation": explanation,
		"citation": source.citation,
		"entry_json": pipeline.dumps({**entry.to_dict(), "explanation": explanation}),
		"extracted_json": source.extracted_json,
		"verification_json": source.verification_json,
		"confidence_json": source.confidence_json,
		"warnings_json": source.warnings_json,
		"prompt_version": source.prompt_version,
		"model": source.model,
	}
	proposal = frappe.get_doc(values)
	proposal.flags.ignore_permissions = True
	proposal.insert()
	pipeline.write_event(
		"correction_proposal_created",
		company=source.company,
		actor_user=user,
		ref_doctype="Nyabo Proposal",
		ref_name=proposal.name,
		reason=reason,
		payload={
			"original_doctype": original_doctype,
			"original_name": original_name,
			"source_proposal": source.name,
		},
	)
	return proposal.name


# --- learned rules -----------------------------------------------------------------------------------------


def _description_key(proposal_name: str) -> str | None:
	import frappe

	extracted = pipeline.loads(frappe.db.get_value("Nyabo Proposal", proposal_name, "extracted_json")) or {}
	lines = extracted.get("lines") or []
	if lines and isinstance(lines[0], dict) and lines[0].get("description"):
		return str(lines[0]["description"]).strip().lower()
	return None


def learn_from_correction(correction: Any) -> str | None:
	"""Two agreeing account corrections for one supplier (or description) -> a pending ``Nyabo Rule``.

	Returns the rule name when one was created. Nothing is created when a rule for the
	same target already exists, so a third correction does not spawn a duplicate.
	"""
	import frappe

	if correction.field != "account_code" or not correction.corrected_value:
		return None
	company = correction.company
	target = str(correction.corrected_value)
	siblings = frappe.get_all(
		"Nyabo Correction",
		filters={"company": company, "field": "account_code", "corrected_value": target},
		fields=["name", "supplier", "proposal"],
		order_by="creation asc",
	)
	if correction.supplier:
		group = [row for row in siblings if row.supplier == correction.supplier]
		match_type = "supplier_register_no"
		register_no = frappe.db.get_value("Supplier", correction.supplier, "register_no")
		match_value = register_no
		if not match_value:
			match_type = "supplier_name_pattern"
			match_value = (
				frappe.db.get_value("Supplier", correction.supplier, "supplier_name") or correction.supplier
			)
	else:
		key = _description_key(correction.proposal) if correction.proposal else None
		if not key:
			return None
		group = [row for row in siblings if row.proposal and _description_key(row.proposal) == key]
		match_type, match_value = "description_pattern", key
	if len(group) < LEARN_MIN_CORRECTIONS:
		return None
	existing = frappe.db.exists(
		"Nyabo Rule",
		{
			"company": company,
			"match_type": match_type,
			"match_value": match_value,
			"target_account_code": target,
			"status": ["in", ["active", "pending_confirmation"]],
		},
	)
	if existing:
		return None
	vat_treatment = (
		frappe.db.get_value("Nyabo Proposal", correction.proposal, "vat_treatment")
		if correction.proposal
		else None
	)
	rule = frappe.get_doc(
		{
			"doctype": "Nyabo Rule",
			"company": company,
			"match_type": match_type,
			"match_value": match_value,
			"target_account_code": target,
			"vat_treatment": vat_treatment or "none",
			"source": "learned",
			"status": "pending_confirmation",
			"created_from_corrections": ", ".join(row.name for row in group),
		}
	)
	rule.flags.ignore_permissions = True
	rule.insert()
	pipeline.write_event(
		"rule_learned",
		company=company,
		ref_doctype="Nyabo Rule",
		ref_name=rule.name,
		reason=mn.MSG_RULE_LEARNED.format(rule=rule.name),
		payload={"corrections": [row.name for row in group]},
	)
	return rule.name


def confirm_rule(name: str, user: str) -> Any:
	import frappe

	rule = frappe.get_doc("Nyabo Rule", name)
	if approver_kind(rule.company, user) != "accountant":
		raise ApprovalError(mn.MSG_NO_PERMISSION, code="no_permission")
	rule.db_set({"status": "active"})
	pipeline.write_event(
		"rule_confirmed",
		company=rule.company,
		actor_user=user,
		ref_doctype="Nyabo Rule",
		ref_name=rule.name,
		reason=mn.MSG_RULE_CONFIRMED.format(rule=rule.name),
	)
	return rule


__all__ = [
	"ITEM_UOM",
	"LEARN_MIN_CORRECTIONS",
	"POSTABLE_STATUSES",
	"ApprovalError",
	"ClosedPeriodError",
	"approver_kind",
	"audit_fields",
	"build_journal_entry",
	"build_purchase_invoice",
	"change_account",
	"check_can_approve",
	"closed_period_for",
	"confirm_rule",
	"learn_from_correction",
	"make_correction_proposal",
	"post_proposal",
	"refuse_if_closed",
	"reject",
	"search_accounts",
	"top_accounts",
]
