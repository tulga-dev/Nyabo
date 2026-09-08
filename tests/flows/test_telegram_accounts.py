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

from nyabo_mn.i18n import mn
from nyabo_mn.matching import bank_import, status
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
	assert outcome["result"]["company"] == imported and outcome["result"]["text"] == text
	assert lines[0] == mn.MSG_RECON_STATUS_HEADER.format(company=imported)
	# The bank printed 1 905 000₮ as its closing balance; summing the imported lines would
	# give 905 000₮ (the file opens at 1 000 000₮), and that is not what the account holds.
	assert lines[1] == "Хаан банк MNT: хуулга 1 905 000₮ · дэвтэр -93 500₮ · зөрүү 1 998 500₮ · тулгаагүй 4"
	assert lines[2].startswith("Худалдаа хөгжлийн банк MNT: хуулга 0₮ · дэвтэр 0₮")
	# The report is dated: the unimported second account is only current as of today.
	assert lines[-1] == mn.MSG_RECON_AS_OF.format(date=dt.date.today().isoformat())
	assert "Khan Bank" not in text and "TDB" not in text  # the accountant reads Mongolian names


def test_the_card_is_the_matching_modules_own_report(imported):
	"""One renderer only: the card the bot sends is what ``status.render`` produces."""
	link_user(9202, "Accountant", imported)
	bot = FakeBotApi()
	run(bot, message_update(9202, "/данс"))
	assert bot.last_text == status.render(imported)
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
