"""``/данс``: the per-bank balance report an accountant reads, over the router.

The empty case is covered elsewhere; what matters here is the report after a real
import — the statement side must be the closing balance the bank printed, the ledger
side ERPNext's balance, and the bank name must be the Mongolian one the accountant
knows. The numbers are the matcher's (``nyabo_mn.matching.status``), so this file also
pins that the command and ``/хаалт``'s reconciliation view can never disagree.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.matching import bank_import, status
from nyabo_mn.telegram import richcards
from tests.fixtures.statements import make_fixtures as fixtures
from tests.fixtures.telegram.fake_bot import FakeBotApi, link_user, message_update, run
from tests.flows import bank_helpers as helpers


@pytest.fixture
def books(company, frappe_hooks):
	"""Тест ХХК without the nyabo doc_events, like the other bank flow tests."""
	with frappe_hooks(without_apps=("nyabo_mn",)):
		yield company


@pytest.fixture
def imported(books):
	"""Two configured banks, one paid invoice in the ledger and the Khan statement imported."""
	banks = helpers.setup_banks(books)
	helpers.register_layouts()
	helpers.paid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01", banks["khan_gl"])
	filename, data = fixtures.khan_xlsx()
	bank_import.import_statement(helpers.statement_document(books, filename, data))
	return books


def test_dans_prints_the_closing_balance_against_the_ledger(imported):
	link_user(9201, "Accountant", imported)
	bot = FakeBotApi()
	outcome = run(bot, message_update(9201, "/данс"))
	text = bot.last_text
	lines = text.split("\n")
	assert outcome["result"] == {"company": imported, "accounts": 2}
	assert lines[0] == mn.CARD_BANK_TITLE.format(date=dt.date.today().isoformat())
	assert lines[1] == " | ".join(
		(mn.COL_ACCOUNT, mn.CARD_COL_LEDGER, mn.CARD_COL_STATEMENT, mn.CARD_COL_DIFF)
	)
	# The bank printed 1 905 000₮ as its closing balance; summing the imported lines would
	# give 905 000₮ (the file opens at 1 000 000₮), and that is not what the account holds.
	assert lines[2].startswith("Хаан банк")
	assert lines[2].endswith(f" | {fmt_mnt(-93500)} | {fmt_mnt(1905000)} | {fmt_mnt(1998500)}")
	assert lines[3].startswith("Худалдаа хөгжлийн банк") and lines[3].endswith(f" | {fmt_mnt(0)}")
	note = mn.CARD_BANK_DIFF_NOTE.format(bank="", diff=fmt_mnt(1998500), count=4)
	assert any(line.startswith("Хаан банк") and line.endswith(note) for line in lines)
	# The report is dated: the unimported second account is only current as of today.
	assert lines[-1] == mn.CARD_BANK_SOURCE.format(date=dt.date.today().isoformat())
	assert "Khan Bank" not in text and "TDB" not in text  # the accountant reads Mongolian names
	# Four lines wait on the accountant, so the card offers to bring them up.
	assert bot.callback_datas()[0] == f"d:{richcards.VIEW_UNMATCHED}"


def test_the_card_is_the_matching_modules_own_report(imported):
	"""One source of numbers: the card shows what ``status.summary`` computes."""
	link_user(9202, "Accountant", imported)
	bot = FakeBotApi()
	run(bot, message_update(9202, "/данс"))
	khan = status.summary(imported, today=dt.date.today())[0]
	assert fmt_mnt(khan["statement_balance"]) in bot.last_html
	assert fmt_mnt(khan["ledger_balance"]) in bot.last_html
	khan = status.summary(imported, today=dt.date(2026, 9, 30))[0]
	assert khan["statement_balance"] == Decimal("1905000.00") and khan["unmatched"] == 4


def test_without_an_active_company_the_user_is_sent_to_the_admin(books):
	link_user(9203, "Owner", None)
	bot = FakeBotApi()
	assert run(bot, message_update(9203, "/данс"))["result"] is None
	assert bot.last_text == mn.MSG_NO_COMPANY


def test_without_configured_bank_accounts_the_card_says_so(books):
	link_user(9204, "Accountant", books)
	bot = FakeBotApi()
	run(bot, message_update(9204, "/данс"))
	assert bot.last_text == mn.MSG_RECON_NONE
