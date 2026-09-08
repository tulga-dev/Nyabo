"""``Засах`` on a posted entry (docs/ARCHITECTURE.md §5.6): reason → reversal → new proposal.

The bot never edits or cancels a submitted document (principle 5); ``compliance.reversal``
makes the reverse JE / debit note and this handler only collects the reason (Law on
Accounting art. 15 wants reason and method recorded) and re-proposes unless the reason
is "duplicate".
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.core import dates
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram import _deps, keyboards
from nyabo_mn.telegram.context import Ctx
from nyabo_mn.telegram.handlers import receipt

STATE_REASON = "correct"
STATE_TEXT = "correct:text"


def _period_label(period: Any) -> str:
	"""``"2026-08"`` -> ``"2026 оны 8-р сар"``; a reversal row can carry anything, so guard it.

	Every message with a ``{period}`` placeholder is written against the label, which
	already ends in «сар» (UX-04) — passing the raw ISO period would read as a machine id.
	"""
	try:
		return dates.period_label(str(period))
	except ValueError:
		return mn.VALUE_UNKNOWN


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``x:<pi|je|si>:<name>:rev``, ``x:<name>:reason:<code>``, ``x:<name>:cancel``."""
	if len(parts) >= 4 and parts[3] == "rev":
		return start(ctx, keyboards.SHORT_DOCTYPE.get(parts[1]), parts[2])
	if len(parts) >= 4 and parts[2] == "reason":
		return reason_chosen(ctx, parts[1], parts[3])
	if len(parts) >= 3 and parts[2] == "cancel":
		ctx.clear_state()
		ctx.edit(ctx.callback_message_id, mn.MSG_CANCELLED, keyboards.empty_markup())
		return None
	log_event("telegram.callback.unknown", level="warning", data=ctx.callback_data[:64])
	return None


def start(ctx: Ctx, doctype: str | None, name: str) -> Any:
	if not ctx.is_accountant:
		ctx.answer(mn.MSG_NO_PERMISSION, show_alert=True)
		return None
	if not doctype or not frappe.db.exists(doctype, name):
		ctx.answer(mn.MSG_PROPOSAL_NOT_FOUND, show_alert=True)
		return None
	ctx.set_state(STATE_REASON, {"doctype": doctype, "name": name})
	ctx.reply(
		mn.MSG_CORRECTION_STARTED.format(doctype=doctype, name=name) + "\n" + mn.MSG_CORRECTION_ASK_REASON,
		keyboards.correction_reasons(name),
	)
	return {"doctype": doctype, "name": name}


def _pending(ctx: Ctx, name: str) -> tuple[str, str] | None:
	state, payload = ctx.get_state()
	if state in (STATE_REASON, STATE_TEXT) and payload.get("name") == name and payload.get("doctype"):
		return payload["doctype"], name
	# The button may be tapped after the state expired; the name is unique across the three doctypes.
	for doctype in keyboards.DOCTYPE_SHORT:
		if frappe.db.exists(doctype, name):
			return doctype, name
	return None


def reason_chosen(ctx: Ctx, name: str, code: str) -> Any:
	if not ctx.is_accountant:
		ctx.answer(mn.MSG_NO_PERMISSION, show_alert=True)
		return None
	pending = _pending(ctx, name)
	if pending is None:
		ctx.answer(mn.MSG_PROPOSAL_NOT_FOUND, show_alert=True)
		return None
	doctype, name = pending
	if code == "other":
		ctx.set_state(STATE_TEXT, {"doctype": doctype, "name": name, "message_id": ctx.callback_message_id})
		ctx.reply(mn.MSG_CORRECTION_ASK_TEXT)
		return None
	ctx.bot.edit_message_reply_markup(ctx.chat_id, ctx.callback_message_id, keyboards.empty_markup())
	return do_reverse(ctx, doctype, name, code, mn.CORRECT_REASONS.get(code, code))


def do_reverse(ctx: Ctx, doctype: str, name: str, code: str, reason_text: str) -> Any:
	ctx.clear_state()
	result = _deps.reverse(doctype, name, code, reason_text, ctx.user) or {}
	reversal = result.get("reversal_name") or result.get("name") or "—"
	from nyabo_mn.telegram.handlers.approve import approver_name

	approver = approver_name(ctx)
	ctx.reply(mn.MSG_CORRECTION_DONE.format(reversal=reversal, reason=reason_text, approver=approver))
	if result.get("period_closed"):
		ctx.reply(mn.MSG_CORRECTION_PERIOD_CLOSED.format(period=_period_label(result.get("original_period"))))
	log_event("telegram.correction.reversed", doctype=doctype, name=name, reason=code, reversal=reversal)
	outcome = {"reversal": reversal, "new_proposal": None}
	if code != "dup":
		ctx.reply(mn.MSG_CORRECTION_NEW_ENTRY_HINT)
		proposal_name = _deps.make_correction_proposal(doctype, name, reason_text, ctx.user)
		if proposal_name:
			receipt.send_proposal_card(proposal_name, chat_id=ctx.chat_id, bot=ctx.bot)
			outcome["new_proposal"] = proposal_name
	return outcome


def handle_state(ctx: Ctx, state: str, payload: dict[str, Any]) -> Any:
	"""Typed text while a correction is open is the free-form reason (code ``other``)."""
	doctype, name = payload.get("doctype"), payload.get("name")
	if not doctype or not name:
		ctx.clear_state()
		return None
	if not ctx.is_accountant:
		ctx.clear_state()
		ctx.reply(mn.MSG_NO_PERMISSION)
		return None
	if state == STATE_REASON and not ctx.text:
		ctx.reply(mn.MSG_CORRECTION_ASK_REASON, keyboards.correction_reasons(name))
		return None
	return do_reverse(ctx, doctype, name, "other", ctx.text.strip()[:200])
