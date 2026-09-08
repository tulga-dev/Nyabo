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
	try:
		link = chat_state.consume_link_code(ctx.text, ctx.sender)
	except chat_state.LinkCodeInvalid:
		log_event("telegram.link_code.invalid", telegram_id=ctx.telegram_id)
		ctx.reply(mn.MSG_LINK_CODE_INVALID)
		return {"linked": False}
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


def _onboarding_done(company: str) -> bool:
	name = frappe.db.exists("Nyabo Company Settings", {"company": company})
	if not name:
		return False
	return bool(frappe.db.get_value("Nyabo Company Settings", name, "onboarding_completed"))
