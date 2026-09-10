"""``/меню`` and ``/тусламж``.

With an active company the menu *is* the dashboard (``handlers.dashboard``): the month's
figures, the bank balances, what waits on a tap, and the command list folded underneath.
Without one there is nothing to draw figures from, so the command list is sent as text.
"""

from __future__ import annotations

from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.telegram.context import Ctx


def handle_menu(ctx: Ctx) -> Any:
	if ctx.company and ctx.company in ctx.companies:
		from nyabo_mn.telegram.handlers import dashboard

		return dashboard.send_home(ctx, ctx.company)
	ctx.reply(mn.MSG_MENU)
	return None


def handle_help(ctx: Ctx) -> Any:
	text = mn.MSG_HELP
	if ctx.is_admin:
		text += "\n\n" + mn.MSG_ADMIN_HELP
	ctx.reply(text)
	return None
