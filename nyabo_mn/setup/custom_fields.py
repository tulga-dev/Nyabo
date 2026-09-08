"""Custom fields Nyabo adds to ERPNext doctypes.

Applied idempotently on install and after every migrate (create_custom_fields with
update=True). Labels are Mongolian because every user of this site is Mongolian; the
fieldnames stay English so code and reports can refer to them.

Transaction doctypes get one collapsible section "Нябо · И-баримт":
    ebarimt_receipt_id, ebarimt_lottery_no, ebarimt_datetime, ebarimt_verified,
    nyabo_explanation, nyabo_prompt_version, ebarimt_qr_data,
    source_document (Link Nyabo Document), nyabo_proposal (Link Nyabo Proposal)
The two Link fields are only created once their target DocTypes exist (Phase 1), so
Phase 0 can install on a site without them and Phase 1 adds them on migrate.

Supplier and Customer get register_no and tin next to ERPNext's own tax_id.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from nyabo_mn.i18n import mn

# doctype -> field we prefer to insert our section after (falls back to the last field).
TRANSACTION_DOCTYPES: dict[str, str] = {
	"Purchase Invoice": "remarks",
	"Sales Invoice": "remarks",
	"Journal Entry": "user_remark",
	"Expense Claim": "remark",  # exists only when HRMS is installed
}
PARTY_DOCTYPES: dict[str, str] = {
	"Supplier": "tax_id",
	"Customer": "tax_id",
}
LINK_FIELDS: tuple[tuple[str, str, str], ...] = (
	# fieldname, target doctype, label
	("source_document", "Nyabo Document", mn.LBL_SOURCE_DOCUMENT),
	("nyabo_proposal", "Nyabo Proposal", mn.LBL_NYABO_PROPOSAL),
)


def transaction_fields(doctype: str, insert_after: str) -> list[dict]:
	chain: list[dict] = []

	def add(**field: object) -> None:
		field.setdefault("insert_after", chain[-1]["fieldname"] if chain else insert_after)
		chain.append(field)

	add(
		fieldname="nyabo_ebarimt_section",
		fieldtype="Section Break",
		label=mn.LBL_SECTION_EBARIMT,
		collapsible=1,
	)
	add(
		fieldname="ebarimt_receipt_id",
		fieldtype="Data",
		label=mn.LBL_EBARIMT_RECEIPT_ID,
		in_standard_filter=1,
	)
	add(fieldname="ebarimt_lottery_no", fieldtype="Data", label=mn.LBL_EBARIMT_LOTTERY_NO)
	add(fieldname="ebarimt_datetime", fieldtype="Datetime", label=mn.LBL_EBARIMT_DATETIME)
	add(fieldname="ebarimt_verified", fieldtype="Check", label=mn.LBL_EBARIMT_VERIFIED, default="0")
	if doctype == "Sales Invoice":
		add(fieldname="ebarimt_customer_tin", fieldtype="Data", label=mn.LBL_EBARIMT_CUSTOMER_TIN)
	add(fieldname="nyabo_ebarimt_column", fieldtype="Column Break")
	add(fieldname="nyabo_explanation", fieldtype="Small Text", label=mn.LBL_NYABO_EXPLANATION)
	add(fieldname="nyabo_prompt_version", fieldtype="Data", label=mn.LBL_NYABO_PROMPT_VERSION, read_only=1)
	add(fieldname="ebarimt_qr_data", fieldtype="Small Text", label=mn.LBL_EBARIMT_QR_DATA, read_only=1)
	for fieldname, target, label in LINK_FIELDS:
		if frappe.db.exists("DocType", target):
			add(fieldname=fieldname, fieldtype="Link", options=target, label=label, read_only=1)
	# Audit trail for corrections (Law on Accounting art. 15) and retention (art. 11.1).
	add(fieldname="nyabo_audit_section", fieldtype="Section Break", label=mn.LBL_SECTION_AUDIT, collapsible=1)
	add(
		fieldname="nyabo_approved_by",
		fieldtype="Link",
		options="User",
		label=mn.LBL_NYABO_APPROVED_BY,
		read_only=1,
	)
	add(fieldname="nyabo_primary_document_ref", fieldtype="Data", label=mn.LBL_NYABO_PRIMARY_DOCUMENT_REF)
	add(fieldname="nyabo_retain_until", fieldtype="Date", label=mn.LBL_NYABO_RETAIN_UNTIL, read_only=1)
	add(fieldname="nyabo_audit_column", fieldtype="Column Break")
	add(
		fieldname="nyabo_corrects",
		fieldtype="Link",
		options=doctype,
		label=mn.LBL_NYABO_CORRECTS,
		read_only=1,
	)
	add(
		fieldname="nyabo_correction_reason",
		fieldtype="Small Text",
		label=mn.LBL_NYABO_CORRECTION_REASON,
		read_only=1,
	)
	return chain


def party_fields(insert_after: str, doctype: str = "Customer") -> list[dict]:
	fields = [
		dict(
			fieldname="register_no",
			fieldtype="Data",
			label=mn.LBL_REGISTER_NO,
			insert_after=insert_after,
			in_standard_filter=1,
		),
		dict(
			fieldname="tin",
			fieldtype="Data",
			label=mn.LBL_TIN,
			insert_after="register_no",
			in_standard_filter=1,
		),
	]
	if doctype == "Supplier":
		# ebarimt public registry result (getInfo?tin=) cached on the supplier for 30 days.
		fields += [
			dict(
				fieldname="ebarimt_vat_payer",
				fieldtype="Check",
				label=mn.LBL_EBARIMT_VAT_PAYER,
				insert_after="tin",
				default="0",
			),
			dict(
				fieldname="ebarimt_checked_at",
				fieldtype="Datetime",
				label=mn.LBL_EBARIMT_CHECKED_AT,
				insert_after="ebarimt_vat_payer",
				read_only=1,
			),
			dict(
				fieldname="nyabo_pending_confirmation",
				fieldtype="Check",
				label=mn.LBL_SUPPLIER_PENDING,
				insert_after="ebarimt_checked_at",
				default="0",
				in_standard_filter=1,
			),
		]
	return fields


def get_custom_fields() -> dict[str, list[dict]]:
	"""Only doctypes that exist on this site; insert_after verified against the meta."""
	fields: dict[str, list[dict]] = {}
	for doctype, preferred in TRANSACTION_DOCTYPES.items():
		if frappe.db.exists("DocType", doctype):
			fields[doctype] = transaction_fields(doctype, _insert_after(doctype, preferred))
	for doctype, preferred in PARTY_DOCTYPES.items():
		if frappe.db.exists("DocType", doctype):
			fields[doctype] = party_fields(_insert_after(doctype, preferred), doctype)
	return fields


def _insert_after(doctype: str, preferred: str) -> str:
	meta = frappe.get_meta(doctype)
	if meta.has_field(preferred):
		return preferred
	return meta.fields[-1].fieldname


def ensure_custom_fields() -> list[str]:
	fields = get_custom_fields()
	create_custom_fields(fields, ignore_validate=frappe.flags.in_patch, update=True)
	return sorted(fields)
