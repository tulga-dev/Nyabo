"""UX-13: no waiting step is a dead end — the four ways the founder got stuck, one test each.

What happened on the live bot: the inventory step of ``/эхлэх`` refused «алгасах» as an
unreadable stock line, the card carried no Cancel, no Back and no way home, and when the
step finally threw, the reply was «Уучлаарай, алдаа гарлаа. Админд мэдэгдлээ.» — which the
founder read as the bot asking an administrator to approve their transaction.
"""

from __future__ import annotations

from typing import Any

import frappe
import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps, keyboards
from tests.fixtures.telegram.fake_bot import FakeBotApi, callback_update, link_user, message_update, run


def _state(chat_id: int) -> str | None:
	return frappe.db.get_value("Nyabo Chat State", {"chat_id": str(chat_id)}, "state")


def _datas(markup: dict[str, Any] | None) -> list[str]:
	rows = (markup or {}).get("inline_keyboard") or []
	return [b.get("callback_data") for row in rows for b in row]


def _at_inventory_list(uid: int, company: str, monkeypatch: pytest.MonkeyPatch) -> FakeBotApi:
	"""Drive onboarding to the step the founder was trapped in: «send me your stock list»."""
	monkeypatch.setattr(_deps, "apply_onboarding", lambda *args: {"ok": True})
	link_user(uid, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(uid, "/эхлэх"))
	run(bot, callback_update(uid, "o:vat:no"))
	run(bot, callback_update(uid, "o:400m:yes"))
	run(bot, callback_update(uid, "o:banks:done"))
	run(bot, callback_update(uid, "o:inv:yes"))
	assert _state(uid) == "onb:inv_wait"
	return bot


# --- 1. «алгасах» in the inventory step skips it and the flow moves on -----------------------------


def test_typing_skip_in_the_inventory_step_advances_the_wizard(company, monkeypatch):
	"""The founder's exact keystroke. It used to reach the stock-list parser and be refused."""
	bot = _at_inventory_list(9201, company, monkeypatch)
	parsed: list[str] = []
	monkeypatch.setattr(_deps, "inventory_parse_text", lambda text: parsed.append(text) or [])

	bot.clear()
	run(bot, message_update(9201, "алгасах"))

	assert parsed == [], "«алгасах» must never reach the step's own parser"
	assert mn.ONB_INVENTORY_SKIPPED in bot.texts()
	assert _state(9201) == "onb:acc_name"
	assert bot.last_text == mn.ONB_ASK_ACCOUNTANT_NAME


def test_tapping_skip_in_the_inventory_step_does_the_same(company, monkeypatch):
	bot = _at_inventory_list(9202, company, monkeypatch)
	assert "e:onb:skip" in _datas(bot.last_markup()), "the optional step must offer Алгасах"

	run(bot, callback_update(9202, "e:onb:skip"))
	assert _state(9202) == "onb:acc_name"
	assert mn.ONB_INVENTORY_SKIPPED in bot.texts()


def test_the_inventory_answer_still_reaches_the_parser(company, monkeypatch):
	"""The escape check must not swallow the step's real input."""
	bot = _at_inventory_list(9203, company, monkeypatch)
	monkeypatch.setattr(
		_deps, "inventory_parse_text", lambda text: [{"item_name": "Цаас", "qty": 2, "rate": 1000}]
	)
	monkeypatch.setattr(_deps, "inventory_create_intake", lambda *a: "NYI-00009")

	run(bot, message_update(9203, "Цаас, 2, 1000"))
	assert _state(9203) == "onb:inv_confirm"


# --- 2. «цуцлах» leaves any waiting state, and says so in Mongolian --------------------------------


@pytest.mark.parametrize("word", ["цуцлах", "болих уу", "гарах", "/cancel"])
def test_typing_cancel_leaves_the_wizard(company, monkeypatch, word):
	uid = 9210 + len(word)
	bot = _at_inventory_list(uid, company, monkeypatch)
	bot.clear()
	run(bot, message_update(uid, word))
	assert _state(uid) in (None, "")
	assert mn.MSG_FLOW_CANCELLED in bot.texts()


def test_typing_cancel_leaves_the_column_mapping_without_saving_a_layout(company):
	"""CORE-08: nothing may be imported on a half-made mapping, so leaving one is always safe."""
	from nyabo_mn.telegram.handlers import statement

	link_user(9230, "Accountant", company)
	bot = FakeBotApi()
	statement.start_layout_mapping(
		bot,
		9230,
		"NYD-00001",
		{"headers": ["Огноо", "Утга", "Дүн"], "preview": [["2026-08-01", "Түлш", "50000"]]},
	)
	assert _state(9230) == "layout:0"
	bot.clear()

	run(bot, message_update(9230, "цуцлах"))
	assert _state(9230) in (None, "")
	assert mn.MSG_STATEMENT_LAYOUT_CANCELLED in bot.texts()
	assert not frappe.get_all("Nyabo Bank Layout", filters={"layout_id": ["like", "custom-%"]})


