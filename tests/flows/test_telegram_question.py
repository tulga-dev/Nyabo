"""The question card: what it says while it works, the buttons under it, and who may ask (§5.7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import frappe
import pytest

from nyabo_mn.agent import post, questions
from nyabo_mn.config import get_settings
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps, cards, context, keyboards
from nyabo_mn.telegram import state as chat_state
from nyabo_mn.telegram.handlers import question
from tests.fixtures.telegram.fake_bot import FakeBotApi, callback_update, link_user, message_update, run
from tests.flows.conftest import ACCOUNTANT

SPEND = questions.QUERY_SHORT["spend_by_account"]
LEDGER = questions.QUERY_SHORT["account_entries"]


def _reply(text: str, *follow_ups: questions.FollowUp, memory: dict | None = None) -> questions.Reply:
	return questions.Reply(text=text, follow_ups=follow_ups, memory=memory, subject="6210 · 2026 оны 9-р сар")


def _spend_reply(memory: dict | None = None) -> questions.Reply:
	return _reply(
		"2026 оны 9-р сар: 6210 - Шатахуун - TST 77 272.73₮",
		questions.FollowUp(
			SPEND, mn.BTN_Q_PREV_PERIOD.format(period="2026 оны 8-р сар"), ("6210", "2026-08")
		),
		questions.FollowUp(LEDGER, mn.BTN_Q_EXPLAIN, ("6210", "2026-09")),
		memory=memory,
	)


def _memory(company: str, *, minutes_old: int = 0, **subject: str) -> dict:
	"""A memory as ``questions.remember`` would have just written it.

	Stamped against the clock rather than a fixed string, because the reads of this memory go
	through ``questions.recall`` and a fixed timestamp is stale within the hour — which is the
	TTL doing its job, not a fixture that still describes the flow.
	"""
	at = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
	return {
		"v": questions.MEMORY_VERSION,
		"company": company,
		"at": at.isoformat(timespec="seconds"),
		"question": "Шатахуунд хэд зарцуулсан бэ?",
		"query_kind": "spend_by_account",
		"subject": subject or {"account_code": "6210", "period": "2026-09"},
	}


# --- the answer card ---------------------------------------------------------------------------------


def test_the_bot_says_it_is_working_and_offers_the_next_read(company, monkeypatch):
	asked: list = []
	monkeypatch.setattr(
		_deps,
		"answer_question",
		lambda user, comp, text, memory=None, on_turn=None: (
			asked.append((comp, text, memory)) or _spend_reply(memory=_memory(comp))
		),
	)
	link_user(9001, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9001, "Шатахуунд хэд зарцуулсан бэ?"))

	assert bot.sent("send_chat_action")[0]["action"] == "typing"
	assert asked[0][0] == company and asked[0][2] == {}
	assert bot.last_text.endswith(mn.MSG_QUESTION_SUBJECT.format(subject="6210 · 2026 оны 9-р сар"))
	assert bot.callback_datas() == [f"q:{SPEND}:6210:2026-08", f"q:{LEDGER}:6210:2026-09"]
	# The memory is stored without opening a conversation step: the next free text is a
	# question again, not an answer to something.
	assert chat_state.get_state(9001) == (None, {})
	assert chat_state.get_question_memory(9001)["subject"] == {"account_code": "6210", "period": "2026-09"}


def test_the_next_question_is_answered_in_the_context_of_the_last(company, monkeypatch):
	seen: list = []

	def _answer(user, comp, text, memory=None, on_turn=None):
		seen.append(memory)
		return _spend_reply(memory=_memory(comp))

	monkeypatch.setattr(_deps, "answer_question", _answer)
	link_user(9002, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9002, "Шатахуунд хэд зарцуулсан бэ?"))
	run(bot, message_update(9002, "мөн өнгөрсөн сард?"))
	assert seen[0] == {}
	assert seen[1]["subject"] == {"account_code": "6210", "period": "2026-09"}
	assert seen[1]["question"] == "Шатахуунд хэд зарцуулсан бэ?"


def test_an_open_flow_takes_the_question_memory_with_it(company, monkeypatch):
	"""Leaving a question for a receipt (or any step) ends the exchange the memory belonged to."""
	monkeypatch.setattr(
		_deps,
		"answer_question",
		lambda user, comp, text, memory=None, on_turn=None: _spend_reply(memory=_memory(comp)),
	)
	link_user(9003, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9003, "Шатахуунд хэд зарцуулсан бэ?"))
	assert chat_state.get_question_memory(9003)
	chat_state.set_state(9003, "onb:banks", {"banks": []})
	assert chat_state.get_question_memory(9003) == {}


def test_the_typing_bubble_is_re_sent_around_every_model_turn(company, monkeypatch):
	"""MINOR: Telegram clears the status after about five seconds; this answer takes five turns.

	One action at the start left the user watching nothing while the question held the short
	queue. The beat is sent between model turns — see ``question._typing`` for why the work
	stays on the short queue rather than moving to long.
	"""
	turns = 3

	def _answer(user, comp, text, memory=None, on_turn=None):
		assert on_turn is not None, "the answerer is given something to beat with"
		for _ in range(turns):
			on_turn()
		return _spend_reply(memory=_memory(comp))

	monkeypatch.setattr(_deps, "answer_question", _answer)
	link_user(9015, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9015, "Шатахуунд хэд зарцуулсан бэ?"))

	actions = bot.sent("send_chat_action")
	assert len(actions) == turns + 1, "one before the call, then one per model turn"
	assert {a["action"] for a in actions} == {"typing"}
	assert bot.last_text.startswith("2026 оны 9-р сар")


def test_a_bot_that_cannot_send_the_action_still_answers(company, monkeypatch):
	"""A missing typing bubble must never cost the answer, mid-loop as well as at the start."""

	def _answer(user, comp, text, memory=None, on_turn=None):
		on_turn()
		return _spend_reply(memory=_memory(comp))

	monkeypatch.setattr(_deps, "answer_question", _answer)
	link_user(9016, "Accountant", company)
	bot = FakeBotApi()
	monkeypatch.setattr(bot, "send_chat_action", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
	run(bot, message_update(9016, "Шатахуунд хэд зарцуулсан бэ?"))
	assert bot.last_text.startswith("2026 оны 9-р сар")


# --- the buttons -------------------------------------------------------------------------------------


def test_a_follow_up_button_re_reads_the_ledger_and_edits_the_card(run_receipt, books):
	"""No model in the loop: the tap runs the handler, so the figure is the books' own."""
	proposal = run_receipt("petrovis_fuel")
	post.post_proposal(proposal.name, ACCOUNTANT)
	link_user(9004, "Accountant", books)
	bot = FakeBotApi()
	before = frappe.db.count("Nyabo LLM Call")
	outcome = run(bot, callback_update(9004, f"q:{SPEND}:6210:2026-09", message_id=555))

	assert bot.sent("answer_callback_query"), "the spinner is stopped before the ledger is read"
	edit = bot.sent("edit_message_text")[-1]
	assert edit["message_id"] == 555 and fmt_mnt("77272.73") in edit["text"]
	assert edit["text"].endswith(mn.MSG_QUESTION_SUBJECT.format(subject="6210 · 2026 оны 9-р сар"))
	assert frappe.db.count("Nyabo LLM Call") == before
	assert outcome["result"]["buttons"] == [SPEND, LEDGER]
	# and the card it just drew offers the month before, which is what it says it does
	assert f"q:{SPEND}:6210:2026-08" in bot.callback_datas()


