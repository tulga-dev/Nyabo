"""Create a company with a Mongolian chart, VAT templates, regime, banks and sane defaults.

From a bench shell (SSH on Frappe Cloud):
    bench --site <site> execute nyabo_mn.setup.provision_company.provision_company \
        --kwargs '{"company_name": "Тест ХХК", "abbr": "TST", "vat_registered": 0, "chart_scheme": "v03"}'

From the browser as a System Manager (F12 -> Console):
    frappe.call("nyabo_mn.setup.provision_company.provision",
        {company_name: "Тест ХХК", abbr: "TST", vat_registered: 0}).then(r => console.log(r.message))

Check an existing company:
    bench --site <site> execute nyabo_mn.setup.provision_company.verify --kwargs '{"company": "Тест ХХК"}'

What it does, in order (all-or-nothing: an error rolls the whole thing back):
1. enables the currency and makes sure a fiscal year covers today (calendar year);
2. inserts the Company with ERPNext's own chart creation switched off
   (frappe.local.flags.ignore_chart_of_accounts, the flag ERPNext's Chart of Accounts
   Importer uses), then installs the chart of the requested scheme with ERPNext's
   create_charts(custom_chart=...): "v1" (the Phase 0 draft), "v03" (seed/chart_v03.json)
   or "accountant" (the accountant's own CSV, with automatic Nyabo Account Alias rows
   where names match the v0.3 template);
3. creates the default warehouses ERPNext skipped, writes Nyabo Company Settings
   (chart scheme, default expense code, regime history from the fiscal-year start,
   inventory flag), sets every Company default account from the scheme's account roles
   (code_roles.json), creates the VAT templates, one GL sub-account + Bank Account per
   bank row, and the company's default Nyabo Rules.

The chart is only installed on a company with no accounts. Replacing the chart of an
existing company is deliberately unsupported here: use ERPNext's Chart of Accounts
Importer for that, it refuses when transactions exist.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.nyabo.seed import seed_path
from nyabo_mn.rules import aliases, regime
from nyabo_mn.rules import seed as seed_mod
from nyabo_mn.setup import banks as banks_mod
from nyabo_mn.setup import chart as chart_mod
from nyabo_mn.setup import chart_csv
from nyabo_mn.setup.chart import ChartError, NormalizedChart
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
DEFAULT_SCHEME = aliases.SCHEME_V1
SETTINGS_DOCTYPE = "Nyabo Company Settings"

# Company default-account field -> account role (code_roles.json). Only fields that exist on this
# ERPNext version are set, and a role the scheme leaves null (D-013) is skipped. ERPNext looks some
# of these up by English account name ("Write Off", "Exchange Gain/Loss", "Round Off"); our charts
# have Mongolian names, so we set them explicitly.
COMPANY_DEFAULTS_BY_ROLE: dict[str, str] = {
	"default_cash_account": "cash",
	"default_bank_account": "bank",
	"default_receivable_account": "receivable",
	"default_payable_account": "payable",
	"default_income_account": "revenue_sales",
	"default_expense_account": "default_expense",
	"round_off_account": "round_off",
	"write_off_account": "write_off",
	"exchange_gain_loss_account": "fx_gain_loss",
	"unrealized_exchange_gain_loss_account": "fx_gain_loss",
	"accumulated_depreciation_account": "accumulated_depreciation",
	"depreciation_expense_account": "depreciation_expense",
	"capital_work_in_progress_account": "cwip",
	"default_inventory_account": "inventory_goods",
	"stock_received_but_not_billed": "srbnb",
	"stock_adjustment_account": "stock_adjustment",
	"expenses_included_in_valuation": "valuation_expense",  # field name up to ERPNext v15
	"expenses_added_to_stock_account": "valuation_expense",  # field name in ERPNext v16
	"asset_received_but_not_billed": "asset_rbnb",
	"disposal_account": "disposal_loss",
	"default_deferred_revenue_account": "deferred_revenue",
	"default_deferred_expense_account": "prepaid_expense",
	"default_discount_account": "sales_discount",
}
TAX_TEMPLATES: dict[str, str] = {
	SALES_TEMPLATE_TITLE: "Sales Taxes and Charges Template",
	PURCHASE_TEMPLATE_TITLE: "Purchase Taxes and Charges Template",
	ITEM_TAX_EXEMPT_TITLE: "Item Tax Template",
	ITEM_TAX_ZERO_TITLE: "Item Tax Template",
}


def company_defaults_by_code(scheme: str) -> dict[str, str]:
	"""Company field -> template code for a scheme; roles the scheme has no account for are left out."""
	table = aliases.code_roles()[aliases.role_scheme(scheme)]
	return {field: str(table[role]) for field, role in COMPANY_DEFAULTS_BY_ROLE.items() if table.get(role)}


# The Phase 0 (V1) rendering, kept for callers and tests that address accounts by V1 code.
COMPANY_DEFAULTS_BY_CODE: dict[str, str] = company_defaults_by_code(aliases.SCHEME_V1)


@frappe.whitelist()
def provision(
	company_name: str,
	abbr: str,
	country: str = DEFAULT_COUNTRY,
	currency: str = DEFAULT_CURRENCY,
	vat_registered: int | str = 0,
	enable_perpetual_inventory: int | str = 0,
	chart_scheme: str = DEFAULT_SCHEME,
	chart_csv_rows: str | list | None = None,
	bank_accounts: str | list | None = None,
	has_inventory: int | str = 0,
) -> dict[str, Any]:
	"""Browser-callable wrapper (System Manager only). List arguments may arrive as JSON text."""
	frappe.only_for("System Manager")
	return provision_company(
		company_name=company_name,
		abbr=abbr,
		country=country,
		currency=currency,
		vat_registered=vat_registered,
		enable_perpetual_inventory=enable_perpetual_inventory,
		chart_scheme=chart_scheme,
		chart_csv=_json_arg(chart_csv_rows),
		bank_accounts=_json_arg(bank_accounts),
		has_inventory=has_inventory,
	)


@frappe.whitelist()
def apply_onboarding(
	company: str,
	vat_registered: bool | int | str = 0,
	banks: Iterable[Mapping[str, Any]] | str | None = None,
	has_inventory: bool | int | str = 0,
	accountant_name: str = "",
	micpa: str = "",
) -> dict[str, Any]:
	"""Apply the answers of the Telegram ``/эхлэх`` wizard to an already provisioned company.

	The wizard writes the answers to Nyabo Company Settings itself (§5.2); this makes the
	ERPNext side match them - VAT templates (default only when the company is registered),
	the regime row from the fiscal-year start, one GL sub-account + ERPNext Bank Account per
	bank the owner named, the inventory flag and the accountant of record. Everything is
	idempotent, so re-running the wizard changes nothing.
	"""
	company = (company or "").strip()
	if not company:
		frappe.throw(_("company is required"))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist").format(company))
	is_vat_payer = bool(cint(vat_registered))
	inventory = bool(cint(has_inventory))
	fiscal_year_start = getdate(frappe.db.get_value("Fiscal Year", _ensure_fiscal_year(), "year_start_date"))
	report: dict[str, Any] = {
		"company": company,
		"vat_registered": is_vat_payer,
		"tax_templates": _apply_vat_templates(company, is_vat_payer, fiscal_year_start),
		"regime": _ensure_regime(company, is_vat_payer, fiscal_year_start),
		"bank_accounts": _ensure_bank_rows(company, _json_arg(banks) or []),
	}
	report["settings"] = _apply_onboarding_settings(company, inventory, accountant_name, micpa)
	log_event(
		"onboarding.applied",
		company=company,
		vat_registered=is_vat_payer,
		banks=len(report["bank_accounts"]),
		has_inventory=inventory,
	)
	return report


def _apply_vat_templates(company: str, is_vat_payer: bool, on_date: Any) -> dict[str, str]:
	"""``ensure_vat_templates`` plus the default flag, which provisioning only sets on creation.

	The company may have been provisioned before the owner answered the VAT question, so the
	templates already exist with ``is_default = 0``; a VAT payer needs them picked up
	automatically (and a company that de-registered needs the flag cleared again).
	"""
	created = ensure_vat_templates(company, is_vat_payer, on_date)
	is_default = 1 if is_vat_payer else 0
	for title in (SALES_TEMPLATE_TITLE, PURCHASE_TEMPLATE_TITLE):
		name = created.get(title)
		if name and frappe.db.get_value(TAX_TEMPLATES[title], name, "is_default") != is_default:
			frappe.db.set_value(TAX_TEMPLATES[title], name, "is_default", is_default)
	return created


def _apply_onboarding_settings(
	company: str, has_inventory: bool, accountant_name: str, micpa: str
) -> str | None:
	"""Inventory flag and accountant of record on Nyabo Company Settings; blanks never overwrite."""
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return None
	name = regime.settings_name(company)
	doc = (
		frappe.get_doc(SETTINGS_DOCTYPE, name)
		if name
		else frappe.get_doc({"doctype": SETTINGS_DOCTYPE, "company": company})
	)
	doc.has_inventory = 1 if has_inventory else 0
	if accountant_name:
		doc.accountant_of_record_name = accountant_name
	if micpa:
		doc.accountant_micpa_permit = micpa
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def _json_arg(value: Any) -> Any:
	if isinstance(value, str) and value.strip().startswith(("[", "{")):
		return json.loads(value)
	return value


def provision_company(
	company_name: str,
	abbr: str,
	country: str = DEFAULT_COUNTRY,
	currency: str = DEFAULT_CURRENCY,
	vat_registered: int | str = 0,
	enable_perpetual_inventory: int | str = 0,
	chart_path: str | None = None,
	chart_scheme: str = DEFAULT_SCHEME,
	chart_csv: Any = None,
	bank_accounts: Iterable[Mapping[str, Any]] | None = None,
	has_inventory: int | str = 0,
) -> dict[str, Any]:
	company_name = (company_name or "").strip()
	abbr = (abbr or "").strip()
	if not company_name or not abbr:
		frappe.throw(_("company_name and abbr are required"))
	if chart_scheme not in aliases.CHART_SCHEMES:
		frappe.throw(_("chart_scheme must be one of {0}").format(", ".join(aliases.CHART_SCHEMES)))
	is_vat_payer = bool(cint(vat_registered))
	perpetual = bool(cint(enable_perpetual_inventory))

	chart, template_match = _load_chart(chart_scheme, chart_path, chart_csv, currency)
	report: dict[str, Any] = {
		"company": company_name,
		"abbr": abbr,
		"vat_registered": is_vat_payer,
		"chart": chart.name,
		"chart_scheme": chart_scheme,
		"warnings": list(chart.warnings),
		"created": {},
	}

	_ensure_currency(currency)
	fiscal_year = _ensure_fiscal_year()
	report["created"]["fiscal_year"] = fiscal_year
	fiscal_year_start = getdate(frappe.db.get_value("Fiscal Year", fiscal_year, "year_start_date"))

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
	report["aliases"] = _ensure_aliases(company_name, chart_scheme, template_match, report["warnings"])
	report["nyabo_settings"] = _ensure_settings(company_name, chart_scheme, bool(cint(has_inventory)))
	report["company_defaults"] = _set_company_defaults(company_name, chart_scheme, report["warnings"])
	report["tax_templates"] = ensure_vat_templates(company_name, is_vat_payer, fiscal_year_start)
	report["regime"] = _ensure_regime(company_name, is_vat_payer, fiscal_year_start)
	report["bank_accounts"] = _ensure_bank_rows(company_name, bank_accounts or [])
	report["created"]["rules"] = seed_mod.seed_default_rules(company_name, aliases.role_scheme(chart_scheme))
	report["verify"] = verify(company_name)

	log_event(
		"provision.done",
		company=company_name,
		scheme=chart_scheme,
		accounts=report["created"]["accounts"],
		vat_registered=is_vat_payer,
		ok=report["verify"]["ok"],
	)
	return report


# --- chart ---------------------------------------------------------------------------------------


def template_chart(currency: str = DEFAULT_CURRENCY) -> NormalizedChart:
	"""The v0.3 model chart (seed/chart_v03.json) through the same loader as the V1 draft."""
	return chart_mod.load_chart(seed_path("chart_v03"), currency=currency)


def _load_chart(
	scheme: str, chart_path: str | None, csv_source: Any, currency: str
) -> tuple[NormalizedChart, chart_csv.TemplateMatch | None]:
	if scheme == aliases.SCHEME_V1:
		return chart_mod.load_chart(chart_path or chart_mod.DEFAULT_CHART_PATH, currency=currency), None
	if scheme == aliases.SCHEME_V03:
		return chart_mod.load_chart(chart_path or seed_path("chart_v03"), currency=currency), None
	if csv_source is None:
		frappe.throw(mn.MSG_CHART_CSV_REQUIRED)
	chart = chart_csv.load_csv_chart(csv_source, currency=currency)
	template = template_chart(currency)
	match = chart_csv.match_template(chart, template)
	chart_csv.apply_template_categories(chart, template, match)
	return chart, match


def _ensure_aliases(
	company: str, scheme: str, match: chart_csv.TemplateMatch | None, warnings: list[str]
) -> dict[str, Any]:
	"""v0.3 companies get the V1 aliases; accountant charts get template + V1 aliases from the name match."""
	if scheme == aliases.SCHEME_V1:
		return {"v1": 0}
	if scheme == aliases.SCHEME_V03:
		return {"v1": aliases.seed_v1_aliases(company)}
	assert match is not None
	for template_code, target in match.aliases.items():
		aliases.upsert_alias(company, aliases.ALIAS_SCHEME_TEMPLATE, template_code, target)
	v1_count = aliases.seed_v1_aliases(company, to_codes=match.aliases)
	if match.unmatched_template:
		warnings.append(
			"template accounts without a match in the accountant's chart: "
			+ ", ".join(match.unmatched_template)
		)
	return {
		"mof": len(match.aliases),
		"v1": v1_count,
		"unmatched_template": list(match.unmatched_template),
		"unmatched_chart": list(match.unmatched_chart),
	}


# --- company, fiscal year, warehouses ------------------------------------------------------------


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


# --- settings, defaults, regime, banks -------------------------------------------------------------


def _resolve_for_scheme(company: str, scheme: str, role: str) -> str | None:
	"""Chart code of a role before the settings row exists (aliases.resolve_code reads the scheme from it)."""
	table = aliases.code_roles()[aliases.role_scheme(scheme)]
	code = table.get(role)
	if not code:
		return None
	if scheme == aliases.SCHEME_ACCOUNTANT:
		return aliases.alias_target(company, str(code), aliases.ALIAS_SCHEME_TEMPLATE) or str(code)
	return str(code)


def _ensure_settings(company: str, scheme: str, has_inventory: bool) -> str | None:
	"""Nyabo Company Settings with the scheme and a default expense code that exists in the chart."""
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return None
	name = frappe.db.get_value(SETTINGS_DOCTYPE, {"company": company}, "name")
	doc = (
		frappe.get_doc(SETTINGS_DOCTYPE, name)
		if name
		else frappe.get_doc({"doctype": SETTINGS_DOCTYPE, "company": company})
	)
	doc.chart_scheme = scheme
	expense_code = _resolve_for_scheme(company, scheme, "default_expense")
	if expense_code and frappe.db.exists("Account", {"company": company, "account_number": expense_code}):
		doc.default_expense_code = expense_code
	if has_inventory:
		doc.has_inventory = 1
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def _set_company_defaults(company: str, scheme: str, warnings: list[str]) -> dict[str, str]:
	meta = frappe.get_meta("Company")
	table = aliases.code_roles()[aliases.role_scheme(scheme)]
	values: dict[str, str] = {}
	for fieldname, role in COMPANY_DEFAULTS_BY_ROLE.items():
		if not meta.has_field(fieldname) or not table.get(role):
			continue  # roles the scheme leaves null (D-013) simply do not become defaults
		try:
			values[fieldname] = aliases.account_for(company, f"role:{role}", leaf=False)
		except ChartError as exc:
			warnings.append(f"company default {fieldname} ({role}) not set: {exc}")
	doc = frappe.get_doc("Company", company)
	doc.update(values)
	doc.flags.ignore_permissions = True
	doc.save()
	return values


def _ensure_regime(company: str, is_vat_payer: bool, fiscal_year_start: Any) -> dict[str, Any]:
	"""First regime row from the fiscal-year start; an existing history is the accountant's and is kept."""
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return {}
	existing = regime.history(company)
	if existing:
		return {"regime": existing[-1][0], "effective_from": str(existing[-1][1]), "created": False}
	name = regime.initial_regime(is_vat_payer)
	regime.set_regime(company, name, fiscal_year_start)
	return {"regime": name, "effective_from": str(getdate(fiscal_year_start)), "created": True}


