"""Free text outside any conversation state → the read-only question answerer (§5.7)."""

from __future__ import annotations

from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps
from nyabo_mn.telegram.context import Ctx


def handle_text(ctx: Ctx) -> Any:
	if not ctx.company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	answer = _deps.answer_question(ctx.user, ctx.company, ctx.text)
	ctx.reply(answer or mn.MSG_QUESTION_CANNOT)
	return {"answer": answer}
