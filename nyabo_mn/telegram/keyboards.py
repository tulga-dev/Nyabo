"""Inline keyboards and callback data (docs/ARCHITECTURE.md §5.1).

Buttons carry state, the model never writes them (principle 7). Callback data is a
colon-separated tuple no longer than 64 bytes (Telegram's limit); ``encode`` asserts it so
a long account code fails in a test, not in production. The one datum built from a document
name a site can rename is the settlement button, and ``settle_row`` catches the refusal
there rather than letting it take the card down with it. Layout rule: the primary action
sits alone on the top row, then at most three buttons per row, so cards read the same
on every phone width.

Every prompt that waits for the user carries an escape row (UX-13): Цуцлах always, Буцах
where there is a previous step and Алгасах where the step is optional. Those three ride on
one prefix (``e:<scope>:<verb>``) so that ``handlers.escape`` is the only place that knows
what leaving a step means, whether the user tapped the button or typed the word.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram.api import MAX_CALLBACK_DATA_BYTES

SEP = ":"
MAX_PER_ROW = 3

# prefixes (§5.1)
PREFIX_PROPOSAL = "p"
PREFIX_BANK = "b"
PREFIX_CLOSE = "c"
PREFIX_CORRECTION = "x"
PREFIX_ONBOARDING = "o"
PREFIX_INTAKE = "i"
PREFIX_LAYOUT = "l"  # statement column mapping; not in §5.1, listed in the module report
PREFIX_ESCAPE = "e"  # e:<scope>:cancel|back|skip|menu — the way out of any waiting step (UX-13)

# Escape verbs. The scope beside them is the flow the button was drawn for, so a tap on a
# card scrolled far up can be recognised as stale instead of cancelling today's work.
ESCAPE_CANCEL = "cancel"
ESCAPE_BACK = "back"
ESCAPE_SKIP = "skip"
ESCAPE_MENU = "menu"

# A scope is the conversation state's prefix, so ``handlers.escape`` can tell a tap on the
# step that is still open from a tap on a card the accountant scrolled back to.
SCOPE_ONBOARDING = "onb"
SCOPE_ACCOUNT_SEARCH = "acc_search"
SCOPE_REJECT_TEXT = "reject_text"
SCOPE_CORRECTION = "correct"
SCOPE_LAYOUT = "layout"
SCOPE_BANK_FIND = "bank_find"
SCOPE_ERROR = "err"  # not a state: the escape the router hands out when a handler failed

# InlineKeyboardButton.style, Bot API 10.3: "Optional. Style of the button. Must be one of
# “danger” (red), “success” (green) or “primary” (blue). If omitted, then an app-specific
# style is used." It carries the meaning of a button without an emoji in the Mongolian label.
STYLE_DANGER = "danger"
STYLE_SUCCESS = "success"
STYLE_PRIMARY = "primary"

DOCTYPE_SHORT = {"Purchase Invoice": "pi", "Journal Entry": "je", "Sales Invoice": "si"}
SHORT_DOCTYPE = {v: k for k, v in DOCTYPE_SHORT.items()}


class CallbackDataTooLong(ValueError):
	pass


def encode(*parts: Any) -> str:
	"""``encode("p", "NYP-00001", "ap") -> "p:NYP-00001:ap"``; refuses more than 64 bytes."""
	data = SEP.join(str(p) for p in parts)
	if len(data.encode("utf-8")) > MAX_CALLBACK_DATA_BYTES:
		raise CallbackDataTooLong(f"callback data exceeds {MAX_CALLBACK_DATA_BYTES} bytes: {data!r}")
	if any(SEP in str(p) for p in parts):
		raise ValueError(f"callback part contains the separator: {parts!r}")
	return data


def decode(data: str) -> list[str]:
	return (data or "").split(SEP)


def button(text: str, data: str, style: str | None = None) -> dict[str, str]:
	"""``style`` is omitted rather than sent as null: the API's default is "an app-specific style"."""
	drawn = {"text": text, "callback_data": data}
	if style:
		drawn["style"] = style
	return drawn


