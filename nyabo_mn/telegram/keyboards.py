"""Inline keyboards and callback data (docs/ARCHITECTURE.md §5.1).

Buttons carry state, the model never writes them (principle 7). Callback data is a
colon-separated tuple no longer than 64 bytes (Telegram's limit); ``encode`` asserts it so
a long account code fails in a test, not in production. Layout rule: the primary action
sits alone on the top row, then at most three buttons per row, so cards read the same
on every phone width.
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


def button(text: str, data: str) -> dict[str, str]:
	return {"text": text, "callback_data": data}


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
		[button(mn.BTN_APPROVE, encode(PREFIX_PROPOSAL, proposal_name, "ap"))],
		[
			button(mn.BTN_CHANGE_ACCOUNT, encode(PREFIX_PROPOSAL, proposal_name, "ch")),
			button(mn.BTN_REJECT, encode(PREFIX_PROPOSAL, proposal_name, "rj")),
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
		*rows(buttons, per_row=2), [button(mn.BTN_CANCEL, encode(PREFIX_CORRECTION, posted_name, "cancel"))]
	)


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
	return markup(*rows(buttons), [button(mn.BTN_CANCEL, encode(PREFIX_BANK, bank_transaction, "later"))])


# --- month-end -------------------------------------------------------------------------------------


def close_confirm(period: str) -> dict[str, Any]:
	return markup(
		[button(mn.BTN_CLOSE_PERIOD, encode(PREFIX_CLOSE, period, "confirm"))],
		[button(mn.BTN_CANCEL, encode(PREFIX_CLOSE, period, "cancel"))],
	)


# --- onboarding ------------------------------------------------------------------------------------


def onboarding_yes_no(step: str) -> dict[str, Any]:
	return markup(
		[
			button(mn.BTN_YES, encode(PREFIX_ONBOARDING, step, "yes")),
			button(mn.BTN_NO, encode(PREFIX_ONBOARDING, step, "no")),
		]
	)


def onboarding_banks(selected: Sequence[str]) -> dict[str, Any]:
	"""Multi-select toggles: the label shows the state, the data toggles one bank."""
	buttons = []
	for bank in mn.BANK_NAMES_MN:
		label = (mn.ONB_BANK_TOGGLE_ON if bank in selected else mn.ONB_BANK_TOGGLE_OFF).format(bank=bank)
		buttons.append(button(label, encode(PREFIX_ONBOARDING, "banks", bank.replace(" ", "_"))))
	return markup(
		*rows(buttons, per_row=2), [button(mn.BTN_DONE, encode(PREFIX_ONBOARDING, "banks", "done"))]
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
	return markup(*rows(buttons), [button(mn.BTN_DONE, encode(PREFIX_ONBOARDING, "cur", "done"))])


def onboarding_skip(step: str) -> dict[str, Any]:
	return markup([button(mn.BTN_SKIP, encode(PREFIX_ONBOARDING, step, "skip"))])


def onboarding_confirm(step: str) -> dict[str, Any]:
	return markup(
		[button(mn.BTN_CONFIRM, encode(PREFIX_ONBOARDING, step, "confirm"))],
		[button(mn.BTN_CANCEL, encode(PREFIX_ONBOARDING, step, "cancel"))],
	)


def intake_confirm(intake_name: str) -> dict[str, Any]:
	return markup(
		[button(mn.BTN_CONFIRM, encode(PREFIX_INTAKE, intake_name, "confirm"))],
		[button(mn.BTN_CANCEL, encode(PREFIX_INTAKE, intake_name, "cancel"))],
	)


# --- statement layout mapping ----------------------------------------------------------------------


def layout_column_roles(column_index: int) -> dict[str, Any]:
	buttons = [
		button(label, encode(PREFIX_LAYOUT, column_index, role)) for role, label in mn.COLUMN_ROLES.items()
	]
	return markup(*rows(buttons))


# --- company switch --------------------------------------------------------------------------------


def company_chooser(companies: Sequence[str]) -> dict[str, Any]:
	"""Company names can be long Cyrillic; the data carries the index into the user's list."""
	buttons = [button(name[:40], encode("k", i)) for i, name in enumerate(companies)]
	return markup(*rows(buttons, per_row=1))


__all__ = [name for name in dir() if not name.startswith("_")]
