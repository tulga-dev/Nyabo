"""Accounting policy document draft (Law on Accounting art. 18.2, 20.2.2) from the company setup.

The text lives in ``mn.POLICY_SECTIONS``; this module only fills the placeholders from
Nyabo Company Settings and Company, renders the Jinja template and turns it into a PDF.
Unknown facts render as "[ ]" and the page carries the ТӨСӨЛ watermark: Nyabo drafts,
the accountant completes and the director signs.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import frappe
from frappe.utils import formatdate, nowdate

from nyabo_mn.compliance import events
from nyabo_mn.compliance.hooks import retention_years
from nyabo_mn.i18n import mn
from nyabo_mn.reports.accounts import chart_scheme
from nyabo_mn.reports.month_end import is_vat_payer
from nyabo_mn.rules import regime

TEMPLATE = "nyabo_mn/templates/policy_document.html"
# Regime keys from rules.regime, wording from i18n/mn.py: neither is spelled here (F-12).
POLICY_REGIME_LABELS: dict[str, str] = {
	regime.REGIME_VAT_PAYER: mn.POLICY_REGIME_VAT_PAYER,
	regime.REGIME_SIMPLIFIED: mn.POLICY_REGIME_SIMPLIFIED,
}


def _settings(company: str) -> Any:
	if not frappe.db.exists("DocType", "Nyabo Company Settings"):
		return frappe._dict()
	name = frappe.db.get_value("Nyabo Company Settings", {"company": company}, "name")
	return frappe.get_doc("Nyabo Company Settings", name) if name else frappe._dict()


def _label(mapping: dict[str, str], key: Any) -> str:
	return mapping.get(key, mn.POLICY_UNKNOWN) if key else mn.POLICY_UNKNOWN


def context(company: str) -> dict[str, Any]:
	"""Everything the template needs; every unknown fact is ``mn.POLICY_UNKNOWN``."""
	settings = _settings(company)
	company_doc = frappe.get_doc("Company", company)
	today = dt.date.fromisoformat(nowdate())
	vat = is_vat_payer(company, today)
	# The regime name comes from rules.regime, never from a literal here (F-12).
	regime_key = None if vat is None else regime.name_for_vat_status(vat)
	values = {
		"company": company,
		"tax_id": company_doc.get("tax_id") or mn.POLICY_UNKNOWN,
		"regime": _label(POLICY_REGIME_LABELS, regime_key),
		"chart_scheme": _label(mn.POLICY_CHART_SCHEME_LABELS, chart_scheme(company)),
		"inventory_method": _label(mn.POLICY_INVENTORY_LABELS, settings.get("inventory_method")),
		"has_inventory": mn.BTN_YES if settings.get("has_inventory") else mn.BTN_NO,
		"depreciation_method": _label(mn.POLICY_DEPRECIATION_LABELS, settings.get("depreciation_method")),
		"fx_policy": settings.get("fx_policy") or mn.POLICY_UNKNOWN,
		"retention_years": str(settings.get("retention_years") or retention_years(today)),
		"accountant": settings.get("accountant_of_record_name") or mn.POLICY_UNKNOWN,
		"micpa_permit": settings.get("accountant_micpa_permit") or mn.POLICY_UNKNOWN,
		"generated_at": formatdate(today),
		"fiscal_year": mn.POLICY_FISCAL_YEAR,
	}
	sections = [
		{
			"key": section["key"],
			"title": section["title"],
			"paragraphs": [p.format(**values) for p in section["paragraphs"]],
		}
		for section in mn.POLICY_SECTIONS
	]
	facts = [(mn.POLICY_FIELD_LABELS[key], values[key]) for key in mn.POLICY_FIELD_LABELS if key in values]
	return {
		"title": mn.POLICY_TITLE,
		"watermark": mn.POLICY_DRAFT_WATERMARK,
		"company": company,
		"intro": mn.POLICY_INTRO.format(company=company),
		"facts": facts,
		"values": values,
		"sections": sections,
		"signatures": [
			mn.POLICY_SIGN_DIRECTOR,
			mn.POLICY_SIGN_ACCOUNTANT.format(accountant=values["accountant"]),
		],
		"footer": mn.POLICY_SOURCES_FOOTER,
		"missing": [key for key, value in values.items() if value == mn.POLICY_UNKNOWN],
	}


def render_html(company: str) -> str:
	return frappe.render_template(TEMPLATE, context(company))


def generate_pdf(company: str) -> bytes:
	from frappe.utils.pdf import get_pdf

	return get_pdf(render_html(company), options={"page-size": "A4"})


def attach_to_settings(company: str) -> str:
	"""Save the PDF as a private File on the company's Nyabo Company Settings; returns file_url."""
	settings = _settings(company)
	if not settings.get("name"):
		frappe.throw(mn.MSG_REGIME_MISSING.format(date=nowdate()))
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": mn.POLICY_FILE_NAME.format(company=company),
			"content": generate_pdf(company),
			"is_private": 1,
			"attached_to_doctype": "Nyabo Company Settings",
			"attached_to_name": settings.name,
		}
	)
	file.flags.ignore_permissions = True
	file.insert()
	events.log(
		mn.EVENT_POLICY_GENERATED,
		company=company,
		ref_doctype="File",
		ref_name=file.name,
		payload={"file_url": file.file_url},
	)
	return file.file_url