# --- escape hatches (UX-13) --------------------------------------------------------------------


def escape_row(
	scope: str, back: bool = False, skip: bool = False, cancel: bool = True
) -> list[dict[str, str]]:
	"""The [Буцах] [Алгасах] [Цуцлах] row for a step, in that reading order.

	``scope`` is the flow tag (the conversation state's prefix), not the step: the open state
	decides what leaving means, and the scope only tells ``handlers.escape`` whether the tap
	came from the flow that is still running.
	"""
	row: list[dict[str, str]] = []
	if back:
		row.append(button(mn.BTN_BACK, encode(PREFIX_ESCAPE, scope, ESCAPE_BACK)))
	if skip:
		row.append(button(mn.BTN_SKIP, encode(PREFIX_ESCAPE, scope, ESCAPE_SKIP)))
	if cancel:
		row.append(button(mn.BTN_CANCEL, encode(PREFIX_ESCAPE, scope, ESCAPE_CANCEL), style=STYLE_DANGER))
	return row


def escape_markup(scope: str, back: bool = False, skip: bool = False) -> dict[str, Any]:
	"""The whole keyboard for a free-text step: nothing to choose, only ways out."""
	return markup(escape_row(scope, back=back, skip=skip))


def menu_markup(scope: str = SCOPE_ERROR) -> dict[str, Any]:
	"""One [Цэс] button: the floor under a failure, where re-offering the step is not possible."""
	return markup([button(mn.BTN_MENU, encode(PREFIX_ESCAPE, scope, ESCAPE_MENU), style=STYLE_PRIMARY)])


def spent(reply_markup: dict[str, Any] | None) -> dict[str, Any]:
	"""The same rows, every button disabled: a prompt that has been answered keeps its shape.

	Bot API 10.3 ``InlineKeyboardButton.disabled`` is a ``DisabledButton`` — "If set, then the
	button is disabled and does nothing"; the class "represents a disabled button which does
	nothing. Currently holds no information", so ``{}`` is the whole value. ``callback_data`` is
	dropped with it, because "Exactly one of the fields other than text, icon_custom_emoji_id,
	and style must be used to specify the type of the button". Editing beats deleting here:
	``deleteMessage`` refuses a message older than 48 hours, an edit does not.
	"""
	keyboard = (reply_markup or {}).get("inline_keyboard") or []
	drawn = []
	for row in keyboard:
		spent_row = []
		for btn in row:
			if not isinstance(btn, dict):
				continue
			kept = {"text": btn.get("text", ""), "disabled": {}}
			if btn.get("style"):
				kept["style"] = btn["style"]
			spent_row.append(kept)
		drawn.append(spent_row)
	return {"inline_keyboard": drawn}


def rows(buttons: Iterable[dict[str, str]], per_row: int = MAX_PER_ROW) -> list[list[dict[str, str]]]:
	items = list(buttons)
	return [items[i : i + per_row] for i in range(0, len(items), per_row)]


def markup(*button_rows: Sequence[dict[str, str]]) -> dict[str, Any]:
	"""InlineKeyboardMarkup; empty rows are dropped so a conditional button needs no branching."""
	return {"inline_keyboard": [list(r) for r in button_rows if r]}


def empty_markup() -> dict[str, Any]:
	return {"inline_keyboard": []}


# --- receipt proposals -----------------------------------------------------------------------------


def receipt_keyboard(proposal_name: str) -> dict[str, Any]:
	return markup(
		[button(mn.BTN_APPROVE, encode(PREFIX_PROPOSAL, proposal_name, "ap"), style=STYLE_SUCCESS)],
		[
			button(mn.BTN_CHANGE_ACCOUNT, encode(PREFIX_PROPOSAL, proposal_name, "ch")),
			button(mn.BTN_REJECT, encode(PREFIX_PROPOSAL, proposal_name, "rj"), style=STYLE_DANGER),
		],
	)


