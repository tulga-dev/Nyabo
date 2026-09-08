"""Text of the bank-line Telegram card. Buttons are built by the Telegram layer.

The card is the accountant's only view of a statement line, so it always shows the
bank, the date, the signed amount, the narrative, and then exactly one of: what it was
matched to, what Nyabo proposes, or "unmatched".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.matching import common
from nyabo_mn.matching import rules as rules_mod


def _bank_label(bank_account: str) -> str:
	import frappe

	bank = frappe.db.get_value("Bank Account", bank_account, "bank") or bank_account
	return mn.BANK_NAMES_MN.get(str(bank), str(bank))


def render_bank_line(bank_transaction_name: str) -> tuple[str, str | None]:
	"""(card text, proposal name or None)."""
	import frappe

	if not frappe.db.exists("Bank Transaction", bank_transaction_name):
		raise rules_mod.ProposalError(mn.MSG_BANK_TRANSACTION_NOT_FOUND.format(name=bank_transaction_name))
	bt = frappe.get_doc("Bank Transaction", bank_transaction_name)
	line = common.line_from_transaction(bt.as_dict())
	parts = [
		mn.CARD_BANK_LINE.format(
			bank=_bank_label(str(bt.bank_account)),
			date=line.date.isoformat(),
			amount=fmt_mnt(line.amount),
			description=line.description[:80],
		)
	]
	proposal_name: str | None = None
	allocated = [p for p in bt.payment_entries if float(p.allocated_amount or 0) > 0]
	if allocated:
		for row in allocated:
			parts.append(mn.CARD_BANK_MATCHED.format(voucher=f"{row.payment_document} {row.payment_entry}"))
	else:
		proposal_name = rules_mod.existing_proposal(bank_transaction_name)
		if proposal_name:
			proposal = frappe.db.get_value(
				"Nyabo Proposal",
				proposal_name,
				["account_code", "account", "explanation", "entry_json"],
				as_dict=True,
			)
			transfer = _transfer_of(proposal.entry_json)
			if transfer:
				parts.append(
					mn.CARD_BANK_TRANSFER.format(
						from_account=_bank_label(_bank_account_of(transfer.get("withdrawal"))),
						to_account=_bank_label(_bank_account_of(transfer.get("deposit"))),
					)
				)
			parts.append(
				mn.CARD_BANK_PROPOSAL.format(
					code=proposal.account_code or "",
					account=_account_label(proposal.account),
					reason=proposal.explanation or "",
				)
			)
		else:
			parts.append(mn.CARD_BANK_UNMATCHED)
	return "\n".join(parts), proposal_name


def _transfer_of(entry_json: Any) -> Mapping[str, Any] | None:
	import json

	if not entry_json:
		return None
	data = entry_json if isinstance(entry_json, dict) else None
	if data is None:
		try:
			data = json.loads(entry_json)
		except (TypeError, ValueError):
			return None
	transfer = data.get("transfer")
	return transfer if isinstance(transfer, dict) else None


def _bank_account_of(bank_transaction: str | None) -> str:
	import frappe

	if not bank_transaction:
		return ""
	return str(frappe.db.get_value("Bank Transaction", bank_transaction, "bank_account") or "")


def _account_label(account: str | None) -> str:
	import frappe

	if not account:
		return ""
	return str(frappe.db.get_value("Account", account, "account_name") or account)


def render_candidates(candidates: Iterable[Mapping[str, Any]]) -> str:
	"""The list shown after [Баримт хайх]; indexes match the buttons the handler builds."""
	items = list(candidates)
	if not items:
		return mn.MSG_BANK_FIND_NONE
	lines = [mn.MSG_BANK_FIND_CANDIDATES]
	for index, item in enumerate(items, start=1):
		lines.append(
			mn.CARD_BANK_CANDIDATE.format(
				index=index,
				voucher=item.get("voucher_name") or item.get("name", ""),
				date=str(item.get("date", ""))[:10],
				amount=fmt_mnt(item.get("amount") or 0),
				party=item.get("party") or item.get("party_name") or "",
			)
		)
	return "\n".join(lines)


__all__ = ["render_bank_line", "render_candidates"]