def test_cancel_with_nothing_open_says_so_instead_of_answering_as_a_question(company):
	link_user(9231, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9231, "цуцлах"))
	assert bot.last_text == mn.MSG_FLOW_NOTHING_TO_CANCEL


def test_a_tapped_cancel_retires_the_prompt_in_place(company, monkeypatch):
	"""Editing beats a new message: the answered prompt keeps its place and its shape.

	Bot API 10.3 DisabledButtons are what keep the shape — the rows stay, inert, so the card
	still reads as the question that was walked away from.
	"""
	bot = _at_inventory_list(9232, company, monkeypatch)
	prompt = bot.last_markup()
	bot.clear()

	run(bot, callback_update(9232, "e:onb:cancel", message_id=555, reply_markup=prompt))

	edits = bot.sent("edit_message_text")
	assert edits and edits[-1]["message_id"] == 555
	assert edits[-1]["text"] == mn.MSG_FLOW_CANCELLED
	buttons = [b for row in edits[-1]["reply_markup"]["inline_keyboard"] for b in row]
	assert buttons and all(b["disabled"] == {} for b in buttons)
	assert all("callback_data" not in b for b in buttons)
	assert _state(9232) in (None, "")
	assert bot.sent("answer_callback_query"), "the spinner must be stopped"


def test_a_cancel_tapped_on_a_card_from_a_finished_step_is_refused(company, monkeypatch):
	"""A stale tap must not take down whatever the accountant started since."""
	bot = _at_inventory_list(9233, company, monkeypatch)
	run(bot, message_update(9233, "алгасах"))  # the wizard has moved on to the accountant's name
	assert _state(9233) == "onb:acc_name"
	bot.clear()

	run(bot, callback_update(9233, "e:layout:cancel"))
	assert _state(9233) == "onb:acc_name"
	answers = bot.sent("answer_callback_query")
	assert answers and answers[-1]["text"] == mn.MSG_ESCAPE_STALE


# --- 3. a parse failure re-offers the buttons and keeps the user in the step -----------------------


def test_an_unreadable_inventory_line_keeps_the_step_and_re_offers_the_buttons(company, monkeypatch, caplog):
	"""What the founder hit: the bot said it could not read the line and left no way to answer."""
	import logging

	bot = _at_inventory_list(9240, company, monkeypatch)

	def unreadable(text):
		raise ValueError("intake: 1-р мөрийг уншиж чадсангүй")

	monkeypatch.setattr(_deps, "inventory_parse_text", unreadable)
	bot.clear()
	with caplog.at_level(logging.ERROR, logger="frappe.nyabo"):
		run(bot, message_update(9240, "хор, зургаа, их"))

	assert bot.last_text == mn.ONB_INVENTORY_PARSE_FAILED
	assert "нэр, тоо, үнэ" in bot.last_text, "the step must say what shape it wanted"
	assert _state(9240) == "onb:inv_wait", "the step stands, so the answer can be given again"
	assert _datas(bot.last_markup()) == ["e:onb:back", "e:onb:skip", "e:onb:cancel"]
	# …and the way out still works from there.
	run(bot, message_update(9240, "алгасах"))
	assert _state(9240) == "onb:acc_name"


def test_an_empty_inventory_list_also_re_offers_the_buttons(company, monkeypatch):
	bot = _at_inventory_list(9241, company, monkeypatch)
	monkeypatch.setattr(_deps, "inventory_parse_text", lambda text: [])
	bot.clear()

	run(bot, message_update(9241, "?"))
	assert _state(9241) == "onb:inv_wait"
	assert "e:onb:cancel" in _datas(bot.last_markup())


# --- 4. the router's failure path attaches an escape ----------------------------------------------


def test_a_handler_failure_answers_with_a_way_out_and_promises_no_approval(company, monkeypatch):
	from nyabo_mn.telegram.handlers import menu

	def boom(ctx):
		raise RuntimeError("nyabo test failure")

	monkeypatch.setattr(menu, "handle_menu", boom)
	link_user(9250, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9250, "/меню"))

	apology = [text for text in bot.texts() if text == mn.MSG_ERROR_ADMIN_NOTIFIED]
	assert apology, bot.texts()
	assert "зөвшөөрөх" in mn.MSG_ERROR_ADMIN_NOTIFIED and "гэсэн үг биш" in mn.MSG_ERROR_ADMIN_NOTIFIED
	sent = [kw for kw in bot.sent("send_message") if kw["text"] == mn.MSG_ERROR_ADMIN_NOTIFIED]
	assert _datas(sent[-1]["reply_markup"]) == ["e:err:menu"]


