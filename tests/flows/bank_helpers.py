"""Shared setup for the bank statement flow tests (tests/flows/test_bank_*.py).

Builds what onboarding/provisioning would create on a real site: Bank rows, one GL
account per bank under the cash group, ERPNext Bank Accounts, and the
``Nyabo Company Settings.bank_accounts`` rows the importer resolves against. Also the
verified *test* layouts for the synthetic fixtures and a Nyabo Document with the file.
"""

from __future__ import annotations

import json
from typing import Any

from tests.fixtures.statements import make_fixtures as fixtures

KHAN_GL_CODE = "1120"  # the V1 chart's bank leaf; the second bank gets a sibling leaf
TDB_GL_CODE = "1121"
KHAN_BANK_ACCOUNT = "Хаан банк MNT - Khan Bank"
TDB_BANK_ACCOUNT = "ХХБ MNT - TDB"


def _account_name(company: str, code: str) -> str:
	import frappe

	return frappe.db.get_value("Account", {"company": company, "account_number": code}, "name")


def ensure_tdb_gl_account(company: str) -> str:
	"""A second bank leaf next to 1120 so transfers have two distinct GL accounts."""
	import frappe

	existing = _account_name(company, TDB_GL_CODE)
	if existing:
		return existing
	parent = frappe.db.get_value("Account", _account_name(company, KHAN_GL_CODE), "parent_account")
	doc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": "ХХБ харилцах данс",
			"account_number": TDB_GL_CODE,
			"parent_account": parent,
			"company": company,
			"account_type": "Bank",
			"is_group": 0,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def setup_banks(company: str) -> dict[str, Any]:
	"""Two bank accounts (Khan Bank MNT, TDB MNT) wired into Nyabo Company Settings."""
	import frappe

	khan_gl = _account_name(company, KHAN_GL_CODE)
	tdb_gl = ensure_tdb_gl_account(company)
	for bank_name in ("Khan Bank", "TDB"):
		if not frappe.db.exists("Bank", bank_name):
			frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(ignore_permissions=True)
	specs = [
		("Хаан банк MNT", "Khan Bank", khan_gl, fixtures.KHAN_ACCOUNT_NO),
		("ХХБ MNT", "TDB", tdb_gl, fixtures.TDB_ACCOUNT_NO),
	]
	names: dict[str, str] = {}
	for account_name, bank, gl, number in specs:
		name = f"{account_name} - {bank}"
		if not frappe.db.exists("Bank Account", name):
			frappe.get_doc(
				{
					"doctype": "Bank Account",
					"account_name": account_name,
					"bank": bank,
					"account": gl,
					"company": company,
					"is_company_account": 1,
					"bank_account_no": number,
				}
			).insert(ignore_permissions=True)
		names[bank] = name
	settings = frappe.get_doc("Nyabo Company Settings", company)
	if not settings.get("bank_accounts"):
		for _label, bank, gl, number in specs:
			settings.append(
				"bank_accounts",
				{
					"bank": bank,
					"currency": "MNT",
					"account_number": number,
					"gl_account": gl,
					"erpnext_bank_account": names[bank],
				},
			)
		settings.flags.ignore_permissions = True
		settings.save()
	return {"khan": names["Khan Bank"], "tdb": names["TDB"], "khan_gl": khan_gl, "tdb_gl": tdb_gl}


def register_layouts(only: list[str] | None = None) -> list[str]:
	"""Insert the synthetic layouts as verified Nyabo Bank Layout rows."""
	import frappe

	created: list[str] = []
	for row in fixtures.LAYOUTS:
		if only and row["layout_id"] not in only:
			continue
		if frappe.db.exists("Nyabo Bank Layout", row["layout_id"]):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Nyabo Bank Layout",
				"layout_id": row["layout_id"],
				"bank": row["bank"],
				"verified": row["verified"],
				"amount_style": row["amount_style"],
				"currency_default": row["currency_default"],
				"date_formats": "\n".join(row["date_formats"]),
				"header_signature_json": json.dumps(row["header_signature"], ensure_ascii=False),
				"column_map_json": json.dumps(row["column_map"], ensure_ascii=False),
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		created.append(doc.name)
	return created


