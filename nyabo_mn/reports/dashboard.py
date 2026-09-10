"""The figures behind the chat dashboard and its report cards — read from the ledger, never written.

Every number a card shows comes from here, and everything here is a query over documents the
accountant already approved: GL Entry for the month's revenue and expense, the bank status
module for balances (it owns the statement side), the proposal table for what still waits on a
tap, the stock ledger for what is on the shelf. Nothing is cached — a dashboard that lags the
ledger by a tap is worse than one that takes a second to draw — and nothing here formats: the
cards decide how a Decimal reads, this module only says what it is.

Sections are independent on purpose. The dashboard calls each through ``section``, which turns
a failure into a logged gap rather than a menu that will not open: the accountant's way to
every other card is the dashboard, so a broken bank query must not take the receipts with it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any, TypeVar

import frappe

from nyabo_mn.core import dates
from nyabo_mn.core.money import quantize, to_decimal
from nyabo_mn.log import log_error
from nyabo_mn.reports import accounts as report_accounts
from nyabo_mn.reports import gl

ZERO = Decimal("0")
TREND_MONTHS = 6
TOP_LIMIT = 5
ROWS_LIMIT = 8
PENDING_LIMIT = 5
INVENTORY_LIMIT = 10

T = TypeVar("T")


def section(name: str, read: Callable[[], T], default: T, **context: Any) -> T:
	"""One dashboard section: its value, or ``default`` with the failure in the error log."""
	try:
		return read()
	except Exception as exc:  # noqa: BLE001 - a section must not take the dashboard down
		log_error(f"dashboard.{name}_failed", exc, **context)
		return default


# --- the month ----------------------------------------------------------------------------------------


def month_totals(company: str, period: str) -> dict[str, Decimal]:
	"""Revenue (net credit of Income accounts), expense (net debit of Expense accounts), profit."""
	start, end = dates.period_bounds(period)
	income = report_accounts.accounts_by_root_type(company, ("Income",))
	expense = report_accounts.accounts_by_root_type(company, ("Expense",))
	revenue = gl.net_credit(gl.rows(company, start, end, income)) if income else ZERO
	spent = gl.net_debit(gl.rows(company, start, end, expense)) if expense else ZERO
	return {"revenue": quantize(revenue), "expense": quantize(spent), "profit": quantize(revenue - spent)}


def month_with_delta(company: str, period: str) -> dict[str, Any]:
	"""This month beside the previous one; ``delta_pct`` is None when last month was zero."""
	current = month_totals(company, period)
	previous = month_totals(company, shift_period(period, -1))
	out: dict[str, Any] = {"period": period, "previous_period": shift_period(period, -1)}
	for key in ("revenue", "expense", "profit"):
		out[key] = current[key]
		out[f"{key}_previous"] = previous[key]
		out[f"{key}_delta_pct"] = pct_change(previous[key], current[key])
	return out


def pct_change(before: Decimal, after: Decimal) -> int | None:
	if before == ZERO:
		return None
	return int(round((after - before) / abs(before) * 100))


def shift_period(period: str, months: int) -> str:
	year, month = dates.parse_period(period)
	index = year * 12 + (month - 1) + months
	return f"{index // 12:04d}-{index % 12 + 1:02d}"


def revenue_trend(company: str, until: str, months: int = TREND_MONTHS) -> list[dict[str, Any]]:
	"""Oldest first: ``{period, revenue, expense, delta_pct}`` for the last ``months`` months."""
	periods = [shift_period(until, offset) for offset in range(-(months - 1), 1)]
	out: list[dict[str, Any]] = []
	previous: Decimal | None = None
	for period in periods:
		totals = month_totals(company, period)
		out.append(
			{
				"period": period,
				"revenue": totals["revenue"],
				"expense": totals["expense"],
				"delta_pct": pct_change(previous, totals["revenue"]) if previous is not None else None,
			}
		)
		previous = totals["revenue"]
	return out


def top_expenses(company: str, period: str, limit: int = TOP_LIMIT) -> dict[str, Any]:
	"""Expense accounts of the month by net debit, largest first, with each one's share."""
	start, end = dates.period_bounds(period)
	expense = report_accounts.accounts_by_root_type(company, ("Expense",))
	totals: dict[str, Decimal] = {}
	for row in gl.rows(company, start, end, expense) if expense else []:
		totals[row.account] = totals.get(row.account, ZERO) + gl.net_debit([row])
	ranked = sorted(((a, v) for a, v in totals.items() if v > ZERO), key=lambda p: p[1], reverse=True)
	total = quantize(sum((v for _a, v in ranked), ZERO))
	names = _account_names(company)
	rows = [
		{
			"account": account,
			"label": names.get(account, account),
			"amount": quantize(amount),
			"share_pct": int(round(amount / total * 100)) if total else 0,
		}
		for account, amount in ranked[:limit]
	]
	return {"period": period, "rows": rows, "total": total, "count": len(ranked)}