def test_the_breakdown_button_shows_the_entries_behind_the_figure(run_receipt, books):
	proposal = run_receipt("petrovis_fuel")
	posted = post.post_proposal(proposal.name, ACCOUNTANT)
	link_user(9005, "Accountant", books)
	bot = FakeBotApi()
	run(bot, callback_update(9005, f"q:{LEDGER}:6210:2026-09"))
	text = bot.sent("edit_message_text")[-1]["text"]
	assert posted["posted_name"] in text and fmt_mnt("77272.73") in text


def test_a_tap_moves_the_memory_to_what_is_now_on_screen(run_receipt, books):
	proposal = run_receipt("petrovis_fuel")
	post.post_proposal(proposal.name, ACCOUNTANT)
	link_user(9006, "Accountant", books)
	bot = FakeBotApi()
	run(bot, callback_update(9006, f"q:{SPEND}:6210:2026-08"))
	memory = chat_state.get_question_memory(9006)
	assert memory["subject"] == {"account_code": "6210", "period": "2026-08"}
	assert memory["company"] == books


def test_a_button_for_a_supplier_the_books_do_not_have_offers_a_person(books, monkeypatch):
	"""MINOR: a not-found read counted as an answer, on the tap as well as on the typed question.

	The card then drew more buttons about a supplier it had just said does not exist, printed
	the unresolved name as the subject line, and stored it as the context for the next question.
	"""
	monkeypatch.setattr(
		_deps,
		"books_answer",
		lambda company, kind, args=None: {
			"supplier": (args or {}).get("supplier", ""),
			"found": False,
			"entries": [],
			"text": mn.SUPPLIER_NOT_FOUND_ANSWER.format(supplier=(args or {}).get("supplier", "")),
		},
	)
	link_user(9017, "Accountant", books)
	bot = FakeBotApi()
	ENT = questions.QUERY_SHORT["last_entries_for_supplier"]
	outcome = run(bot, callback_update(9017, f"q:{ENT}:Хэн ч биш ХХК", message_id=777))

	assert outcome["result"]["buttons"] == [questions.VERB_ESCALATE, questions.VERB_MENU]
	text = bot.sent("edit_message_text")[-1]["text"]
	assert text.startswith(mn.SUPPLIER_NOT_FOUND_ANSWER.format(supplier="Хэн ч биш ХХК"))
	assert mn.MSG_QUESTION_SUBJECT.format(subject="Хэн ч биш ХХК") not in text
	assert chat_state.get_question_memory(9017) == {}


