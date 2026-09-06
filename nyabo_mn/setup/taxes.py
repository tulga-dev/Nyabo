"""VAT (НӨАТ) templates for a company, built from the chart codes.

Sales side:    "НӨАТ 10%"                -> 2210 Төлөх НӨАТ (output VAT, liability)
Purchase side: "Татан суутгах НӨАТ 10%"  -> 1810 Татан суутгах НӨАТ (input VAT, asset)
Item tax templates: exempt and zero-rated, both 0% on both accounts.

For a company that is not a VAT payer (simplified regime) the templates still exist so
the accountant can use them deliberately, but none is marked default, so invoices do
not pick up VAT automatically and purchase VAT stays inside the expense.
"""

from __future__ import annotations

import frappe

from nyabo_mn.i18n import mn
from nyabo_mn.setup.chart_db import account_for_code

VAT_RATE = 10.0
OUTPUT_VAT_CODE = "2210"
INPUT_VAT_CODE = "1810"

SALES_TEMPLATE_TITLE = mn.TAX_SALES_VAT_10
PURCHASE_TEMPLATE_TITLE = mn.TAX_PURCHASE_VAT_10
ITEM_TAX_EXEMPT_TITLE = mn.TAX_ITEM_EXEMPT
ITEM_TAX_ZERO_TITLE = mn.TAX_ITEM_ZERO
VAT_ROW_DESCRIPTION = mn.TAX_SALES_VAT_10


def ensure_vat_templates(company: str, vat_registered: bool) -> dict[str, str]:
	"""Create the four templates if missing. Returns {title: document name}."""
	output_vat = account_for_code(company, OUTPUT_VAT_CODE)
	input_vat = account_for_code(company, INPUT_VAT_CODE)
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
					"rate": VAT_RATE,
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
					"rate": VAT_RATE,
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