def _ensure_bank_rows(company: str, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
	rows = list(rows)
	if not rows:
		return []
	created = banks_mod.ensure_bank_accounts(company, rows)
	settings = regime.settings_name(company)
	if settings:
		doc = frappe.get_doc(SETTINGS_DOCTYPE, settings)
		existing = {(r.bank, r.currency, r.account_number or None): r for r in doc.bank_accounts or []}
		for row in created:
			key = (row["bank"], row["currency"], row["account_number"])
			target = existing.get(key) or doc.append("bank_accounts", {})
			target.update(row)
		doc.flags.ignore_permissions = True
		doc.save()
	return created


# --- verify ------------------------------------------------------------------------------------


def _expected_default_fields(company: str, scheme: str) -> list[str]:
	"""Company defaults a scheme must have: on the accountant's chart only roles its aliases reach."""
	fields = list(company_defaults_by_code(scheme))
	if scheme != aliases.SCHEME_ACCOUNTANT:
		return fields
	return [
		field
		for field in fields
		if aliases.in_chart(company, aliases.resolve_code(company, f"role:{COMPANY_DEFAULTS_BY_ROLE[field]}"))
	]


@frappe.whitelist()
def verify(company: str) -> dict[str, Any]:
	"""Compare a company against its chart scheme, the default accounts and the tax templates."""
	if frappe.session.user != "Administrator":
		frappe.only_for("System Manager")
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist").format(company))

	scheme = aliases.chart_scheme(company)
	found = code_map(company)
	if scheme == aliases.SCHEME_V1:
		expected = set(chart_mod.load_chart().by_number())
	elif scheme == aliases.SCHEME_V03:
		expected = set(template_chart().by_number())
	else:
		expected = set(found)
	missing_codes = sorted(code for code in expected if code not in found)

	meta = frappe.get_meta("Company")
	defaults = {
		fieldname: frappe.db.get_value("Company", company, fieldname)
		for fieldname in _expected_default_fields(company, scheme)
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
		"chart_scheme": scheme,
		"accounts_expected": len(expected),
		"accounts_found": len(found),
		"company_defaults": defaults,
		"tax_templates": templates,
		"problems": problems,
		"ok": not problems,
	}


def account_by_role(company: str, role: str) -> str:
	"""ERPNext account of a role for handlers that only know the role name (kept for callers of Phase 0)."""
	return account_for_code(company, aliases.resolve_code(company, f"role:{role}"))
