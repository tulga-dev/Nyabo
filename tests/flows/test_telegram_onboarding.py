"""Onboarding /эхлэх end to end: answers land in Nyabo Company Settings."""

from __future__ import annotations

import datetime as dt

import frappe

from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps
from tests.fixtures.telegram.fake_bot import FakeBotApi, callback_update, link_user, message_update, run


def _state(chat_id: int) -> str | None:
	return frappe.db.get_value("Nyabo Chat State", {"chat_id": str(chat_id)}, "state")


def test_full_onboarding_stores_settings(company, monkeypatch):
	applied: list[tuple] = []
	monkeypatch.setattr(_deps, "apply_onboarding", lambda *args: applied.append(args) or {"ok": True})
	intakes: list = []
	monkeypatch.setattr(
		_deps,
		"inventory_parse_text",
		lambda text: [
			{"item_name": "Принтерийн хор", "qty": 5, "rate": 45000},
			{"item_name": "Цаас", "qty": 10, "rate": 12000},
		],
	)
	monkeypatch.setattr(
		_deps,
		"inventory_create_intake",
		lambda company, items, source, user: intakes.append((company, items, source, user)) or "NYI-00001",
	)
	posted: list = []
	monkeypatch.setattr(
		_deps,
		"inventory_post_intake",
		lambda name, user: posted.append((name, user)) or {"created": ["MAT-STE-2026-00001"]},
	)

	link_user(9001, "Accountant", company)
	uid = 9001
	bot = FakeBotApi()
	run(bot, message_update(uid, "/эхлэх"))
	assert _state(uid) == "onb:vat"
	assert mn.ONB_ASK_VAT in bot.texts()
	assert bot.callback_datas() == ["o:vat:yes", "o:vat:no"]

	run(bot, callback_update(uid, "o:vat:no"))
	assert mn.ONB_VAT_NO_NOTE in bot.texts()
	assert _state(uid) == "onb:400m"
	run(bot, callback_update(uid, "o:400m:yes"))
	assert _state(uid) == "onb:banks"
	assert "o:banks:Khan_Bank" in bot.callback_datas() and "o:banks:done" in bot.callback_datas()

	run(bot, callback_update(uid, "o:banks:Khan_Bank"))
	run(bot, callback_update(uid, "o:banks:TDB"))
	run(bot, callback_update(uid, "o:banks:TDB"))  # toggle off again
	markup = bot.sent("edit_message_reply_markup")[-1]["reply_markup"]
	labels = [b["text"] for row in markup["inline_keyboard"] for b in row]
	assert mn.ONB_BANK_TOGGLE_ON.format(bank="Khan Bank") in labels
	assert mn.ONB_BANK_TOGGLE_OFF.format(bank="TDB") in labels
	run(bot, callback_update(uid, "o:banks:done"))
	assert _state(uid) == "onb:cur"
	assert mn.ONB_ASK_CURRENCIES.format(bank="Khan Bank") in bot.last_text

	run(bot, callback_update(uid, "o:cur:MNT"))
	run(bot, callback_update(uid, "o:cur:USD"))
	run(bot, callback_update(uid, "o:cur:done"))
	assert _state(uid) == "onb:acct"
	assert bot.last_text == mn.ONB_ASK_ACCOUNT_NUMBER.format(bank="Khan Bank", currency="MNT")
	run(bot, message_update(uid, "5001234567"))
	assert bot.last_text == mn.ONB_ASK_ACCOUNT_NUMBER.format(bank="Khan Bank", currency="USD")
	run(bot, callback_update(uid, "o:acct:skip"))
	assert _state(uid) == "onb:inv"

	run(bot, callback_update(uid, "o:inv:yes"))
	assert _state(uid) == "onb:inv_wait" and bot.last_text == mn.ONB_INVENTORY_HOW
	run(bot, message_update(uid, "Принтерийн хор, 5, 45000\nЦаас, 10, 12000"))
	assert intakes and intakes[0][0] == company and intakes[0][2] == "text"
	assert bot.last_text == mn.ONB_INVENTORY_PARSED.format(count=2, total=fmt_mnt(345000))
	assert bot.callback_datas() == ["i:NYI-00001:confirm", "i:NYI-00001:cancel"]
	run(bot, callback_update(uid, "i:NYI-00001:confirm"))
	assert posted == [("NYI-00001", "tg-9001@nyabo.local")]
	assert mn.ONB_INVENTORY_POSTED.format(docs="MAT-STE-2026-00001") in bot.texts()
	assert _state(uid) == "onb:acc_name"

	run(bot, message_update(uid, "Сарантуяа"))
	assert _state(uid) == "onb:micpa"
	run(bot, message_update(uid, "MICPA-778"))
	assert _state(uid) == "onb:summary"
	assert mn.ONB_CONFIRM_SUMMARY in bot.last_text
	run(bot, callback_update(uid, "o:summary:confirm"))
	assert _state(uid) in (None, "")

	settings = frappe.get_doc(
		"Nyabo Company Settings", frappe.db.exists("Nyabo Company Settings", {"company": company})
	)
	assert settings.onboarding_completed == 1
	assert settings.expects_under_400m_2027 == 1
	assert settings.has_inventory == 1
	assert settings.accountant_of_record_name == "Сарантуяа"
	assert settings.accountant_micpa_permit == "MICPA-778"
	regimes = [(r.regime, r.effective_from) for r in settings.regimes]
	assert regimes == [("simplified_1pct", dt.date(dt.date.today().year, 1, 1))]
	banks = [(r.bank, r.currency, r.account_number) for r in settings.bank_accounts]
	assert banks == [("Khan Bank", "MNT", "5001234567"), ("Khan Bank", "USD", "")]
	assert applied == [
		(
			company,
			False,
			[
				{"bank": "Khan Bank", "currency": "MNT", "account_number": "5001234567"},
				{"bank": "Khan Bank", "currency": "USD", "account_number": ""},
			],
			True,
			"Сарантуяа",
			"MICPA-778",
		)
	]
	summary = bot.last_text
	assert mn.ONB_SUMMARY_REGIME_SIMPLIFIED in summary and "Khan Bank (MNT/USD)" in summary
	assert "Сарантуяа (MICPA-778)" in summary


