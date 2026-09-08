"""VAT summary, simplified 1% summary, month-end checklist / trial balance / summaries."""

from __future__ import annotations

from decimal import Decimal

import frappe
import pytest
from compliance_helpers import BANK, CASH, EXPENSE, INCOME, INPUT_VAT, OUTPUT_VAT, make_je, make_pi, make_si
from openpyxl import load_workbook

from nyabo_mn.i18n import mn
from nyabo_mn.reports import export, month_end, rules_bridge, simplified_summary, vat_summary


@pytest.fixture
def books(company):
	"""A VAT-registered March: one purchase invoice with input VAT, one sales invoice with output VAT."""
	supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": "Петровис ХХК"}).insert()
	customer = frappe.get_doc({"doctype": "Customer", "customer_name": "Хэрэглэгч ХХК"}).insert()
	pi = make_pi(
		company,
		supplier,
		nyabo_primary_document_ref="AB-1",
		taxes=[
			{"account_head": INPUT_VAT, "charge_type": "On Net Total", "rate": 10, "description": "НӨАТ 10%"}
		],
	).insert()
	pi.submit()
	si = make_si(company, customer, amount=200000, nyabo_primary_document_ref="SI-1").insert()
	si.submit()
	je = make_je(
		company,
		amount=50000,
		posting_date="2026-03-20",
		debit=EXPENSE,
		credit=BANK,
		nyabo_primary_document_ref="x",
	)
	je.insert()
	je.submit()
	return company


def _settings(company, regime):
	name = frappe.db.get_value("Nyabo Company Settings", {"company": company}, "name")
	doc = (
		frappe.get_doc("Nyabo Company Settings", name)
		if name
		else frappe.get_doc({"doctype": "Nyabo Company Settings", "company": company})
	)
	doc.regimes = []
	doc.append("regimes", {"regime": regime, "effective_from": "2026-01-01"})
	doc.accountant_of_record_name = "Б. Батаа"
	doc.save()
	return doc


def test_vat_summary_from_gl_rows(books):
	summary = vat_summary.compute(books, "2026-03")
	assert summary["output_vat"] == Decimal("20000.00")
	assert summary["input_vat"] == Decimal("8500.00")
	assert summary["net"] == Decimal("11500.00")
	assert summary["accounts"] == {"output_vat": OUTPUT_VAT, "input_vat": INPUT_VAT}
	docs = {d["voucher_type"]: d for d in summary["by_document"]}
	assert docs["Sales Invoice"]["output_vat"] == Decimal("20000.00")
	assert docs["Purchase Invoice"]["input_vat"] == Decimal("8500.00")
	assert vat_summary.compute(books, "2026-04")["net"] == Decimal("0.00")


def test_simplified_summary_uses_the_parameter_row_and_refuses_unverified(books):
	with pytest.raises(rules_bridge.UnverifiedRuleError) as exc:
		simplified_summary.compute(books, "2026-Q1")
	assert "simplified.rate" in str(exc.value)
	simulated = simplified_summary.compute(books, "2026-Q1", simulation=True)
	assert simulated["revenue"] == Decimal("200000.00")
	assert simulated["tax_1pct"] == Decimal("2000.00")
	assert simulated["simulation"] is True and simulated["rate_row"]["verified"] is False
	assert [m["period"] for m in simulated["months"]] == ["2026-01", "2026-02", "2026-03"]
	assert simulated["months"][2]["revenue"] == Decimal("200000.00")

	frappe.get_doc(
		{
			"doctype": "Nyabo Tax Parameter",
			"key": "simplified.rate",
			"effective_from": "2026-01-01",
			"value_json": "0.01",
			"unit": "fraction",
			"status": "active",
			"verified": 1,
			"source_text": "ААНОАТ-ын тухай хууль",
		}
	).insert()
	real = simplified_summary.compute(books, "2026-Q1")
	assert real["tax_1pct"] == Decimal("2000.00") and real["rate_row"]["verified"] is True
	with pytest.raises(frappe.ValidationError):
		simplified_summary.compute(books, "2026-Q9")


def test_month_end_checklist_and_trial_balance(books):
	frappe.get_doc(
		{"doctype": "Nyabo Proposal", "company": books, "kind": "receipt", "status": "proposed"}
	).insert()
	frappe.get_doc(
		{"doctype": "Supplier", "supplier_name": "Шинэ ХХК", "nyabo_pending_confirmation": 1}
	).insert()
	check = month_end.checklist(books, "2026-03")
	assert (check["proposals"], check["pending_suppliers"], check["unverified_rules"]) == (1, 1, 0)
	assert check["blocking"] is False and check["inventory_count_required"] is False
	assert "Шийдвэрлээгүй санал: 1" in check["text"]
	assert mn.MSG_CLOSE_INVENTORY_COUNT in month_end.checklist(books, "2026-12")["text"]

	tb = month_end.trial_balance(books, "2026-03")
	assert tb["source"] == "gl_entry" and tb["debit"] == tb["credit"] == Decimal("363500.00")
	by_account = {r["account"]: r for r in tb["rows"]}
	assert (
		by_account[EXPENSE]["debit"] == Decimal("135000.00") and by_account[EXPENSE]["account_code"] == "6210"
	)
	assert by_account[INCOME]["credit"] == Decimal("200000.00")
	assert by_account[CASH]["credit"] == Decimal("0.00") if CASH in by_account else True


def test_month_end_summaries_pick_the_regime(books):
	assert month_end.summaries(books, "2026-03")["is_vat_payer"] is None
	_settings(books, "vat_payer")
	out = month_end.summaries(books, "2026-03")
	assert out["is_vat_payer"] is True and set(out["pdfs"]) == {"vat_summary"}
	assert any("11 500" in line or "11,500" in line or "11500" in line for line in out["text_lines"])
	assert mn.REPORT_VAT_SUMMARY in out["pdfs"]["vat_summary"].decode("utf-8")
	assert "DejaVu Sans" in out["pdfs"]["vat_summary"].decode("utf-8")

	_settings(books, "simplified_1pct")
	out = month_end.summaries(books, "2026-03", simulation=True)
	assert out["is_vat_payer"] is False and set(out["pdfs"]) == {"simplified_summary"}
	assert any("1% татвар" in line for line in out["text_lines"])
	html = out["pdfs"]["simplified_summary"].decode("utf-8")
	assert mn.LBL_SIMULATION in html and mn.JOURNAL_KEPT_BY in html
	with pytest.raises(rules_bridge.UnverifiedRuleError):
		month_end.summaries(books, "2026-03")


def test_report_to_xlsx_round_trips(books):
	data = export.report_to_xlsx(
		"Nyabo VAT Summary", {"company": books, "from_date": "2026-03-01", "to_date": "2026-03-31"}
	)
	from io import BytesIO

	sheet = load_workbook(BytesIO(data)).active
	rows = [list(r) for r in sheet.iter_rows(values_only=True)]
	assert rows[0][:2] == [mn.COL_DATE, mn.COL_VOUCHER_TYPE]
	assert len(rows) == 3 and {r[1] for r in rows[1:]} == {"Purchase Invoice", "Sales Invoice"}