def _account_names(company: str) -> dict[str, str]:
	rows = frappe.get_all("Account", filters={"company": company}, fields=["name", "account_name"])
	return {r.name: (r.account_name or r.name) for r in rows}


# --- what waits on a tap ------------------------------------------------------------------------------


def _count(doctype: str, filters: dict[str, Any]) -> int:
	if not frappe.db.exists("DocType", doctype):
		return 0
	return int(frappe.db.count(doctype, filters) or 0)


def pending_counts(company: str) -> dict[str, int]:
	"""Proposals waiting for a tap, statement lines nobody matched, rules that would refuse a post."""
	from nyabo_mn.rules import verify

	return {
		"proposals": _count("Nyabo Proposal", {"company": company, "status": "proposed"}),
		"unmatched": _count(
			"Bank Transaction",
			{"company": company, "docstatus": 1, "status": ["in", ["Pending", "Unreconciled"]]},
		),
		"rules": len(verify.pending(company=company)),
	}


def pending_proposals(company: str, limit: int = PENDING_LIMIT) -> list[dict[str, Any]]:
	if not frappe.db.exists("DocType", "Nyabo Proposal"):
		return []
	rows = frappe.get_all(
		"Nyabo Proposal",
		filters={"company": company, "status": "proposed"},
		fields=["name", "kind", "supplier", "posting_date", "total", "account", "needs_accountant"],
		order_by="creation desc",
		limit=limit,
	)
	out = []
	for row in rows:
		supplier = row.get("supplier")
		label = supplier and frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier or ""
		out.append(
			{
				"name": row["name"],
				"kind": row.get("kind") or "receipt",
				"label": label,
				"date": row.get("posting_date"),
				"total": quantize(to_decimal(row.get("total") or 0)),
				"account": row.get("account"),
				"needs_accountant": bool(row.get("needs_accountant")),
			}
		)
	return out


# --- the month's vouchers ---------------------------------------------------------------------------


def recent_vouchers(company: str, period: str, limit: int = ROWS_LIMIT) -> dict[str, Any]:
	"""Posted vouchers of the month, newest first: date, what it was, amount and direction.

	One row per voucher, not per GL line: the accountant thinks in documents. ``direction``
	is ``out`` when a cash/bank account was credited, ``in`` when one was debited, else ``""``
	(a pure accrual). ``label`` is the party when there is one, else the voucher's remark,
	else the first account that is not cash or bank — the thing the money went to.
	"""
	start, end = dates.period_bounds(period)
	cash = set(report_accounts.cash_bank_accounts(company))
	names = _account_names(company)
	vouchers: dict[tuple[str, str], dict[str, Any]] = {}
	for row in gl.rows(company, start, end):
		key = (row.voucher_type, row.voucher_no)
		voucher = vouchers.setdefault(
			key,
			{
				"date": row.posting_date,
				"voucher_type": row.voucher_type,
				"voucher_no": row.voucher_no,
				"party": None,
				"remark": None,
				"account": None,
				"debit": ZERO,
				"direction": "",
			},
		)
		voucher["debit"] += to_decimal(row.debit or 0)
		if row.party and not voucher["party"]:
			voucher["party"] = row.party
		if row.remarks and not voucher["remark"]:
			voucher["remark"] = row.remarks
		if row.account in cash:
			if to_decimal(row.credit or 0) > ZERO:
				voucher["direction"] = "out"
			elif to_decimal(row.debit or 0) > ZERO and not voucher["direction"]:
				voucher["direction"] = "in"
		elif not voucher["account"]:
			voucher["account"] = row.account
	ordered = sorted(vouchers.values(), key=lambda v: (str(v["date"]), v["voucher_no"]), reverse=True)
	rows = []
	for v in ordered[:limit]:
		label = v["party"] or v["remark"] or names.get(v["account"] or "", v["account"] or "")
		rows.append(
			{
				"date": v["date"],
				"label": str(label or "")[:60],
				"amount": quantize(v["debit"]),
				"direction": v["direction"],
				"voucher_type": v["voucher_type"],
				"voucher_no": v["voucher_no"],
			}
		)
	return {"period": period, "rows": rows, "count": len(ordered)}


