"""Print formats (МХ-1, МХ-2, ТМ-1, payment order list) and the Financial Report Templates."""

from __future__ import annotations

import json
import os

import frappe
import pytest
from compliance_helpers import BANK, CASH, EXPENSE, INCOME, make_je, make_si
from erpnext.accounts.doctype.financial_report_template.financial_report_template import (
	sync_financial_report_templates,
)

from nyabo_mn.i18n import mn
from nyabo_mn.reports.labels import print_labels

PRINT_FORMATS = {
	"nyabo_cash_receipt_voucher": ("Journal Entry", mn.FORM_CASH_RECEIPT_VOUCHER),
	"nyabo_cash_payment_voucher": ("Journal Entry", mn.FORM_CASH_PAYMENT_VOUCHER),
	"nyabo_invoice": ("Sales Invoice", mn.FORM_INVOICE),
	"nyabo_payment_order_list": ("Payment Entry", mn.FORM_PAYMENT_ORDER_LIST),
}


def _template(scrub: str) -> tuple[dict, str]:
	folder = frappe.get_app_path("nyabo_mn", "nyabo", "print_format", scrub)
	with open(os.path.join(folder, f"{scrub}.json"), encoding="utf-8") as f:
		meta = json.load(f)
	with open(os.path.join(folder, f"{scrub}.html"), encoding="utf-8") as f:
		html = f.read()
	return meta, html


def test_print_format_json_follows_the_shipped_shape():
	for scrub, (doc_type, _title) in PRINT_FORMATS.items():
		meta, html = _template(scrub)
		assert meta["doctype"] == "Print Format" and meta["standard"] == "Yes" and meta["module"] == "Nyabo"
		assert (
			meta["doc_type"] == doc_type
			and meta["print_format_type"] == "Jinja"
			and meta["custom_format"] == 0
		)
		assert frappe.scrub(meta["name"]) == scrub
		assert 'frappe.call("nyabo_mn.reports.labels.print_labels")' in html
	labels = print_labels()
	assert labels["FORM_CASH_RECEIPT_VOUCHER"] == mn.FORM_CASH_RECEIPT_VOUCHER and "COL_DEBIT" in labels
	assert all(isinstance(v, str) for v in labels.values())


def test_cash_vouchers_render_two_copies_with_signatures(company):
	receipt = make_je(
		company, amount=120000, debit=CASH, credit=INCOME, nyabo_primary_document_ref="ТМ-5 №4"
	).insert()
	_meta, html = _template("nyabo_cash_receipt_voucher")
	out = frappe.render_template(html, {"doc": receipt})
	assert out.count(mn.FORM_CASH_RECEIPT_VOUCHER) == 2 and mn.FORM_LBL_COPY_2 in out
	assert mn.FORM_PROVISIONAL_WATERMARK in out and mn.FORM_SOURCE_ORDER_347 in out
	assert "ТМ-5 №4" in out and CASH in out and INCOME in out and mn.FORM_LBL_CASHIER in out
	payment = make_je(
		company, amount=70000, debit=EXPENSE, credit=CASH, nyabo_primary_document_ref="x"
	).insert()
	_meta, html = _template("nyabo_cash_payment_voucher")
	out = frappe.render_template(html, {"doc": payment})
	assert (
		out.count(mn.FORM_CASH_PAYMENT_VOUCHER) == 2
		and mn.FORM_LBL_DIRECTOR in out
		and mn.FORM_LBL_RECEIVED_BY in out
	)


def test_invoice_renders_vat_line_and_party_ids(company):
	customer = frappe.get_doc(
		{"doctype": "Customer", "customer_name": "Хэрэглэгч ХХК", "register_no": "1234567", "tin": "98765432"}
	).insert()
	si = make_si(company, customer, amount=200000, nyabo_primary_document_ref="SI-1").insert()
	_meta, html = _template("nyabo_invoice")
	out = frappe.render_template(html, {"doc": si})
	assert mn.FORM_INVOICE in out and "1234567" in out and "98765432" in out
	assert mn.FORM_LBL_VAT in out and "10" in out and mn.FORM_LBL_GRAND_TOTAL in out
	assert "Үйлчилгээ" in out and mn.FORM_SOURCE_ORDER_347 in out


def test_payment_order_list_renders_with_the_bank_form_note(company):
	pe = frappe.get_doc(
		{
			"doctype": "Payment Entry",
			"payment_type": "Pay",
			"company": company,
			"posting_date": "2026-03-20",
			"party_type": "Supplier",
			"party": "Петровис ХХК",
			"paid_from": BANK,
			"paid_to": "2110 - Дансны өглөг - TST",
			"paid_amount": 50000,
			"received_amount": 50000,
			"remarks": "Шатахуун",
		}
	)
	_meta, html = _template("nyabo_payment_order_list")
	out = frappe.render_template(html, {"doc": pe})
	assert mn.FORM_PAYMENT_ORDER_LIST in out and mn.FORM_PAYMENT_ORDER_NOTE in out and "Шатахуун" in out


def _frt(scrub: str) -> dict:
	path = frappe.get_app_path("nyabo_mn", "nyabo", "financial_report_template", scrub, f"{scrub}.json")
	with open(path, encoding="utf-8") as f:
		return json.load(f)


@pytest.mark.parametrize("scrub", ["nyabo_sme_balance_sheet_(mn)", "nyabo_sme_income_statement_(mn)"])
def test_financial_report_templates_use_known_categories_and_are_marked_provisional(site, scrub):
	template = _frt(scrub)
	assert frappe.scrub(template["name"]) == scrub and template["module"] == "Nyabo"
	assert template["report_type"] in ("Balance Sheet", "Profit and Loss Statement")
	assert template["rows"][0]["display_name"] == mn.REPORT_PROVISIONAL
	known = set(frappe.get_all("Account Category", pluck="name"))
	codes = set()
	for row in template["rows"]:
		if row.get("reference_code"):
			codes.add(row["reference_code"])
		if row.get("data_source") != "Account Data":
			continue
		formula = json.loads(row["calculation_formula"])
		for clause in _clauses(formula):
			field, _op, value = clause
			if field == "account_category":
				for category in value if isinstance(value, list) else [value]:
					assert category in known, (row["reference_code"], category)
			else:
				assert field in ("account_number", "root_type")
	for row in template["rows"]:
		if row.get("data_source") == "Calculated Amount":
			for token in row["calculation_formula"].replace("(", " ").replace(")", " ").split():
				if token not in ("+", "-", "*", "/"):
					assert token in codes, (row["reference_code"], token)


def _clauses(formula):
	if isinstance(formula, dict):
		for parts in formula.values():
			for part in parts:
				yield from _clauses(part)
	elif formula and isinstance(formula[0], str):
		yield formula
	else:
		for part in formula:
			yield from _clauses(part)


def test_templates_sync_into_the_site(site):
	sync_financial_report_templates()
	names = frappe.get_all("Financial Report Template", pluck="name")
	assert {"Nyabo SME Balance Sheet (MN)", "Nyabo SME Income Statement (MN)"} <= set(names)
	doc = frappe.get_doc("Financial Report Template", "Nyabo SME Income Statement (MN)")
	assert doc.report_type == "Profit and Loss Statement" and len(doc.rows) > 10
