"""``/чанар``: the last 30 days of quality metrics from ``evals.metrics``."""

from __future__ import annotations

from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps, cards
from nyabo_mn.telegram.context import Ctx

DAYS = 30


def handle_command(ctx: Ctx) -> Any:
	if not ctx.company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	metrics = _deps.quality_summary(ctx.company, days=DAYS)
	ctx.reply(cards.quality_card(ctx.company, DAYS, metrics))
	return metrics
