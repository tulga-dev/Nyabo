"""Script reports: general journal (ЕЖ), cash journal (МГ-1), VAT and simplified summaries through query_report."""

from __future__ import annotations

import frappe
import pytest
from compliance_helpers import BANK, CASH, EXPENSE, make_je, make_nyabo_document
from frappe.desk import query_report

from nyabo_mn.i18n import mn
from nyabo_mn.reports import export

FILTERS = {"from_date": "2026-03-01", "to_date": "2026-03-31"}


@pytest.fixture
def journal(company):
	nyd = make_nyabo_document(company)
	je = make_je(company, amount=85000, source_document=nyd.name, nyabo_approved_by="Administrator").insert()
	je.submit()
	bank = make_je(
		company,
		amount=30000,
		posting_date="2026-03-12",
		debit=EXPENSE,
		credit=BANK,
		nyabo_primary_document_ref="Гэрээ 7",
	)
	bank.insert()
	bank.submit()
	return company, je, bank, nyd


def test_general_journal_returns_rows_in_form_order(journal):
	company, je, bank, nyd = journal
	result = query_report.run(
		"Nyabo General Journal", filters={"company": company, **FILTERS}, ignore_prepared_report=True
	)
	labels = [c["label"] for c in result["columns"]]
	assert labels[:5] == [
		mn.LBL_ROW_NO,
		mn.COL_DOC_DATE,
		mn.COL_VOUCHER_TYPE,
		mn.COL_DOC_NO,
		mn.COL_DESCRIPTION,
	]
	assert mn.COL_DEBIT in labels and mn.COL_CREDIT in labels and mn.COL_PRIMARY_DOCUMENT in labels
	rows = result["result"]
	assert len(rows) == 4 and [r["row_no"] for r in rows] == [1, 2, 3, 4]
	first = [r for r in rows if r["voucher_no"] == je.name]
	assert {(r["account"], r["debit"], r["credit"]) for r in first} == {
		(EXPENSE, 85000.0, 0.0),
		(CASH, 0.0, 85000.0),
	}
	assert all(r["primary_document"] == nyd.name and r["approved_by"] == "Administrator" for r in first)
	assert all(r["prepared_by"] == "Administrator" for r in rows)
	assert {r["account_code"] for r in rows} == {"6210", "1110", "1120"}
	second = [r for r in rows if r["voucher_no"] == bank.name]
	assert second[0]["primary_document"] == "Гэрээ 7"
	assert (
		query_report.run("Nyabo General Journal", filters={"company": company}, ignore_prepared_report=True)[
			"result"
		]
		== []
	)


def test_cash_journal_lists_cash_and_bank_rows_with_balances(journal):
	company, je, bank, _nyd = journal
	result = query_report.run(
		"Nyabo Cash Journal", filters={"company": company, **FILTERS}, ignore_prepared_report=True
	)
	rows = result["result"]
	assert [r["account"] for r in rows] == [CASH, BANK]
	assert rows[0]["credit"] == 85000.0 and rows[0]["against"] == EXPENSE and rows[0]["voucher_no"] == je.name
	assert rows[1]["credit"] == 30000.0 and rows[1]["reference"] == "Гэрээ 7"
	labels = [c["label"] for c in result["columns"]]
	assert mn.LBL_CASH_RECEIPT in labels and mn.LBL_CASH_PAYMENT in labels and mn.COL_RATE not in labels
	summary = {s["label"]: s["value"] for s in result["report_summary"]}
	assert summary[f"{mn.COL_CLOSING} ({CASH})"] == -85000.0
	assert summary[f"{mn.COL_OPENING} ({CASH})"] == 0.0
	only_bank = query_report.run(
		"Nyabo Cash Journal",
		filters={"company": company, "account": BANK, **FILTERS},
		ignore_prepared_report=True,
	)
	assert [r["account"] for r in only_bank["result"]] == [BANK]


def test_general_journal_pdf_carries_the_mof_header_and_signatures(journal):
	company = journal[0]
	pdf = export.report_to_pdf(
		"Nyabo General Journal",
		{"company": company, **FILTERS},
		mn.REPORT_GENERAL_JOURNAL,
		company,
		"2026 оны 3-р сар",
		signatures=[(mn.JOURNAL_KEPT_BY, "Б. Батаа"), (mn.JOURNAL_CHECKED_BY, "")],
	)
	html = pdf.decode("utf-8")
	for text in (
		mn.REPORT_GENERAL_JOURNAL,
		mn.LBL_COMPANY,
		mn.JOURNAL_TYPE_GENERAL,
		mn.JOURNAL_KEPT_BY,
		mn.JOURNAL_CHECKED_BY,
		mn.FORM_SOURCE_ORDER_100,
		"Б. Батаа",
		"DejaVu Sans",
		mn.REPORT_PROVISIONAL,
	):
		assert text in html
	call = frappe._stub.calls("get_pdf")[-1]
	assert call.options["orientation"] == "Landscape"


def test_report_roles_are_checked_for_non_admin_users(journal, as_user):
	company = journal[0]
	with as_user("owner@example.com", ["Nyabo Owner"]):
		with pytest.raises(frappe.PermissionError):
			query_report.run("Nyabo General Journal", filters={"company": company, **FILTERS})
