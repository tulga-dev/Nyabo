"""Script report -> PDF (Cyrillic-safe HTML through wkhtmltopdf) or XLSX.

The PDF is rendered from ``nyabo_mn/templates/report.html`` with the MoF header fields
(Байгууллагын нэр, Журналын төрөл, Тайлант үе) and the two signature lines of the
Order 100/2018 journals; every label comes from ``i18n/mn.py``. A report with no MoF form
behind it (the VAT and 1% summaries) is footed ``mn.FORM_SOURCE_INTERNAL``: Nyabo does not
name an instrument it has not read (``docs/legal/README.md``).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import frappe
from frappe.utils import formatdate, nowdate

from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn

REPORT_TEMPLATE = "nyabo_mn/templates/report.html"
JOURNAL_TYPES: dict[str, str] = {
	"Nyabo General Journal": mn.JOURNAL_TYPE_GENERAL,
	"Nyabo Cash Journal": mn.JOURNAL_TYPE_CASH_MNT,
}
SOURCES: dict[str, str] = {
	"Nyabo General Journal": mn.FORM_SOURCE_ORDER_100,
	"Nyabo Cash Journal": mn.FORM_SOURCE_ORDER_100,
}
MONEY_TYPES: tuple[str, ...] = ("Currency", "Float")


def run_report(report_name: str, filters: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Any]]:
	"""(columns, rows) of a script report through frappe.desk.query_report.run."""
	from frappe.desk import query_report

	result = query_report.run(report_name, filters=filters, ignore_prepared_report=True)
	return list(result.get("columns") or []), list(result.get("result") or [])


def _column(col: Any) -> dict[str, Any]:
	if isinstance(col, str):
		label, _sep, rest = col.partition(":")
		fieldtype = rest.split("/")[0] if rest else "Data"
		return {"label": label, "fieldname": frappe.scrub(label), "fieldtype": fieldtype or "Data"}
	return {
		"label": col.get("label") or col.get("fieldname"),
		"fieldname": col.get("fieldname") or frappe.scrub(col.get("label") or ""),
		"fieldtype": col.get("fieldtype") or "Data",
	}


def format_cell(value: Any, fieldtype: str) -> str:
	if value in (None, ""):
		return ""
	if fieldtype in MONEY_TYPES:
		return fmt_mnt(Decimal(str(value)))
	if fieldtype == "Date" or isinstance(value, dt.date):
		return formatdate(value)
	return str(value)


def _rows_as_cells(columns: list[dict[str, Any]], rows: list[Any]) -> list[list[str]]:
	out: list[list[str]] = []
	for index, row in enumerate(rows, 1):
		cells: list[str] = []
		for position, col in enumerate(columns):
			if isinstance(row, dict):
				value = row.get(col["fieldname"])
			else:
				value = row[position] if position < len(row) else None
			if col["fieldname"] == "row_no" and value in (None, ""):
				value = index
			cells.append(format_cell(value, col["fieldtype"]))
		out.append(cells)
	return out


def render_report_html(
	report_name: str,
	filters: dict[str, Any],
	title_mn: str,
	company: str,
	period: str,
	signatures: list[tuple[str, str]] | None = None,
) -> str:
	columns, rows = run_report(report_name, filters)
	return render_rows_html(report_name, columns, rows, filters, title_mn, company, period, signatures)


def render_rows_html(
	report_name: str,
	columns: list[Any],
	rows: list[Any],
	filters: dict[str, Any],
	title_mn: str,
	company: str,
	period: str,
	signatures: list[tuple[str, str]] | None = None,
) -> str:
	"""The same form as a script report, from columns and rows the caller already has.

	The trial balance card uses this: its rows come from ``month_end.trial_balance`` (ERPNext's
	report when it runs, the GL aggregation when it does not), so there is no report name to
	run — only the sheet to print.
	"""
	cols = [_column(c) for c in columns]
	signature_lines = signatures or [(mn.JOURNAL_KEPT_BY, ""), (mn.JOURNAL_CHECKED_BY, "")]
	context = {
		"title": title_mn,
		"company": company,
		"period": period,
		"journal_type": JOURNAL_TYPES.get(report_name, ""),
		"source": SOURCES.get(report_name, mn.FORM_SOURCE_INTERNAL),
		"from_date": formatdate(filters.get("from_date")) if filters.get("from_date") else "",
		"to_date": formatdate(filters.get("to_date")) if filters.get("to_date") else "",
		"columns": cols,
		"rows": _rows_as_cells(cols, rows),
		"signatures": signature_lines,
		"prepared_on": formatdate(nowdate()),
		"watermark": mn.REPORT_PROVISIONAL,
		"L": {
			"company": mn.LBL_COMPANY,
			"period": mn.LBL_PERIOD,
			"journal_type": mn.LBL_JOURNAL_TYPE,
			"from_date": mn.LBL_FROM_DATE,
			"to_date": mn.LBL_TO_DATE,
			"prepared_on": mn.LBL_PREPARED_ON,
			"signature": mn.LBL_SIGNATURE,
			"source": mn.LBL_REPORT_SOURCE,
			"row_no": mn.LBL_ROW_NO,
		},
		"footer": mn.REPORT_PDF_FOOTER.format(source=SOURCES.get(report_name, mn.FORM_SOURCE_INTERNAL)),
	}
	return frappe.render_template(REPORT_TEMPLATE, context)


def report_to_pdf(
	report_name: str,
	filters: dict[str, Any],
	title_mn: str,
	company: str,
	period: str,
	signatures: list[tuple[str, str]] | None = None,
) -> bytes:
	"""Render the report as PDF bytes (landscape A4 fits the seven ЕЖ columns)."""
	from frappe.utils.pdf import get_pdf

	html = render_report_html(report_name, filters, title_mn, company, period, signatures)
	return get_pdf(html, options={"orientation": "Landscape", "page-size": "A4"})


def rows_to_pdf(
	title_mn: str, company: str, period: str, columns: list[Any], rows: list[Any], filters: dict[str, Any]
) -> bytes:
	from frappe.utils.pdf import get_pdf

	html = render_rows_html(title_mn, columns, rows, filters, title_mn, company, period)
	return get_pdf(html, options={"orientation": "Landscape", "page-size": "A4"})


def report_to_xlsx(report_name: str, filters: dict[str, Any]) -> bytes:
	"""Header row + data rows as an .xlsx (bytes) via frappe.utils.xlsxutils.make_xlsx."""
	columns, rows = run_report(report_name, filters)
	return rows_to_xlsx(report_name, columns, rows)


def rows_to_xlsx(sheet_name: str, columns: list[Any], rows: list[Any]) -> bytes:
	from frappe.utils.xlsxutils import make_xlsx

	cols = [_column(c) for c in columns]
	data: list[list[Any]] = [[c["label"] for c in cols]]
	for row in rows:
		if isinstance(row, dict):
			data.append([_plain(row.get(c["fieldname"])) for c in cols])
		else:
			data.append([_plain(v) for v in row])
	return make_xlsx(data, sheet_name[:31]).getvalue()


def _plain(value: Any) -> Any:
	if isinstance(value, Decimal):
		return float(value)
	if isinstance(value, dt.date):
		return value.isoformat()
	return value