def posted_keyboard(posted_doctype: str, posted_name: str) -> dict[str, Any]:
	"""After posting the only action left is a correction (reversal), §5.6."""
	short = DOCTYPE_SHORT.get(posted_doctype)
	if not short:
		return empty_markup()
	return markup([button(mn.BTN_EDIT, encode(PREFIX_CORRECTION, short, posted_name, "rev"))])


def account_chooser(
	prefix: str, name: str, accounts: Sequence[tuple[str, str]], more: bool = True
) -> dict[str, Any]:
	"""``p:<name>:acc:<code>`` (or ``b:`` for bank lines); the label is ``code name`` truncated."""
	buttons = [button(f"{code} {label}"[:40], encode(prefix, name, "acc", code)) for code, label in accounts]
	extra = [button(mn.BTN_MORE_ACCOUNTS, encode(prefix, name, "acc", "more"))] if more else []
	back = [button(mn.BTN_BACK, encode(prefix, name, "back"))]
	return markup(*rows(buttons, per_row=2), extra, back)


def reject_reasons(proposal_name: str) -> dict[str, Any]:
	buttons = [
		button(label, encode(PREFIX_PROPOSAL, proposal_name, "rr", code))
		for code, label in mn.REJECT_REASONS.items()
	]
	return markup(
		*rows(buttons, per_row=2), [button(mn.BTN_BACK, encode(PREFIX_PROPOSAL, proposal_name, "back"))]
	)


# --- corrections -----------------------------------------------------------------------------------


def correction_reasons(posted_name: str) -> dict[str, Any]:
	buttons = [
		button(label, encode(PREFIX_CORRECTION, posted_name, "reason", code))
		for code, label in mn.CORRECT_REASONS.items()
	]
	return markup(
		*rows(buttons, per_row=2),
		[button(mn.BTN_CANCEL, encode(PREFIX_CORRECTION, posted_name, "cancel"), style=STYLE_DANGER)],
	)


def correction_text() -> dict[str, Any]:
	"""Typing the free-form reason: Буцах returns to the reason buttons, Цуцлах drops the whole thing."""
	return escape_markup(SCOPE_CORRECTION, back=True)


def account_search_prompt() -> dict[str, Any]:
	"""Typing an account name: Буцах puts the card's own buttons back."""
	return escape_markup(SCOPE_ACCOUNT_SEARCH, back=True)


def reject_text_prompt() -> dict[str, Any]:
	"""Typing a rejection reason: Буцах puts the reason buttons back."""
	return escape_markup(SCOPE_REJECT_TEXT, back=True)


def bank_find_prompt() -> dict[str, Any]:
	"""Typing what a bank line pays: leaving it is the same as [Дараа]."""
	return escape_markup(SCOPE_BANK_FIND, back=True)


# --- bank lines ------------------------------------------------------------------------------------


def settle_row(bank_transaction: str, voucher_doctype: str, voucher_name: str) -> list[dict[str, str]]:
	"""The [Төлбөр бүртгэх] row, or an empty row when the voucher cannot be carried.

	The button carries the voucher itself (short doctype + name) rather than an index into
	the chat state, because ``Nyabo Chat State`` is one row per chat with a single payload:
	a statement import sends one card per unmatched line, so an index would be overwritten
	by the next card and by whatever the accountant does next, and the tap has to still work
	on a card opened tomorrow. (``bank_candidates`` may use an index precisely because the
	find flow writes the state one message earlier and the taps follow immediately.)

	The price is that a document name long enough to push the datum past Telegram's 64-byte
	limit cannot be encoded. Losing the button is a nuisance; losing the card is not — the
	``CallbackDataTooLong`` used to escape ``matching.match._send_card`` (which catches only
	Telegram and settings errors) and abort the whole statement import, so every later line
	of the statement went uncarded too. The refusal is logged so the silence is visible.
	"""
	short = DOCTYPE_SHORT.get(voucher_doctype)
	if not short:
		return []
	try:
		data = encode(PREFIX_BANK, bank_transaction, "st", short, voucher_name)
	except CallbackDataTooLong:
		log_event(
			"telegram.settle_button_too_long",
			level="warning",
			bank_transaction=bank_transaction,
			voucher=f"{voucher_doctype} {voucher_name}",
		)
		return []
	return [button(mn.BTN_RECORD_PAYMENT, data)]