def test_a_datum_this_build_does_not_understand_says_so(company):
	link_user(9007, "Accountant", company)
	bot = FakeBotApi()
	run(bot, callback_update(9007, "q:zzz:6210"))
	assert bot.last_text == mn.MSG_QUESTION_CONTEXT_GONE
	run(bot, callback_update(9007, f"q:{SPEND}:6210"))  # one argument short
	assert bot.last_text == mn.MSG_QUESTION_CONTEXT_GONE


def test_a_refused_query_leaves_the_card_and_offers_a_person(books):
	link_user(9008, "Accountant", books)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(9008, f"q:{SPEND}:4242:2026-09"))
	assert outcome["result"] == {"error": "unknown_account"}
	assert bot.sent("edit_message_text") == []
	assert mn.MSG_QUESTION_TRY_REPHRASE in bot.last_text
	assert bot.callback_datas() == [f"q:{questions.VERB_ESCALATE}", f"q:{questions.VERB_MENU}"]


def test_the_typed_dead_end_says_the_same_next_step_as_the_tapped_one(books, monkeypatch):
	"""MINOR: the tapped card told the user what to do next and the typed card did not.

	Same failure, two ways in: a button whose query the books refuse, and a question the model
	could not answer. The typed one sent MSG_QUESTION_CANNOT on its own, which reads as a dead
	end; the words are now one string so the two cannot drift apart again.
	"""
	link_user(9021, "Accountant", books)
	bot = FakeBotApi()
	run(bot, callback_update(9021, f"q:{SPEND}:4242:2026-09"))
	tapped = bot.last_text

	monkeypatch.setattr(
		_deps,
		"answer_question",
		lambda user, comp, text, memory=None, on_turn=None: questions.Reply(
			text=mn.MSG_QUESTION_CANNOT_FULL,
			follow_ups=question.STUCK_BUTTONS,
		),
	)
	run(bot, message_update(9021, "Кассад хэд байна?"))
	assert bot.last_text == tapped
	assert mn.MSG_QUESTION_TRY_REPHRASE in bot.last_text
	assert bot.callback_datas() == [f"q:{questions.VERB_ESCALATE}", f"q:{questions.VERB_MENU}"]


def test_an_empty_answer_still_reaches_the_card_with_its_next_step():
	"""MINOR: the card's own empty-answer default was the third place the dead end could drift.

	Both callers pass ``MSG_QUESTION_CANNOT_FULL`` for the failures they know about, so this
	default only fires on one they do not — and it used to render the bare refusal, which is
	the very card the typed path was just fixed for.
	"""
	assert cards.question_card("") == mn.MSG_QUESTION_CANNOT_FULL
	assert mn.MSG_QUESTION_TRY_REPHRASE in cards.question_card("   ")


def test_the_ask_admin_button_escalates_with_the_question_the_user_typed(company, monkeypatch):
	monkeypatch.setattr(
		_deps,
		"answer_question",
		lambda user, comp, text, memory=None, on_turn=None: _spend_reply(memory=_memory(comp)),
	)
	link_user(9009, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(9009, "Шатахуунд хэд зарцуулсан бэ?"))
	run(bot, callback_update(9009, f"q:{questions.VERB_ESCALATE}"))
	assert bot.sent("edit_message_text")[-1]["text"] == mn.MSG_ESCALATED
	events = frappe.get_all(
		"Nyabo Event", filters={"event_type": "question_escalated"}, fields=["reason", "company"]
	)
	assert len(events) == 1 and events[0].company == company
	assert "Шатахуунд хэд зарцуулсан бэ?" in events[0].reason


