"""``/start`` and ``/whoami``: the two things anyone may do before being linked."""

from __future__ import annotations

from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.telegram.context import Ctx


def handle_start(ctx: Ctx) -> Any:
	"""Welcome; unlinked senders are told how to get a code, linked ones get the menu."""
	if ctx.link is None:
		ctx.reply(mn.MSG_WELCOME + "\n\n" + mn.MSG_NOT_LINKED)
		return {"linked": False}
	ctx.reply(mn.MSG_WELCOME + "\n\n" + mn.MSG_MENU)
	return {"linked": True}


def handle_whoami(ctx: Ctx) -> Any:
	"""The numeric id an admin needs for ADMIN_TELEGRAM_IDS; safe to show to anyone (it is theirs)."""
	ctx.reply(mn.MSG_YOUR_TELEGRAM_ID.format(telegram_id=ctx.telegram_id))
	return {"telegram_id": ctx.telegram_id}