def bank_line_keyboard(bank_transaction: str, settle: tuple[str, str] | None = None) -> dict[str, Any]:
	"""``settle`` is (voucher doctype, voucher name) when the line clearly pays an unpaid invoice."""
	return markup(
		settle_row(bank_transaction, *settle) if settle is not None else [],
		[button(mn.BTN_FIND_DOCUMENT, encode(PREFIX_BANK, bank_transaction, "find"))],
		[
			button(mn.BTN_RECORD_EXPENSE, encode(PREFIX_BANK, bank_transaction, "exp")),
			button(mn.BTN_LATER, encode(PREFIX_BANK, bank_transaction, "later")),
		],
	)


def bank_settle(bank_transaction: str, voucher_doctype: str, voucher_name: str) -> dict[str, Any]:
	"""The [Төлбөр бүртгэх] offer shown after [Баримт хайх] picked an unpaid invoice."""
	row = settle_row(bank_transaction, voucher_doctype, voucher_name)
	if not row:
		return empty_markup()
	return markup(row, [button(mn.BTN_LATER, encode(PREFIX_BANK, bank_transaction, "later"))])


def bank_candidates(bank_transaction: str, count: int) -> dict[str, Any]:
	"""Candidates live in the chat state; the button carries only the index (64-byte limit)."""
	buttons = [button(str(i + 1), encode(PREFIX_BANK, bank_transaction, "m", i)) for i in range(count)]
	return markup(
		*rows(buttons),
		[button(mn.BTN_CANCEL, encode(PREFIX_BANK, bank_transaction, "later"), style=STYLE_DANGER)],
	)


# --- month-end -------------------------------------------------------------------------------------


def close_confirm(period: str) -> dict[str, Any]:
	"""Цуцлах is red everywhere it appears, so the word and the colour always agree."""
	return markup(
		[button(mn.BTN_CLOSE_PERIOD, encode(PREFIX_CLOSE, period, "confirm"), style=STYLE_PRIMARY)],
		[button(mn.BTN_CANCEL, encode(PREFIX_CLOSE, period, "cancel"), style=STYLE_DANGER)],
	)


# --- onboarding ------------------------------------------------------------------------------------


def onboarding_yes_no(step: str, back: bool = True) -> dict[str, Any]:
	"""``back`` is off only on the first question, where there is nothing to go back to."""
	return markup(
		[
			button(mn.BTN_YES, encode(PREFIX_ONBOARDING, step, "yes")),
			button(mn.BTN_NO, encode(PREFIX_ONBOARDING, step, "no")),
		],
		escape_row(SCOPE_ONBOARDING, back=back),
	)


def onboarding_banks(selected: Sequence[str]) -> dict[str, Any]:
	"""Multi-select toggles: the label shows the state, the data toggles one bank."""
	buttons = []
	for bank in mn.BANK_NAMES_MN:
		label = (mn.ONB_BANK_TOGGLE_ON if bank in selected else mn.ONB_BANK_TOGGLE_OFF).format(bank=bank)
		buttons.append(button(label, encode(PREFIX_ONBOARDING, "banks", bank.replace(" ", "_"))))
	return markup(
		*rows(buttons, per_row=2),
		[button(mn.BTN_DONE, encode(PREFIX_ONBOARDING, "banks", "done"), style=STYLE_PRIMARY)],
		escape_row(SCOPE_ONBOARDING, back=True, skip=True),
	)


OFFERED_CURRENCIES = ("MNT", "USD")


