"""UX-13: no waiting step is a dead end — the four ways the founder got stuck, one test each.

What happened on the live bot: the inventory step of ``/эхлэх`` refused «алгасах» as an
unreadable stock line, the card carried no Cancel, no Back and no way home, and when the
step finally threw, the reply was «Уучлаарай, алдаа гарлаа. Админд мэдэгдлээ.» — which the
founder read as the bot asking an administrator to approve their transaction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import frappe
import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps, keyboards
from tests.fixtures.telegram.fake_bot import FakeBotApi, callback_update, link_user, message_update, run

TELEGRAM = Path(__file__).resolve().parents[2] / "nyabo_mn" / "telegram"


def _state(chat_id: int) -> str | None:
	return frappe.db.get_value("Nyabo Chat State", {"chat_id": str(chat_id)}, "state")


def _payload(chat_id: int) -> dict[str, Any]:
	"""What the wizard is carrying between turns, so a test can see an answer nobody gave."""
	raw = frappe.db.get_value("Nyabo Chat State", {"chat_id": str(chat_id)}, "payload_json")
	return json.loads(raw) if raw else {}


def _datas(markup: dict[str, Any] | None) -> list[str]:
	rows = (markup or {}).get("inline_keyboard") or []
	return [b.get("callback_data") for row in rows for b in row]


def _escape_datum(markup: dict[str, Any] | None, verb: str) -> str:
	"""The datum of the escape button the prompt really drew, so a test taps what a user taps."""
	drawn = [
		str(d)
		for d in _datas(markup)
		if str(d).startswith(f"{keyboards.PREFIX_ESCAPE}:") and str(d).split(":")[2] == verb
	]
	assert drawn, f"no «{verb}» button on this prompt: {_datas(markup)}"
	return drawn[0]


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
	assert "e:onb:skip:inv_wait" in _datas(bot.last_markup()), "the step must offer Алгасах"

	run(bot, callback_update(9202, "e:onb:skip:inv_wait"))
	assert _state(9202) == "onb:acc_name"
	assert mn.ONB_INVENTORY_SKIPPED in bot.texts()


def _walk_to_the_summary(bot: FakeBotApi, uid: int) -> None:
	"""From onb:acc_name to the summary card: a name, then Алгасах on the MICPA permit."""
	run(bot, message_update(uid, "Дорж"))
	run(bot, message_update(uid, "алгасах"))
	assert _state(uid) == "onb:summary"


def test_re_answering_the_stock_question_forgets_the_list_that_was_skipped(company, monkeypatch):
	"""MAJOR: the summary reported a list left for later on a company that holds no stock at all.

	``inventory_skipped`` was set by Алгасах and popped only by a list that arrived afterwards,
	so a walk that goes back to the Тийм/Үгүй question and answers Үгүй left the flag standing
	and the card said «байгаа, жагсаалт оруулаагүй» about books with no inventory in them.
	"""
	bot = _at_inventory_list(9209, company, monkeypatch)

	run(bot, callback_update(9209, "e:onb:skip:inv_wait"))
	assert _state(9209) == "onb:acc_name"
	run(bot, callback_update(9209, "e:onb:back:acc_name"))
	assert _state(9209) == "onb:inv_wait"
	run(bot, callback_update(9209, "e:onb:back:inv_wait"))
	assert _state(9209) == "onb:inv"

	run(bot, callback_update(9209, "o:inv:no"))
	assert _state(9209) == "onb:acc_name"
	assert _payload(9209).get("inventory_skipped") is None, "the question was answered afresh"
	_walk_to_the_summary(bot, 9209)

	assert mn.ONB_SUMMARY_INVENTORY_NONE in bot.last_text
	assert mn.ONB_SUMMARY_INVENTORY_SKIPPED not in bot.last_text


def test_skipping_the_stock_list_is_what_the_summary_says(company, monkeypatch):
	"""BLOCKER: the card used to report «0 бараа», i.e. a stock count that came out empty."""
	bot = _at_inventory_list(9205, company, monkeypatch)

	run(bot, callback_update(9205, "e:onb:skip:inv_wait"))
	_walk_to_the_summary(bot, 9205)

	assert mn.ONB_SUMMARY_INVENTORY_SKIPPED in bot.last_text
	assert mn.ONB_SUMMARY_INVENTORY_COUNT.format(count=0) not in bot.last_text
	assert mn.ONB_SUMMARY_INVENTORY_NONE not in bot.last_text, "the company did answer Тийм"


def test_skipping_after_a_list_was_read_does_not_report_it_as_filed(company, monkeypatch):
	"""The list was parsed and previewed, never confirmed: nothing was filed, so nothing is counted."""
	bot = _at_inventory_list(9206, company, monkeypatch)
	monkeypatch.setattr(
		_deps, "inventory_parse_text", lambda text: [{"item_name": "Цаас", "qty": 2, "rate": 1000}]
	)
	monkeypatch.setattr(_deps, "inventory_create_intake", lambda *a, **kw: "NYI-00011")
	run(bot, message_update(9206, "Цаас, 2, 1000"))
	assert _state(9206) == "onb:inv_confirm"

	run(bot, callback_update(9206, "e:onb:skip:inv_confirm"))
	_walk_to_the_summary(bot, 9206)

	assert mn.ONB_SUMMARY_INVENTORY_SKIPPED in bot.last_text
	assert mn.ONB_SUMMARY_INVENTORY_COUNT.format(count=1) not in bot.last_text


def test_the_inventory_answer_still_reaches_the_parser(company, monkeypatch):
	"""The escape check must not swallow the step's real input."""
	bot = _at_inventory_list(9203, company, monkeypatch)
	monkeypatch.setattr(
		_deps, "inventory_parse_text", lambda text: [{"item_name": "Цаас", "qty": 2, "rate": 1000}]
	)
	monkeypatch.setattr(_deps, "inventory_create_intake", lambda *a, **kw: "NYI-00009")

	run(bot, message_update(9203, "Цаас, 2, 1000"))
	assert _state(9203) == "onb:inv_confirm"


