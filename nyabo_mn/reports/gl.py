"""GL Entry access shared by the summaries and the script reports.

Amounts come back as ``Decimal`` (money is Decimal everywhere in Nyabo); cancelled rows
are excluded; ranges are inclusive dates. ``primary_document_of`` reads the voucher's
Nyabo fields once per voucher so the journals can show the art. 13.7 reference.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import frappe
from frappe.utils import getdate

from nyabo_mn.core.dates import parse_period, period_bounds, quarter_bounds
from nyabo_mn.core.money import quantize
from nyabo_mn.i18n import mn

GL_FIELDS: tuple[str, ...] = (
	"name",
	"posting_date",
	"account",
	"party_type",
	"party",
	"debit",
	"credit",
	"against",
	"voucher_type",
	"voucher_no",
	"remarks",
	"account_currency",
	"debit_in_account_currency",
	"credit_in_account_currency",
	"is_opening",
)
VOUCHER_REFERENCE_FIELDS: tuple[str, ...] = (
	"source_document",
	"nyabo_primary_document_ref",
	"nyabo_approved_by",
	"owner",
	"nyabo_explanation",
)


def money(value: Any) -> Decimal:
	return quantize(Decimal(str(value or 0)))


def range_of(period: str | tuple[Any, Any]) -> tuple[dt.date, dt.date]:
	"""'YYYY-MM', 'YYYY-Qn' or an explicit (from, to) pair -> inclusive date range."""
	if isinstance(period, tuple):
		return getdate(period[0]), getdate(period[1])
	text = (period or "").strip().upper()
	if "Q" in text:
		year_text, _q, quarter_text = text.partition("-Q")
		if not (year_text.isdigit() and quarter_text.isdigit()):
			frappe.throw(mn.MSG_QUARTER_USAGE)
		try:
			return quarter_bounds(int(year_text), int(quarter_text))
		except ValueError:
			frappe.throw(mn.MSG_QUARTER_USAGE)
			raise  # unreachable
	try:
		year, month = parse_period(text)
	except ValueError:
		frappe.throw(mn.MSG_CLOSE_USAGE)
		raise  # unreachable
	return period_bounds(f"{year:04d}-{month:02d}")


def rows(
	company: str,
	start: dt.date,
	end: dt.date,
	accounts: list[str] | None = None,
	extra_filters: dict[str, Any] | None = None,
) -> list[Any]:
	"""Non-cancelled GL Entry rows of the company in the range, oldest first."""
	filters: dict[str, Any] = {
		"company": company,
		"is_cancelled": 0,
		"posting_date": ["between", [start.isoformat(), end.isoformat()]],
	}
	if accounts is not None:
		if not accounts:
			return []
		filters["account"] = ["in", list(accounts)]
	if extra_filters:
		filters.update(extra_filters)
	return frappe.get_all(
		"GL Entry",
		filters=filters,
		fields=list(GL_FIELDS),
		order_by="posting_date asc, voucher_no asc, name asc",
	)


def net_credit(gl_rows: list[Any]) -> Decimal:
	return quantize(sum((money(r.credit) - money(r.debit) for r in gl_rows), Decimal("0")))


def net_debit(gl_rows: list[Any]) -> Decimal:
	return quantize(sum((money(r.debit) - money(r.credit) for r in gl_rows), Decimal("0")))


def primary_document_of(voucher_type: str, voucher_no: str, cache: dict[tuple[str, str], Any]) -> Any:
	"""Nyabo reference fields of the voucher (source_document / written ref / approver / owner)."""
	key = (voucher_type, voucher_no)
	if key in cache:
		return cache[key]
	meta = None
	try:
		meta = frappe.get_meta(voucher_type)
	except frappe.DoesNotExistError:
		meta = None
	fields = ["owner"] + [
		f for f in VOUCHER_REFERENCE_FIELDS if meta is not None and meta.has_field(f) and f != "owner"
	]
	row = frappe.db.get_value(voucher_type, voucher_no, fields, as_dict=True) if meta is not None else None
	cache[key] = row or frappe._dict()
	return cache[key]


def primary_reference(info: Any) -> str:
	return (info.get("source_document") or info.get("nyabo_primary_document_ref") or "") if info else ""


def totals_row(
	data: list[dict[str, Any]],
	*,
	label_field: str,
	label: str = mn.FORM_LBL_GRAND_TOTAL,
	amount_fields: tuple[str, ...] = ("debit", "credit"),
) -> dict[str, Any]:
	"""The form's Нийт дүн line: the money columns summed, every other column blank.

	WHY the journals build this instead of letting Frappe's ``add_total_row`` do it (F10):
	that helper adds up every numeric column of the result, so the МГ-1 and ЕЖ forms printed
	a "total" of the row numbers and, on a foreign-currency МГ-2, a total of the exchange
	rates - numbers that mean nothing on a Ministry of Finance form and that an inspector
	reads as an arithmetic error. Only the debit and credit columns are totalled.
	"""
	row: dict[str, Any] = {label_field: label}
	for field in amount_fields:
		total = sum((money(entry.get(field)) for entry in data), Decimal("0"))
		row[field] = float(quantize(total))
	return row