def test_the_escape_on_a_failure_reaches_the_menu_and_clears_a_stuck_step(company, monkeypatch):
	bot = _at_inventory_list(9251, company, monkeypatch)
	bot.clear()

	run(bot, callback_update(9251, "e:err:menu"))
	assert _state(9251) in (None, "")
	assert mn.MSG_FLOW_LEFT_FOR_COMMAND in bot.texts()
	assert any(mn.MSG_MENU in text for text in bot.texts())


# --- 5. the menu, and the commands that reach it --------------------------------------------------


def test_a_command_mid_flow_says_the_flow_was_left(company, monkeypatch):
	"""A command has always abandoned the conversation; it used to do it silently."""
	bot = _at_inventory_list(9260, company, monkeypatch)
	bot.clear()

	run(bot, message_update(9260, "/цэс"))
	assert _state(9260) in (None, "")
	assert mn.MSG_FLOW_LEFT_FOR_COMMAND in bot.texts()
	assert any(mn.MSG_MENU in text for text in bot.texts())


def test_the_word_menu_goes_home_too(company, monkeypatch):
	bot = _at_inventory_list(9261, company, monkeypatch)
	bot.clear()
	run(bot, message_update(9261, "цэс"))
	assert _state(9261) in (None, "")
	assert any(mn.MSG_MENU in text for text in bot.texts())


def test_the_menu_names_the_way_out_and_telegram_is_told_about_cancel(site):
	from nyabo_mn.telegram import commands, router

	assert "/цуцлах" in mn.MSG_MENU
	assert "cancel" in commands.MENU_COMMANDS
	assert router.is_routable("/cancel") and "/cancel" not in router._commands()
	bot = FakeBotApi()
	commands.setup_commands(bot=bot)
	registered = {c["command"] for c in bot.sent("set_my_commands")[0]["commands"]}
	assert "cancel" in registered


# --- 6. Буцах, where there is a step behind ------------------------------------------------------


def test_back_returns_to_the_previous_question(company, monkeypatch):
	bot = _at_inventory_list(9270, company, monkeypatch)
	bot.clear()

	run(bot, callback_update(9270, "e:onb:back"))
	assert _state(9270) == "onb:inv"
	assert bot.last_text == mn.ONB_ASK_INVENTORY

	run(bot, message_update(9270, "буцах"))
	assert _state(9270) == "onb:banks"
	assert bot.last_text == mn.ONB_ASK_BANKS


def test_back_on_the_first_question_says_so_and_leaves_the_step_standing(company, monkeypatch):
	monkeypatch.setattr(_deps, "apply_onboarding", lambda *args: {"ok": True})
	link_user(9271, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9271, "/эхлэх"))
	assert _state(9271) == "onb:vat"
	assert "e:onb:back" not in _datas(bot.last_markup()), "nothing to go back to"
	bot.clear()

	run(bot, message_update(9271, "буцах"))
	assert bot.last_text == mn.MSG_STEP_NO_BACK
	assert _state(9271) == "onb:vat"


def test_a_step_that_cannot_be_skipped_says_so_and_stays(company, monkeypatch):
	monkeypatch.setattr(_deps, "apply_onboarding", lambda *args: {"ok": True})
	link_user(9272, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9272, "/эхлэх"))
	bot.clear()

	run(bot, message_update(9272, "алгасах"))
	assert bot.last_text == mn.MSG_STEP_CANNOT_SKIP
	assert _state(9272) == "onb:vat", "the VAT regime has no default worth guessing"


# --- 7. every waiting prompt carries a way out ----------------------------------------------------


def test_every_prompt_in_the_wizard_offers_an_escape(company, monkeypatch):
	"""Walk the whole of /эхлэх and check that no message with a keyboard is a dead end."""
	monkeypatch.setattr(_deps, "apply_onboarding", lambda *args: {"ok": True})
	link_user(9280, "Accountant", company)
	bot = FakeBotApi()
	for update in (
		message_update(9280, "/эхлэх"),
		callback_update(9280, "o:vat:no"),
		callback_update(9280, "o:400m:yes"),
		callback_update(9280, "o:banks:Khan_Bank"),
		callback_update(9280, "o:banks:done"),
		callback_update(9280, "o:cur:MNT"),
		callback_update(9280, "o:cur:done"),
		message_update(9280, "5001234567"),
		callback_update(9280, "o:inv:no"),
		message_update(9280, "Дорж"),
	):
		run(bot, update)
		if _state(9280) and bot.last_markup():
			assert any(
				str(data).startswith(f"{keyboards.PREFIX_ESCAPE}:") for data in _datas(bot.last_markup())
			), f"no way out of {_state(9280)}"


