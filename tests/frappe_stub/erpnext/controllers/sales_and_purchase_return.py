"""``make_return_doc`` (erpnext/controllers/sales_and_purchase_return.py, version-16).

Kept: the mapped return document gets ``is_return = 1`` and ``return_against``, every
item's ``qty`` (and ``stock_qty`` / ``received_qty``) is negated, ``Actual`` taxes are
negated, and totals are recomputed. Not mirrored: serial/batch bundles, POS payments,
print headings, returned-qty maps against earlier returns and payment schedules.
"""

from __future__ import annotations

from typing import Any

from frappe.utils.data import flt


def make_return_doc(
	doctype: str, source_name: str, target_doc: Any = None, return_against_rejected_qty: bool = False
) -> Any:
	import frappe
	from frappe.model.mapper import get_mapped_doc

	def set_missing_values(source: Any, target: Any) -> None:
		doc = frappe.get_doc(target) if isinstance(target, dict) else target
		doc.is_return = 1
		doc.return_against = source.name
		if doc.meta.has_field("ignore_pricing_rule"):
			doc.ignore_pricing_rule = 1
		if doc.meta.has_field("set_warehouse"):
			doc.set_warehouse = ""
		if doctype == "Sales Invoice":
			doc.is_debit_note = 0
			doc.is_pos = source.is_pos
		if doc.meta.has_field("tax_withholding_group"):
			doc.tax_withholding_group = source.get("tax_withholding_group")
			doc.ignore_tax_withholding_threshold = source.get("ignore_tax_withholding_threshold")
		for tax in doc.get("taxes") or []:
			if tax.charge_type == "Actual":
				tax.tax_amount = -1 * flt(tax.tax_amount)
		if doctype == "Purchase Invoice":
			doc.paid_amount = -1 * flt(source.paid_amount)
			doc.base_paid_amount = -1 * flt(source.base_paid_amount)
			doc.payment_terms_template = ""
		if doc.get("discount_amount"):
			doc.discount_amount = -1 * flt(source.discount_amount)
		doc.run_method("calculate_taxes_and_totals")

	def update_item(source_doc: Any, target_doc: Any, source_parent: Any) -> None:
		target_doc.qty = -1 * flt(source_doc.qty)
		if target_doc.meta.has_field("stock_qty"):
			target_doc.stock_qty = -1 * flt(source_doc.stock_qty)
		if doctype == "Purchase Invoice":
			target_doc.received_qty = -1 * flt(source_doc.received_qty)
			target_doc.rejected_qty = -1 * flt(source_doc.rejected_qty)
			target_doc.purchase_invoice_item = source_doc.name
			target_doc.apply_tds = source_doc.apply_tds
		elif doctype == "Sales Invoice":
			target_doc.sales_invoice_item = source_doc.name

	def item_condition(doc: Any) -> Any:
		return doc.qty

	return get_mapped_doc(
		doctype,
		source_name,
		{
			doctype: {"doctype": doctype, "validation": {"docstatus": ["=", 1]}},
			doctype + " Item": {
				"doctype": doctype + " Item",
				"field_map": {"serial_no": "serial_no", "batch_no": "batch_no", "bom": "bom"},
				"postprocess": update_item,
				"condition": item_condition,
			},
		},
		target_doc,
		set_missing_values,
	)
