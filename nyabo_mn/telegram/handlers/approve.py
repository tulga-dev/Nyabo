"""Proposal card taps: approve, change account, reject (docs/ARCHITECTURE.md §5.3).

Role gate (§5.3 step 7): an accountant may approve anything; an owner only a proposal
without ``needs_accountant`` and only when the company's ``auto_approve_policy`` allows
it. The tap is the human decision the Law on Accounting wants recorded, so the
approver's user and Telegram id go to the pipeline and from there onto the posted
document.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import frappe

from nyabo_mn.core.money import quantize, to_decimal
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram import _deps, cards, keyboards
from nyabo_mn.telegram.context import Ctx
from nyabo_mn.telegram.handlers import receipt

PROPOSAL = "Nyabo Proposal"
TOP_ACCOUNTS = 6


def approver_name(ctx: Ctx) -> str:
	"""The name stored at link time (what the admin vetted), not whatever Telegram sends now."""
	link = ctx.link
	if link is not None and (link.first_name or link.telegram_username):
		return link.first_name or f"@{link.telegram_username}"
	return ctx.sender.get("first_name") or ctx.user


# --- permissions -----------------------------------------------------------------------------------


def can_approve(ctx: Ctx, proposal: Any) -> bool:
	if ctx.is_accountant:
		return True
	if not ctx.is_owner or proposal.needs_accountant:
		return False
	return owner_policy_allows(proposal)


def owner_policy_allows(proposal: Any) -> bool:
	"""``owner_simple``: under the amount cap and, when a list is set, in the allowed accounts."""
	name = frappe.db.exists("Nyabo Company Settings", {"company": proposal.company})
	if not name:
		return False
	settings = frappe.db.get_value(
		"Nyabo Company Settings",
		name,
		["auto_approve_policy", "auto_approve_max_amount", "auto_approve_accounts"],
		as_dict=True,
	)
	if not settings or settings.auto_approve_policy != "owner_simple":
		return False
	cap = quantize(to_decimal(settings.auto_approve_max_amount or 0))
	if cap > Decimal("0") and quantize(to_decimal(proposal.total or 0)) > cap:
		return False
	allowed = [
		c.strip() for c in (settings.auto_approve_accounts or "").replace("\n", ",").split(",") if c.strip()
	]
	if allowed and (proposal.account_code or "") not in allowed:
		return False
	return True


def _load(ctx: Ctx, name: str) -> Any | None:
	if not frappe.db.exists(PROPOSAL, name):
		ctx.answer(mn.MSG_PROPOSAL_NOT_FOUND, show_alert=True)
		return None
	proposal = frappe.get_doc(PROPOSAL, name)
	if proposal.company and proposal.company not in ctx.companies:
		ctx.answer(mn.MSG_NO_PERMISSION, show_alert=True)
		return None
	return proposal


def _decided(ctx: Ctx, proposal: Any) -> bool:
	if proposal.status != "proposed":
		ctx.answer(mn.MSG_PROPOSAL_ALREADY_DECIDED.format(status=proposal.status), show_alert=True)
		receipt.update_card(proposal.name, bot=ctx.bot)
		return True
	return False


# --- callbacks -------------------------------------------------------------------------------------


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``p:<name>:ap|ch|rj|back``, ``p:<name>:acc:<code>``, ``p:<name>:rr:<reason>``."""
	if len(parts) < 3:
		return None
	_prefix, name, action, *rest = parts
	proposal = _load(ctx, name)
	if proposal is None:
		return None
	if action == "ap":
		return approve(ctx, proposal)
	if action == "ch":
		return choose_account(ctx, proposal)
	if action == "acc":
		return account_chosen(ctx, proposal, rest[0] if rest else "")
	if action == "rj":
		return ask_reject_reason(ctx, proposal)
	if action == "rr":
		return reject(ctx, proposal, rest[0] if rest else "other")
	if action == "back":
		if _decided(ctx, proposal):
			return None
		ctx.bot.edit_message_reply_markup(
			ctx.chat_id, ctx.callback_message_id, keyboards.receipt_keyboard(name)
		)
		return None
	log_event("telegram.callback.unknown", level="warning", data=ctx.callback_data[:64])
	return None


def approve(ctx: Ctx, proposal: Any) -> Any:
	if _decided(ctx, proposal):
		return None
	if not can_approve(ctx, proposal):
		ctx.answer(mn.MSG_ACCOUNTANT_ONLY, show_alert=True)
		ctx.reply(mn.MSG_ACCOUNTANT_ONLY)
		log_event(
			"telegram.approve.refused", proposal=proposal.name, role=ctx.role, telegram_id=ctx.telegram_id
		)
		return {"approved": False}
	text = cards.receipt_card(receipt.proposal_to_dict(proposal)) + "\n" + mn.MSG_APPROVED_POSTING
	ctx.edit(ctx.callback_message_id, text, keyboards.empty_markup())
	result = _deps.post_proposal(proposal.name, ctx.user, str(ctx.telegram_id)) or {}
	proposal.reload()
	posted_doctype = result.get("posted_doctype") or proposal.posted_doctype or ""
	posted_name = result.get("posted_name") or proposal.posted_name or "—"
	data = receipt.proposal_to_dict(proposal)
	approver = approver_name(ctx)
	ctx.edit(
		ctx.callback_message_id,
		cards.posted_card(data, posted_name, approver),
		keyboards.posted_keyboard(posted_doctype, posted_name),
	)
	ctx.answer(mn.MSG_POSTED.format(doc_name=posted_name))
	log_event("telegram.approve.posted", proposal=proposal.name, posted=posted_name, user=ctx.user)
	return {"approved": True, "posted_doctype": posted_doctype, "posted_name": posted_name}