def onboarding_currencies(selected: Sequence[str], custom: Sequence[str] = ()) -> dict[str, Any]:
	"""Toggles for MNT/USD plus every code the accountant typed under [Бусад валют].

	UX-11: a typed code used to be stored and never drawn, so the accountant had no
	confirmation it registered and no way to take it off again. It is now one more toggle,
	and it stays on the keyboard after being switched off so it can be switched back on —
	``_on_currency`` already toggles whatever value it is handed.
	"""
	extra = [c for c in dict.fromkeys([*custom, *selected]) if c not in OFFERED_CURRENCIES]
	buttons = []
	for currency in (*OFFERED_CURRENCIES, *extra):
		label = (mn.ONB_BANK_TOGGLE_ON if currency in selected else mn.ONB_BANK_TOGGLE_OFF).format(
			bank=currency
		)
		buttons.append(button(label, encode(PREFIX_ONBOARDING, "cur", currency)))
	buttons.append(button(mn.ONB_CURRENCY_OTHER, encode(PREFIX_ONBOARDING, "cur", "other")))
	return markup(
		*rows(buttons),
		[button(mn.BTN_DONE, encode(PREFIX_ONBOARDING, "cur", "done"), style=STYLE_PRIMARY)],
		escape_row(SCOPE_ONBOARDING, back=True, skip=True),
	)


def onboarding_skip(step: str, back: bool = True) -> dict[str, Any]:
	"""An optional typed step: the old ``o:<step>:skip`` button stays for cards sent before UX-13.

	A card lives in the chat across a deploy, so the button an accountant is looking at right
	now must keep working; the escape row beside it is what everything new is routed through.
	"""
	return markup(
		[button(mn.BTN_SKIP, encode(PREFIX_ONBOARDING, step, "skip"))],
		escape_row(SCOPE_ONBOARDING, back=back, skip=False),
	)


def onboarding_text_step(back: bool = True, skip: bool = False) -> dict[str, Any]:
	"""A typed onboarding answer with no choices of its own: only the ways out.

	The inventory list is the step the founder was trapped in, so it is drawn with all three:
	Буцах to the Тийм/Үгүй question, Алгасах because the list is optional, Цуцлах to leave.
	"""
	return escape_markup(SCOPE_ONBOARDING, back=back, skip=skip)


def onboarding_confirm(step: str) -> dict[str, Any]:
	return markup(
		[button(mn.BTN_CONFIRM, encode(PREFIX_ONBOARDING, step, "confirm"), style=STYLE_SUCCESS)],
		escape_row(SCOPE_ONBOARDING, back=True),
	)


def intake_confirm(intake_name: str) -> dict[str, Any]:
	return markup(
		[button(mn.BTN_CONFIRM, encode(PREFIX_INTAKE, intake_name, "confirm"), style=STYLE_SUCCESS)],
		[button(mn.BTN_CANCEL, encode(PREFIX_INTAKE, intake_name, "cancel"), style=STYLE_DANGER)],
		escape_row(SCOPE_ONBOARDING, back=True, skip=True, cancel=False),
	)


# --- statement layout mapping ----------------------------------------------------------------------


def layout_column_roles(column_index: int, back: bool = False) -> dict[str, Any]:
	"""``back`` is on from the second column: the answer to the previous one can be re-taken."""
	buttons = [
		button(label, encode(PREFIX_LAYOUT, column_index, role)) for role, label in mn.COLUMN_ROLES.items()
	]
	return markup(*rows(buttons), escape_row(SCOPE_LAYOUT, back=back))


# --- company switch --------------------------------------------------------------------------------


def company_chooser(companies: Sequence[str]) -> dict[str, Any]:
	"""Company names can be long Cyrillic; the data carries the index into the user's list."""
	buttons = [button(name[:40], encode("k", i)) for i, name in enumerate(companies)]
	return markup(*rows(buttons, per_row=1))


__all__ = [name for name in dir() if not name.startswith("_")]
