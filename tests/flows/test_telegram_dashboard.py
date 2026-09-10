"""The dashboard: ``/меню`` draws the month, the banks and what waits on a tap; each button opens a card.

Every figure on these cards is read from the ledger the fixtures posted to, so the tests pin
the number the accountant sees against the number the books hold. The cards are rich messages
(``telegram.rich``); what is asserted is their plain twin — the words — plus, where the shape
matters, the HTML Telegram was handed.
"""

from __future__ import annotations

import datetime as dt

from nyabo_mn.agent import post, questions
from nyabo_mn.core import dates
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.reports import dashboard as data
from nyabo_mn.telegram import richcards
from tests.fixtures.telegram.fake_bot import FakeBotApi, callback_update, link_user, message_update, run
from tests.flows.conftest import ACCOUNTANT

TODAY = dt.date.today()
PERIOD = dates.period_of(TODAY)
FUEL_NET = "77272.73"  # petrovis_fuel: 85 000₮ gross, VAT payer in 2026 -> 77 272.73₮ on 6210


def _posted(run_receipt, books):
	proposal = run_receipt("petrovis_fuel", date=TODAY.isoformat())
	return post.post_proposal(proposal.name, ACCOUNTANT)


def test_the_menu_is_the_dashboard(run_receipt, books):
	_posted(run_receipt, books)
	link_user(9301, "Accountant", books)
	bot = FakeBotApi()
	outcome = run(bot, message_update(9301, "/меню"))

	assert outcome["result"] == {"view": richcards.VIEW_HOME, "company": books}
	text = bot.last_text
	assert text.startswith(mn.CARD_DASHBOARD_TITLE.format(company=books))
	assert mn.MSG_ACTIVE_COMPANY.format(company=books) in text
	assert mn.MSG_MENU in text, "the command list is still there, folded under the figures"
	assert f"{mn.CARD_EXPENSE} | {fmt_mnt(FUEL_NET)}₮ | {mn.CARD_DELTA_NONE}" in text
	assert f"{mn.CARD_PROFIT} | -{fmt_mnt(FUEL_NET)}₮" in text
	assert mn.MSG_RECON_NONE in text and mn.CARD_TODO_NONE in text
	assert bot.callback_datas() == [f"d:tx:{PERIOD}", "d:bank", "d:rep", "d:home"]
	html = bot.last_html
	assert html.startswith(f"<h3>{mn.CARD_DASHBOARD_TITLE.format(company=books)}</h3>")
	assert "<table bordered compact>" in html and f"<details><summary>{mn.CARD_COMMANDS}</summary>" in html


def test_start_for_a_linked_user_is_the_welcome_and_the_dashboard(books):
	link_user(9302, "Owner", books)
	bot = FakeBotApi()
	run(bot, message_update(9302, "/start"))
	assert bot.texts()[0] == mn.MSG_WELCOME
	assert bot.last_text.startswith(mn.CARD_DASHBOARD_TITLE.format(company=books))
	assert mn.CARD_MONTH_EMPTY in bot.last_text  # nothing posted yet: say so, no zero table


def test_what_waits_on_a_tap_is_listed_and_the_proposal_card_comes_back(run_receipt, books):
	proposal = run_receipt("petrovis_fuel", date=TODAY.isoformat())
	link_user(9303, "Accountant", books)
	bot = FakeBotApi()
	run(bot, message_update(9303, "/меню"))
	assert f"☐ {mn.CARD_TODO_PROPOSALS.format(count=1)}" in bot.last_text
	assert bot.callback_datas() == [f"d:tx:{PERIOD}", "d:bank", "d:rep", "d:pend", "d:home"]

	run(bot, callback_update(9303, "d:pend", message_id=800))
	edit = bot.sent("edit_rich_message")[-1]
	assert edit["message_id"] == 800
	assert mn.CARD_PENDING_TITLE.format(count=1) in edit["text"] and fmt_mnt(85000) in edit["text"]
	assert f"p:{proposal.name}:sh" in bot.callback_datas()

	run(bot, callback_update(9303, f"p:{proposal.name}:sh"))
	# The proposal's own card, with its own buttons: approval still goes through handlers.approve.
	assert bot.callback_datas() == [
		f"p:{proposal.name}:ap",
		f"p:{proposal.name}:ch",
		f"p:{proposal.name}:rj",
	]


def test_the_transactions_card_lists_the_months_vouchers_and_pages_by_month(run_receipt, books):
	posted = _posted(run_receipt, books)
	link_user(9304, "Accountant", books)
	bot = FakeBotApi()
	run(bot, callback_update(9304, f"d:tx:{PERIOD}", message_id=801))
	edit = bot.sent("edit_rich_message")[-1]
	assert edit["message_id"] == 801
	text = edit["text"]
	assert text.startswith(mn.CARD_TX_TITLE.format(period=dates.period_label(PERIOD)))
	assert f"| {fmt_mnt(85000)} | {mn.CARD_STATUS_POSTED}" in text
	assert posted["posted_name"] not in text  # the accountant reads what it was, not a voucher id
	previous = data.shift_period(PERIOD, -1)
	assert f"d:tx:{previous}" in bot.callback_datas() and "d:home" in bot.callback_datas()