def statement_document(company: str, filename: str, data: bytes, telegram_id: str = "2002") -> str:
	"""Nyabo Document(bank_statement) with the file attached, as the Telegram handler would."""
	import frappe

	file_doc = frappe.get_doc(
		{"doctype": "File", "file_name": filename, "content": data, "is_private": 1}
	).insert(ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": "Nyabo Document",
			"company": company,
			"doc_type": "bank_statement",
			"status": "received",
			"file": file_doc.file_url,
			"file_hash": file_doc.content_hash,
			"sender_telegram_id": telegram_id,
			"mime_type": "application/octet-stream",
			"size_bytes": len(data),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	file_doc.db_set("attached_to_doctype", "Nyabo Document")
	file_doc.db_set("attached_to_name", doc.name)
	return doc.name


def ensure_role(role: str) -> str:
	"""An ERPNext role the site fixture does not create (Payment Entry asks for Accounts User)."""
	import frappe

	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
			ignore_permissions=True
		)
	return role


def ensure_supplier(name: str) -> str:
	import frappe

	if not frappe.db.exists("Supplier", name):
		frappe.get_doc({"doctype": "Supplier", "supplier_name": name}).insert(ignore_permissions=True)
	return name


def paid_purchase_invoice(
	company: str, supplier: str, amount: float, posting_date: str, bank_gl: str, expense_code: str = "6210"
) -> Any:
	"""A submitted Purchase Invoice paid from the bank (is_paid) — the voucher a statement line settles."""
	import frappe

	ensure_supplier(supplier)
	expense = _account_name(company, expense_code)
	pi = frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"company": company,
			"supplier": supplier,
			"posting_date": posting_date,
			"bill_no": f"INV-{supplier[:3]}-{int(amount)}",
			"is_paid": 1,
			"cash_bank_account": bank_gl,
			"paid_amount": amount,
			"items": [{"item_name": "Үйлчилгээ", "qty": 1, "rate": amount, "expense_account": expense}],
		}
	)
	pi.flags.ignore_permissions = True
	pi.insert()
	pi.submit()
	return pi


def unpaid_purchase_invoice(
	company: str,
	supplier: str,
	amount: float,
	posting_date: str,
	expense_code: str = "6210",
	currency: str | None = None,
	**extra: Any,
) -> Any:
	"""A submitted Purchase Invoice that still owes money - the voucher a Payment Entry settles.

	No ``is_paid``: the credit sits on the payable and nothing has touched a bank account,
	which is what a card / QPay / transfer purchase looks like until its statement line
	arrives (docs/DECISIONS.md PIPE-03).
	"""
	import frappe

	ensure_supplier(supplier)
	expense = _account_name(company, expense_code)
	values = {
		"doctype": "Purchase Invoice",
		"company": company,
		"supplier": supplier,
		"posting_date": posting_date,
		"bill_no": f"INV-{supplier[:3]}-{int(amount)}",
		"items": [{"item_name": "Үйлчилгээ", "qty": 1, "rate": amount, "expense_account": expense}],
	}
	if currency:
		values["currency"] = currency
		values["conversion_rate"] = 3500.0  # the stub does not fetch rates
	values.update(extra)
	pi = frappe.get_doc(values)
	pi.flags.ignore_permissions = True
	pi.insert()
	pi.submit()
	return pi


def unpaid_sales_invoice(
	company: str, customer: str, amount: float, posting_date: str, income_code: str = "4110"
) -> Any:
	"""A submitted Sales Invoice with an outstanding balance - what a deposit line collects."""
	import frappe

	if not frappe.db.exists("Customer", customer):
		frappe.get_doc({"doctype": "Customer", "customer_name": customer}).insert(ignore_permissions=True)
	income = _account_name(company, income_code)
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": company,
			"customer": customer,
			"posting_date": posting_date,
			"po_no": f"SO-{customer[:3]}-{int(amount)}",
			"items": [{"item_name": "Үйлчилгээ", "qty": 1, "rate": amount, "income_account": income}],
		}
	)
	si.flags.ignore_permissions = True
	si.insert()
	si.submit()
	return si


def fixture_bytes(name: str) -> tuple[str, bytes]:
	builders = {builder.__name__: builder for builder in fixtures.BUILDERS}
	return builders[name]()
