"""Free text outside any conversation state → the read-only question answerer (§5.7).

Three jobs beyond forwarding the text:

* **It says it is working.** A ledger question is a model call and several reads, and the
  chat is silent for seconds; ``sendChatAction`` is the cheapest honest signal there is, and
  it is re-sent between model turns because Telegram clears it after about five (``_typing``,
  which also says why this work stays on the short queue). A callback query is answered
  before the work starts so no client is left spinning.
* **It offers the next read as buttons.** ``agent.questions`` builds them from the tool
  trace; each button carries its whole query, so a tap runs the *handler* again with no model
  in the loop — the answer to a button is therefore always a figure the books produced. A tap
  edits the answer in place instead of stacking another card under it.
* **It keeps the company boundary.** Every path answers about ``ctx.company`` and re-checks
  it against the caller's links, so callback data (attacker-chosen, TG-03) and a subject
  remembered from another client can never reach these books.

Nothing here writes to the ledger: the only tools are reads, and the only side effect is the
escalation event the user asked for by tapping [Админаас асуух].
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from nyabo_mn.agent import questions
from nyabo_mn.agent.llm_client import ToolCall
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram import _deps, cards, keyboards
from nyabo_mn.telegram import state as chat_state
from nyabo_mn.telegram.context import Ctx

TYPING = "typing"
STUCK_BUTTONS = (
	questions.FollowUp(questions.VERB_ESCALATE, mn.BTN_Q_ASK_ADMIN),
	questions.FollowUp(questions.VERB_MENU, mn.BTN_MENU),
)


def _company(ctx: Ctx) -> str | None:
	"""The active company, but only while the caller is still linked to it (SEC-06).

	``Ctx.company`` is derived from the link, so this is belt and braces — and it is the brace
	that holds when a company row is removed from a link between two messages, or when a
	context is built by something other than the router.
	"""
	company = ctx.company
	if not company:
		return None
	if company not in ctx.companies:
		log_event(
			"telegram.question.company_not_linked",
			level="warning",
			telegram_id=ctx.telegram_id,
			company=company,
		)
		return None
	return company


def _send(ctx: Ctx, reply: questions.Reply, message_id: int | None = None) -> dict[str, Any]:
	"""Draw the answer and its buttons, editing the card the tap came from when there is one."""
	text = cards.question_card(reply.text, reply.subject)
	markup = keyboards.question_keyboard(reply.follow_ups) if reply.follow_ups else None
	if message_id is None:
		ctx.reply(text, markup)
	else:
		ctx.edit(message_id, text, markup)
	return {"answer": reply.text, "buttons": [f.verb for f in reply.follow_ups]}


def _typing(ctx: Ctx) -> Callable[[], None]:
	"""A callable that re-sends «typing…»; handed to the answerer to beat between model turns.

	"The status is set for 5 seconds or less" and Telegram clears it when the answer lands
	(telegram.api.send_chat_action). One action at the start was enough when the answer was
	one lookup and a sentence; this branch gives the question five turns on a slower model
	across ten query kinds, so the bubble expired and the user was left watching nothing.
	``agent.questions`` calls this once per tool dispatch — the seam between two model turns,
	and the only place that loop is visible from outside.

	Why the question stays on the SHORT queue, unlike receipts and statements: those are
	handed off because the user is expected to walk away from them — a photo is sent and the
	card arrives later. A question is a thing the user is waiting for with the chat open, and
	its whole value is coming back inside the conversation. Moving it to long would add a
	round trip through the queue and turn a slow answer into a late one, arriving detached
	from the turn it belongs to. The queue was never the problem; the missing sign of life
	was. If the answer's latency ever grows past what a person will hold a phone for, the fix
	is the model or the turn budget, not the queue.
	"""

	def beat() -> None:
		try:
			ctx.bot.send_chat_action(ctx.chat_id, TYPING)
		except Exception as exc:  # noqa: BLE001 - a missing typing bubble must never cost the answer
			log_event("telegram.chat_action_failed", level="warning", error=type(exc).__name__)

	return beat


def handle_text(ctx: Ctx) -> Any:
	company = _company(ctx)
	if not company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	beat = _typing(ctx)
	beat()
	memory = chat_state.get_question_memory(ctx.chat_id)
	reply = _deps.answer_question(ctx.user, company, ctx.text, memory, on_turn=beat)
	chat_state.set_question_memory(ctx.chat_id, reply.memory, telegram_id=ctx.telegram_id)
	return _send(ctx, reply)


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``q:<verb>[:<arg>…]`` — the next read offered under an answer.

	The datum carries the whole query, so this never asks the chat memory *what* to run; the
	memory is only written afterwards, so a typed follow-up after a tap resolves against the
	month the accountant is now looking at.
	"""
	ctx.answer()  # first, so the client stops spinning while the ledger is read
	company = _company(ctx)
	if not company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	verb = parts[1] if len(parts) > 1 else ""
	arguments = parts[2:]

	if verb == questions.VERB_MENU:
		from nyabo_mn.telegram.handlers import menu

		return menu.handle_menu(ctx)
	if verb == questions.VERB_ESCALATE:
		return _escalate(ctx, company)

	query_kind = questions.SHORT_QUERY.get(verb)
	if query_kind is None or len(arguments) != len(questions.QUERY_ARGS[query_kind]):
		# A datum this build does not understand: a card drawn by a later deploy, or a tampered
		# one. Say so rather than guess which query was meant.
		log_event("telegram.question.unknown_followup", level="warning", data=ctx.callback_data[:64])
		ctx.reply(mn.MSG_QUESTION_CONTEXT_GONE)
		return None

	now = dt.datetime.now(dt.timezone.utc)
	args = dict(zip(questions.QUERY_ARGS[query_kind], arguments, strict=True))
	result = _deps.books_answer(company, query_kind, args)
	if result.get("error"):
		# The books refused the query (an account that no longer exists, a period that is not
		# one). The card stays as it is; the user is told, and the way forward is a person.
		ctx.reply(
			cards.question_card(f"{mn.MSG_QUESTION_CANNOT}\n{mn.MSG_QUESTION_TRY_REPHRASE}"),
			keyboards.question_keyboard(STUCK_BUTTONS),
		)
		return {"error": result["error"]}

	trace = (_as_tool_call(query_kind, args, result),)
	# A read that found nothing — the supplier is gone, the document was never this company's —
	# is not an answer: its sentence quotes the name the datum carried, so the card must offer
	# a person rather than more buttons about a subject the books do not have.
	answered = bool(result.get("text")) and questions.resolved(result)
	subject = {key: value for key, value in args.items() if value} if answered else {}
	if answered:
		subject.update({k: str(v) for k, v in result.items() if k in questions.SUBJECT_KEYS and v})
	reply = questions.Reply(
		text=str(result.get("text") or mn.MSG_QUESTION_CANNOT),
		follow_ups=questions.follow_ups(trace, now=now, answered=answered),
		memory=questions.remember(_question_of(ctx, company), trace, company=company, now=now),
		subject=questions.subject_label(subject),
	)
	chat_state.set_question_memory(ctx.chat_id, reply.memory, telegram_id=ctx.telegram_id)
	return _send(ctx, reply, message_id=ctx.callback_message_id)