def test_a_file_is_the_answer_whatever_its_caption_says(company, monkeypatch):
	"""A workbook captioned «цуцлах» is still the stock list, not a way out."""
	bot = _at_inventory_list(9204, company, monkeypatch)
	bot.files["f-inv"] = b"PK\x03\x04 not really a workbook"
	monkeypatch.setattr(
		_deps, "inventory_parse_table", lambda content, name: [{"item_name": "Цаас", "qty": 1, "rate": 9}]
	)
	monkeypatch.setattr(_deps, "inventory_create_intake", lambda *a, **kw: "NYI-00010")

	run(
		bot,
		message_update(
			9204,
			"цуцлах",
			document={"file_id": "f-inv", "file_name": "uldegdel.xlsx", "file_size": 24},
		),
	)
	assert _state(9204) == "onb:inv_confirm"


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
	# One goodbye, not two: this line says more than the generic one (the statement was not
	# imported), so the generic one must not follow it.
	assert mn.MSG_FLOW_CANCELLED not in bot.texts()
	assert not frappe.get_all("Nyabo Bank Layout", filters={"layout_id": ["like", "custom-%"]})


def _in_the_bank_find_step(uid: int, company: str) -> FakeBotApi:
	"""The typed step of an unmatched bank line, without needing a statement behind it."""
	from nyabo_mn.telegram import state as chat_state
	from nyabo_mn.telegram.handlers import bank

	link_user(uid, "Accountant", company)
	chat_state.set_state(uid, bank.STATE_FIND, {})
	bot = FakeBotApi()
	return bot


@pytest.mark.parametrize("tapped", [False, True])
def test_leaving_the_bank_line_search_says_goodbye_once(company, tapped):
	"""MINOR: «Дараа руу шилжүүллээ» was followed by «Болилоо…», two answers to one action."""
	uid = 9295 if tapped else 9296
	bot = _in_the_bank_find_step(uid, company)

	if tapped:
		run(bot, callback_update(uid, "e:bank_find:cancel"))
	else:
		run(bot, message_update(uid, "цуцлах"))

	assert _state(uid) in (None, "")
	assert bot.texts().count(mn.MSG_BANK_LATER) == 1
	assert mn.MSG_FLOW_CANCELLED not in bot.texts()
	assert bot.sent("answer_callback_query") or not tapped


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