def test_vat_yes_no_banks_no_inventory_without_setup_module(company):
	link_user(9002, "Owner", company)
	uid = 9002
	bot = FakeBotApi()
	run(bot, message_update(uid, "/эхлэх"))
	run(bot, callback_update(uid, "o:vat:yes"))
	assert mn.ONB_VAT_YES_NOTE in bot.texts()
	run(bot, callback_update(uid, "o:400m:no"))
	run(bot, callback_update(uid, "o:banks:done"))
	assert _state(uid) == "onb:inv"
	run(bot, callback_update(uid, "o:inv:no"))
	run(bot, message_update(uid, "Дорж"))
	run(bot, callback_update(uid, "o:micpa:skip"))
	run(bot, callback_update(uid, "o:summary:confirm"))
	settings = frappe.get_doc(
		"Nyabo Company Settings", frappe.db.exists("Nyabo Company Settings", {"company": company})
	)
	assert settings.onboarding_completed == 1 and settings.has_inventory == 0
	assert [r.regime for r in settings.regimes] == ["vat_payer"]
	assert settings.bank_accounts == []
	assert mn.MSG_ONBOARDING_APPLY_PENDING in bot.texts()  # apply_onboarding not present in this checkout
	assert mn.ONB_SUMMARY_REGIME_VAT in bot.last_text

	bot.clear()
	run(bot, message_update(uid, "/эхлэх"))
	assert bot.last_text == mn.MSG_ONBOARDING_ALREADY_DONE
	run(bot, message_update(uid, "/эхлэх дахин"))
	assert _state(uid) == "onb:vat"
	run(bot, callback_update(uid, "o:summary:cancel"))  # stale step for the open state is ignored
	assert _state(uid) == "onb:vat"
	run(bot, message_update(uid, "/меню"))  # a command abandons the conversation
	assert _state(uid) in (None, "")


def test_text_during_button_step_repeats_question(company):
	link_user(9003, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9003, "/эхлэх"))
	bot.clear()
	run(bot, message_update(9003, "тийм"))
	assert bot.last_text == mn.ONB_ASK_VAT and bot.callback_datas() == ["o:vat:yes", "o:vat:no"]


def test_onboarding_with_unparseable_inventory(company, monkeypatch):
	def bad(text):
		raise ValueError("мөр 1: дүн уншигдсангүй")

	monkeypatch.setattr(_deps, "inventory_parse_text", bad)
	link_user(9004, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9004, "/эхлэх"))
	run(bot, callback_update(9004, "o:vat:no"))
	run(bot, callback_update(9004, "o:400m:yes"))
	run(bot, callback_update(9004, "o:banks:done"))
	run(bot, callback_update(9004, "o:inv:yes"))
	run(bot, message_update(9004, "хор, зургаа, их"))
	assert bot.last_text == mn.ONB_INVENTORY_PARSE_ERROR.format(error="мөр 1: дүн уншигдсангүй")
	assert _state(9004) == "onb:inv_wait"