def test_the_escalation_never_quotes_a_memory_from_another_company(company, company_v03, monkeypatch):
	"""MINOR: ``_question_of`` read the chat state directly — no TTL, no version, no company.

	It is the one read that skipped every check, and ``_escalate`` quotes its text to an
	admin, so a question typed about another client could be sent out under this company's
	name. It goes through ``questions.recall`` like every other read of that memory.
	"""
	monkeypatch.setattr(
		_deps,
		"answer_question",
		lambda user, comp, text, memory=None, on_turn=None: _spend_reply(memory=_memory(comp)),
	)
	link_user(9014, "Accountant", company)
	bot = FakeBotApi()

	def _reasons() -> list[str]:
		rows = frappe.get_all(
			"Nyabo Event",
			filters={"event_type": "question_escalated", "company": company},
			fields=["reason"],
			order_by="creation asc, name asc",
		)
		return [row.reason for row in rows]

	foreign = _memory(company_v03)
	foreign["question"] = "Гурав ХХК-д шатахуунд хэд зарцуулсан бэ?"
	chat_state.set_question_memory(9014, foreign, telegram_id=9014)

	run(bot, callback_update(9014, f"q:{questions.VERB_ESCALATE}"))
	assert len(_reasons()) == 1 and "Гурав ХХК" not in _reasons()[0]

	# nor one of this company that the TTL has since expired
	stale = _memory(company, minutes_old=questions.MEMORY_TTL_MINUTES + 1)
	chat_state.set_question_memory(9014, stale, telegram_id=9014)
	run(bot, callback_update(9014, f"q:{questions.VERB_ESCALATE}"))
	assert "Шатахуунд хэд зарцуулсан бэ?" not in _reasons()[-1]

	# a memory of this company, still fresh, is quoted as before
	chat_state.set_question_memory(9014, _memory(company), telegram_id=9014)
	run(bot, callback_update(9014, f"q:{questions.VERB_ESCALATE}"))
	assert "Шатахуунд хэд зарцуулсан бэ?" in _reasons()[-1]


def test_the_menu_button_reaches_the_menu(company):
	link_user(9010, "Accountant", company)
	bot = FakeBotApi()
	run(bot, callback_update(9010, f"q:{questions.VERB_MENU}"))
	assert bot.texts(), "the menu card is drawn"


def test_a_button_that_cannot_be_encoded_is_dropped_not_the_card():
	"""settle_row's lesson: losing a button is a nuisance, losing the answer is not."""
	long_name = "Х" * 40
	markup = keyboards.question_keyboard(
		(
			questions.FollowUp(questions.QUERY_SHORT["last_entries_for_supplier"], "ok", ("Петровис ХХК",)),
			questions.FollowUp(questions.QUERY_SHORT["last_entries_for_supplier"], "too long", (long_name,)),
			questions.FollowUp(questions.QUERY_SHORT["last_entries_for_supplier"], "separator", ("a:b",)),
		)
	)
	datas = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
	assert datas == ["q:ent:Петровис ХХК"]


# --- who may ask -------------------------------------------------------------------------------------


def test_a_question_about_a_company_the_user_is_not_linked_to_is_refused(company, company_v03, monkeypatch):
	"""The company on the context is re-checked against the caller's links before anything is read."""
	called: list = []
	monkeypatch.setattr(_deps, "answer_question", lambda *a, **k: called.append(a) or _spend_reply())
	link_user(9011, "Accountant", company)
	bot = FakeBotApi()
	ctx = context.from_update(message_update(9011, "Гурав ХХК-д хэд зарцуулсан бэ?"), bot, get_settings())
	ctx.link = chat_state.get_link(9011)
	ctx.company = company_v03  # not one of this link's companies
	assert ctx.company not in ctx.companies

	assert question.handle_text(ctx) is None
	assert called == [] and bot.last_text == mn.MSG_NO_COMPANY


def test_a_button_tap_for_another_company_is_refused_too(company, company_v03, monkeypatch):
	reads: list = []
	monkeypatch.setattr(_deps, "books_answer", lambda *a, **k: reads.append(a) or {"text": "x"})
	link_user(9012, "Accountant", company)
	bot = FakeBotApi()
	ctx = context.from_update(callback_update(9012, f"q:{SPEND}:6210:2026-09"), bot, get_settings())
	ctx.link = chat_state.get_link(9012)
	ctx.company = company_v03

	assert question.handle_callback(ctx, keyboards.decode(ctx.callback_data)) is None
	assert reads == [] and bot.last_text == mn.MSG_NO_COMPANY


@pytest.mark.parametrize("data", ["q:esc", "q:spd:6210:2026-09"])
def test_a_chat_with_no_company_is_told_so(company, data, monkeypatch):
	reads: list = []
	monkeypatch.setattr(_deps, "books_answer", lambda *a, **k: reads.append(a) or {"text": "x"})
	link_user(9013, "Accountant", None)  # a link with no company row at all
	bot = FakeBotApi()
	run(bot, callback_update(9013, data))
	assert reads == [] and bot.last_text == mn.MSG_NO_COMPANY
