"""Naming rules of the stub: Frappe autoname options and ERPNext controller names."""

from __future__ import annotations

import frappe
import pytest


def test_series_counter_is_zero_padded_per_prefix(site):
	first = frappe.get_doc({"doctype": "Nyabo LLM Call", "purpose": "extract"}).insert()
	second = frappe.get_doc({"doctype": "Nyabo LLM Call", "purpose": "classify"}).insert()
	assert first.name == "NYL-000001"
	assert second.name == "NYL-000002"
	# a different prefix keeps its own counter
	from frappe.model.naming import make_autoname

	assert make_autoname("NYD-.#####") == "NYD-00001"
	assert make_autoname("NYD-.#####") == "NYD-00002"
	assert make_autoname("NYL-.######") == "NYL-000003"


def test_field_and_format_autoname(site, company):
	settings = frappe.get_doc("Nyabo Company Settings", company)
	assert settings.name == company  # field:company
	param = frappe.get_doc(
		{
			"doctype": "Nyabo Tax Parameter",
			"key": "vat_rate",
			"value_json": {"rate": 0.1},
			"effective_from": "2026-01-01",
		}
	).insert()
	assert param.name == "vat_rate:2026-01-01"  # format:{key}:{effective_from}


def test_hash_names_are_ten_characters(site):
	doc = frappe.get_doc({"doctype": "Version", "ref_doctype": "Role", "docname": "x", "data": "{}"}).insert()
	assert len(doc.name) == 10


def test_naming_series_uses_first_option_and_year(site, company):
	supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": "Петровис ХХК"}).insert()
	assert supplier.name == "Петровис ХХК"
	customer = frappe.get_doc({"doctype": "Customer", "customer_name": "Хэрэглэгч"}).insert()
	assert customer.name == "Хэрэглэгч"
	item = frappe.get_doc({"doctype": "Item", "item_code": "Бензин АИ-92", "item_group": "Products"}).insert()
	assert item.name == "Бензин АИ-92"


def test_erpnext_names_follow_abbreviation(site, company):
	assert frappe.db.exists("Account", "6210 - Шатахуун - TST")
	assert frappe.db.exists("Warehouse", "Stores - TST")
	assert frappe.db.exists("Cost Center", "Main - TST")
	assert frappe.db.get_value("Company", company, "cost_center") == "Main - TST"
	bank = frappe.get_doc({"doctype": "Bank", "bank_name": "Khan Bank"}).insert()
	account = frappe.get_doc(
		{
			"doctype": "Bank Account",
			"account_name": "Хаан банк MNT",
			"bank": bank.name,
			"account": "1120 - Банкны харилцах данс - TST",
			"company": company,
			"is_company_account": 1,
		}
	).insert()
	assert account.name == "Хаан банк MNT - Khan Bank"
	period = frappe.get_doc(
		{
			"doctype": "Accounting Period",
			"period_name": "2026-01",
			"company": company,
			"start_date": "2026-01-01",
			"end_date": "2026-01-31",
		}
	)
	from frappe._stub.hooks import temporary_hooks

	with temporary_hooks(without_apps=("nyabo_mn",)):
		period.insert()
	assert period.name == "2026-01 - TST"
	assert [d.document_type for d in period.closed_documents][:3] == [
		"Sales Invoice",
		"Purchase Invoice",
		"Journal Entry",
	]
	assert frappe.db.exists("Fiscal Year", "2026")


def test_file_name_is_hash_and_file_name_kept(site):
	doc = frappe.get_doc(
		{"doctype": "File", "file_name": "receipt.jpg", "content": b"jpeg", "is_private": 1}
	).insert()
	assert len(doc.name) == 10
	assert doc.file_name == "receipt.jpg"
	assert doc.file_url == "/private/files/receipt.jpg"


def test_missing_field_autoname_value_raises(site):
	with pytest.raises(frappe.ValidationError):
		frappe.get_doc({"doctype": "Role"}).insert()
