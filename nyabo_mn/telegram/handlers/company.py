"""``/компани``: switch the active company for a user linked to several."""

from __future__ import annotations

from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import keyboards
from nyabo_mn.telegram import state as chat_state
from nyabo_mn.telegram.context import Ctx


def handle_command(ctx: Ctx) -> Any:
	companies = ctx.companies
	if not companies:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	if ctx.args:
		return _switch(ctx, ctx.args)
	if len(companies) == 1:
		ctx.reply(mn.MSG_ACTIVE_COMPANY.format(company=companies[0]))
		return None
	ctx.reply(mn.MSG_CHOOSE_COMPANY, keyboards.company_chooser(companies))
	return None


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``k:<index>`` — the index into the user's own company list (names exceed 64 bytes)."""
	companies = ctx.companies
	try:
		index = int(parts[1])
		company = companies[index]
	except (IndexError, ValueError):
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	return _switch(ctx, company, message_id=ctx.callback_message_id)


def _switch(ctx: Ctx, company: str, message_id: int | None = None) -> Any:
	if company not in ctx.companies:
		ctx.reply(mn.MSG_NO_PERMISSION)
		return None
	chat_state.set_active_company(ctx.link, company)
	ctx.company = company
	ctx.edit(message_id, mn.MSG_ACTIVE_COMPANY.format(company=company), keyboards.empty_markup())
	return {"company": company}