def test_a_cancel_on_an_inaccessible_message_is_sent_not_edited(company, monkeypatch):
	"""``InaccessibleMessage.date`` is "Always 0" — there is nothing there to edit, so we send."""
	bot = _at_inventory_list(9234, company, monkeypatch)
	bot.clear()

	run(bot, callback_update(9234, "e:onb:cancel", message_id=777, message_date=0))

	assert not bot.sent("edit_message_text")
	assert bot.last_text == mn.MSG_FLOW_CANCELLED
	assert _state(9234) in (None, "")


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


def test_a_typed_step_leaves_its_escape_row_live_and_that_tap_is_refused(company, monkeypatch):
	"""MAJOR: a step answered by typing is never edited, so its buttons stay above the next one.

	The skeptic's walk: reach onb:acc_name, type the name (the wizard moves to onb:micpa), then
	tap the [Буцах] still sitting on the earlier card. With only the flow tag in the datum it
	was indistinguishable from the open step's own button and moved the wizard from a step it
	was not drawn for.
	"""
	bot = _at_inventory_list(9207, company, monkeypatch)
	run(bot, callback_update(9207, _escape_datum(bot.last_markup(), keyboards.ESCAPE_SKIP)))
	assert _state(9207) == "onb:acc_name"
	stale_row = bot.last_markup()  # the escape row of the name prompt, still on screen

	run(bot, message_update(9207, "Дорж"))
	assert _state(9207) == "onb:micpa"
	open_row = bot.last_markup()  # the MICPA prompt, the question actually on screen
	bot.clear()

	run(bot, callback_update(9207, _escape_datum(stale_row, keyboards.ESCAPE_BACK)))
	assert _state(9207) == "onb:micpa", "a tap from a finished step must not move the open one"
	answers = bot.sent("answer_callback_query")
	assert answers and answers[-1]["text"] == mn.MSG_ESCAPE_STALE

	# …while the open step's own row still works.
	run(bot, callback_update(9207, _escape_datum(open_row, keyboards.ESCAPE_BACK)))
	assert _state(9207) == "onb:acc_name"


def test_a_card_drawn_before_the_step_rode_along_still_works(company, monkeypatch):
	"""A card lives in the chat across a deploy: ``e:onb:skip`` with no step is the old shape."""
	bot = _at_inventory_list(9208, company, monkeypatch)

	run(bot, callback_update(9208, "e:onb:skip"))
	assert _state(9208) == "onb:acc_name"
	assert mn.ONB_INVENTORY_SKIPPED in bot.texts()


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
	assert _datas(bot.last_markup()) == [
		"e:onb:back:inv_wait",
		"e:onb:skip:inv_wait",
		"e:onb:cancel:inv_wait",
	]
	# …and the way out still works from there.
	run(bot, message_update(9240, "алгасах"))
	assert _state(9240) == "onb:acc_name"


def test_a_refusal_from_the_intake_itself_keeps_the_step_and_shows_its_message(company, monkeypatch):
	"""MINOR: create_intake re-validates the rows and raises the same error from outside the guard.

	``as_rows`` re-reads the dicts the chat carried between turns, so a row the preview accepted
	and the document refuses (a qty that is not positive) raised IntakeParseError from the
	create call, which sat after the try/except and reached the router's generic apology.
	"""
	from nyabo_mn.setup.inventory_intake import IntakeParseError

	bot = _at_inventory_list(9242, company, monkeypatch)
	monkeypatch.setattr(
		_deps, "inventory_parse_text", lambda text: [{"item_name": "Хор", "qty": 0, "rate": 5}]
	)

	def refuse(*args, **kwargs):
		raise IntakeParseError(mn.MSG_INTAKE_QTY_RATE_POSITIVE.format(item="Хор"))

	monkeypatch.setattr(_deps, "inventory_create_intake", refuse)
	bot.clear()
	run(bot, message_update(9242, "Хор, 0, 5"))

	assert mn.MSG_INTAKE_QTY_RATE_POSITIVE.format(item="Хор") in bot.last_text
	assert mn.MSG_ERROR_ADMIN_NOTIFIED not in bot.texts()
	assert _state(9242) == "onb:inv_wait", "the step stands, so the list can be sent again"
	assert _datas(bot.last_markup()) == [
		"e:onb:back:inv_wait",
		"e:onb:skip:inv_wait",
		"e:onb:cancel:inv_wait",
	]


