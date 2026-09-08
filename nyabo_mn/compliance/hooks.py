"""Document-level compliance constraints (doc_events in nyabo_mn/hooks.py).

Law on Accounting: no entry without a primary document (art. 13.7), documents kept ten
years (art. 11.1), corrections only by reversal (art. 15). ERPNext enforces none of these
by itself, so every handler here refuses the operation with a Mongolian message instead
of relying on the bot to behave. Handler signature is Frappe's ``(doc, method=None)``.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import frappe
from frappe.utils import add_years, formatdate, getdate, nowdate

from nyabo_mn.core.rules_engine import ParameterRow, RuleError, resolve_parameter
from nyabo_mn.i18n import mn
from nyabo_mn.nyabo.seed import load_seed

EXPLANATION_MAX_LENGTH = 300
RETENTION_PARAMETER_KEY = "retention.years"
# Fields a submitted accounting document may still change: Nyabo's own audit trail and the
# free-text remark ERPNext lets users edit after submit.
EDITABLE_AFTER_SUBMIT: frozenset[str] = frozenset({"remarks"})
EDITABLE_PREFIX = "nyabo_"
# Standard columns Frappe rewrites on every save; never a user edit.
_SYSTEM_FIELDS: frozenset[str] = frozenset(
	{"modified", "modified_by", "idx", "docstatus", "creation", "owner", "_user_tags", "_comments"}
)
RETAINED_PARENTS: dict[str, str] = {
	"Nyabo Document": "retain_until",
	"Purchase Invoice": "nyabo_retain_until",
	"Journal Entry": "nyabo_retain_until",
	"Sales Invoice": "nyabo_retain_until",
	"Payment Entry": "nyabo_retain_until",
}
PRIMARY_DOCUMENT_DOCTYPES: frozenset[str] = frozenset({"Purchase Invoice", "Journal Entry", "Payment Entry"})
# Fields that mark a document as Nyabo's own: the proposal it came from, the Nyabo Document
# behind it, or the Mongolian explanation every Nyabo posting carries. A settlement Payment
# Entry has no proposal, so asking for that alone left it deletable after cancel (COMP-10).
NYABO_TRAIL_FIELDS: tuple[str, ...] = ("nyabo_proposal", "source_document", "nyabo_explanation")
# Journal Entries ERPNext builds and submits itself: asset depreciation and disposal
# (erpnext/assets/doctype/asset/depreciation.py, a daily scheduler job), exchange-rate
# revaluation and its gain/loss entry (erpnext/accounts/utils.py), and opening entries.
# They carry no Nyabo Document, no written reference and no attachment, so the art. 13.7
# rule would refuse a posting no human made; their primary document is ERPNext's own
# register or calculation sheet, which is stamped on the entry instead.
SYSTEM_GENERATED_VOUCHER_TYPES: frozenset[str] = frozenset(
	{
		"Depreciation Entry",
		"Asset Disposal",
		"Exchange Rate Revaluation",
		"Exchange Gain Or Loss",
		"Opening Entry",
	}
)


def retention_years(on_date: dt.date | str | None = None) -> int:
	"""Retention period from the ``retention.years`` tax parameter (data, not a constant).

	Rows in the Nyabo Tax Parameter table win; before the seed is synced the shipped
	seed file is read, because a document received on day one must still carry a date.
	"""
	on = getdate(on_date) if on_date else getdate(nowdate())
	rows: list[ParameterRow] = []
	if frappe.db.exists("DocType", "Nyabo Tax Parameter"):
		for row in frappe.get_all(
			"Nyabo Tax Parameter",
			filters={"key": RETENTION_PARAMETER_KEY},
			fields=["key", "value_json", "unit", "effective_from", "effective_to", "status", "verified"],
		):
			value = row.get("value_json")
			if isinstance(value, str):
				value = frappe.parse_json(value)
			rows.append(ParameterRow.from_dict({**row, "value": value}))
	if not rows:
		rows = [
			ParameterRow.from_dict(r)
			for r in load_seed("tax_parameters")["rows"]
			if r.get("key") == RETENTION_PARAMETER_KEY
		]
	try:
		return int(resolve_parameter(rows, RETENTION_PARAMETER_KEY, on).as_decimal())
	except RuleError as exc:
		frappe.throw(exc.message_mn)
		raise  # unreachable; keeps type checkers honest


def _retain_until(start: dt.date | str | None) -> dt.date:
	start_date = getdate(start) if start else getdate(nowdate())
	return getdate(add_years(start_date, retention_years(start_date)))


# --- validate ------------------------------------------------------------------------------


def validate_accounting_document(doc: Any, method: str | None = None) -> None:
	"""Explanation length, proposal link integrity, retention date (PI / JE / SI)."""
	explanation = doc.get("nyabo_explanation") or ""
	if len(explanation) > EXPLANATION_MAX_LENGTH:
		frappe.throw(mn.MSG_EXPLANATION_TOO_LONG.format(max=EXPLANATION_MAX_LENGTH, length=len(explanation)))
	proposal = doc.get("nyabo_proposal")
	if proposal:
		proposal_company = frappe.db.get_value("Nyabo Proposal", proposal, "company")
		if proposal_company is None:
			frappe.throw(mn.MSG_PROPOSAL_MISSING_ON_DOCUMENT.format(proposal=proposal))
		if proposal_company != doc.company:
			frappe.throw(
				mn.MSG_PROPOSAL_COMPANY_MISMATCH.format(
					proposal=proposal, proposal_company=proposal_company, company=doc.company
				)
			)
	if doc.meta.has_field("nyabo_retain_until"):
		doc.nyabo_retain_until = _retain_until(doc.get("posting_date"))


def _has_attachment(doc: Any) -> bool:
	if doc.is_new() or not doc.name:
		return False
	return bool(
		frappe.get_all(
			"File",
			filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
			limit=1,
			pluck="name",
		)
	)


def system_generated_source(doc: Any) -> str | None:
	"""What ERPNext generated this Journal Entry from, or None when a person made it.

	``is_system_generated`` is set only on the Exchange Gain Or Loss entries, so the
	voucher type carries the rest (depreciation, disposal, revaluation, opening); a
	reversal is generated from the entry it reverses.
	"""
	if doc.doctype != "Journal Entry":
		return None
	if doc.get("reversal_of"):
		return str(doc.get("reversal_of"))
	voucher_type = (doc.get("voucher_type") or "").strip()
	if int(doc.get("is_system_generated") or 0) or voucher_type in SYSTEM_GENERATED_VOUCHER_TYPES:
		return voucher_type or doc.doctype
	return None


def has_nyabo_trail(doc: Any) -> bool:
	"""True when the document carries one of Nyabo's own audit fields (NYABO_TRAIL_FIELDS)."""
	return any(str(doc.get(field) or "").strip() for field in NYABO_TRAIL_FIELDS)


