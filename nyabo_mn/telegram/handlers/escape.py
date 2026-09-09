"""The way out of any waiting step: Цуцлах / Буцах / Алгасах, tapped or typed (UX-13).

The founder was stuck in the inventory step of ``/эхлэх``: they typed «алгасах», the step's
own parser refused the line, and the card offered no Cancel, no Back and no way home. Two
things follow from that. First, every state that waits for the user must carry the escapes
on the message itself (``keyboards.escape_row``). Second, a user who *types* the escape
instead of tapping it must be understood before the step's parser ever sees the text — the
router asks this module first, and only then hands the message to the flow.

The verbs are the same on both paths so there is one place that knows what leaving a step
means. What it means is the flow's business, so each flow exports ``handle_escape`` and this
module only decides which flow is open, refuses a tap on a step that has closed, and falls
back to a plain cancel when a flow has nothing special to say.

"A step that has closed" is compared on the whole state name, not only the flow: the steps
answered by typing never have their prompt edited, so their escape row stays live above the
question that came after it, and a tap on it used to move the wizard from a step it was not
drawn for.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram import keyboards
from nyabo_mn.telegram.context import Ctx

CANCEL = keyboards.ESCAPE_CANCEL
BACK = keyboards.ESCAPE_BACK
SKIP = keyboards.ESCAPE_SKIP
MENU = keyboards.ESCAPE_MENU

# Words the user types. These are *input* Nyabo reads, not output it writes, which is why they
# live here and not in i18n (tests/unit/test_i18n_no_hardcoded_mongolian.py allow-list).
#
# «буцаах» is deliberately absent: it is BTN_REVERSE, the word for reversing a posted entry,
# and must never be read as "go back one step" (принцип 5 — corrections are reversals).
WORDS: dict[str, str] = {
	# cancel / stop / get me out
	"цуцлах": CANCEL,
	"цуцла": CANCEL,
	"цуцал": CANCEL,
	"болих": CANCEL,
	"болих уу": CANCEL,
	"болъё": CANCEL,
	"болилоо": CANCEL,
	"гарах": CANCEL,
	"зогсоо": CANCEL,
	"cancel": CANCEL,
	"stop": CANCEL,
	# back one step
	"буцах": BACK,
	"буцъя": BACK,
	"өмнөх": BACK,
	"back": BACK,
	# skip an optional step
	"алгасах": SKIP,
	"алгас": SKIP,
	"алгасъя": SKIP,
	"skip": SKIP,
	# home
	"цэс": MENU,
	"меню": MENU,
	"үндсэн цэс": MENU,
	"menu": MENU,
	"home": MENU,
}
# The slash spellings the ☰ menu and a Latin keyboard produce. ``/menu`` and ``/start`` are
# real commands with their own handlers and are routed there, not here.
COMMANDS: dict[str, str] = {
	"/cancel": CANCEL,
	"/цуцлах": CANCEL,
	"/back": BACK,
	"/буцах": BACK,
	"/skip": SKIP,
	"/алгасах": SKIP,
}

# Trailing question marks and the Mongolian quotation marks a phone keyboard adds by itself.
_TRIM = re.compile(r"^[«\"'\s]+|[»\"'\s.!?…]+$")


def intent(text: str) -> str | None:
	"""``«Болих уу?»`` -> ``"cancel"``; None for anything that is not an escape.

	Matching is on the whole message, never on a word inside it: an account search for
	«гарах зардал» or a rejection reason that mentions цуцлах must reach its own step.
	"""
	cleaned = _TRIM.sub("", (text or "").strip().lower())
	cleaned = " ".join(cleaned.split())
	if not cleaned:
		return None
	if cleaned.startswith("/"):
		# ``/cancel@nyabo_bot`` is what a group-style client sends; the router strips nothing here.
		return COMMANDS.get(cleaned.split("@", 1)[0].split(maxsplit=1)[0])
	return WORDS.get(cleaned)


def _flow_handlers() -> dict[str, Callable[[Ctx, str, dict[str, Any], str], bool | str]]:
	"""State prefix -> the flow's own ``handle_escape``; missing means the plain cancel.

	A flow answers with ``True`` when it dealt with the verb itself (it moved the step and said
	so), ``CANCEL`` when its own clean-up is done and leaving is now the right outcome, and
	``False`` when the verb means nothing there — Буцах on the first question, Алгасах on a
	step that has no default worth guessing.
	"""
	from nyabo_mn.telegram.handlers import approve, bank, correct, onboarding, statement

	return {
		keyboards.SCOPE_ONBOARDING: onboarding.handle_escape,
		keyboards.SCOPE_ACCOUNT_SEARCH: approve.handle_escape,
		keyboards.SCOPE_REJECT_TEXT: approve.handle_escape,
		keyboards.SCOPE_CORRECTION: correct.handle_escape,
		keyboards.SCOPE_LAYOUT: statement.handle_escape,
		keyboards.SCOPE_BANK_FIND: bank.handle_escape,
	}


def state_scope(state: str | None) -> str:
	"""``"onb:inv_wait"`` -> ``"onb"``; the scope a button drawn for that state carries."""
	return (state or "").split(":", 1)[0]


def state_step(state: str | None) -> str:
	"""``"onb:inv_wait"`` -> ``"inv_wait"``; "" for a flow whose state is the scope itself."""
	_scope, _, step = (state or "").partition(":")
	return step


def drawn_for_open_step(scope: str, step: str | None, state: str | None) -> bool:
	"""Is this button still the open question's own button?

	``step`` is None for a card drawn before the step rode along in the datum (a card lives in
	the chat across a deploy). There is nothing to compare then, so the old flow-level check is
	all that can be asked of it.
	"""
	if scope != state_scope(state):
		return False
	return step is None or step == state_step(state)


# --- typed words -------------------------------------------------------------------------------


def handle_typed(ctx: Ctx, verb: str) -> Any:
	"""The router's hook: the user typed the escape instead of tapping it."""
	state, payload = ctx.get_state()
	log_event("telegram.escape.typed", verb=verb, state=state or "", chat_id=ctx.chat_id)
	return _apply(ctx, state, payload, verb)