def test_a_missing_intake_module_still_reaches_the_router(company, monkeypatch):
	"""DependencyMissing keeps propagating: it is an install problem, not a bad stock list."""
	bot = _at_inventory_list(9243, company, monkeypatch)
	monkeypatch.setattr(
		_deps, "inventory_parse_text", lambda text: [{"item_name": "Хор", "qty": 1, "rate": 5}]
	)

	def missing(*args, **kwargs):
		raise _deps.DependencyMissing("nyabo_mn.setup.inventory_intake.create_intake is not available")

	monkeypatch.setattr(_deps, "inventory_create_intake", missing)
	bot.clear()
	run(bot, message_update(9243, "Хор, 1, 5"))

	sent = [kw for kw in bot.sent("send_message") if kw["text"] == mn.MSG_FEATURE_UNAVAILABLE]
	assert sent, bot.texts()
	assert _datas(sent[-1]["reply_markup"]) == ["e:err:menu"]


def test_an_empty_inventory_list_also_re_offers_the_buttons(company, monkeypatch):
	bot = _at_inventory_list(9241, company, monkeypatch)
	monkeypatch.setattr(_deps, "inventory_parse_text", lambda text: [])
	bot.clear()

	run(bot, message_update(9241, "?"))
	assert _state(9241) == "onb:inv_wait"
	assert "e:onb:cancel:inv_wait" in _datas(bot.last_markup())


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


def test_only_the_caller_that_draws_the_button_and_notifies_says_so(company):
	"""MAJOR: three of the four call sites named a «Цэс» button that was not on the message.

	``router`` is the only one that attaches ``keyboards.menu_markup()`` and calls
	``notify_admins``; the failed receipt card and the statement worker draw no keyboard and
	send nothing, so they get the variants that name /меню as a command and claim no notice.
	"""
	assert "доорх" in mn.MSG_ERROR_ADMIN_NOTIFIED and "доорх" in mn.MSG_FEATURE_UNAVAILABLE
	for text in (mn.MSG_ERROR_NO_BUTTON, mn.MSG_FEATURE_UNAVAILABLE_NO_BUTTON):
		assert "доорх" not in text and "/меню" in text
	# The sentence the founder needed is in every one of them.
	for text in (
		mn.MSG_ERROR_ADMIN_NOTIFIED,
		mn.MSG_ERROR_NO_BUTTON,
		mn.MSG_FEATURE_UNAVAILABLE_NO_BUTTON,
	):
		assert "зөвшөөрөх" in text and "гэсэн үг биш" in text

	promising = re.compile(r"mn\.(MSG_ERROR_ADMIN_NOTIFIED|MSG_FEATURE_UNAVAILABLE)\b")
	users = {
		path.name for path in TELEGRAM.rglob("*.py") if promising.search(path.read_text(encoding="utf-8"))
	}
	assert users == {"router.py"}, users


def test_a_failed_receipt_card_does_not_promise_a_button_it_has_not_got(company):
	"""The pipeline's failure path writes a Nyabo Event and a log line; it notifies nobody."""
	from nyabo_mn.telegram.handlers import receipt
	from tests.fixtures.telegram.fake_bot import make_proposal

	proposal = make_proposal(company, status="failed")
	text, markup = receipt.card_for(proposal)
	assert mn.MSG_ERROR_NO_BUTTON in text
	assert mn.MSG_ERROR_ADMIN_NOTIFIED not in text
	assert markup == keyboards.empty_markup()


def test_the_escape_on_a_failure_reaches_the_menu_and_clears_a_stuck_step(company, monkeypatch):
	bot = _at_inventory_list(9251, company, monkeypatch)
	bot.clear()

	run(bot, callback_update(9251, "e:err:menu"))
	assert _state(9251) in (None, "")
	# The error card has no state of its own, so it may close whatever is open — and says which.
	assert mn.MSG_FLOW_LEFT_NAMED.format(flow=mn.FLOW_NAMES["onb"]) in bot.texts()
	assert any(mn.MSG_MENU in text for text in bot.texts())