def require_primary_document(doc: Any, method: str | None = None) -> None:
	"""before_submit: a Nyabo Document, a written reference or an attached File (art. 13.7).

	An entry ERPNext generated itself (depreciation, revaluation, a reversal) has none of
	the three and no human to ask, so instead of breaking the ERPNext feature the handler
	writes what produced it into ``nyabo_primary_document_ref``: the trail art. 13.7 wants
	stays on the document, and the entry says in Mongolian that no person filed a receipt.

	A Payment Entry is the exception the other two doctypes do not need. Nyabo did not put
	it on the site: ERPNext submits Payment Entries of its own from the desk, from the Bank
	Reconciliation Tool (``bank_reconciliation_tool.create_payment_entry_bts``, which builds
	``frappe.new_doc("Payment Entry")`` and calls ``pe.insert(); pe.submit()`` with no Nyabo
	field on it) and from a Payment Request, none of which can name a primary document, and
	Journal Entry's escape hatch (``system_generated_source``) answers None for anything that
	is not a Journal Entry. Asking art. 13.7 of every Payment Entry therefore refused every
	payment the site made. The rule is asked of the ones Nyabo posts — a settlement stamps
	``source_document``, ``nyabo_explanation`` and ``nyabo_primary_document_ref`` — which is
	exactly what ``has_nyabo_trail`` recognises (COMP-10).
	"""
	if doc.doctype not in PRIMARY_DOCUMENT_DOCTYPES:
		return
	if doc.doctype == "Payment Entry" and not has_nyabo_trail(doc):
		return
	if doc.get("source_document") or (doc.get("nyabo_primary_document_ref") or "").strip():
		return
	source = system_generated_source(doc)
	if source:
		doc.nyabo_primary_document_ref = mn.MSG_PRIMARY_DOCUMENT_SYSTEM_GENERATED.format(source=source)
		return
	if _has_attachment(doc):
		return
	frappe.throw(mn.MSG_PRIMARY_DOCUMENT_REQUIRED)


# --- no edit after submit ------------------------------------------------------------------


def _editable(fieldname: str) -> bool:
	return fieldname.startswith(EDITABLE_PREFIX) or fieldname in EDITABLE_AFTER_SUBMIT


def _row_values(row: Any, table_meta: Any) -> dict[str, Any]:
	"""Comparable view of a child row; without a meta (unknown child doctype) every column counts."""
	if table_meta is None:
		data = row.as_dict() if hasattr(row, "as_dict") else dict(row)
		return {
			k: v
			for k, v in data.items()
			if k not in _SYSTEM_FIELDS
			and k not in ("name", "parent", "parenttype", "parentfield", "doctype")
			and not _editable(k)
		}
	return {
		df.fieldname: row.get(df.fieldname)
		for df in table_meta.fields
		if df.fieldtype not in ("Section Break", "Column Break", "Tab Break", "HTML", "Button")
		and not _editable(df.fieldname)
	}