def choose_account(ctx: Ctx, proposal: Any) -> Any:
	if _decided(ctx, proposal):
		return None
	accounts = _deps.top_accounts(proposal.company, n=TOP_ACCOUNTS)
	ctx.bot.edit_message_reply_markup(
		ctx.chat_id,
		ctx.callback_message_id,
		keyboards.account_chooser(keyboards.PREFIX_PROPOSAL, proposal.name, accounts),
	)
	ctx.answer(mn.MSG_CHOOSE_ACCOUNT)
	return {"accounts": accounts}


def account_chosen(ctx: Ctx, proposal: Any, code: str) -> Any:
	if _decided(ctx, proposal):
		return None
	if code == "more":
		ctx.set_state("acc_search", {"proposal": proposal.name, "message_id": ctx.callback_message_id})
		ctx.reply(mn.MSG_SEARCH_ACCOUNT)
		return None
	if not ctx.is_accountant and not ctx.is_owner:
		ctx.answer(mn.MSG_NO_PERMISSION, show_alert=True)
		return None
	updated = _deps.change_account(proposal.name, code, ctx.user)
	proposal.reload()
	data = receipt.proposal_to_dict(proposal)
	ctx.edit(ctx.callback_message_id, cards.receipt_card(data), keyboards.receipt_keyboard(proposal.name))
	ctx.answer(
		mn.MSG_ACCOUNT_CHANGED.format(
			code=proposal.account_code or code, account=data.get("account_name") or ""
		)
	)
	return {"changed": True, "proposal": getattr(updated, "name", proposal.name)}


def ask_reject_reason(ctx: Ctx, proposal: Any) -> Any:
	if _decided(ctx, proposal):
		return None
	ctx.bot.edit_message_reply_markup(
		ctx.chat_id, ctx.callback_message_id, keyboards.reject_reasons(proposal.name)
	)
	ctx.answer(mn.MSG_ASK_REJECT_REASON)
	return None


def reject(
	ctx: Ctx, proposal: Any, reason_code: str, reason_text: str | None = None, message_id: int | None = None
) -> Any:
	if _decided(ctx, proposal):
		return None
	if reason_code == "other" and not reason_text:
		ctx.set_state("reject_text", {"proposal": proposal.name, "message_id": ctx.callback_message_id})
		ctx.reply(mn.MSG_REJECT_TEXT_ASK)
		return None
	reason = reason_text or mn.REJECT_REASONS.get(reason_code, mn.REJECT_OTHER)
	_deps.reject(proposal.name, reason, ctx.user)
	proposal.reload()
	data = receipt.proposal_to_dict(proposal)
	ctx.edit(
		message_id or ctx.callback_message_id, cards.rejected_card(data, reason), keyboards.empty_markup()
	)
	ctx.answer(mn.MSG_REJECTED.format(reason=reason))
	log_event("telegram.reject", proposal=proposal.name, reason=reason_code, user=ctx.user)
	return {"rejected": True, "reason": reason}


# --- conversation states ---------------------------------------------------------------------------


def handle_state(ctx: Ctx, state: str, payload: dict[str, Any]) -> Any:
	if state == "acc_search":
		ctx.clear_state()
		query = ctx.text.strip()
		company = ctx.company or ""
		accounts = _deps.search_accounts(company, query)[:12]
		if not accounts:
			ctx.reply(mn.MSG_ACCOUNT_NOT_FOUND.format(query=query))
			return {"accounts": []}
		if payload.get("bank_transaction"):
			markup = keyboards.account_chooser(
				keyboards.PREFIX_BANK, payload["bank_transaction"], accounts, more=False
			)
		else:
			markup = keyboards.account_chooser(
				keyboards.PREFIX_PROPOSAL, payload.get("proposal", ""), accounts, more=False
			)
		ctx.reply(cards.account_chooser_text(accounts, query), markup)
		return {"accounts": accounts}
	if state == "reject_text":
		ctx.clear_state()
		name = payload.get("proposal", "")
		if not frappe.db.exists(PROPOSAL, name):
			ctx.reply(mn.MSG_PROPOSAL_NOT_FOUND)
			return None
		proposal = frappe.get_doc(PROPOSAL, name)
		return reject(
			ctx, proposal, "other", reason_text=ctx.text.strip()[:200], message_id=payload.get("message_id")
		)
	ctx.clear_state()
	return None