# --- tapped buttons ----------------------------------------------------------------------------


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``e:<scope>:cancel|back|skip|menu`` from any prompt's escape row."""
	if len(parts) < 3:
		return None
	scope, verb = parts[1], parts[2]
	step = parts[3] if len(parts) > 3 else None
	state, payload = ctx.get_state()
	if verb == MENU:
		_retire_prompt(ctx)
		return _go_home(ctx, state)
	if not drawn_for_open_step(scope, step, state):
		# The question this button belonged to is answered; acting now would move — or take
		# down — whatever the accountant has open instead. Say so, and leave that alone.
		ctx.answer(mn.MSG_ESCAPE_STALE, show_alert=True)
		log_event(
			"telegram.escape.stale",
			level="warning",
			scope=scope,
			step=step or "",
			state=state or "",
		)
		return {"stale": True}
	if verb == CANCEL:
		announced = _retire_prompt(ctx, mn.MSG_FLOW_CANCELLED)
		return _apply(ctx, state, payload, verb, announced=announced)
	_retire_prompt(ctx)
	return _apply(ctx, state, payload, verb)


def _message_is_accessible(ctx: Ctx) -> bool:
	"""``CallbackQuery.message`` is a MaybeInaccessibleMessage; ``date`` is "Always 0" when it is
	an InaccessibleMessage, which "describes a message that was deleted or is otherwise
	inaccessible to the bot" — editing that would be a guess, so we send instead."""
	message = (ctx.callback or {}).get("message") or {}
	return bool(message) and message.get("date") != 0


def _retire_prompt(ctx: Ctx, text: str | None = None) -> bool:
	"""Take the answered prompt out of service in place; True when ``text`` reached the user.

	The buttons are re-sent disabled (``keyboards.spent``) so the card keeps its shape and the
	user can still read what they walked away from; ``CallbackQuery.message`` carries the
	original ``reply_markup``, so nothing has to be reconstructed. The return value is what
	stops a tapped cancel from saying the same thing twice — and, when there was no message to
	edit, what makes sure it gets said at all.
	"""
	if not ctx.is_callback or ctx.callback_message_id is None or not _message_is_accessible(ctx):
		if text:
			ctx.reply(text)
			return True
		return False
	message = (ctx.callback or {}).get("message") or {}
	markup = keyboards.spent(message.get("reply_markup"))
	if text:
		ctx.edit(ctx.callback_message_id, text, markup)
		return True
	try:
		ctx.bot.edit_message_reply_markup(ctx.chat_id, ctx.callback_message_id, markup)
	except Exception as exc:  # a spent keyboard is cosmetic; the step still has to move on
		log_event("telegram.escape.retire_failed", level="warning", error=type(exc).__name__)
	return False


# --- what an escape does -----------------------------------------------------------------------


def _apply(ctx: Ctx, state: str | None, payload: dict[str, Any], verb: str, announced: bool = False) -> Any:
	if verb == MENU:
		return _go_home(ctx, state)
	if not state:
		return _nothing_open(ctx, verb)
	handler = _flow_handlers().get(state_scope(state))
	outcome: bool | str = handler(ctx, state, payload, verb) if handler is not None else False
	if outcome is True:
		return {"escape": verb, "state": state}
	if verb == CANCEL or outcome == CANCEL:
		return _cancel(ctx, announced=announced)
	# A flow that cannot go back or skip here must not be left silent: say why and let the
	# state stand, so the prompt on screen is still the answer to give.
	ctx.reply(mn.MSG_STEP_NO_BACK if verb == BACK else mn.MSG_STEP_CANNOT_SKIP)
	return {"escape": verb, "refused": True, "state": state}


def _cancel(ctx: Ctx, announced: bool = False) -> Any:
	ctx.clear_state()
	if not announced:
		ctx.reply(mn.MSG_FLOW_CANCELLED)
	ctx.answer(mn.MSG_CANCELLED)
	return {"escape": CANCEL, "cleared": True}


def _nothing_open(ctx: Ctx, verb: str) -> Any:
	"""«цуцлах» with no conversation open: say there is nothing to leave, not "I did not understand"."""
	ctx.reply(mn.MSG_FLOW_NOTHING_TO_CANCEL)
	ctx.answer()
	return {"escape": verb, "state": None}


def _go_home(ctx: Ctx, state: str | None) -> Any:
	from nyabo_mn.telegram.handlers import menu

	if state:
		ctx.clear_state()
		ctx.reply(mn.MSG_FLOW_LEFT_FOR_COMMAND)
	ctx.answer()
	return menu.handle_menu(ctx)


__all__ = [
	"BACK",
	"CANCEL",
	"MENU",
	"SKIP",
	"drawn_for_open_step",
	"handle_callback",
	"handle_typed",
	"intent",
	"state_scope",
	"state_step",
]
