"""provision_company with the v0.3 chart, bank sub-accounts, the accountant's CSV chart, and V1 parity."""

from __future__ import annotations

import frappe
import pytest

from nyabo_mn.setup import chart_csv
from nyabo_mn.setup.chart import ChartError
from nyabo_mn.setup.provision_company import (
	COMPANY_DEFAULTS_BY_CODE,
	company_defaults_by_code,
	provision,
	provision_company,
	template_chart,
	verify,
)
from tests.flows.conftest import BANK_ROWS, V03_COMPANY

# The Phase 0 literal table: the role-based mapping must reproduce it exactly.
PHASE0_V1_DEFAULTS = {
	"default_cash_account": "1110",
	"default_bank_account": "1120",
	"default_receivable_account": "1310",
	"default_payable_account": "2110",
	"default_income_account": "4110",
	"default_expense_account": "6910",
	"round_off_account": "6920",
	"write_off_account": "6940",
	"exchange_gain_loss_account": "6930",
	"unrealized_exchange_gain_loss_account": "6930",
	"accumulated_depreciation_account": "1519",
	"depreciation_expense_account": "6530",
	"capital_work_in_progress_account": "1530",
	"default_inventory_account": "1410",
	"stock_received_but_not_billed": "2120",
	"stock_adjustment_account": "5120",
	"expenses_included_in_valuation": "5130",
	"expenses_added_to_stock_account": "5130",
}


def test_v1_defaults_are_unchanged():
	assert COMPANY_DEFAULTS_BY_CODE == PHASE0_V1_DEFAULTS
	assert company_defaults_by_code("v03")["default_expense_account"] == "7090"
	assert company_defaults_by_code("v03")["disposal_account"] == "8703"


def test_v03_company_with_two_banks(company_v03):
	result = verify(company_v03)
	assert result["ok"] and result["chart_scheme"] == "v03"
	assert result["accounts_expected"] == len(template_chart().by_number())
	company_doc = frappe.get_doc("Company", company_v03)
	assert company_doc.default_expense_account == "7090 - Бусад үйл ажиллагааны зардал - GUR"
	assert company_doc.default_bank_account == "1101 - Банк МНТ - GUR"
	assert company_doc.disposal_account == "8703 - Үндсэн хөрөнгө данснаас хассаны гарз - GUR"

	settings = frappe.get_doc("Nyabo Company Settings", company_v03)
	assert settings.chart_scheme == "v03" and settings.default_expense_code == "7090"
	assert settings.has_inventory == 1
	assert [(r.regime, str(r.effective_from), r.effective_to) for r in settings.regimes] == [
		("vat_payer", "2026-01-01", None)
	]
	rows = [
		(r.bank, r.currency, r.account_number, r.gl_account, r.erpnext_bank_account)
		for r in settings.bank_accounts
	]
	assert rows == [
		(
			"Khan Bank",
			"MNT",
			"5001234567",
			"1103 - Хаан банк MNT 4567 - GUR",
			"Хаан банк MNT 4567 - Khan Bank",
		),
		("Golomt Bank", "USD", None, "1104 - Голомт банк USD - GUR", "Голомт банк USD - Golomt Bank"),
	]
	khan = frappe.get_doc("Account", "1103 - Хаан банк MNT 4567 - GUR")
	assert khan.parent_account == "11 - Банкинд байгаа мөнгө - GUR"
	assert khan.account_type == "Bank" and khan.account_currency == "MNT" and khan.is_group == 0
	assert frappe.get_doc("Account", "1104 - Голомт банк USD - GUR").account_currency == "USD"
	bank_account = frappe.get_doc("Bank Account", "Хаан банк MNT 4567 - Khan Bank")
	assert (bank_account.account, bank_account.is_company_account, bank_account.bank_account_no) == (
		"1103 - Хаан банк MNT 4567 - GUR",
		1,
		"5001234567",
	)
	assert frappe.db.exists("Bank", "Khan Bank") and frappe.db.exists("Bank", "Golomt Bank")
	assert (
		frappe.db.get_value("Sales Taxes and Charges Template", {"company": company_v03}, "is_default") == 1
	)
	template = frappe.get_doc("Purchase Taxes and Charges Template", {"company": company_v03})
	assert template.taxes[0].account_head == "1210 - НӨАТ-ын авлага - GUR" and template.taxes[0].rate == 10.0

	# provisioning again with the same banks creates nothing new
	again = provision_company(
		V03_COMPANY, "GUR", vat_registered=1, chart_scheme="v03", bank_accounts=BANK_ROWS
	)
	assert again["created"]["company"] is False and again["verify"]["ok"]
	assert (
		frappe.db.count("Account", {"company": company_v03, "account_type": "Bank"}) == 4
	)  # 1101, 1102 + two
	assert frappe.db.count("Bank Account", {"company": company_v03}) == 2
	assert len(frappe.get_doc("Nyabo Company Settings", company_v03).bank_accounts) == 2


