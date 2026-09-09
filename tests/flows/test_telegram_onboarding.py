"""Onboarding /эхлэх end to end: answers land in Nyabo Company Settings."""

from __future__ import annotations

import datetime as dt
import logging

import frappe

from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps, keyboards
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
	# The first question has no step behind it, so Буцах is absent and Цуцлах is not (UX-13).
	assert bot.callback_datas() == ["o:vat:yes", "o:vat:no", "e:onb:cancel:vat"]

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
	assert bot.callback_datas() == [
		"i:NYI-00001:confirm",
		"i:NYI-00001:cancel",
		"e:onb:back:inv_confirm",
		"e:onb:skip:inv_confirm",
	]
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


def test_vat_yes_no_banks_no_inventory(company):
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
	assert mn.MSG_ONBOARDING_APPLY_PENDING not in bot.texts()  # apply_onboarding really ran
	assert mn.ONB_SUMMARY_REGIME_VAT in bot.last_text
	# The company was provisioned as a non-VAT payer; answering "тийм" makes the templates default.
	assert frappe.db.get_value("Sales Taxes and Charges Template", {"company": company}, "is_default") == 1
	assert frappe.db.get_value("Purchase Taxes and Charges Template", {"company": company}, "is_default") == 1

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
	assert bot.last_text == mn.ONB_ASK_VAT
	assert bot.callback_datas() == ["o:vat:yes", "o:vat:no", "e:onb:cancel:vat"]


def test_custom_currency_is_shown_and_can_be_removed(company):
	"""UX-11: a typed code used to be stored, never drawn, and impossible to take off."""
	link_user(9005, "Accountant", company)
	uid = 9005
	bot = FakeBotApi()
	run(bot, message_update(uid, "/эхлэх"))
	run(bot, callback_update(uid, "o:vat:no"))
	run(bot, callback_update(uid, "o:400m:yes"))
	run(bot, callback_update(uid, "o:banks:Khan_Bank"))
	run(bot, callback_update(uid, "o:banks:done"))
	run(bot, callback_update(uid, "o:cur:MNT"))

	run(bot, callback_update(uid, "o:cur:other"))
	assert bot.last_text == mn.ONB_ASK_CURRENCY_CODE
	run(bot, message_update(uid, " cny "))
	assert mn.ONB_CURRENCY_ADDED.format(currency="CNY") in bot.last_text
	labels = [b["text"] for row in bot.last_markup()["inline_keyboard"] for b in row]
	assert mn.ONB_BANK_TOGGLE_ON.format(bank="CNY") in labels
	assert "o:cur:CNY" in bot.callback_datas()

	# The same tap that adds a currency takes it away again, and the toggle stays on the
	# keyboard so it can be switched back on.
	run(bot, callback_update(uid, "o:cur:CNY"))
	markup = bot.sent("edit_message_reply_markup")[-1]["reply_markup"]
	labels = [b["text"] for row in markup["inline_keyboard"] for b in row]
	assert mn.ONB_BANK_TOGGLE_OFF.format(bank="CNY") in labels
	run(bot, callback_update(uid, "o:cur:CNY"))
	run(bot, callback_update(uid, "o:cur:done"))
	assert bot.last_text == mn.ONB_ASK_ACCOUNT_NUMBER.format(bank="Khan Bank", currency="MNT")

	# …and the code reaches the summary the accountant confirms.
	run(bot, callback_update(uid, "o:acct:skip"))
	run(bot, callback_update(uid, "o:acct:skip"))
	run(bot, callback_update(uid, "o:inv:no"))
	run(bot, message_update(uid, "Дорж"))
	run(bot, callback_update(uid, "o:micpa:skip"))
	assert "Khan Bank (MNT/CNY)" in bot.last_text


