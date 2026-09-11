"""The accountant's notes: detectors find, the model phrases, the figures are checked, the card shows.

``TODAY`` is fixed rather than the clock's, because half of the detectors reason about the day
of the month (a supplier's usual day, the month-end window) and a test that passed on the 20th
and failed on the 3rd would be describing the calendar, not the code.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import frappe

from nyabo_mn.agent import insights
from nyabo_mn.core import dates
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.telegram import api as telegram_api
from nyabo_mn.telegram import richcards
from tests.fixtures.telegram.fake_bot import FakeBotApi, link_user, message_update, run
from tests.flows import bank_helpers as helpers
from tests.flows import compliance_helpers as ch

TODAY = dt.date(2026, 9, 20)
PERIOD = dates.period_of(TODAY)
LAST = "2026-08"


def _je(company, amount, day, debit=ch.EXPENSE, credit=ch.CASH):
	doc = ch.make_je(company, amount, day, debit, credit, nyabo_primary_document_ref="Тест")
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	return doc


def _pi(company, supplier, day, amount=250000):
	doc = ch.make_pi(
		company,
		supplier,
		posting_date=day,
		bill_no=f"R-{day}",
		nyabo_primary_document_ref="Тест",
		items=[{"item_name": "Түрээс", "qty": 1, "rate": amount, "expense_account": ch.EXPENSE}],
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	return doc


class _Client:
	"""A model that answers with whatever note the test hands it, and counts the calls."""

	def __init__(self, note: str):
		self.note = note
		self.calls = 0

	def structured(self, **kwargs):
		self.calls += 1
		return SimpleNamespace(data={"note_mn": self.note, "order": []})


# --- detectors ---------------------------------------------------------------------------------------


def test_a_cost_that_jumped_and_a_cash_balance_below_zero_are_noticed(books):
	_je(books, 500000, f"{LAST}-05")
	_je(books, 1200000, f"{PERIOD}-05")  # +140% on the same account, paid from a cash box holding 0
	found = {s.kind: s for s in insights.signals(books, TODAY)}
	spike = found["expense_spike"]
	assert spike.severity == 2 and spike.facts["change_pct"] == 140
	assert spike.text == mn.INS_EXPENSE_SPIKE.format(
		account="Шатахуун", amount=fmt_mnt(1200000), previous=fmt_mnt(500000), pct=140
	)
	assert spike.action_view == "top" and spike.action_arg == PERIOD
	cash = found["cash_negative"]
	assert cash.severity == 3 and cash.facts["cash_balance"] == fmt_mnt(-1700000)
	assert [s.kind for s in insights.signals(books, TODAY)][0] == "cash_negative", "loudest first"


def test_a_supplier_paid_every_month_and_not_this_one_is_noticed_after_its_usual_day(books):
	supplier = ch.make_supplier("Монгол Пропертиз ХХК")
	for month in ("2026-06", "2026-07", "2026-08"):
		_pi(books, supplier, f"{month}-05")
	kinds = [s.kind for s in insights.signals(books, TODAY)]
	assert "recurring_missing" in kinds
	missing = next(s for s in insights.signals(books, TODAY) if s.kind == "recurring_missing")
	assert missing.facts == {"supplier": "Монгол Пропертиз ХХК", "months_seen": 3, "usual_day": 5}
	# On the 8th the usual day plus the grace has not passed: nothing to say yet.
	assert "recurring_missing" not in [s.kind for s in insights.signals(books, dt.date(2026, 9, 8))]
	# And once this month's invoice is in, nothing is missing.
	_pi(books, supplier, f"{PERIOD}-04")
	assert "recurring_missing" not in [s.kind for s in insights.signals(books, TODAY)]


def test_statement_lines_left_unmatched_for_a_week_are_noticed(books):
	banks = helpers.setup_banks(books)
	for offset, amount in ((10, 150000.0), (2, 50000.0)):
		doc = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"date": (TODAY - dt.timedelta(days=offset)).isoformat(),
				"deposit": amount,
				"withdrawal": 0.0,
				"description": "Тест",
				"reference_number": f"T-{offset}",
				"transaction_id": f"T-{offset}",
				"bank_account": banks["khan"],
				"company": books,
				"currency": "MNT",
				"status": "Pending",
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		doc.submit()
	aging = next(s for s in insights.signals(books, TODAY) if s.kind == "unmatched_aging")
	assert aging.severity == 2 and aging.facts["count"] == 2 and aging.facts["oldest_days"] == 10
	assert aging.action_view == "unm"
	assert aging.severity == 2
	assert next(s for s in insights.signals(books, TODAY + dt.timedelta(days=25))).severity == 3


def test_a_quiet_ledger_has_no_note(books):
	assert insights.signals(books, TODAY) == []
	assert insights.note_for(books, TODAY) is None


# --- the note ------------------------------------------------------------------------------------------


def test_the_models_note_is_kept_only_when_every_figure_is_the_detectors(books):
	_je(books, 500000, f"{LAST}-05")
	_je(books, 1200000, f"{PERIOD}-05")
	found = insights.signals(books, TODAY)
	honest = f"Хамгийн түрүүнд касс: {fmt_mnt(-1700000)}₮ сөрөг байна. Шатахуун {fmt_mnt(1200000)}₮ болж 140% өслөө."
	assert insights.note_is_honest(honest, found)
	invented = "Шатахуун 1 250 000₮ болж 140% өслөө."
	assert not insights.note_is_honest(invented, found)

	text, from_model = insights.narrate(books, found, client=_Client(invented))
	assert from_model is False and text == insights.deterministic_note(found)
	text, from_model = insights.narrate(books, found, client=_Client(honest))
	assert from_model is True and text == honest


def test_the_note_is_cached_on_the_signals_not_the_clock(books):
	_je(books, 500000, f"{LAST}-05")
	_je(books, 1200000, f"{PERIOD}-05")
	client = _Client(f"Касс {fmt_mnt(-1700000)}₮ сөрөг байна.")
	first = insights.note_for(books, TODAY, client=client)
	second = insights.note_for(books, TODAY, client=client)
	assert first is not None and first.from_model and first.text == second.text
	assert client.calls == 1, "the same signals get the same note without a second model call"
	_je(books, 300000, f"{PERIOD}-06")  # the cash balance moved: the signals changed
	insights.note_for(books, TODAY, client=client)
	assert client.calls == 2


def test_a_model_that_fails_leaves_the_detectors_sentences(books):
	_je(books, 500000, f"{LAST}-05")
	_je(books, 1200000, f"{PERIOD}-05")

	class Broken:
		def structured(self, **kwargs):
			raise RuntimeError("no key")

	note = insights.note_for(books, TODAY, client=Broken())
	assert note is not None and note.from_model is False
	assert note.text == insights.deterministic_note(note.signals)
	assert note.severity == 3


# --- the card and the morning push -------------------------------------------------------------------


def _fake_note(company: str) -> insights.Note:
	spike = insights.Signal(
		kind="expense_spike",
		severity=2,
		text="Шатахуун өслөө.",
		facts={},
		action_label=mn.BTN_Q_TOP_ACCOUNTS,
		action_view="top",
		action_arg=PERIOD,
	)
	return insights.Note(text="Шатахуун өслөө; кассыг шалгаарай.", signals=(spike,), from_model=True)


def test_the_dashboard_carries_the_note_and_its_buttons(books, monkeypatch):
	monkeypatch.setattr(insights, "note_for", lambda company, today=None, **kw: _fake_note(company))
	link_user(9601, "Accountant", books)
	bot = FakeBotApi()
	run(bot, message_update(9601, "/меню"))
	text = bot.last_text
	assert mn.INS_HEADING in text and "Шатахуун өслөө; кассыг шалгаарай." in text
	assert text.index(mn.INS_HEADING) < text.index(mn.CARD_YOUR_TURN), "the note comes before the checklist"
	assert f"d:top:{PERIOD}" in bot.callback_datas()
	assert f"<h5>{mn.INS_HEADING}</h5>" in bot.last_html


def test_the_morning_push_sends_once_to_the_accountant_and_only_when_it_matters(books, monkeypatch):
	settings = frappe.get_doc(
		"Nyabo Company Settings", frappe.db.exists("Nyabo Company Settings", {"company": books})
	)
	settings.accountant_telegram_id = "9602"
	settings.flags.ignore_permissions = True
	settings.save()
	monkeypatch.setattr(insights, "note_for", lambda company, today=None, **kw: _fake_note(company))
	bot = FakeBotApi()
	with telegram_api.use_bot(bot):
		first = insights.push_daily(TODAY)
		second = insights.push_daily(TODAY)
	assert first["sent"] == [books] and second["sent"] == [] and books in second["skipped"]
	assert len(bot.sent("send_rich_message")) == 1
	card = bot.sent("send_rich_message")[0]
	assert card["chat_id"] == "9602"
	assert card["text"].startswith(mn.INS_PUSH_TITLE.format(company=books))
	assert "d:home" in bot.callback_datas()
	assert frappe.db.exists("Nyabo Event", {"event_type": insights.EVENT_SENT, "company": books})

	quiet = insights.Note(text="x", signals=(insights.Signal("month_end_due", 1, "x"),), from_model=False)
	monkeypatch.setattr(insights, "note_for", lambda company, today=None, **kw: quiet)
	frappe.db.delete("Nyabo Event", {"event_type": insights.EVENT_SENT})
	with telegram_api.use_bot(bot):
		assert insights.push_daily(TODAY)["sent"] == [], "severity 1 is worth knowing, not a push"


def test_notes_card_offers_one_button_per_view():
	found = (
		insights.Signal("cash_negative", 3, "a", action_label="Гүйлгээ", action_view="tx", action_arg=PERIOD),
		insights.Signal(
			"recurring_missing", 2, "b", action_label="Гүйлгээ", action_view="tx", action_arg=PERIOD
		),
		insights.Signal("rules_blocking", 2, "c", action_label="Дүрэм", action_view="rules"),
		insights.Signal("month_end_due", 1, "d"),
	)
	buttons = richcards.signal_buttons(found)
	assert [b.data for b in buttons] == [f"d:tx:{PERIOD}", "d:rules"]
