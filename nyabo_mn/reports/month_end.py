"""Month-end checklist, trial balance and summaries for ``/хаалт YYYY-MM`` (ARCHITECTURE §5.5).

The checklist counts what still blocks a clean close; the trial balance prefers ERPNext's
own report and falls back to a GL aggregation where the report is unavailable (the test
stub, or a site where the report is disabled); the summaries pick VAT or the 1% quarter
by the company's regime history — the only regime lookup outside the rules package, done
through ``core.rules_engine.regime_on`` so the regime names stay in one place.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import frappe

from nyabo_mn.core.dates import period_label, quarter_label, quarter_of
from nyabo_mn.core.money import fmt_mnt, quantize
from nyabo_mn.core.rules_engine import MissingRuleError, regime_on
from nyabo_mn.i18n import mn
from nyabo_mn.reports import accounts, export, gl, simplified_summary, vat_summary

TRIAL_BALANCE_REPORT = "Trial Balance"


def _count(doctype: str, filters: dict[str, Any]) -> int:
	if not frappe.db.exists("DocType", doctype):
		return 0
	return frappe.db.count(doctype, filters)


def checklist(company: str, period: str) -> dict[str, Any]:
	"""Open items per MSG_CLOSE_OPEN_ITEMS plus the December inventory-count line (art. 12.2.1)."""
	start, end = gl.range_of(period)
	between = ["between", [start.isoformat(), end.isoformat()]]
	proposals = _count("Nyabo Proposal", {"company": company, "status": "proposed"})
	unmatched = _count(
		"Bank Transaction",
		{"company": company, "docstatus": 1, "status": ["in", ["Pending", "Unreconciled"]], "date": between},
	)
	unverified_docs = 0
	for doctype in ("Purchase Invoice", "Journal Entry"):
		unverified_docs += _count(
			doctype,
			{
				"company": company,
				"docstatus": 1,
				"posting_date": between,
				"source_document": ["!=", ""],
				"ebarimt_verified": 0,
			},
		)
	pending_suppliers = _count("Supplier", {"nyabo_pending_confirmation": 1})
	from nyabo_mn.compliance.period import unverified_proposals

	unverified_rules = len(unverified_proposals(company, start, end))
	items = {
		"proposals": proposals,
		"unmatched": unmatched,
		"unverified_docs": unverified_docs,
		"pending_suppliers": pending_suppliers,
		"unverified_rules": unverified_rules,
	}
	lines = [mn.MSG_CLOSE_OPEN_ITEMS.format(**items)]
	if end.month == 12:
		lines.append(mn.MSG_CLOSE_INVENTORY_COUNT)
	return {
		**items,
		"inventory_count_required": end.month == 12,
		"blocking": unverified_rules > 0,
		"text": "\n".join(lines),
		"from_date": start,
		"to_date": end,
	}


def _trial_balance_from_gl(company: str, start: dt.date, end: dt.date) -> dict[str, Any]:
	numbers = accounts.account_numbers(company)
	totals: dict[str, dict[str, Decimal]] = {}
	for row in gl.rows(company, start, end):
		bucket = totals.setdefault(row.account, {"debit": Decimal("0"), "credit": Decimal("0")})
		bucket["debit"] += gl.money(row.debit)
		bucket["credit"] += gl.money(row.credit)
	rows = [
		{
			"account": account,
			"account_code": numbers.get(account, ""),
			"debit": quantize(v["debit"]),
			"credit": quantize(v["credit"]),
		}
		for account, v in sorted(totals.items(), key=lambda kv: (numbers.get(kv[0], ""), kv[0]))
	]
	return {
		"debit": quantize(sum((r["debit"] for r in rows), Decimal("0"))),
		"credit": quantize(sum((r["credit"] for r in rows), Decimal("0"))),
		"rows": rows,
		"source": "gl_entry",
		"note": mn.MSG_CLOSE_TRIAL_BALANCE_SOURCE_FALLBACK,
	}


def trial_balance(company: str, period: str) -> dict[str, Any]:
	"""{debit, credit, rows, source}: ERPNext's Trial Balance when available, else GL aggregation."""
	start, end = gl.range_of(period)
	try:
		from erpnext.accounts.utils import get_fiscal_year
		from frappe.desk import query_report

		fiscal_year = get_fiscal_year(end, company=company)[0]
		result = query_report.run(
			TRIAL_BALANCE_REPORT,
			filters={
				"company": company,
				"fiscal_year": fiscal_year,
				"from_date": start.isoformat(),
				"to_date": end.isoformat(),
			},
			ignore_prepared_report=True,
		)
	except (frappe.DoesNotExistError, NotImplementedError, ImportError):
		return _trial_balance_from_gl(company, start, end)
	rows: list[dict[str, Any]] = []
	for row in result.get("result") or []:
		if not isinstance(row, dict) or not row.get("account"):
			continue
		rows.append(
			{
				"account": row.get("account"),
				"account_code": row.get("account_number") or "",
				"debit": gl.money(row.get("debit")),
				"credit": gl.money(row.get("credit")),
			}
		)
	return {
		"debit": quantize(sum((r["debit"] for r in rows), Decimal("0"))),
		"credit": quantize(sum((r["credit"] for r in rows), Decimal("0"))),
		"rows": rows,
		"source": TRIAL_BALANCE_REPORT,
	}