def _escalate(ctx: Ctx, company: str) -> Any:
	"""Hand the question to a human, quoting what the user actually asked."""
	question = _question_of(ctx, company)
	summary = mn.MSG_QUESTION_ESCALATE_SUMMARY.format(button=mn.BTN_Q_ASK_ADMIN, question=question)
	_deps.escalate_question(ctx.user, company, question, summary)
	ctx.edit(ctx.callback_message_id, mn.MSG_ESCALATED, keyboards.menu_markup())
	return {"escalated": True}


def _question_of(ctx: Ctx, company: str) -> str:
	"""The remembered question this card answers, else the card's own text.

	Through ``questions.recall``, not straight off the chat state: this was the one read of
	the memory with no TTL, no version and no company check, and ``_escalate`` quotes the
	result to an admin — so a question typed about another client, or twenty minutes and one
	/компани ago, could be sent out under this company's name.

	Never the callback datum: what an admin is asked to act on has to be what a person wrote.
	"""
	memory = questions.recall(
		chat_state.get_question_memory(ctx.chat_id),
		company=company,
		now=dt.datetime.now(dt.timezone.utc),
	)
	stored = str((memory or {}).get("question") or "").strip()
	if stored:
		return stored
	return (((ctx.callback or {}).get("message") or {}).get("text") or "").strip()[:200]


def _as_tool_call(query_kind: str, args: dict[str, str], result: dict[str, Any]) -> ToolCall:
	"""The tap, in the shape ``agent.questions`` reads a tool trace in.

	A button and a typed question then build their follow-ups and their memory through exactly
	the same code, so the two can never offer different next steps for the same answer.
	"""
	full: dict[str, Any] = dict.fromkeys(questions.SUBJECT_KEYS)
	full.update(args)
	return ToolCall(
		name="answer_from_books",
		arguments={"query_kind": query_kind, "args": full},
		result=result,
		is_error=False,
	)
