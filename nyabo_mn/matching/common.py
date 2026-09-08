"""Helpers shared by the matching modules: settings rows, bank lines, events.

Kept apart from ``bank_import`` and ``match`` so neither imports the other for a
utility, and so the Telegram handlers can reuse them without pulling the matcher in.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from nyabo_mn.core.models import BankLine
from nyabo_mn.core.money import quantize, to_decimal

SETTINGS_DOCTYPE = "Nyabo Company Settings"
BANK_ROW_DOCTYPE = "Nyabo Bank Account Row"
BANK_ROW_FIELDS = ("name", "bank", "currency", "account_number", "gl_account", "erpnext_bank_account", "idx")


def settings_name(company: str) -> str | None:
	import frappe

	return frappe.db.get_value(SETTINGS_DOCTYPE, {"company": company}, "name")


def bank_rows(company: str) -> list[dict[str, Any]]:
	"""The company's configured bank accounts (Nyabo Company Settings.bank_accounts)."""
	import frappe

	parent = settings_name(company)
	if not parent:
		return []
	rows = frappe.get_all(
		BANK_ROW_DOCTYPE,
		filters={"parent": parent, "parenttype": SETTINGS_DOCTYPE},
		fields=list(BANK_ROW_FIELDS),
		order_by="idx asc",
	)
	return [dict(r) for r in rows]


def own_account_numbers(company: str) -> list[str]:
	return [str(r["account_number"]) for r in bank_rows(company) if r.get("account_number")]


def settings_value(company: str, fieldname: str, default: Any = None) -> Any:
	import frappe

	name = settings_name(company)
	if not name:
		return default
	value = frappe.db.get_value(SETTINGS_DOCTYPE, name, fieldname)
	return default if value in (None, "") else value


def gl_account_of(bank_account: str) -> str | None:
	import frappe

	return frappe.db.get_value("Bank Account", bank_account, "account")


def account_code_of(account: str | None) -> str:
	import frappe

	if not account:
		return ""
	return str(frappe.db.get_value("Account", account, "account_number") or "")


def to_date(value: Any) -> dt.date:
	if isinstance(value, dt.datetime):
		return value.date()
	if isinstance(value, dt.date):
		return value
	return dt.date.fromisoformat(str(value)[:10])


def line_from_transaction(row: Mapping[str, Any]) -> BankLine:
	"""A Bank Transaction row (get_all dict or Document) as the core BankLine.

	``row_hash`` carries the Bank Transaction name so match results can be mapped back;
	``row_index`` is the idx-less 0 because ordering inside a run is by date.
	"""
	get = row.get if hasattr(row, "get") else lambda k, d=None: getattr(row, k, d)
	deposit = quantize(to_decimal(get("deposit") or 0))
	withdrawal = quantize(to_decimal(get("withdrawal") or 0))
	balance = None
	return BankLine(
		date=to_date(get("date")),
		description=str(get("description") or ""),
		debit=withdrawal,
		credit=deposit,
		amount=quantize(deposit - withdrawal),
		balance=balance,
		reference=str(get("reference_number") or ""),
		currency=str(get("currency") or "MNT"),
		row_index=0,
		row_hash=str(get("name") or ""),
	)


def write_event(
	event_type: str,
	*,
	company: str | None,
	ref_doctype: str | None = None,
	ref_name: str | None = None,
	reason: str | None = None,
	payload: Mapping[str, Any] | None = None,
	actor_user: str | None = None,
	actor_telegram_id: str | None = None,
) -> str:
	"""Append-only audit row (Nyabo Event). Returns its name."""
	import frappe

	doc = frappe.get_doc(
		{
			"doctype": "Nyabo Event",
			"event_type": event_type,
			"company": company,
			"actor_user": actor_user or frappe.session.user,
			"actor_telegram_id": actor_telegram_id,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"reason": reason,
			"payload_json": json.dumps(dict(payload or {}), ensure_ascii=False, default=str),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def event_payload(row: Mapping[str, Any]) -> dict[str, Any]:
	raw = row.get("payload_json")
	if not raw:
		return {}
	if isinstance(raw, dict):
		return raw
	try:
		return json.loads(raw)
	except (TypeError, ValueError):
		return {}


def decimal_str(value: Decimal | int | float | str | None) -> str:
	return str(quantize(to_decimal(value or 0)))


def unique(items: Iterable[str]) -> list[str]:
	seen: set[str] = set()
	out: list[str] = []
	for item in items:
		if item and item not in seen:
			seen.add(item)
			out.append(item)
	return out


__all__ = [
	"BANK_ROW_DOCTYPE",
	"SETTINGS_DOCTYPE",
	"account_code_of",
	"bank_rows",
	"decimal_str",
	"event_payload",
	"gl_account_of",
	"line_from_transaction",
	"own_account_numbers",
	"settings_name",
	"settings_value",
	"to_date",
	"unique",
	"write_event",
]