def test_the_biggest_cost_card_ranks_expense_accounts_with_their_share(run_receipt, books):
	_posted(run_receipt, books)
	link_user(9305, "Accountant", books)
	bot = FakeBotApi()
	run(bot, callback_update(9305, f"d:top:{PERIOD}", message_id=802))
	edit = bot.sent("edit_rich_message")[-1]
	assert edit["text"].startswith(mn.CARD_TOP_TITLE.format(period=dates.period_label(PERIOD)))
	assert f"| {fmt_mnt(FUEL_NET)}₮ | 100%" in edit["text"]
	assert f"| {fmt_mnt(FUEL_NET)}₮ | 100%" in edit["text"]
	assert "<mark>" in edit["html"], "the account the money went to is the highlighted word"


def test_the_trend_card_shows_six_months_oldest_first(run_receipt, books):
	_posted(run_receipt, books)
	link_user(9306, "Accountant", books)
	bot = FakeBotApi()
	run(bot, callback_update(9306, "d:rev", message_id=803))
	text = bot.sent("edit_rich_message")[-1]["text"]
	labels = [dates.period_label(data.shift_period(PERIOD, -i)) for i in range(5, -1, -1)]
	assert text.startswith(mn.CARD_TREND_TITLE.format(from_period=labels[0], to_period=labels[-1]))
	assert [line.split(" | ")[0] for line in text.split("\n") if line.split(" | ")[0] in labels] == labels
	assert f"{labels[-1]} | {fmt_mnt(0)}₮ | {fmt_mnt(FUEL_NET)}₮ | —" in text
	assert mn.CARD_TREND_BEST.split("{")[0] not in text, "spend without revenue names no best month"


def test_the_trial_balance_card_and_its_files(run_receipt, books):
	_posted(run_receipt, books)
	link_user(9307, "Accountant", books)
	bot = FakeBotApi()
	run(bot, callback_update(9307, f"d:tb:{PERIOD}", message_id=804))
	text = bot.sent("edit_rich_message")[-1]["text"]
	assert text.startswith(mn.CARD_TB_TITLE.format(period=dates.period_label(PERIOD)))
	assert mn.CARD_TB_TOTALS.format(debit=fmt_mnt(85000), credit=fmt_mnt(85000)) in text
	assert f"d:tbpdf:{PERIOD}" in bot.callback_datas() and f"d:tbx:{PERIOD}" in bot.callback_datas()

	run(bot, callback_update(9307, f"d:tbx:{PERIOD}"))
	assert bot.sent("send_document")[-1]["filename"] == f"trial_balance_{PERIOD}.xlsx"
	run(bot, callback_update(9307, f"d:tbpdf:{PERIOD}"))
	assert bot.sent("send_document")[-1]["filename"] == f"trial_balance_{PERIOD}.pdf"


def test_the_empty_cards_say_so_instead_of_drawing_zeros(books):
	link_user(9308, "Accountant", books)
	bot = FakeBotApi()
	run(bot, callback_update(9308, "d:bank", message_id=805))
	assert bot.sent("edit_rich_message")[-1]["text"] == mn.MSG_RECON_NONE
	run(bot, callback_update(9308, "d:inv", message_id=805))
	assert mn.CARD_INV_NONE in bot.sent("edit_rich_message")[-1]["text"]
	run(bot, callback_update(9308, "d:unm", message_id=805))
	assert bot.last_text == mn.CARD_UNMATCHED_NONE
	run(bot, callback_update(9308, "d:stm", message_id=805))
	assert bot.last_text == mn.CARD_STATEMENT_HINT
	run(bot, callback_update(9308, "d:rep", message_id=805))
	assert bot.sent("edit_rich_message")[-1]["text"].startswith(mn.CARD_REPORTS_TITLE)
	assert f"d:tb:{PERIOD}" in bot.callback_datas() and "d:inv" in bot.callback_datas()


def test_a_datum_this_build_does_not_know_falls_back_to_the_dashboard(books):
	link_user(9309, "Accountant", books)
	bot = FakeBotApi()
	run(bot, callback_update(9309, "d:zzz:2026-13", message_id=806))
	assert bot.sent("edit_rich_message")[-1]["text"].startswith(mn.CARD_DASHBOARD_TITLE.format(company=books))
	assert bot.sent("answer_callback_query"), "the spinner is stopped first"


def test_without_a_company_the_dashboard_is_refused(books):
	link_user(9310, "Owner", None)
	bot = FakeBotApi()
	run(bot, callback_update(9310, "d:home"))
	assert bot.last_text == mn.MSG_NO_COMPANY


def test_a_failing_section_is_a_gap_not_a_dead_menu(books, monkeypatch):
	def explode(company, today=None):
		raise RuntimeError("bank status down")

	monkeypatch.setattr(data, "bank_summary", explode)
	link_user(9311, "Accountant", books)
	bot = FakeBotApi()
	run(bot, message_update(9311, "/меню"))
	assert bot.last_text.startswith(mn.CARD_DASHBOARD_TITLE.format(company=books))
	assert mn.MSG_RECON_NONE in bot.last_text


def test_the_breakdown_answer_draws_the_entries_as_a_table(run_receipt, books):
	"""The answer card: the handler's rows become a table, the subject line stays the footer."""
	posted = _posted(run_receipt, books)
	link_user(9312, "Accountant", books)
	bot = FakeBotApi()
	ledger = questions.QUERY_SHORT["account_entries"]
	run(bot, callback_update(9312, f"q:{ledger}:6210:{PERIOD}", message_id=807))
	edit = bot.sent("edit_rich_message")[-1]
	assert f"<td>{posted['posted_name']}</td>" in edit["html"]
	assert "<table bordered striped compact>" in edit["html"]
	assert edit["html"].endswith("</footer>")
	assert edit["text"].endswith(
		mn.MSG_QUESTION_SUBJECT.format(subject=f"6210 · {dates.period_label(PERIOD)}")
	)
