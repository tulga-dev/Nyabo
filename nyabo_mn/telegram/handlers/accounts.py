"""``/данс``: per bank account, ledger balance vs statement balance and the unmatched count.

The numbers come from ``nyabo_mn.matching.status`` (through ``reports.dashboard``), which
owns the statement side and knows each import's closing balance; the card is
``richcards.bank_card``. This handler only decides who may ask: without an active company
there is nothing to report.

Why not compute them here: a second implementation drifted from the matcher's and printed
the running sum of imported transactions as the "statement" balance, which is a different
number from the closing balance the bank printed whenever the opening balance was not zero.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.reports import dashboard as data
from nyabo_mn.telegram import richcards
from nyabo_mn.telegram.context import Ctx


def handle_command(ctx: Ctx) -> Any:
	if not ctx.company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	today = dt.date.today()
	rows = data.bank_summary(ctx.company, today)
	ctx.reply_card(richcards.bank_card(rows, today))
	return {"company": ctx.company, "accounts": len(rows)}