def regime_history(company: str) -> list[tuple[str, Any, Any]]:
	rows = frappe.get_all(
		"Nyabo Tax Regime Period",
		filters={"parenttype": "Nyabo Company Settings", "parent": company},
		fields=["regime", "effective_from", "effective_to"],
	)
	return [(r.regime, r.effective_from, r.effective_to) for r in rows]


def is_vat_payer(company: str, on_date: dt.date) -> bool | None:
	"""True/False from the regime history; None when onboarding has not recorded a regime."""
	try:
		return regime_on(regime_history(company), on_date).is_vat_payer
	except MissingRuleError:
		return None


def summaries(company: str, period: str, *, simulation: bool = False) -> dict[str, Any]:
	"""Chat lines and PDFs for the close card: trial balance + VAT (monthly) or 1% (quarterly)."""
	start, end = gl.range_of(period)
	tb = trial_balance(company, period)
	text_lines = [mn.MSG_CLOSE_TRIAL_BALANCE.format(debit=fmt_mnt(tb["debit"]), credit=fmt_mnt(tb["credit"]))]
	pdfs: dict[str, bytes] = {}
	filters = {"company": company, "from_date": start.isoformat(), "to_date": end.isoformat()}
	vat_payer = is_vat_payer(company, end)
	if vat_payer is None:
		text_lines.append(mn.MSG_REGIME_MISSING.format(date=end.isoformat()))
	elif vat_payer:
		vat = vat_summary.compute(company, (start, end))
		text_lines.append(
			mn.MSG_CLOSE_VAT_SUMMARY.format(
				output=fmt_mnt(vat["output_vat"]), input=fmt_mnt(vat["input_vat"]), net=fmt_mnt(vat["net"])
			)
		)
		pdfs["vat_summary"] = export.report_to_pdf(
			"Nyabo VAT Summary", filters, mn.REPORT_VAT_SUMMARY, company, period_label(period)
		)
	else:
		quarter = f"{end.year}-Q{quarter_of(end)}"
		summary = simplified_summary.compute(company, quarter, simulation=simulation)
		text_lines.append(
			mn.MSG_CLOSE_SIMPLIFIED_SUMMARY.format(
				revenue=fmt_mnt(summary["revenue"]),
				tax=fmt_mnt(summary["tax_1pct"]),
				quarter=quarter_label(end.year, quarter_of(end)),
			)
		)
		text_lines.extend(
			mn.MSG_CLOSE_SIMPLIFIED_MONTH_LINE.format(month=period_label(m["period"]), revenue=fmt_mnt(m["revenue"]))
			for m in summary["months"]
		)
		pdfs["simplified_summary"] = export.report_to_pdf(
			"Nyabo Simplified Tax Summary",
			{**filters, "simulation": 1 if simulation else 0},
			mn.REPORT_SIMPLIFIED_SUMMARY,
			company,
			quarter_label(end.year, quarter_of(end)),
		)
	return {"text_lines": text_lines, "pdfs": pdfs, "trial_balance": tb, "is_vat_payer": vat_payer}
