"""Link-code consumption: a six-digit code typed into the chat becomes a Nyabo User Link.

The first accountant linked to a company without completed settings is sent straight
into onboarding (§5.2), because nothing can be posted until the regime is known.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram import state as chat_state
from nyabo_mn.telegram.context import Ctx


def handle_code(ctx: Ctx) -> Any:
	# A six-digit code is the only credential guarding a company's books, so guessing is
	# capped per chat (SEC-05); without a cap the 10^6 space is walkable inside a code's
	# thirty-minute life.
	if chat_state.link_blocked_for(ctx.chat_id):
		ctx.reply(mn.MSG_LINK_CODE_TOO_MANY.format(minutes=chat_state.LINK_BLOCK_MINUTES))
		return {"linked": False, "blocked": True}
	try:
		link = chat_state.consume_link_code(ctx.text, ctx.sender)
	except chat_state.LinkCodeInvalid:
		attempts = chat_state.record_link_failure(ctx.chat_id)
		log_event(
			"telegram.link_code.invalid",
			level="warning",
			telegram_id=ctx.telegram_id,
			attempts=attempts,
			blocked=attempts >= chat_state.LINK_ATTEMPT_LIMIT,
		)
		if attempts >= chat_state.LINK_ATTEMPT_LIMIT:
			_notify_admins_of_guessing(ctx, attempts)
			ctx.reply(mn.MSG_LINK_CODE_TOO_MANY.format(minutes=chat_state.LINK_BLOCK_MINUTES))
		else:
			ctx.reply(mn.MSG_LINK_CODE_INVALID)
		return {"linked": False}
	chat_state.clear_link_failures(ctx.chat_id)
	ctx.link = link
	ctx.company = chat_state.active_company(link)
	frappe.set_user(link.user)
	ctx.reply(mn.MSG_LINKED.format(role=mn.ROLE_LABELS.get(link.role, link.role), company=ctx.company or "—"))
	if link.role == "Accountant" and ctx.company and not _onboarding_done(ctx.company):
		from nyabo_mn.telegram.handlers import onboarding

		onboarding.start(ctx)
	else:
		ctx.reply(mn.MSG_MENU)
	return {"linked": True, "role": link.role, "company": ctx.company}


def _notify_admins_of_guessing(ctx: Ctx, attempts: int) -> None:
	"""A blocked chat is an audit-trail event, not just a log line, and the admins are told."""
	from nyabo_mn.compliance import events
	from nyabo_mn.telegram.router import notify_admins

	events.log(
		"link_code_guessing_blocked",
		payload={"attempts": attempts, "minutes": chat_state.LINK_BLOCK_MINUTES},
		actor_telegram_id=ctx.telegram_id,
	)
	notify_admins(ctx.bot, ctx.settings, mn.MSG_ADMIN_LINK_GUESSING.format(chat_id=ctx.chat_id))


def _onboarding_done(company: str) -> bool:
	name = frappe.db.exists("Nyabo Company Settings", {"company": company})
	if not name:
		return False
	return bool(frappe.db.get_value("Nyabo Company Settings", name, "onboarding_completed"))