def test_custom_currency_refuses_a_code_that_is_not_three_latin_letters(company):
	"""The code goes into colon-separated callback data; only ISO-4217 shapes are accepted."""
	link_user(9006, "Accountant", company)
	uid = 9006
	bot = FakeBotApi()
	run(bot, message_update(uid, "/эхлэх"))
	run(bot, callback_update(uid, "o:vat:no"))
	run(bot, callback_update(uid, "o:400m:yes"))
	run(bot, callback_update(uid, "o:banks:Khan_Bank"))
	run(bot, callback_update(uid, "o:banks:done"))
	run(bot, callback_update(uid, "o:cur:other"))
	run(bot, message_update(uid, "юань:1"))
	assert mn.ONB_CURRENCY_CODE_INVALID in bot.last_text
	# Nothing the user typed may reach the data, and no datum grows a field of its own:
	# an escape carries at most prefix, scope, verb and step.
	assert all("юань" not in data for data in bot.callback_datas())
	assert all(len(keyboards.decode(data)) <= 4 for data in bot.callback_datas())


def test_onboarding_with_unparseable_inventory(company, monkeypatch, caplog):
	detail = "openpyxl: /tmp/upload/inventory.xlsx sheet 'Лист1' row 1 broken"

	def bad(text):
		raise ValueError(detail)

	monkeypatch.setattr(_deps, "inventory_parse_text", bad)
	link_user(9004, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9004, "/эхлэх"))
	run(bot, callback_update(9004, "o:vat:no"))
	run(bot, callback_update(9004, "o:400m:yes"))
	run(bot, callback_update(9004, "o:banks:done"))
	run(bot, callback_update(9004, "o:inv:yes"))
	with caplog.at_level(logging.ERROR, logger="frappe.nyabo"):
		run(bot, message_update(9004, "хор, зургаа, их"))
	# SEC-09: the reader gets the Mongolian instruction, never the parser's own words.
	assert bot.last_text == mn.ONB_INVENTORY_PARSE_FAILED
	assert detail not in "\n".join(bot.texts())
	# …and the detail an admin needs is in the log.
	assert "telegram.onboarding.inventory_parse_failed" in caplog.text and detail in caplog.text
	assert _state(9004) == "onb:inv_wait"


def test_onboarding_applies_bank_accounts_to_erpnext(company):
	"""The wizard's bank answers must reach ERPNext, or the next statement import has no account."""
	link_user(9101, "Owner", company)
	uid = 9101
	bot = FakeBotApi()
	run(bot, message_update(uid, "/эхлэх"))
	run(bot, callback_update(uid, "o:vat:no"))
	run(bot, callback_update(uid, "o:400m:no"))
	run(bot, callback_update(uid, "o:banks:Khan_Bank"))
	run(bot, callback_update(uid, "o:banks:done"))
	run(bot, callback_update(uid, "o:cur:MNT"))
	run(bot, callback_update(uid, "o:cur:done"))
	run(bot, message_update(uid, "5001234567"))
	run(bot, callback_update(uid, "o:inv:no"))
	run(bot, message_update(uid, "Дорж"))
	run(bot, callback_update(uid, "o:micpa:skip"))
	run(bot, callback_update(uid, "o:summary:confirm"))

	assert mn.MSG_ONBOARDING_APPLY_PENDING not in bot.texts()
	bank_accounts = frappe.get_all(
		"Bank Account", filters={"company": company}, fields=["name", "bank", "bank_account_no"]
	)
	assert len(bank_accounts) == 1
	assert bank_accounts[0]["bank"] == "Khan Bank"
	assert bank_accounts[0]["bank_account_no"] == "5001234567"
	settings = frappe.get_doc(
		"Nyabo Company Settings", frappe.db.exists("Nyabo Company Settings", {"company": company})
	)
	rows = [(r.bank, r.currency, r.erpnext_bank_account) for r in settings.bank_accounts]
	assert rows == [("Khan Bank", "MNT", bank_accounts[0]["name"])]
	assert settings.accountant_of_record_name == "Дорж"


def test_apply_onboarding_is_idempotent(company):
	from nyabo_mn.setup import provision_company as provision

	rows = [{"bank": "Khan Bank", "currency": "MNT", "account_number": "5001234567"}]
	first = provision.apply_onboarding(company, True, rows, False, "Дорж", "MICPA-1")
	second = provision.apply_onboarding(company, True, rows, False, "Дорж", "MICPA-1")
	assert first["bank_accounts"] == second["bank_accounts"]
	assert len(frappe.get_all("Bank Account", filters={"company": company})) == 1
	settings = frappe.get_doc("Nyabo Company Settings", second["settings"])
	assert len(settings.bank_accounts) == 1
	assert settings.accountant_micpa_permit == "MICPA-1"
