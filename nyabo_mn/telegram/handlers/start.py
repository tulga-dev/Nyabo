"""``/start`` and ``/whoami``: the two things anyone may do before being linked."""

from __future__ import annotations

from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.telegram.context import Ctx


def handle_start(ctx: Ctx) -> Any:
	"""Welcome; unlinked senders are told how to get a code, linked ones get the dashboard."""
	if ctx.link is None:
		from nyabo_mn.telegram import richcards

		ctx.reply_card(richcards.welcome_card())
		return {"linked": False}
	from nyabo_mn.telegram.handlers import menu

	ctx.reply(mn.MSG_WELCOME)
	menu.handle_menu(ctx)
	return {"linked": True}


def handle_whoami(ctx: Ctx) -> Any:
	"""The numeric id an admin needs for ADMIN_TELEGRAM_IDS; safe to show to anyone (it is theirs)."""
	ctx.reply(mn.MSG_YOUR_TELEGRAM_ID.format(telegram_id=ctx.telegram_id))
	return {"telegram_id": ctx.telegram_id}