def test_a_menu_button_from_a_finished_step_does_not_close_todays_work(company, monkeypatch):
	"""MINOR: [Цэс] used to skip the staleness check that the other three verbs go through.

	A flow's own menu button is a button on a question; when that question is over, tapping it
	must not clear whatever the accountant has open now. Only the error card's [Цэс] is exempt,
	because a handler that failed may have left any state, or none.
	"""
	bot = _at_inventory_list(9252, company, monkeypatch)
	stale_menu = keyboards.escape_data("onb:inv_wait", keyboards.ESCAPE_MENU)
	run(bot, callback_update(9252, _escape_datum(bot.last_markup(), keyboards.ESCAPE_SKIP)))
	assert _state(9252) == "onb:acc_name"
	bot.clear()

	run(bot, callback_update(9252, stale_menu))

	assert _state(9252) == "onb:acc_name"
	answers = bot.sent("answer_callback_query")
	assert answers and answers[-1]["text"] == mn.MSG_ESCAPE_STALE
	assert not any(mn.MSG_MENU in text for text in bot.texts())

	# …while the menu button of the open step is still a way home, and names what it closed.
	run(bot, callback_update(9252, keyboards.escape_data("onb:acc_name", keyboards.ESCAPE_MENU)))
	assert _state(9252) in (None, "")
	assert mn.MSG_FLOW_LEFT_NAMED.format(flow=mn.FLOW_NAMES["onb"]) in bot.texts()


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


def _wizard_steps(uid: int, with_inventory: bool) -> list[dict[str, Any]]:
	"""The whole of ``/эхлэх``, one update per answer, through both inventory branches."""
	if with_inventory:
		tail = [
			callback_update(uid, "o:inv:yes"),
			message_update(uid, "Цаас, 2, 1000"),  # -> inv_confirm (the preview card)
			callback_update(uid, "e:onb:skip:inv_confirm"),  # -> acc_name, the list left for later
		]
	else:
		tail = [callback_update(uid, "o:inv:no")]
	return [
		message_update(uid, "/эхлэх"),
		callback_update(uid, "o:vat:no"),
		callback_update(uid, "o:400m:yes"),
		callback_update(uid, "o:banks:Khan_Bank"),
		callback_update(uid, "o:banks:done"),
		callback_update(uid, "o:cur:other"),  # -> cur_other, the typed currency code
		message_update(uid, "CNY"),
		callback_update(uid, "o:cur:done"),
		message_update(uid, "5001234567"),  # -> acct
		*tail,
		message_update(uid, "Дорж"),  # -> micpa
		message_update(uid, "12345"),  # -> summary
	]


def _walk_the_wizard(uid: int, company: str, monkeypatch, with_inventory: bool, upto: int) -> FakeBotApi:
	monkeypatch.setattr(_deps, "apply_onboarding", lambda *args: {"ok": True})
	monkeypatch.setattr(
		_deps, "inventory_parse_text", lambda text: [{"item_name": "Цаас", "qty": 2, "rate": 1000}]
	)
	monkeypatch.setattr(_deps, "inventory_create_intake", lambda *a, **kw: "NYI-09000")
	link_user(uid, "Accountant", company)
	bot = FakeBotApi()
	for update in _wizard_steps(uid, with_inventory)[: upto + 1]:
		run(bot, update)
	return bot


