"""Хялбаршуулсан горимын тойм (1%) — quarterly revenue and tax from nyabo_mn.reports.simplified_summary.

Rows: the three months of the quarter (revenue), then the quarter total with the rate and
the tax, then the tax-parameter row that supplied the rate (key, effective date, verified).

There is no Simulation filter (F-11): it used to be one, and ticking it switched off the
verified guard on the statutory 1% rate for anyone who could open the report. The label
still appears when ``frappe.flags.nyabo_simulation`` is set, which only the simulator and
the tests do.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import getdate

from nyabo_mn.core.dates import period_label, quarter_of
from nyabo_mn.i18n import mn
from nyabo_mn.reports import simplified_summary


def columns() -> list[dict[str, Any]]:
	return [
		{"label": mn.LBL_MONTH, "fieldname": "label", "fieldtype": "Data", "width": 260},
		{"label": mn.LBL_REVENUE, "fieldname": "revenue", "fieldtype": "Currency", "width": 160},
		{"label": mn.LBL_RATE_PCT, "fieldname": "rate_pct", "fieldtype": "Percent", "width": 90},
		{"label": mn.LBL_TAX, "fieldname": "tax", "fieldtype": "Currency", "width": 160},
		{"label": mn.LBL_TAX_PARAMETER_ROW, "fieldname": "parameter", "fieldtype": "Data", "width": 260},
	]


def _clearance(row: dict[str, Any]) -> str:
	"""Which of the three things lets this parameter carry a statutory figure (VER-07).

	The guard refuses an uncleared row before any of this is printed, so «Баталгаажаагүй» here
	means only one thing outside a simulation: this company's accountant accepted it, and that
	is a named person on the record rather than nothing at all.
	"""
	if row.get("verified"):
		return mn.LBL_VERIFIED
	return mn.LBL_ACCEPTED_FOR_COMPANY if row.get("accepted") else mn.LBL_UNVERIFIED


def execute(filters: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
	filters = frappe._dict(filters or {})
	if not (filters.company and filters.to_date):
		return columns(), []
	end = getdate(filters.to_date)
	quarter = f"{end.year}-Q{quarter_of(end)}"
	summary = simplified_summary.compute(filters.company, quarter)
	rate_pct = float(summary["rate"] * 100)
	data = [
		{"label": period_label(m["period"]), "revenue": float(m["revenue"]), "rate_pct": None, "tax": None}
		for m in summary["months"]
	]
	row = summary["rate_row"]
	verified = _clearance(row)
	data.append(
		{
			"label": mn.LBL_TOTAL,
			"revenue": float(summary["revenue"]),
			"rate_pct": rate_pct,
			"tax": float(summary["tax_1pct"]),
			"parameter": f"{row['key']} ({row['effective_from']}) · {verified}"
			+ (f" · {mn.LBL_SIMULATION}" if summary["simulation"] else ""),
		}
	)
	# The regime's conditions the figure rests on (CIT art. 29.1 and 29.3.1), and any warning.
	for condition in summary["eligibility"]["rows"].values():
		state = _clearance(condition)
		data.append(
			{
				"label": mn.LBL_REGIME_CONDITION,
				"parameter": f"{condition['key']} ({condition['article']}) · {state}",
			}
		)
	data.extend({"label": warning} for warning in summary["warnings"])
	return columns(), data