def test_v1_company_gets_bank_sub_accounts_under_the_cash_group(company):
	provision_company(
		"Тест ХХК",
		"TST",
		vat_registered=0,
		bank_accounts=[{"bank": "TDB", "currency": "MNT", "account_number": "99"}],
	)
	account = frappe.get_doc("Account", {"company": company, "account_name": "Худалдаа хөгжлийн банк MNT 99"})
	assert account.account_number == "1121" and account.parent_account == "1100 - Мөнгөн хөрөнгө - TST"


ACCOUNTANT_CSV = "\n".join(
	[
		"code,name,parent_code,root_type,account_type",
		"1,Хөрөнгө,,Asset,",
		"11,Мөнгөн хөрөнгө,1,,",
		"1110,Касс МНТ,11,,Cash",
		"1120,Банк МНТ,11,,Bank",
		"12,Авлага,1,,",
		"1211,Дансны авлага,12,,Receivable",
		"1213,НӨАТ-ын авлага,12,,Tax",
		"1890,Түр нээлтийн данс,12,,Temporary",
		"14,Бараа материал,1,,",
		"1401,Бараа,14,,Stock",
		"2,Өр төлбөр,,Liability,",
		"21,Өглөг,2,,",
		"2111,Дансны өглөг (нийлүүлэгч),21,,Payable",
		"2113,НӨАТ-ын өглөг,21,,Tax",
		"3,Эзэмшигчийн өмч,,Equity,",
		"3101,Хувь нийлүүлсэн хөрөнгө,3,,Equity",
		"4,Орлого,,Income,",
		"4101,Борлуулалтын орлого,4,,Income Account",
		"5,Зардал,,Expense,",
		"5101,Шатахуун,5,,Expense Account",
		"5190,Бусад үйл ажиллагааны зардал,5,,Expense Account",
		"5191,Тоймлолтын зөрүү,5,,Round Off",
		"5192,Банкны үйлчилгээний хураамж,5,,Expense Account",
		"5199,Нягтлангийн өөрийн данс,5,,Expense Account",
	]
)


def test_csv_chart_loader_matches_template_by_name():
	chart = chart_csv.load_csv_chart(ACCOUNTANT_CSV)
	assert chart.name and len(chart.leaf_numbers()) == 15
	match = chart_csv.match_template(chart, template_chart())
	assert (
		match.aliases["1001"] == "1110"
		and match.aliases["7003"] == "5101"
		and match.aliases["1890"] == "1890"
	)
	assert match.aliases["7091"] == "5191" and match.aliases["3101"] == "2111"
	assert "7001" in match.unmatched_template and match.unmatched_chart == ["5199"]
	rows_as_dicts = [
		{"Код": "1", "Нэр": "Хөрөнгө", "Эцэг": "", "Төрөл": "Asset", "Дансны төрөл": ""},
		{"Код": "1110", "Нэр": "Касс", "Эцэг": "1", "Төрөл": "", "Дансны төрөл": "Cash"},
	]
	assert chart_csv.load_csv_chart(rows_as_dicts).leaf_numbers() == {"1110"}
	with pytest.raises(ChartError, match="эцэг данс"):
		chart_csv.load_csv_chart("code,name,parent_code,root_type\n1,Хөрөнгө,9,Asset\n")
	with pytest.raises(ChartError, match="root_type"):
		chart_csv.load_csv_chart("code,name,parent_code,root_type\n1,Хөрөнгө,,Assets\n")
	with pytest.raises(ChartError, match="баганууд"):
		chart_csv.load_csv_chart("foo,bar\n1,2\n")