def test_leaving_the_account_search_gives_the_card_its_own_buttons_back(company, monkeypatch):
	"""Otherwise the card is left wearing the account chooser and can no longer be approved."""
	from tests.fixtures.telegram.fake_bot import make_proposal

	monkeypatch.setattr(_deps, "top_accounts", lambda company, n=6: [("6210", "Шатахуун")])
	proposal = make_proposal(company)
	link_user(9290, "Accountant", company)
	bot = FakeBotApi()
	run(bot, callback_update(9290, f"p:{proposal.name}:ch"))
	run(bot, callback_update(9290, f"p:{proposal.name}:acc:more"))
	assert _state(9290) == "acc_search"
	assert _datas(bot.last_markup()) == ["e:acc_search:back", "e:acc_search:cancel"]
	bot.clear()

	run(bot, message_update(9290, "цуцлах"))
	assert _state(9290) in (None, "")
	restored = bot.sent("edit_message_reply_markup")[-1]["reply_markup"]
	assert _datas(restored) == [
		f"p:{proposal.name}:ap",
		f"p:{proposal.name}:ch",
		f"p:{proposal.name}:rj",
	]


def test_skipping_a_statement_column_marks_it_unused_and_moves_on(company):
	"""«Ашиглахгүй» is already one of the roles, so Алгасах is simply that answer."""
	from nyabo_mn.telegram.handlers import statement

	link_user(9291, "Accountant", company)
	bot = FakeBotApi()
	statement.start_layout_mapping(
		bot,
		9291,
		"NYD-00002",
		{"headers": ["Дугаар", "Огноо", "Утга", "Дүн"], "preview": [["1", "2026-08-01", "Түлш", "5"]]},
	)
	assert _state(9291) == "layout:0"

	run(bot, callback_update(9291, "e:layout:skip"))
	assert _state(9291) == "layout:1"
	assert "e:layout:back" in _datas(bot.last_markup()), "the second column can re-take the first"
	run(bot, callback_update(9291, "l:1:date"))
	run(bot, callback_update(9291, "l:2:description"))
	run(bot, callback_update(9291, "l:3:amount"))

	layout = frappe.get_doc("Nyabo Bank Layout", frappe.get_all("Nyabo Bank Layout", pluck="name")[0])
	assert layout.verified == 0
	assert "Дугаар" not in layout.column_map_json


def test_going_back_a_statement_column_forgets_the_answer_it_re_asks(company):
	"""Otherwise the column keeps the role it was given and Буцах changes nothing."""
	from nyabo_mn.telegram.handlers import statement

	link_user(9292, "Accountant", company)
	bot = FakeBotApi()
	statement.start_layout_mapping(
		bot,
		9292,
		"NYD-00003",
		{"headers": ["Огноо", "Утга", "Дүн"], "preview": [["2026-08-01", "Түлш", "5"]]},
	)
	run(bot, callback_update(9292, "l:0:reference"))  # the wrong role, on purpose
	assert _state(9292) == "layout:1"

	run(bot, callback_update(9292, "e:layout:back"))
	assert _state(9292) == "layout:0"
	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Огноо")
	run(bot, callback_update(9292, "l:0:date"))
	run(bot, callback_update(9292, "l:1:description"))
	run(bot, callback_update(9292, "l:2:amount"))

	layout = frappe.get_doc("Nyabo Bank Layout", frappe.get_all("Nyabo Bank Layout", pluck="name")[0])
	assert "reference" not in layout.column_map_json


def test_the_free_text_steps_outside_onboarding_offer_an_escape_too(company):
	"""The account search, the rejection reason, the correction text and the bank-line search."""
	assert _datas(keyboards.account_search_prompt()) == ["e:acc_search:back", "e:acc_search:cancel"]
	assert _datas(keyboards.reject_text_prompt()) == ["e:reject_text:back", "e:reject_text:cancel"]
	assert _datas(keyboards.correction_text()) == ["e:correct:back", "e:correct:cancel"]
	assert _datas(keyboards.bank_find_prompt()) == ["e:bank_find:back", "e:bank_find:cancel"]
