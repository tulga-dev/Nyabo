"""VAT (НӨАТ) templates for a company, built from account roles and the dated VAT rate.

Sales side:    "НӨАТ 10%"                -> role output_vat (2210 on V1, 3110 on v0.3)
Purchase side: "Татан суутгах НӨАТ 10%"  -> role input_vat  (1810 on V1, 1210 on v0.3)
Item tax templates: exempt and zero-rated, both 0% on both accounts.

The rate comes from the `vat.rate` tax parameter on the fiscal-year start (a fraction;
ERPNext wants percent, converted here and nowhere else). It is read with
`allow_unverified=True` because provisioning creates templates, it does not post.

For a company that is not a VAT payer (simplified regime) the templates still exist so
the accountant can use them deliberately, but none is marked default, so invoices do
not pick up VAT automatically and purchase VAT stays inside the expense.
"""

from __future__ import annotations

import datetime as dt

import frappe
from frappe.utils import getdate, today

from nyabo_mn.i18n import mn
from nyabo_mn.rules import aliases, params

OUTPUT_VAT_ROLE = "output_vat"
INPUT_VAT_ROLE = "input_vat"
VAT_RATE_KEY = "vat.rate"

SALES_TEMPLATE_TITLE = mn.TAX_SALES_VAT_10
PURCHASE_TEMPLATE_TITLE = mn.TAX_PURCHASE_VAT_10
ITEM_TAX_EXEMPT_TITLE = mn.TAX_ITEM_EXEMPT
ITEM_TAX_ZERO_TITLE = mn.TAX_ITEM_ZERO
VAT_ROW_DESCRIPTION = mn.TAX_SALES_VAT_10


def vat_rate_percent(on_date: dt.date | str | None = None) -> float:
	"""The VAT rate on a date as ERPNext's percent (0.10 -> 10.0)."""
	rate = params.get_decimal(VAT_RATE_KEY, getdate(on_date or today()), allow_unverified=True)
	return float(rate * 100)


def ensure_vat_templates(
	company: str, vat_registered: bool, on_date: dt.date | str | None = None
) -> dict[str, str]:
	"""Create the four templates if missing. Returns {title: document name}."""
	output_vat = aliases.account_for(company, f"role:{OUTPUT_VAT_ROLE}")
	input_vat = aliases.account_for(company, f"role:{INPUT_VAT_ROLE}")
	rate = vat_rate_percent(on_date)
	is_default = 1 if vat_registered else 0
	created: dict[str, str] = {}

	created[SALES_TEMPLATE_TITLE] = _ensure(
		"Sales Taxes and Charges Template",
		company,
		SALES_TEMPLATE_TITLE,
		{
			"is_default": is_default,
			"taxes": [
				{
					"charge_type": "On Net Total",
					"account_head": output_vat,
					"description": VAT_ROW_DESCRIPTION,
					"rate": rate,
				}
			],
		},
	)
	created[PURCHASE_TEMPLATE_TITLE] = _ensure(
		"Purchase Taxes and Charges Template",
		company,
		PURCHASE_TEMPLATE_TITLE,
		{
			"is_default": is_default,
			"taxes": [
				{
					"category": "Total",
					"add_deduct_tax": "Add",
					"charge_type": "On Net Total",
					"account_head": input_vat,
					"description": VAT_ROW_DESCRIPTION,
					"rate": rate,
				}
			],
		},
	)
	zero_rows = [
		{"tax_type": output_vat, "tax_rate": 0},
		{"tax_type": input_vat, "tax_rate": 0},
	]
	for title in (ITEM_TAX_EXEMPT_TITLE, ITEM_TAX_ZERO_TITLE):
		created[title] = _ensure("Item Tax Template", company, title, {"taxes": zero_rows})
	return created


def _ensure(doctype: str, company: str, title: str, values: dict) -> str:
	existing = frappe.db.get_value(doctype, {"title": title, "company": company}, "name")
	if existing:
		return existing
	doc = frappe.get_doc({"doctype": doctype, "title": title, "company": company, **values})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name