def test_accountant_chart_provisions_with_automatic_aliases(seeded):
	report = provision_company(
		"Нягтлан ХХК", "NYA", vat_registered=1, chart_scheme="accountant", chart_csv=ACCOUNTANT_CSV
	)
	assert report["verify"]["ok"], report["verify"]["problems"]
	assert (
		report["aliases"]["mof"] == 14 and report["aliases"]["v1"] > 0
	)  # 15 leaves, 5199 has no template match
	assert "7001" in report["aliases"]["unmatched_template"]
	assert any("without a match" in w for w in report["warnings"])
	company_doc = frappe.get_doc("Company", "Нягтлан ХХК")
	assert company_doc.default_expense_account == "5190 - Бусад үйл ажиллагааны зардал - NYA"
	assert company_doc.default_cash_account == "1110 - Касс МНТ - NYA"
	assert company_doc.round_off_account == "5191 - Тоймлолтын зөрүү - NYA"
	assert not company_doc.depreciation_expense_account  # unmatched template account: left empty, warned
	assert any("depreciation_expense_account" in w for w in report["warnings"])
	settings = frappe.get_doc("Nyabo Company Settings", "Нягтлан ХХК")
	assert settings.chart_scheme == "accountant" and settings.default_expense_code == "5190"
	from nyabo_mn.rules import aliases

	assert aliases.account_for("Нягтлан ХХК", "role:bank_fee") == "5192 - Банкны үйлчилгээний хураамж - NYA"
	assert aliases.resolve_code("Нягтлан ХХК", "6210") == "5101"  # V1 -> v0.3 7003 -> accountant 5101
	assert aliases.resolve_code("Нягтлан ХХК", "7003") == "5101"
	template = frappe.get_doc("Sales Taxes and Charges Template", {"company": "Нягтлан ХХК"})
	assert template.taxes[0].account_head == "2113 - НӨАТ-ын өглөг - NYA"
	assert frappe.get_doc("Account", "1110 - Касс МНТ - NYA").account_category == "Cash and Cash Equivalents"
	with pytest.raises(frappe.ValidationError, match="chart_csv"):
		provision_company("Зургаа ХХК", "ZUR", chart_scheme="accountant")


# frappe/__init__.py: a bare @frappe.whitelist() means every verb, and frappe/auth.py only
# validates the CSRF token on POST/PUT/DELETE/PATCH -- so a state-changing method must pin its verb.
FRAPPE_DEFAULT_METHODS = ["GET", "POST", "PUT", "DELETE"]
UNSAFE_HTTP_METHODS = frozenset(("POST", "PUT", "DELETE", "PATCH"))


def allowed_methods(fn):
	assert getattr(fn, "is_whitelisted", False), f"{fn.__name__} is not whitelisted"
	return getattr(fn, "allowed_http_methods", None) or FRAPPE_DEFAULT_METHODS


def test_provision_endpoints_pin_their_http_verb():
	# provision() creates a company, chart, warehouses and tax templates: CSRF-checked verbs only.
	assert allowed_methods(provision) == ["POST"]
	assert set(allowed_methods(provision)) <= UNSAFE_HTTP_METHODS
	assert "GET" not in allowed_methods(provision)
	# verify() only reads, so GET is fine, but it still must not accept PUT/DELETE.
	assert allowed_methods(verify) == ["GET", "POST"]
	assert "PUT" not in allowed_methods(verify) and "DELETE" not in allowed_methods(verify)
