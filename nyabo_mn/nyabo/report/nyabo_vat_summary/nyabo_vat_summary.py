"""НӨАТ-ын тойм — per-document output / input VAT for the month, from nyabo_mn.reports.vat_summary."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import getdate

from nyabo_mn.i18n import mn
from nyabo_mn.reports import vat_summary


def columns() -> list[dict[str, Any]]:
	return [
		{"label": mn.COL_DATE, "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": mn.COL_VOUCHER_TYPE, "fieldname": "voucher_type", "fieldtype": "Data", "width": 130},
		{
			"label": mn.COL_VOUCHER_NO,
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 170,
		},
		{"label": mn.COL_PARTY, "fieldname": "party", "fieldtype": "Data", "width": 180},
		{"label": mn.LBL_OUTPUT_VAT, "fieldname": "output_vat", "fieldtype": "Currency", "width": 140},
		{"label": mn.LBL_INPUT_VAT, "fieldname": "input_vat", "fieldtype": "Currency", "width": 140},
	]


def execute(
	filters: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], None, None, list[dict[str, Any]]]:
	filters = frappe._dict(filters or {})
	if not (filters.company and filters.from_date and filters.to_date):
		return columns(), [], None, None, []
	summary = vat_summary.compute(filters.company, (getdate(filters.from_date), getdate(filters.to_date)))
	data = [
		{
			"posting_date": d["posting_date"],
			"voucher_type": d["voucher_type"],
			"voucher_no": d["voucher_no"],
			"party": d["party"],
			"output_vat": float(d["output_vat"]),
			"input_vat": float(d["input_vat"]),
		}
		for d in summary["by_document"]
	]
	report_summary = [
		{"label": mn.LBL_OUTPUT_VAT, "value": float(summary["output_vat"]), "datatype": "Currency"},
		{"label": mn.LBL_INPUT_VAT, "value": float(summary["input_vat"]), "datatype": "Currency"},
		{"label": mn.LBL_NET_VAT, "value": float(summary["net"]), "datatype": "Currency"},
	]
	return columns(), data, None, None, report_summary
