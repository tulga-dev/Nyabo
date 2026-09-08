"""``/данс``: per bank account, statement balance vs ledger balance and the unmatched count.

The numbers and the card text both come from ``nyabo_mn.matching.status`` (through
``_deps``), which owns the statement side and knows each import's closing balance. This
handler only decides who may ask: without an active company there is nothing to report.

Why not compute them here: a second implementation drifted from the matcher's and printed
the running sum of imported transactions as the "statement" balance, which is a different
number from the closing balance the bank printed whenever the opening balance was not zero.
"""

from __future__ import annotations

from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps
from nyabo_mn.telegram.context import Ctx


def handle_command(ctx: Ctx) -> Any:
	if not ctx.company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	text = _deps.recon_status(ctx.company)
	ctx.reply(text)
	return {"company": ctx.company, "text": text}
