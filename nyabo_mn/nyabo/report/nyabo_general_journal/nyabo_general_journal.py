"""Ерөнхий журнал (ЕЖ) — MoF Order 100/2018 general journal from GL Entry rows.

One row per ledger line (the ЕЖ form's Дүн / Дебет / Кредит columns are split into
debit and credit amounts so the report totals reconcile with the trial balance). Each
row carries the art. 13.7 primary-document reference, who prepared the voucher (owner)
and who approved it (``nyabo_approved_by``) — the audit-friendly data source Order
47/2018 annex 1 item 1.10 asks for.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import getdate

from nyabo_mn.i18n import mn
from nyabo_mn.reports import accounts, gl


def columns() -> list[dict[str, Any]]:
	return [
		{"label": mn.LBL_ROW_NO, "fieldname": "row_no", "fieldtype": "Int", "width": 50},
		{"label": mn.COL_DOC_DATE, "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": mn.COL_VOUCHER_TYPE, "fieldname": "voucher_type", "fieldtype": "Data", "width": 120},
		{
			"label": mn.COL_DOC_NO,
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 160,
		},
		{"label": mn.COL_DESCRIPTION, "fieldname": "remarks", "fieldtype": "Data", "width": 240},
		{"label": mn.COL_ACCOUNT_CODE, "fieldname": "account_code", "fieldtype": "Data", "width": 80},
		{"label": mn.COL_ACCOUNT, "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 220},
		{"label": mn.COL_PARTY, "fieldname": "party", "fieldtype": "Data", "width": 160},
		{"label": mn.COL_DEBIT, "fieldname": "debit", "fieldtype": "Currency", "width": 120},
		{"label": mn.COL_CREDIT, "fieldname": "credit", "fieldtype": "Currency", "width": 120},
		{"label": mn.COL_PRIMARY_DOCUMENT, "fieldname": "primary_document", "fieldtype": "Data", "width": 160},
		{"label": mn.COL_PREPARED_BY, "fieldname": "prepared_by", "fieldtype": "Data", "width": 140},
		{"label": mn.COL_APPROVED_BY, "fieldname": "approved_by", "fieldtype": "Data", "width": 140},
	]


def execute(filters: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
	filters = frappe._dict(filters or {})
	if not (filters.company and filters.from_date and filters.to_date):
		return columns(), []
	numbers = accounts.account_numbers(filters.company)
	cache: dict[tuple[str, str], Any] = {}
	data: list[dict[str, Any]] = []
	for index, row in enumerate(
		gl.rows(filters.company, getdate(filters.from_date), getdate(filters.to_date)), 1
	):
		info = gl.primary_document_of(row.voucher_type, row.voucher_no, cache)
		data.append(
			{
				"row_no": index,
				"posting_date": row.posting_date,
				"voucher_type": row.voucher_type,
				"voucher_no": row.voucher_no,
				"remarks": row.remarks,
				"account_code": numbers.get(row.account, ""),
				"account": row.account,
				"party": row.party,
				"debit": float(gl.money(row.debit)),
				"credit": float(gl.money(row.credit)),
				"primary_document": gl.primary_reference(info),
				"prepared_by": info.get("owner") if info else None,
				"approved_by": info.get("nyabo_approved_by") if info else None,
			}
		)
	return columns(), data
