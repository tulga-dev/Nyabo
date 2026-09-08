"""``/данс``: per bank account, statement movement vs ledger balance and the unmatched count.

The ledger side is ERPNext's ``get_balance_on`` for the GL sub-account of each bank row
in Nyabo Company Settings; the statement side is the net of imported Bank Transactions.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import frappe

from nyabo_mn.core.money import quantize, to_decimal
from nyabo_mn.i18n import mn
from nyabo_mn.telegram import cards
from nyabo_mn.telegram.context import Ctx


def handle_command(ctx: Ctx) -> Any:
	if not ctx.company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	rows = recon_rows(ctx.company)
	ctx.reply(cards.recon_status(ctx.company, rows))
	return rows


def recon_rows(company: str) -> list[dict[str, Any]]:
	name = frappe.db.exists("Nyabo Company Settings", {"company": company})
	if not name:
		return []
	settings = frappe.get_doc("Nyabo Company Settings", name)
	rows: list[dict[str, Any]] = []
	for row in settings.get("bank_accounts") or []:
		statement = Decimal("0.00")
		unmatched = 0
		if row.erpnext_bank_account:
			txns = frappe.get_all(
				"Bank Transaction",
				filters={"bank_account": row.erpnext_bank_account, "docstatus": 1},
				fields=["deposit", "withdrawal", "status"],
			)
			for txn in txns:
				statement += quantize(to_decimal(txn.deposit or 0)) - quantize(
					to_decimal(txn.withdrawal or 0)
				)
				if txn.status in ("Pending", "Unreconciled"):
					unmatched += 1
		ledger = Decimal("0.00")
		if row.gl_account:
			from erpnext.accounts.utils import get_balance_on

			ledger = quantize(to_decimal(get_balance_on(account=row.gl_account, company=company) or 0))
		rows.append(
			{
				"bank": row.bank,
				"currency": row.currency,
				"statement": statement,
				"ledger": ledger,
				"unmatched": unmatched,
			}
		)
	return rows
