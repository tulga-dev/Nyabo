"""Unmatched bank line cards: [Баримт хайх] [Зардал бүртгэх] [Дараа] (docs/ARCHITECTURE.md §5.4)."""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram import _deps, cards, keyboards
from nyabo_mn.telegram._deps import DependencyMissing
from nyabo_mn.telegram.context import Ctx
from nyabo_mn.telegram.handlers import receipt

BANK_TRANSACTION = "Bank Transaction"
STATE_FIND = "bank_find"
TOP_ACCOUNTS = 6


def bank_line_text(txn_name: str) -> str:
	try:
		rendered = _deps.render_bank_line(txn_name)
	except DependencyMissing:
		rendered = None
	if isinstance(rendered, tuple):  # matching.cards.render_bank_line -> (text, proposal name)
		return str(rendered[0])
	if isinstance(rendered, str):
		return rendered
	if True:
		doc = frappe.get_doc(BANK_TRANSACTION, txn_name)
		data = doc.as_dict()
		if doc.bank_account:
			data["bank"] = frappe.db.get_value("Bank Account", doc.bank_account, "bank") or doc.bank_account
		return cards.bank_line_card(data)


def chat_id_for(company: str | None, document: str | None = None) -> str | None:
	"""Where an unmatched-line card belongs: the chat the statement arrived in, else the accountant's.

	Mirrors ``receipt.chat_id_for``; a bank line has no card chat of its own, so the
	``Nyabo Document`` of the import is the first source (``matching.match.run`` passes it).
	"""
	if document and frappe.db.exists("Nyabo Document", document):
		chat_id = frappe.db.get_value("Nyabo Document", document, "telegram_chat_id")
		if chat_id:
			return str(chat_id)
	if company:
		name = frappe.db.exists("Nyabo Company Settings", {"company": company})
		if name:
			settings = frappe.db.get_value(
				"Nyabo Company Settings", name, ["accountant_telegram_id", "owner_telegram_id"], as_dict=True
			)
			chat_id = settings.accountant_telegram_id or settings.owner_telegram_id
			return str(chat_id) if chat_id else None
	return None


def send_bank_card(bot: Any, chat_id: int | str, txn_name: str) -> dict[str, Any]:
	message = bot.send_message(
		chat_id, bank_line_text(txn_name), reply_markup=keyboards.bank_line_keyboard(txn_name)
	)
	return {"message_id": message.get("message_id")}


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``b:<name>:find|exp|later|back``, ``b:<name>:acc:<code>``, ``b:<name>:m:<index>``."""
	if len(parts) < 3:
		return None
	_prefix, name, action, *rest = parts
	if not frappe.db.exists(BANK_TRANSACTION, name):
		ctx.answer(mn.MSG_BANK_TRANSACTION_NOT_FOUND.format(name=name), show_alert=True)
		return None
	if action == "find":
		ctx.set_state(STATE_FIND, {"bank_transaction": name, "message_id": ctx.callback_message_id})
		ctx.reply(mn.MSG_BANK_FIND_ASK)
		return None
	if action == "m":
		return match_chosen(ctx, name, rest[0] if rest else "")
	if action == "exp":
		company = frappe.db.get_value(BANK_TRANSACTION, name, "company") or ctx.company or ""
		accounts = _deps.top_accounts(company, n=TOP_ACCOUNTS)
		ctx.reply(
			mn.MSG_BANK_EXPENSE_CHOOSE_ACCOUNT,
			keyboards.account_chooser(keyboards.PREFIX_BANK, name, accounts),
		)
		return {"accounts": accounts}
	if action == "acc":
		code = rest[0] if rest else ""
		if code == "more":
			ctx.set_state("acc_search", {"bank_transaction": name})
			ctx.reply(mn.MSG_SEARCH_ACCOUNT)
			return None
		proposal_name = _deps.propose_bank_expense(name, code, ctx.user)
		ctx.edit(
			ctx.callback_message_id,
			mn.MSG_ACCOUNT_CHANGED.format(code=code, account=""),
			keyboards.empty_markup(),
		)
		if proposal_name:
			receipt.send_proposal_card(proposal_name, chat_id=ctx.chat_id, bot=ctx.bot)
		return {"proposal": proposal_name}
	if action == "later":
		ctx.clear_state()
		ctx.bot.edit_message_reply_markup(ctx.chat_id, ctx.callback_message_id, keyboards.empty_markup())
		ctx.answer(mn.MSG_BANK_LATER)
		return None
	if action == "back":
		ctx.bot.edit_message_reply_markup(
			ctx.chat_id, ctx.callback_message_id, keyboards.bank_line_keyboard(name)
		)
		return None
	log_event("telegram.callback.unknown", level="warning", data=ctx.callback_data[:64])
	return None


def _candidate_dict(candidate: Any) -> dict[str, Any]:
	if isinstance(candidate, dict):
		return dict(candidate)
	if hasattr(candidate, "to_dict"):
		return dict(candidate.to_dict())
	return {
		k: getattr(candidate, k)
		for k in ("voucher_doctype", "voucher_name", "date", "amount", "party")
		if hasattr(candidate, k)
	}


def handle_state(ctx: Ctx, state: str, payload: dict[str, Any]) -> Any:
	name = payload.get("bank_transaction")
	if not name:
		ctx.clear_state()
		return None
	candidates = [_candidate_dict(c) for c in (_deps.find_candidates(name, ctx.text.strip()) or [])][:9]
	if not candidates:
		ctx.reply(mn.MSG_BANK_FIND_NONE)
		return {"candidates": []}
	payload["candidates"] = candidates
	ctx.set_state(STATE_FIND, payload)
	ctx.reply(cards.bank_candidates_text(candidates), keyboards.bank_candidates(name, len(candidates)))
	return {"candidates": candidates}


def match_chosen(ctx: Ctx, name: str, index_text: str) -> Any:
	state, payload = ctx.get_state()
	candidates = payload.get("candidates") or []
	try:
		candidate = candidates[int(index_text)]
	except (IndexError, ValueError):
		ctx.answer(mn.MSG_BANK_FIND_NONE, show_alert=True)
		return None
	ctx.clear_state()
	voucher_doctype = candidate.get("voucher_doctype") or candidate.get("doctype") or ""
	voucher_name = candidate.get("voucher_name") or candidate.get("name") or ""
	_deps.reconcile(name, voucher_doctype, voucher_name, ctx.user)
	ctx.edit(
		ctx.callback_message_id, mn.MSG_BANK_MATCHED.format(voucher=voucher_name), keyboards.empty_markup()
	)
	log_event("telegram.bank.reconciled", bank_transaction=name, voucher=voucher_name, user=ctx.user)
	return {"matched": voucher_name}
