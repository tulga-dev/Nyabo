"""The real provisioning and install code running through the stub."""

from __future__ import annotations

import sys
import types

import frappe
import pytest
from erpnext.accounts.doctype.financial_report_template.financial_report_template import (
	sync_financial_report_templates,
)
from frappe.desk import query_report

from nyabo_mn.setup import chart as chart_mod
from nyabo_mn.setup.chart_db import account_for_code
from nyabo_mn.setup.provision_company import COMPANY_DEFAULTS_BY_CODE, provision_company, verify


def test_provisioning_verifies_ok(company):
	result = verify(company)
	assert result["ok"] and result["problems"] == []
	assert result["accounts_found"] == len(chart_mod.load_chart().by_number())
	assert frappe.db.count("Account", {"company": company}) == 58
	assert account_for_code(company, "6210") == "6210 - Шатахуун - TST"
	root = frappe.get_doc("Account", "Зардал - TST")
	assert root.is_group == 1 and root.root_type == "Expense" and root.report_type == "Profit and Loss"
	leaf = frappe.get_doc("Account", "1110 - Касс - TST")
	assert (leaf.parent_account, leaf.account_type, leaf.account_currency, leaf.account_category) == (
		"1100 - Мөнгөн хөрөнгө - TST",
		"Cash",
		"MNT",
		"Cash and Cash Equivalents",
	)
	company_doc = frappe.get_doc("Company", company)
	for fieldname, code in COMPANY_DEFAULTS_BY_CODE.items():
		if company_doc.meta.has_field(fieldname):
			assert company_doc.get(fieldname) == account_for_code(company, code, leaf=False)
	assert frappe.db.get_value("Sales Taxes and Charges Template", {"company": company}, "is_default") == 0
	assert frappe.db.get_value("Nyabo Company Settings", company, "company") == company
	assert frappe.db.exists("Fiscal Year", "2026")


def test_provisioning_is_idempotent_and_refuses_standard_chart(company, site):
	again = provision_company("Тест ХХК", "TST", vat_registered=0)
	assert again["created"]["company"] is False and again["verify"]["ok"]
	with pytest.raises(NotImplementedError, match="Standard chart"):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": "Хоёр ХХК",
				"abbr": "HOY",
				"country": "Mongolia",
				"default_currency": "MNT",
			}
		).insert()
	with pytest.raises(frappe.ValidationError, match="Abbreviation already used"):
		frappe.local.flags.ignore_chart_of_accounts = True
		try:
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": "Гурав ХХК",
					"abbr": "TST",
					"country": "Mongolia",
					"default_currency": "MNT",
				}
			).insert()
		finally:
			frappe.local.flags.ignore_chart_of_accounts = False


def test_after_install_creates_custom_field_rows(site):
	from nyabo_mn.setup.install import after_install

	after_install()
	assert frappe.db.exists("Custom Field", "Purchase Invoice-nyabo_explanation")
	assert frappe.db.exists("Custom Field", "Supplier-tin")
	assert frappe.db.get_value("Custom Field", "Journal Entry-nyabo_corrects", "options") == "Journal Entry"
	after_install()  # idempotent
	assert frappe.db.count("Custom Field", {"dt": "Supplier"}) == 5
	with pytest.raises(frappe.ValidationError, match="already exists"):
		frappe.get_doc(
			{"doctype": "Custom Field", "dt": "Supplier", "fieldname": "supplier_name", "fieldtype": "Data"}
		).insert()
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	make_property_setter("Supplier", "supplier_type", "reqd", 0, "Check")
	assert frappe.get_meta("Supplier").get_field("supplier_type").reqd == 0


def test_sync_financial_report_templates_records_the_call(site):
	sync_financial_report_templates()
	sync_financial_report_templates(existing_company="X")
	calls = frappe._stub.calls("sync_financial_report_templates")
	assert [c.existing_company for c in calls] == [None, "X"]


def test_query_report_runs_nyabo_script_reports_only(site):
	with pytest.raises(frappe.DoesNotExistError, match="Trial Balance"):
		query_report.run("Trial Balance", filters={"company": "X"})
	module = types.ModuleType("nyabo_mn.nyabo.report.stub_probe.stub_probe")

	def execute(filters=None):
		return [{"label": "Данс", "fieldname": "account"}], [{"account": filters.get("account")}], "тайлбар"

	module.execute = execute
	sys.modules[module.__name__] = module
	try:
		frappe.get_doc(
			{
				"doctype": "Report",
				"report_name": "Stub Probe",
				"ref_doctype": "Account",
				"is_standard": "Yes",
				"report_type": "Script Report",
				"module": "Nyabo",
			}
		).insert()
		out = query_report.run("Stub Probe", filters={"account": "1110"}, ignore_prepared_report=True)
	finally:
		sys.modules.pop(module.__name__, None)
	assert out["result"] == [{"account": "1110"}] and out["columns"][0]["fieldname"] == "account"
	assert out["message"] == "тайлбар" and out["skip_total_row"] == 0
