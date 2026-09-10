"""Demo entries: an empty test ledger gets six months of figures; a real one is refused."""

from __future__ import annotations

import datetime as dt

import frappe
import pytest

from nyabo_mn import api
from nyabo_mn.agent import post
from nyabo_mn.core import dates
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.reports import dashboard as data
from nyabo_mn.setup import demo
from tests.fixtures.telegram.fake_bot import FakeBotApi, callback_update, link_user, message_update, run
from tests.flows import bank_helpers as helpers
from tests.flows.conftest import ACCOUNTANT

TODAY = dt.date.today()
PERIOD = dates.period_of(TODAY)


def test_an_empty_ledger_gets_six_months_and_the_dashboard_shows_them(books):
	report = demo.seed(books, today=TODAY)
	assert report["already"] is False
	assert report["vouchers"] == demo.MONTHS * 8
	assert report["period_to"] == PERIOD and report["bank"]["skipped"]
	# Every voucher says what it is, and none pretends to a paper document (art. 13.7).
	refs = frappe.get_all(
		"Journal Entry", filters={"company": books, "docstatus": 1}, pluck="nyabo_primary_document_ref"
	)
	assert refs and all(r.startswith(demo.DEMO_TAG) for r in refs)

	month = data.month_with_delta(books, PERIOD)
	assert month["revenue"] > month["expense"] > 0
	assert month["revenue_delta_pct"] is not None and month["revenue_delta_pct"] > 0
	assert [row["revenue"] > 0 for row in data.revenue_trend(books, PERIOD)] == [True] * 6
	top = data.top_expenses(books, PERIOD)
	assert top["rows"][0]["amount"] == demo.RENT[1] and top["rows"][0]["share_pct"] > 40

	link_user(9401, "Accountant", books)
	bot = FakeBotApi()
	run(bot, message_update(9401, "/меню"))
	assert f"{mn.CARD_REVENUE} | {fmt_mnt(month['revenue'])}₮" in bot.last_text
	run(bot, callback_update(9401, "d:rev", message_id=1))
	assert (
		mn.CARD_TREND_BEST.format(period=dates.period_label(PERIOD), amount=fmt_mnt(month["revenue"]))
		in bot.last_text
	)


def test_a_second_run_changes_nothing(books):
	demo.seed(books, today=TODAY)
	before = frappe.db.count("GL Entry", {"company": books, "is_cancelled": 0})
	assert demo.seed(books, today=TODAY) == {"company": books, "already": True}
	assert frappe.db.count("GL Entry", {"company": books, "is_cancelled": 0}) == before


def test_unseed_cancels_every_demo_voucher_and_nothing_else(run_receipt, books):
	proposal = run_receipt("petrovis_fuel", date=TODAY.isoformat())
	real = post.post_proposal(proposal.name, ACCOUNTANT)["posted_name"]
	helpers.setup_banks(books)
	demo.seed(books, today=TODAY, allow_existing_postings=True)
	report = demo.unseed(books)
	assert report["journal_entries"] + report["purchase_invoices"] == demo.MONTHS * 8
	assert report["bank_transactions"] == 2
	assert frappe.db.get_value("Purchase Invoice", real, "docstatus") == 1, "the real posting stands"
	live = frappe.get_all("GL Entry", filters={"company": books, "is_cancelled": 0}, pluck="voucher_no")
	assert set(live) == {real}
	assert not demo.already_seeded(books)
	# …and the company can be seeded again, on the same rule as the first time.
	assert demo.seed(books, today=TODAY, allow_existing_postings=True)["vouchers"] == demo.MONTHS * 8
	assert demo.already_seeded(books)


def test_a_ledger_with_a_real_posting_is_refused(run_receipt, books):
	proposal = run_receipt("petrovis_fuel", date=TODAY.isoformat())
	post.post_proposal(proposal.name, ACCOUNTANT)
	with pytest.raises(demo.DemoRefused, match=mn.MSG_DEMO_LEDGER_NOT_EMPTY.format(company=books)):
		demo.seed(books, today=TODAY)
	assert not demo.already_seeded(books)
	# The founder's own test company, trial receipts and all: allowed when said so, in one place.
	before = frappe.db.count("GL Entry", {"company": books, "is_cancelled": 0})
	report = demo.seed(books, today=TODAY, allow_existing_postings=True)
	assert report["vouchers"] == demo.MONTHS * 8
	assert frappe.db.count("GL Entry", {"company": books, "is_cancelled": 0}) > before


def test_with_a_bank_account_two_lines_wait_and_the_statement_balance_is_printed(books):
	banks = helpers.setup_banks(books)
	report = demo.seed(books, today=TODAY)
	assert report["bank"]["bank_account"] == banks["khan"] and len(report["bank"]["transactions"]) == 2
	rows = data.bank_summary(books, TODAY)
	khan = next(r for r in rows if r["bank_account"] == banks["khan"])
	assert khan["unmatched"] == 2
	assert khan["diff"] == sum(amount for _d, amount in demo.UNMATCHED)
	# The money went through the configured bank's own GL account, so its ledger balance is
	# the demo months' net — not zero beside a statement that says otherwise.
	assert khan["ledger_balance"] > 0 and khan["statement_balance"] == khan["ledger_balance"] + khan["diff"]
	link_user(9402, "Accountant", books)
	bot = FakeBotApi()
	run(bot, message_update(9402, "/данс"))
	assert mn.CARD_RECON_UNMATCHED.format(count=2) not in bot.last_text  # that cell is the dashboard's
	assert f"| {fmt_mnt(200000)}" in bot.last_text and "d:unm" in bot.callback_datas()


def test_the_endpoint_is_for_system_managers_and_refuses_in_mongolian(books, as_user):
	email = "reader@example.com"
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Reader"}).insert(
			ignore_permissions=True
		)
	with as_user(email):
		with pytest.raises(frappe.PermissionError):
			api.seed_demo(books)
	with pytest.raises(frappe.ValidationError, match="компани алга"):
		api.seed_demo("Байхгүй ХХК")
	assert getattr(api.seed_demo, "is_whitelisted", False)
	assert api.seed_demo(books)["already"] is False