@pytest.mark.parametrize("with_inventory", [True, False])
def test_every_escape_button_the_wizard_draws_actually_works(company, monkeypatch, with_inventory):
	"""Tap every verb each prompt offers: a drawn button may never answer «there is no such step».

	Presence was all the old walk checked, which is how a [Буцах] on onb:acc_name shipped green
	while ``BACK_STEPS`` had no entry for it and the tap answered «this is the first step».
	"""
	uid = 9280 if with_inventory else 9285
	probe = uid + 100
	steps = _wizard_steps(uid, with_inventory)
	seen: list[str] = []
	bot = FakeBotApi()
	monkeypatch.setattr(_deps, "apply_onboarding", lambda *args: {"ok": True})
	monkeypatch.setattr(
		_deps, "inventory_parse_text", lambda text: [{"item_name": "Цаас", "qty": 2, "rate": 1000}]
	)
	monkeypatch.setattr(_deps, "inventory_create_intake", lambda *a, **kw: "NYI-09000")
	link_user(uid, "Accountant", company)
	for index, update in enumerate(steps):
		run(bot, update)
		state = _state(uid)
		if not state or not bot.last_markup():
			continue
		seen.append(state)
		offered = [d for d in _datas(bot.last_markup()) if str(d).startswith(f"{keyboards.PREFIX_ESCAPE}:")]
		assert offered, f"no way out of {state}"
		for datum in offered:
			verb = str(datum).split(":")[2]
			if verb == keyboards.ESCAPE_CANCEL:
				continue  # leaving is always allowed; it is Буцах and Алгасах that can refuse
			probe += 1
			replayed = _walk_the_wizard(probe, company, monkeypatch, with_inventory, index)
			assert _state(probe) == state, f"the replay did not reach {state}"
			replayed.clear()
			run(replayed, callback_update(probe, datum))
			refusals = (mn.MSG_STEP_NO_BACK, mn.MSG_STEP_CANNOT_SKIP, mn.MSG_ESCAPE_STALE)
			said = replayed.texts() + [
				kw.get("text") for kw in replayed.sent("answer_callback_query") if kw.get("text")
			]
			assert not [text for text in said if text in refusals], (
				f"{datum} is drawn on {state} but refuses: {said}"
			)
	assert "onb:acc_name" in seen and "onb:summary" in seen, seen
	if with_inventory:
		assert "onb:inv_wait" in seen and "onb:inv_confirm" in seen, seen


def test_back_from_the_accountant_name_returns_to_the_inventory_branch(company, monkeypatch):
	"""MAJOR: the step behind the name is the stock list when there is one, the question when not."""
	bot = _at_inventory_list(9287, company, monkeypatch)
	run(bot, callback_update(9287, _escape_datum(bot.last_markup(), keyboards.ESCAPE_SKIP)))
	assert _state(9287) == "onb:acc_name"
	back = _escape_datum(bot.last_markup(), keyboards.ESCAPE_BACK)

	run(bot, callback_update(9287, back))
	assert _state(9287) == "onb:inv_wait"
	assert bot.last_text == mn.ONB_INVENTORY_HOW

	# …and with no stock at all, back is the Тийм/Үгүй question it really came from.
	monkeypatch.setattr(_deps, "apply_onboarding", lambda *args: {"ok": True})
	link_user(9288, "Accountant", company)
	other = FakeBotApi()
	run(other, message_update(9288, "/эхлэх"))
	run(other, callback_update(9288, "o:vat:no"))
	run(other, callback_update(9288, "o:400m:yes"))
	run(other, callback_update(9288, "o:banks:done"))
	run(other, callback_update(9288, "o:inv:no"))
	assert _state(9288) == "onb:acc_name"
	run(other, callback_update(9288, _escape_datum(other.last_markup(), keyboards.ESCAPE_BACK)))
	assert _state(9288) == "onb:inv"
	assert other.last_text == mn.ONB_ASK_INVENTORY


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

	run(bot, callback_update(9291, "e:layout:skip:0"))
	assert _state(9291) == "layout:1"
	assert "e:layout:back:1" in _datas(bot.last_markup()), "the second column can re-take the first"
	run(bot, callback_update(9291, "l:1:date"))
	run(bot, callback_update(9291, "l:2:description"))
	run(bot, callback_update(9291, "l:3:amount"))

	layout = frappe.get_doc("Nyabo Bank Layout", frappe.get_all("Nyabo Bank Layout", pluck="name")[0])
	assert layout.verified == 0
	assert "Дугаар" not in layout.column_map_json


