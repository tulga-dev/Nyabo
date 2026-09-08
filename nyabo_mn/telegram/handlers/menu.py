"""``/меню`` and ``/тусламж``."""

from __future__ import annotations

from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.telegram.context import Ctx


def handle_menu(ctx: Ctx) -> Any:
	text = mn.MSG_MENU
	if ctx.company:
		text = mn.MSG_ACTIVE_COMPANY.format(company=ctx.company) + "\n" + text
	ctx.reply(text)
	return None


def handle_help(ctx: Ctx) -> Any:
	text = mn.MSG_HELP
	if ctx.is_admin:
		text += "\n\n" + mn.MSG_ADMIN_HELP
	ctx.reply(text)
	return None