def _table_meta(doctype: str) -> Any:
	try:
		return frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return None


def changed_fields_after_submit(doc: Any) -> list[str]:
	"""Fieldnames whose value differs from the saved version, ignoring the editable ones."""
	before = doc.get_doc_before_save()
	if before is None:
		return []
	changed: list[str] = []
	for df in doc.meta.fields:
		fieldname = df.fieldname
		if fieldname in _SYSTEM_FIELDS or _editable(fieldname):
			continue
		if df.fieldtype in ("Section Break", "Column Break", "Tab Break", "HTML", "Button"):
			continue
		if df.fieldtype in ("Table", "Table MultiSelect"):
			table_meta = _table_meta(df.options)
			old_rows = [_row_values(r, table_meta) for r in (before.get(fieldname) or [])]
			new_rows = [_row_values(r, table_meta) for r in (doc.get(fieldname) or [])]
			if old_rows != new_rows:
				changed.append(fieldname)
			continue
		old_value, new_value = before.get(fieldname), doc.get(fieldname)
		if old_value in (None, "") and new_value in (None, ""):
			continue
		if str(old_value) != str(new_value):
			changed.append(fieldname)
	return changed


def guard_no_edit_after_submit(doc: Any, method: str | None = None) -> None:
	"""before_update_after_submit: only ``nyabo_*`` audit fields and remarks may change (art. 15.1).

	``frappe.flags.nyabo_allow_submit_edit`` lets ERPNext's own system updates through
	(status recalculation, clearance) when they go through ``save`` instead of ``db_set``.
	"""
	if frappe.flags.get("nyabo_allow_submit_edit"):
		return
	changed = changed_fields_after_submit(doc)
	if changed:
		frappe.throw(mn.MSG_NO_EDIT_AFTER_SUBMIT)


# --- delete guards -------------------------------------------------------------------------


def block_delete_of_posted(doc: Any, method: str | None = None) -> None:
	"""on_trash: a submitted or cancelled document Nyabo posted stays (art. 11.1).

	``doc.flags.nyabo_discarding`` is the single exception, and only
	``matching.match._discard_payment_entry`` sets it: a settlement whose own transaction
	failed, being undone inside the savepoint that failed. Nothing was shown to the
	accountant and nothing outlives the rollback, so there is no record art. 11.1 protects —
	while without the exception the cleanup could not run at all, because the settlement has
	already stamped ``nyabo_explanation`` and the guard fired on every attempt.

	The flag reaches this handler through ``frappe.delete_doc(..., flags={...})``, which
	``update_flags`` applies to the freshly loaded document *before* ``doc.run_method(
	"on_trash")`` (frappe/model/delete_doc.py, version-16) — setting it on the caller's own
	copy would not, because ``delete_doc`` re-fetches the document by name.
	"""
	if doc.flags.get("nyabo_discarding"):
		return
	if int(doc.docstatus or 0) not in (1, 2):
		return
	if has_nyabo_trail(doc):
		frappe.throw(mn.MSG_POSTED_DELETE_BLOCKED)


def _parent_retain_until(doctype: str, name: str) -> dt.date | None:
	field = RETAINED_PARENTS.get(doctype)
	if not field or not name:
		return None
	value = frappe.db.get_value(doctype, name, field)
	return getdate(value) if value else None


def block_retained_file_delete(doc: Any, method: str | None = None) -> None:
	"""on_trash of File: an attachment of a retained accounting document is kept (art. 11.1).

	The parent's retention date decides; a parent that is already gone (Frappe deletes the
	row before its Files) has passed the parent's own delete guard, so the File may go.
	Maintenance jobs set ``frappe.flags.nyabo_allow_file_delete`` for legitimate cleanup.
	"""
	if frappe.flags.get("nyabo_allow_file_delete"):
		return
	retain_until = _parent_retain_until(doc.get("attached_to_doctype"), doc.get("attached_to_name"))
	if retain_until and retain_until > getdate(nowdate()):
		frappe.throw(mn.MSG_RETAINED_FILE_DELETE_BLOCKED.format(retain_until=formatdate(retain_until)))


def stamp_retention(doc: Any, method: str | None = None) -> None:
	"""before_insert of Nyabo Document: retain_until = received_at (or today) + retention years."""
	received = doc.get("received_at")
	doc.retain_until = _retain_until(getdate(received) if received else None)


def block_retained_document_delete(doc: Any, method: str | None = None) -> None:
	"""on_trash of Nyabo Document: refused while the retention period runs."""
	if frappe.flags.get("nyabo_allow_file_delete"):
		return
	retain_until = getdate(doc.get("retain_until")) if doc.get("retain_until") else None
	if retain_until is None or retain_until > getdate(nowdate()):
		frappe.throw(
			mn.MSG_RETAINED_DOCUMENT_DELETE_BLOCKED.format(
				retain_until=formatdate(retain_until) if retain_until else mn.POLICY_UNKNOWN
			)
		)
