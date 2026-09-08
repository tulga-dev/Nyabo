"""``/данс``: per bank account, statement balance vs ledger balance and the unmatched count.

Statement balance is the closing balance column of the latest import when the bank
prints one (kept in the ``statement_imported`` event payload), else the running sum of
imported transactions. Ledger balance is ERPNext's ``get_balance_on`` on the GL account
at the same date, so the two numbers are comparable.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from nyabo_mn.core.money import fmt_mnt, quantize, to_decimal
from nyabo_mn.i18n import mn
from nyabo_mn.matching import common


def _transactions_sum(bank_account: str, as_of: dt.date) -> Decimal:
	import frappe

	rows = frappe.get_all(
		"Bank Transaction",
		filters={"bank_account": bank_account, "docstatus": 1, "date": ["<=", as_of.isoformat()]},
		fields=["deposit", "withdrawal"],
	)
	total = Decimal("0")
	for row in rows:
		total += to_decimal(row.deposit or 0) - to_decimal(row.withdrawal or 0)
	return quantize(total)


def _unmatched_count(bank_account: str) -> int:
	import frappe

	return frappe.db.count(
		"Bank Transaction", {"bank_account": bank_account, "docstatus": 1, "unallocated_amount": [">", 0]}
	)


def _latest_import(company: str, bank_account: str) -> dict[str, Any] | None:
	from nyabo_mn.matching.bank_import import import_event_payloads

	payloads = import_event_payloads(company, bank_account)
	return payloads[0] if payloads else None


def account_summary(company: str, row: dict[str, Any], today: dt.date | None = None) -> dict[str, Any]:
	from erpnext.accounts.utils import get_balance_on

	bank_account = str(row.get("erpnext_bank_account") or "")
	gl_account = row.get("gl_account") or (common.gl_account_of(bank_account) if bank_account else None)
	latest = _latest_import(company, bank_account) if bank_account else None
	as_of = today or dt.date.today()
	source = "transactions"
	if latest and latest.get("closing_date"):
		as_of = common.to_date(latest["closing_date"])
	if latest and latest.get("closing_balance") not in (None, ""):
		statement = quantize(to_decimal(latest["closing_balance"]))
		source = "statement"
	else:
		statement = _transactions_sum(bank_account, as_of) if bank_account else Decimal("0.00")
	ledger = (
		quantize(to_decimal(get_balance_on(gl_account, as_of.isoformat()) or 0))
		if gl_account
		else Decimal("0.00")
	)
	return {
		"bank": row.get("bank"),
		"currency": row.get("currency") or "MNT",
		"account_number": row.get("account_number"),
		"bank_account": bank_account or None,
		"gl_account": gl_account,
		"as_of": as_of,
		"statement_balance": statement,
		"statement_source": source,
		"ledger_balance": ledger,
		"diff": quantize(statement - ledger),
		"unmatched": _unmatched_count(bank_account) if bank_account else 0,
	}


def summary(company: str, today: dt.date | None = None) -> list[dict[str, Any]]:
	"""One dict per configured bank account (Nyabo Company Settings.bank_accounts)."""
	return [account_summary(company, row, today) for row in common.bank_rows(company)]


def render(company: str, today: dt.date | None = None) -> str:
	rows = summary(company, today)
	if not rows:
		return mn.MSG_RECON_NONE
	lines = [mn.MSG_RECON_STATUS_HEADER.format(company=company)]
	for row in rows:
		lines.append(
			mn.MSG_RECON_STATUS_LINE.format(
				bank=mn.BANK_NAMES_MN.get(str(row["bank"]), str(row["bank"])),
				currency=row["currency"],
				statement=fmt_mnt(row["statement_balance"]),
				ledger=fmt_mnt(row["ledger_balance"]),
				diff=fmt_mnt(row["diff"]),
				unmatched=row["unmatched"],
			)
		)
	as_of = max(row["as_of"] for row in rows)
	lines.append(mn.MSG_RECON_AS_OF.format(date=as_of.isoformat()))
	return "\n".join(lines)


__all__ = ["account_summary", "render", "summary"]
