"""Мөнгөн гүйлгээний журнал (МГ-1 төгрөг / МГ-2 валют) — MoF Order 100/2018.

GL rows on the cash and bank ledger accounts, with the counter-account, the reference
and the primary document. An MNT account renders the МГ-1 columns; a foreign-currency
account adds Ханш / Гүйлгээний дүн гадаад валютаар / төгрөгөөр (МГ-2). Opening and
closing balances come from ``get_balance_on`` so the form's Эхний / Эцсийн үлдэгдэл rows
can be printed by the PDF template.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import frappe
from frappe.utils import add_days, getdate

from nyabo_mn.core.money import quantize
from nyabo_mn.i18n import mn
from nyabo_mn.reports import accounts, gl


def columns(foreign: bool) -> list[dict[str, Any]]:
	cols: list[dict[str, Any]] = [
		{"label": mn.LBL_ROW_NO, "fieldname": "row_no", "fieldtype": "Int", "width": 50},
		{"label": mn.COL_DOC_DATE, "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{
			"label": mn.COL_DOC_NO,
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 160,
		},
		{"label": mn.COL_VOUCHER_TYPE, "fieldname": "voucher_type", "fieldtype": "Data", "width": 110},
		{"label": mn.COL_DESCRIPTION, "fieldname": "remarks", "fieldtype": "Data", "width": 220},
		{"label": mn.COL_ACCOUNT, "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 200},
	]
	if foreign:
		cols += [
			{"label": mn.COL_CURRENCY, "fieldname": "currency", "fieldtype": "Data", "width": 60},
			{"label": mn.COL_RATE, "fieldname": "rate", "fieldtype": "Float", "width": 90},
			{"label": mn.COL_AMOUNT_FX, "fieldname": "amount_fx", "fieldtype": "Float", "width": 120},
		]
	cols += [
		{"label": mn.LBL_CASH_RECEIPT, "fieldname": "debit", "fieldtype": "Currency", "width": 120},
		{"label": mn.LBL_CASH_PAYMENT, "fieldname": "credit", "fieldtype": "Currency", "width": 120},
		{"label": mn.LBL_COUNTER_ACCOUNT, "fieldname": "against", "fieldtype": "Data", "width": 220},
		{"label": mn.COL_PARTY, "fieldname": "party", "fieldtype": "Data", "width": 140},
		{"label": mn.LBL_REFERENCE, "fieldname": "reference", "fieldtype": "Data", "width": 120},
		{"label": mn.COL_PRIMARY_DOCUMENT, "fieldname": "primary_document", "fieldtype": "Data", "width": 160},
	]
	return cols


def _balance(account: str, on_date: Any, company: str) -> Decimal:
	from erpnext.accounts.utils import get_balance_on

	return quantize(Decimal(str(get_balance_on(account, on_date, company=company) or 0)))


def execute(filters: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], None, None, list[dict[str, Any]]]:
	filters = frappe._dict(filters or {})
	if not (filters.company and filters.from_date and filters.to_date):
		return columns(False), [], None, None, []
	company_currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	selected = [filters.account] if filters.get("account") else accounts.cash_bank_accounts(filters.company)
	foreign = any((accounts.account_currency(a) or company_currency) != company_currency for a in selected)
	start, end = getdate(filters.from_date), getdate(filters.to_date)
	cache: dict[tuple[str, str], Any] = {}
	data: list[dict[str, Any]] = []
	for index, row in enumerate(gl.rows(filters.company, start, end, accounts=selected), 1):
		info = gl.primary_document_of(row.voucher_type, row.voucher_no, cache)
		debit, credit = gl.money(row.debit), gl.money(row.credit)
		entry: dict[str, Any] = {
			"row_no": index,
			"posting_date": row.posting_date,
			"voucher_no": row.voucher_no,
			"voucher_type": row.voucher_type,
			"remarks": row.remarks,
			"account": row.account,
			"debit": float(debit),
			"credit": float(credit),
			"against": row.against,
			"party": row.party,
			"reference": info.get("nyabo_primary_document_ref") if info else None,
			"primary_document": gl.primary_reference(info),
		}
		if foreign:
			fx_amount = gl.money(row.debit_in_account_currency) - gl.money(row.credit_in_account_currency)
			mnt_amount = debit - credit
			entry["currency"] = row.account_currency
			entry["amount_fx"] = float(fx_amount)
			entry["rate"] = float(quantize(mnt_amount / fx_amount)) if fx_amount else None
		data.append(entry)
	summary = [
		{
			"label": f"{mn.COL_OPENING} ({a})",
			"value": float(_balance(a, add_days(start, -1), filters.company)),
			"datatype": "Currency",
		}
		for a in selected
	] + [
		{"label": f"{mn.COL_CLOSING} ({a})", "value": float(_balance(a, end, filters.company)), "datatype": "Currency"}
		for a in selected
	]
	return columns(foreign), data, None, None, summary