def test_skipping_every_statement_column_saves_no_layout_and_says_why(company):
	"""MAJOR: an empty mapping reads nothing, and would be re-used for that bank's format for ever.

	``save_layout`` keys the row on the header signature, so a mapping with no date and no
	amount would be found again by every later import of the same export and would send the
	admins a card asking them to verify a layout that imports zero lines.
	"""
	from nyabo_mn.telegram.handlers import statement

	link_user(9293, "Accountant", company)
	bot = FakeBotApi()
	statement.start_layout_mapping(
		bot,
		9293,
		"NYD-00004",
		{"headers": ["Огноо", "Утга", "Дүн"], "preview": [["2026-08-01", "Түлш", "50000"]]},
	)
	for index in (0, 1):
		run(bot, callback_update(9293, f"e:layout:skip:{index}"))
	assert _state(9293) == "layout:2"
	bot.clear()

	run(bot, callback_update(9293, "e:layout:skip:2"))

	assert not frappe.get_all("Nyabo Bank Layout", filters={"layout_id": ["like", "custom-%"]})
	assert _state(9293) == "layout:2", "the last question stands until the mapping can be used"
	said = " ".join(bot.texts())
	assert mn.MSG_STATEMENT_LAYOUT_NEEDS_DATE in said and mn.MSG_STATEMENT_LAYOUT_NEEDS_AMOUNT in said
	assert not [kw for kw in bot.sent("send_message") if mn.MSG_STATEMENT_ADMIN_VERIFY[:20] in kw["text"]]

	# The way out of it is an answer, not a loop: Буцах to the columns that carry the data.
	run(bot, callback_update(9293, "l:2:amount"))
	assert _state(9293) == "layout:2", "still no date column"
	run(bot, callback_update(9293, "e:layout:back:2"))
	run(bot, callback_update(9293, "e:layout:back:1"))
	assert _state(9293) == "layout:0"
	run(bot, callback_update(9293, "l:0:date"))
	run(bot, callback_update(9293, "l:1:description"))
	run(bot, callback_update(9293, "l:2:amount"))
	assert _state(9293) in (None, "")
	layouts = frappe.get_all("Nyabo Bank Layout", filters={"layout_id": ["like", "custom-%"]}, pluck="name")
	assert len(layouts) == 1
	assert "amount" in frappe.get_doc("Nyabo Bank Layout", layouts[0]).column_map_json


def test_ignoring_every_statement_column_by_button_is_refused_too(company):
	"""«Ашиглахгүй» on every column is the same empty mapping, reached without the escape row."""
	from nyabo_mn.telegram.handlers import statement

	link_user(9294, "Accountant", company)
	bot = FakeBotApi()
	statement.start_layout_mapping(bot, 9294, "NYD-00005", {"headers": ["A", "B"], "preview": [["1", "2"]]})
	run(bot, callback_update(9294, "l:0:ignore"))
	run(bot, callback_update(9294, "l:1:ignore"))

	assert not frappe.get_all("Nyabo Bank Layout", filters={"layout_id": ["like", "custom-%"]})
	assert _state(9294) == "layout:1"


def test_a_mapping_says_what_it_still_needs(site):
	"""The check itself: a date and one money column are what parse_rows reads."""
	from nyabo_mn.telegram.handlers import statement

	assert statement.missing_for_import({"date": "Огноо", "amount": "Дүн"}) == []
	assert statement.missing_for_import({"date": "Огноо", "debit": "Зарлага"}) == []
	assert statement.missing_for_import({"date": "Огноо", "credit": "Орлого"}) == []
	assert statement.missing_for_import({}) == [
		mn.MSG_STATEMENT_LAYOUT_NEEDS_DATE,
		mn.MSG_STATEMENT_LAYOUT_NEEDS_AMOUNT,
	]
	assert statement.missing_for_import({"amount": "Дүн"}) == [mn.MSG_STATEMENT_LAYOUT_NEEDS_DATE]
	assert statement.missing_for_import({"date": "Огноо", "balance": "Үлдэгдэл"}) == [
		mn.MSG_STATEMENT_LAYOUT_NEEDS_AMOUNT
	]


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

	run(bot, callback_update(9292, "e:layout:back:1"))
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
	assert _datas(keyboards.correction_text()) == ["e:correct:back:text", "e:correct:cancel:text"]
	assert _datas(keyboards.bank_find_prompt()) == ["e:bank_find:back", "e:bank_find:cancel"]
