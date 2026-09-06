"""Create a company with the Mongolian chart, VAT templates and sane defaults.

From a bench shell (SSH on Frappe Cloud):
    bench --site <site> execute nyabo_mn.setup.provision_company.provision_company \
        --kwargs '{"company_name": "Тест ХХК", "abbr": "TST", "vat_registered": 0}'

From the browser as a System Manager (F12 -> Console):
    frappe.call("nyabo_mn.setup.provision_company.provision",
        {company_name: "Тест ХХК", abbr: "TST", vat_registered: 0}).then(r => console.log(r.message))

Check an existing company:
    bench --site <site> execute nyabo_mn.setup.provision_company.verify --kwargs '{"company": "Тест ХХК"}'

What it does, in order (all-or-nothing: an error rolls the whole thing back):
1. enables the currency and makes sure a fiscal year covers today (calendar year);
2. inserts the Company with ERPNext's own chart creation switched off
   (frappe.local.flags.ignore_chart_of_accounts, the flag ERPNext's Chart of Accounts
   Importer uses), then installs our tree with ERPNext's create_charts(custom_chart=...);
3. creates the default warehouses ERPNext skipped, sets every Company default account
   from the V1 codes below, creates the VAT templates, and records the VAT regime in
   Nyabo Company Settings when that DocType exists (Phase 1).

The chart is only installed on a company with no accounts. Replacing the chart of an
existing company is deliberately unsupported here: use ERPNext's Chart of Accounts
Importer for that, it refuses when transactions exist.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from nyabo_mn.log import log_event
from nyabo_mn.setup import chart as chart_mod
from nyabo_mn.setup.chart_db import account_for_code, code_map, install_chart
from nyabo_mn.setup.taxes import (
	ITEM_TAX_EXEMPT_TITLE,
	ITEM_TAX_ZERO_TITLE,
	PURCHASE_TEMPLATE_TITLE,
	SALES_TEMPLATE_TITLE,
	ensure_vat_templates,
)

DEFAULT_COUNTRY = "Mongolia"
DEFAULT_CURRENCY = "MNT"

# Company default-account field -> V1 code. Only fields that exist on this ERPNext version are set.
# ERPNext looks some of these up by English account name ("Write Off", "Exchange Gain/Loss",
# "Round Off"); our chart has Mongolian names, so we set them explicitly.
COMPANY_DEFAULTS_BY_CODE: dict[str, str] = {
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
	"expenses_included_in_valuation": "5130",  # field name up to ERPNext v15
	"expenses_added_to_stock_account": "5130",  # field name in ERPNext v16
}
TAX_TEMPLATES: dict[str, str] = {
	SALES_TEMPLATE_TITLE: "Sales Taxes and Charges Template",
	PURCHASE_TEMPLATE_TITLE: "Purchase Taxes and Charges Template",
	ITEM_TAX_EXEMPT_TITLE: "Item Tax Template",
	ITEM_TAX_ZERO_TITLE: "Item Tax Template",
}


@frappe.whitelist()
def provision(
	company_name: str,
	abbr: str,
	country: str = DEFAULT_COUNTRY,
	currency: str = DEFAULT_CURRENCY,
	vat_registered: int | str = 0,
	enable_perpetual_inventory: int | str = 0,
) -> dict[str, Any]:
	"""Browser-callable wrapper (System Manager only)."""
	frappe.only_for("System Manager")
	return provision_company(
		company_name=company_name,
		abbr=abbr,
		country=country,
		currency=currency,
		vat_registered=vat_registered,
		enable_perpetual_inventory=enable_perpetual_inventory,
	)


def provision_company(
	company_name: str,
	abbr: str,
	country: str = DEFAULT_COUNTRY,
	currency: str = DEFAULT_CURRENCY,
	vat_registered: int | str = 0,
	enable_perpetual_inventory: int | str = 0,
	chart_path: str | None = None,
) -> dict[str, Any]:
	company_name = (company_name or "").strip()
	abbr = (abbr or "").strip()
	if not company_name or not abbr:
		frappe.throw(_("company_name and abbr are required"))
	is_vat_payer = bool(cint(vat_registered))
	perpetual = bool(cint(enable_perpetual_inventory))

	chart = chart_mod.load_chart(chart_path or chart_mod.DEFAULT_CHART_PATH, currency=currency)
	report: dict[str, Any] = {
		"company": company_name,
		"abbr": abbr,
		"vat_registered": is_vat_payer,
		"chart": chart.name,
		"warnings": list(chart.warnings),
		"created": {},
	}

	_ensure_currency(currency)
	report["created"]["fiscal_year"] = _ensure_fiscal_year()

	if frappe.db.exists("Company", company_name):
		report["created"]["company"] = False
		if frappe.db.exists("Account", {"company": company_name}):
			report["created"]["accounts"] = 0
			report["warnings"].append("company already had accounts; chart left untouched")
		else:
			report["created"]["accounts"] = install_chart(company_name, chart)
	else:
		_create_company(company_name, abbr, country, currency, perpetual)
		report["created"]["company"] = True
		report["created"]["accounts"] = install_chart(company_name, chart)

	report["created"]["warehouses"] = _ensure_warehouses(company_name)
	report["company_defaults"] = _set_company_defaults(company_name)
	report["tax_templates"] = ensure_vat_templates(company_name, is_vat_payer)
	report["nyabo_settings"] = _set_nyabo_settings(company_name, is_vat_payer)
	report["verify"] = verify(company_name)

	log_event(
		"provision.done",
		company=company_name,
		accounts=report["created"]["accounts"],
		vat_registered=is_vat_payer,
		ok=report["verify"]["ok"],
	)
	return report


def _ensure_currency(currency: str) -> None:
	if not frappe.db.exists("Currency", currency):
		frappe.throw(_("Currency {0} does not exist").format(currency))
	frappe.db.set_value("Currency", currency, "enabled", 1)


def _ensure_fiscal_year() -> str:
	now = getdate(today())
	existing = frappe.db.get_value(
		"Fiscal Year", {"year_start_date": ["<=", now], "year_end_date": [">=", now]}, "name"
	)
	if existing:
		return existing
	year = str(now.year)
	doc = frappe.get_doc(
		{
			"doctype": "Fiscal Year",
			"year": year,
			"year_start_date": f"{year}-01-01",
			"year_end_date": f"{year}-12-31",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _create_company(name: str, abbr: str, country: str, currency: str, perpetual: bool):
	doc = frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": name,
			"abbr": abbr,
			"country": country,
			"default_currency": currency,
			"create_chart_of_accounts_based_on": "Standard Template",
			"chart_of_accounts": "Standard",
			"enable_perpetual_inventory": 1 if perpetual else 0,
		}
	)
	doc.flags.ignore_permissions = True
	# ERPNext's Company.on_update creates the Standard chart unless this flag is set
	# (erpnext/setup/doctype/company/company.py). We install our own tree right after.
	frappe.local.flags.ignore_chart_of_accounts = True
	try:
		doc.insert()
	finally:
		frappe.local.flags.ignore_chart_of_accounts = False
	return doc


def _ensure_warehouses(company: str) -> bool:
	if frappe.db.exists("Warehouse", {"company": company}):
		return False
	doc = frappe.get_doc("Company", company)
	doc.create_default_warehouses()
	return True


def _set_company_defaults(company: str) -> dict[str, str]:
	meta = frappe.get_meta("Company")
	values = {
		fieldname: account_for_code(company, code)
		for fieldname, code in COMPANY_DEFAULTS_BY_CODE.items()
		if meta.has_field(fieldname)
	}
	doc = frappe.get_doc("Company", company)
	doc.update(values)
	doc.flags.ignore_permissions = True
	doc.save()
	return values


def _set_nyabo_settings(company: str, is_vat_payer: bool) -> str | None:
	"""Record the VAT regime once Nyabo Company Settings exists (Phase 1 DocType)."""
	if not frappe.db.exists("DocType", "Nyabo Company Settings"):
		return None
	name = frappe.db.get_value("Nyabo Company Settings", {"company": company}, "name")
	doc = (
		frappe.get_doc("Nyabo Company Settings", name)
		if name
		else frappe.get_doc({"doctype": "Nyabo Company Settings", "company": company})
	)
	meta = frappe.get_meta("Nyabo Company Settings")
	if meta.has_field("vat_registered"):
		doc.vat_registered = 1 if is_vat_payer else 0
	if meta.has_field("simplified_regime"):
		doc.simplified_regime = 0 if is_vat_payer else 1
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


@frappe.whitelist()
def verify(company: str) -> dict[str, Any]:
	"""Compare a company against the chart, the default accounts and the tax templates."""
	if frappe.session.user != "Administrator":
		frappe.only_for("System Manager")
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist").format(company))

	expected = chart_mod.load_chart().by_number()
	found = code_map(company)
	missing_codes = sorted(code for code in expected if code not in found)

	meta = frappe.get_meta("Company")
	defaults = {
		fieldname: frappe.db.get_value("Company", company, fieldname)
		for fieldname in COMPANY_DEFAULTS_BY_CODE
		if meta.has_field(fieldname)
	}
	templates = {
		title: frappe.db.get_value(doctype, {"title": title, "company": company}, "name")
		for title, doctype in TAX_TEMPLATES.items()
	}
	problems = [f"missing account code {c}" for c in missing_codes]
	problems += [f"company default {f} is empty" for f, v in defaults.items() if not v]
	problems += [f"tax template {t} is missing" for t, v in templates.items() if not v]
	return {
		"company": company,
		"accounts_expected": len(expected),
		"accounts_found": len(found),
		"company_defaults": defaults,
		"tax_templates": templates,
		"problems": problems,
		"ok": not problems,
	}