# --- stock --------------------------------------------------------------------------------------------


def inventory(company: str, limit: int = INVENTORY_LIMIT) -> dict[str, Any]:
	"""Quantity and value on hand per item, largest value first, and the total.

	From Stock Ledger Entry when the site has one (every ERPNext site does); the opening
	Stock Reconciliation lines are the fallback for a checkout without the stock module, which
	is what the test bench is.
	"""
	balances: dict[str, dict[str, Decimal]] = {}
	if frappe.db.exists("DocType", "Stock Ledger Entry"):
		rows = frappe.get_all(
			"Stock Ledger Entry",
			filters={"company": company, "is_cancelled": 0},
			fields=["item_code", "actual_qty", "stock_value_difference"],
		)
		for row in rows:
			item = balances.setdefault(row.item_code, {"qty": ZERO, "value": ZERO})
			item["qty"] += to_decimal(row.actual_qty or 0)
			item["value"] += to_decimal(row.stock_value_difference or 0)
	elif frappe.db.exists("DocType", "Stock Reconciliation Item"):
		for row in frappe.get_all(
			"Stock Reconciliation Item",
			filters={"docstatus": 1},
			fields=["item_code", "qty", "valuation_rate", "parent"],
		):
			if frappe.db.get_value("Stock Reconciliation", row.parent, "company") != company:
				continue
			item = balances.setdefault(row.item_code, {"qty": ZERO, "value": ZERO})
			item["qty"] += to_decimal(row.qty or 0)
			item["value"] += to_decimal(row.qty or 0) * to_decimal(row.valuation_rate or 0)
	item_names = (
		{
			r.name: r.item_name
			for r in frappe.get_all(
				"Item", filters={"name": ["in", list(balances)]}, fields=["name", "item_name"]
			)
		}
		if balances
		else {}
	)
	ranked = sorted(
		((code, b) for code, b in balances.items() if b["qty"] != ZERO),
		key=lambda p: p[1]["value"],
		reverse=True,
	)
	rows = [
		{
			"item_code": code,
			"label": item_names.get(code) or code,
			"qty": b["qty"],
			"rate": quantize(b["value"] / b["qty"]) if b["qty"] else ZERO,
			"value": quantize(b["value"]),
		}
		for code, b in ranked[:limit]
	]
	total = quantize(sum((b["value"] for _c, b in ranked), ZERO))
	return {"rows": rows, "total": total, "count": len(ranked)}


# --- the whole dashboard ------------------------------------------------------------------------------


def bank_summary(company: str, today: dt.date | None = None) -> list[dict[str, Any]]:
	from nyabo_mn.matching import status

	return status.summary(company, today)


def overview(company: str, today: dt.date | None = None) -> dict[str, Any]:
	"""Every section of the dashboard, each one failing on its own (see ``section``)."""
	today = today or dt.date.today()
	period = dates.period_of(today)
	return {
		"company": company,
		"today": today,
		"period": period,
		"month": section("month", lambda: month_with_delta(company, period), None, company=company),
		"banks": section("banks", lambda: bank_summary(company, today), [], company=company),
		"pending": section(
			"pending",
			lambda: pending_counts(company),
			{"proposals": 0, "unmatched": 0, "rules": 0},
			company=company,
		),
	}


def trend_rows(company: str, today: dt.date) -> list[dict[str, Any]]:
	return revenue_trend(company, dates.period_of(today))


__all__: Sequence[str] = [
	"inventory",
	"month_totals",
	"month_with_delta",
	"overview",
	"pending_counts",
	"pending_proposals",
	"pct_change",
	"recent_vouchers",
	"revenue_trend",
	"section",
	"shift_period",
	"top_expenses",
]
