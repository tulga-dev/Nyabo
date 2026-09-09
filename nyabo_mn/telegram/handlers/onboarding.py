"""``/эхлэх`` onboarding state machine (docs/ARCHITECTURE.md §5.2).

Steps: VAT → 400M question → banks (multi-select) → currencies per bank → account numbers
→ inventory (yes: file/text intake → confirm) → accountant of record → summary → apply.
Answers accumulate in the Nyabo Chat State payload; nothing is written to the company
until the summary is confirmed, so an abandoned onboarding leaves no half-configured
company. On confirm the answers are persisted to Nyabo Company Settings and
``setup.provision_company.apply_onboarding`` creates the GL sub-accounts and ERPNext
Bank Accounts; when that module is not present yet the answers are still saved and the
admin is told.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import frappe
from frappe.utils import getdate, today

from nyabo_mn.core.models import Regime
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_error, log_event
from nyabo_mn.telegram import _deps, cards, files, keyboards
from nyabo_mn.telegram._deps import DependencyMissing
from nyabo_mn.telegram.context import Ctx

SETTINGS = "Nyabo Company Settings"
PREFIX = "onb"
BANKS = tuple(mn.BANK_NAMES_MN)
DEFAULT_CURRENCY = "MNT"


def _state(step: str) -> str:
	return f"{PREFIX}:{step}"


def _currency_code(text: str) -> str:
	"""ISO-4217-shaped code from what the accountant typed, or "" when it is not one.

	The code is put straight into callback data, which is colon-separated (``keyboards.encode``
	refuses a colon) and capped at 64 bytes, so anything but three ASCII letters is refused
	rather than sanitised into something the user did not type.
	"""
	code = (text or "").strip().upper()
	return code if len(code) == 3 and code.isascii() and code.isalpha() else ""


# --- entry -------------------------------------------------------------------------------------------


def handle_command(ctx: Ctx) -> Any:
	if not ctx.company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	if not (ctx.is_accountant or ctx.is_owner):
		ctx.reply(mn.MSG_NO_PERMISSION)
		return None
	return start(ctx, force=bool(ctx.args))


def start(ctx: Ctx, force: bool = False) -> Any:
	"""Begin at the VAT question; a completed company needs ``/эхлэх дахин`` (any argument)."""
	settings = _settings_doc(ctx.company)
	if settings.onboarding_completed and not force:
		ctx.reply(mn.MSG_ONBOARDING_ALREADY_DONE)
		return {"already": True}
	ctx.set_state(_state("vat"), {"company": ctx.company, "banks": []})
	_set_progress(settings, "vat")
	ctx.reply(mn.ONB_START.format(company=ctx.company))
	# The first question has no step behind it, so it is drawn without Буцах (UX-13).
	ctx.reply(mn.ONB_ASK_VAT, keyboards.onboarding_yes_no("vat", back=False))
	return {"step": "vat"}


def _settings_doc(company: str) -> Any:
	name = frappe.db.exists(SETTINGS, {"company": company})
	if name:
		return frappe.get_doc(SETTINGS, name)
	doc = frappe.get_doc({"doctype": SETTINGS, "company": company})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def _set_progress(settings: Any, step: str | None) -> None:
	settings.onboarding_state = step
	settings.flags.ignore_permissions = True
	settings.save()


def _advance(ctx: Ctx, payload: dict[str, Any], step: str) -> None:
	ctx.set_state(_state(step), payload)


# --- callbacks (buttons) -----------------------------------------------------------------------------


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``o:<step>:<value>``; the step must match the open state, else the tap is stale."""
	if len(parts) < 3:
		return None
	_prefix, step, value = parts[0], parts[1], parts[2]
	state, payload = ctx.get_state()
	if not state or not state.startswith(PREFIX + ":"):
		ctx.answer(mn.MSG_ESCAPE_STALE, show_alert=True)
		return None
	current = state.split(":", 1)[1]
	if step != current and not (step == "banks" and current == "banks"):
		ctx.answer(mn.MSG_ESCAPE_STALE, show_alert=True)
		return None
	handler = {
		"vat": _on_vat,
		"400m": _on_400m,
		"banks": _on_banks,
		"cur": _on_currency,
		"acct": _on_account_skip,
		"inv": _on_inventory,
		"micpa": _on_micpa_skip,
		"summary": _on_summary,
	}.get(step)
	if handler is None:
		return None
	return handler(ctx, payload, value)


def _on_vat(ctx: Ctx, payload: dict[str, Any], value: str) -> Any:
	payload["vat_registered"] = value == "yes"
	ctx.edit(
		ctx.callback_message_id,
		mn.ONB_ASK_VAT + " " + (mn.BTN_YES if value == "yes" else mn.BTN_NO),
		keyboards.empty_markup(),
	)
	ctx.reply(mn.ONB_VAT_YES_NOTE if payload["vat_registered"] else mn.ONB_VAT_NO_NOTE)
	_advance(ctx, payload, "400m")
	ctx.reply(mn.ONB_ASK_UNDER_400M, keyboards.onboarding_yes_no("400m"))
	return {"vat_registered": payload["vat_registered"]}


def _on_400m(ctx: Ctx, payload: dict[str, Any], value: str) -> Any:
	payload["under_400m"] = value == "yes"
	ctx.edit(
		ctx.callback_message_id,
		mn.ONB_ASK_UNDER_400M + " " + (mn.BTN_YES if value == "yes" else mn.BTN_NO),
		keyboards.empty_markup(),
	)
	payload["selected_banks"] = []
	_advance(ctx, payload, "banks")
	ctx.reply(mn.ONB_ASK_BANKS, keyboards.onboarding_banks([]))
	return {"under_400m": payload["under_400m"]}


def _on_banks(ctx: Ctx, payload: dict[str, Any], value: str) -> Any:
	selected: list[str] = list(payload.get("selected_banks") or [])
	if value != "done":
		bank = value.replace("_", " ")
		if bank not in BANKS:
			return None
		if bank in selected:
			selected.remove(bank)
		else:
			selected.append(bank)
		payload["selected_banks"] = selected
		_advance(ctx, payload, "banks")
		ctx.bot.edit_message_reply_markup(
			ctx.chat_id, ctx.callback_message_id, keyboards.onboarding_banks(selected)
		)
		return {"selected": selected}
	ctx.edit(
		ctx.callback_message_id,
		mn.ONB_ASK_BANKS + " " + (", ".join(selected) or mn.ONB_SUMMARY_BANKS_NONE),
		keyboards.empty_markup(),
	)
	payload["banks"] = [{"bank": b, "currencies": [], "accounts": {}} for b in selected]
	payload["bank_index"] = 0
	return _ask_currencies(ctx, payload)


def _ask_currencies(ctx: Ctx, payload: dict[str, Any]) -> Any:
	index = payload.get("bank_index", 0)
	banks = payload.get("banks") or []
	if index >= len(banks):
		return _ask_inventory(ctx, payload)
	# Each bank starts from a clean slate, typed codes included: an MNT/CNY account at one
	# bank says nothing about the next one.
	payload["cur_selected"] = []
	payload["cur_custom"] = []
	_advance(ctx, payload, "cur")
	ctx.reply(mn.ONB_ASK_CURRENCIES.format(bank=banks[index]["bank"]), keyboards.onboarding_currencies([]))
	return {"step": "cur", "bank": banks[index]["bank"]}


def _on_currency(ctx: Ctx, payload: dict[str, Any], value: str) -> Any:
	selected: list[str] = list(payload.get("cur_selected") or [])
	if value == "other":
		_advance(ctx, payload, "cur_other")
		ctx.reply(mn.ONB_ASK_CURRENCY_CODE, keyboards.onboarding_text_step("cur_other"))
		return None
	if value != "done":
		if value in selected:
			selected.remove(value)
		else:
			selected.append(value)
		payload["cur_selected"] = selected
		_advance(ctx, payload, "cur")
		ctx.bot.edit_message_reply_markup(
			ctx.chat_id,
			ctx.callback_message_id,
			keyboards.onboarding_currencies(selected, payload.get("cur_custom") or []),
		)
		return {"selected": selected}
	bank = payload["banks"][payload["bank_index"]]
	bank["currencies"] = selected or [DEFAULT_CURRENCY]
	ctx.edit(
		ctx.callback_message_id,
		mn.ONB_ASK_CURRENCIES.format(bank=bank["bank"]) + " " + "/".join(bank["currencies"]),
		keyboards.empty_markup(),
	)
	payload["acct_queue"] = list(bank["currencies"])
	return _ask_account_number(ctx, payload)


def _ask_account_number(ctx: Ctx, payload: dict[str, Any]) -> Any:
	queue: list[str] = payload.get("acct_queue") or []
	bank = payload["banks"][payload["bank_index"]]
	if not queue:
		payload["bank_index"] = payload.get("bank_index", 0) + 1
		return _ask_currencies(ctx, payload)
	_advance(ctx, payload, "acct")
	ctx.reply(
		mn.ONB_ASK_ACCOUNT_NUMBER.format(bank=bank["bank"], currency=queue[0]),
		keyboards.onboarding_skip("acct"),
	)
	return {"step": "acct", "currency": queue[0]}


def _store_account_number(ctx: Ctx, payload: dict[str, Any], number: str | None) -> Any:
	queue: list[str] = payload.get("acct_queue") or []
	bank = payload["banks"][payload["bank_index"]]
	if queue:
		currency = queue.pop(0)
		if number:
			bank["accounts"][currency] = number
	payload["acct_queue"] = queue
	return _ask_account_number(ctx, payload)


def _on_account_skip(ctx: Ctx, payload: dict[str, Any], value: str) -> Any:
	ctx.bot.edit_message_reply_markup(ctx.chat_id, ctx.callback_message_id, keyboards.empty_markup())
	return _store_account_number(ctx, payload, None)


def _ask_inventory(ctx: Ctx, payload: dict[str, Any]) -> Any:
	_advance(ctx, payload, "inv")
	ctx.reply(mn.ONB_ASK_INVENTORY, keyboards.onboarding_yes_no("inv"))
	return {"step": "inv"}


def _on_inventory(ctx: Ctx, payload: dict[str, Any], value: str) -> Any:
	payload["has_inventory"] = value == "yes"
	ctx.edit(
		ctx.callback_message_id,
		mn.ONB_ASK_INVENTORY + " " + (mn.BTN_YES if value == "yes" else mn.BTN_NO),
		keyboards.empty_markup(),
	)
	if payload["has_inventory"]:
		return _ask_inventory_list(ctx, payload)
	return _ask_accountant(ctx, payload)


def _forget_inventory_list(payload: dict[str, Any]) -> None:
	"""Drop every trace of a list that was read but never filed (the draft intake included).

	``cards.onboarding_summary`` and ``finish`` read whatever the payload still holds, so a
	count left behind by a preview the accountant walked away from would be reported as
	opening stock that exists.
	"""
	for key in ("intake", "inventory_count", "inventory_total"):
		payload.pop(key, None)


def _ask_inventory_list(ctx: Ctx, payload: dict[str, Any]) -> Any:
	"""The step the founder was trapped in: optional, so it is drawn with Алгасах and Буцах."""
	_advance(ctx, payload, "inv_wait")
	ctx.reply(mn.ONB_INVENTORY_HOW, keyboards.onboarding_text_step("inv_wait", back=True, skip=True))
	return {"step": "inv_wait"}


def _ask_accountant(ctx: Ctx, payload: dict[str, Any]) -> Any:
	_advance(ctx, payload, "acc_name")
	ctx.reply(mn.ONB_ASK_ACCOUNTANT_NAME, keyboards.onboarding_text_step("acc_name", skip=True))
	return {"step": "acc_name"}


def _on_micpa_skip(ctx: Ctx, payload: dict[str, Any], value: str) -> Any:
	ctx.bot.edit_message_reply_markup(ctx.chat_id, ctx.callback_message_id, keyboards.empty_markup())
	payload["micpa"] = ""
	return _show_summary(ctx, payload)


def _show_summary(ctx: Ctx, payload: dict[str, Any]) -> Any:
	_advance(ctx, payload, "summary")
	ctx.reply(
		cards.onboarding_summary(payload, payload.get("company") or ctx.company or "")
		+ "\n"
		+ mn.ONB_CONFIRM_SUMMARY,
		keyboards.onboarding_confirm("summary"),
	)
	return {"step": "summary"}


def _on_summary(ctx: Ctx, payload: dict[str, Any], value: str) -> Any:
	if value != "confirm":
		ctx.clear_state()
		ctx.edit(ctx.callback_message_id, mn.MSG_CANCELLED, keyboards.empty_markup())
		return {"cancelled": True}
	ctx.bot.edit_message_reply_markup(ctx.chat_id, ctx.callback_message_id, keyboards.empty_markup())
	return finish(ctx, payload)


# --- inventory intake --------------------------------------------------------------------------------


def _inventory_from_message(ctx: Ctx) -> tuple[list[dict[str, Any]], str, str | None]:
	"""``(items, source, file_url)``: the rows, and the workbook they were read out of.

	The upload is kept, not thrown away. ``post_intake`` submits an opening Journal Entry (or
	a Stock Reconciliation) for these numbers, and every posted document must carry the primary
	document behind it — Law on Accounting art. 13.7, enforced by ``compliance.hooks``. The
	receipt path is the precedent (``handlers.receipt._intake``): ``files.save_document`` writes
	a Nyabo Document with the bytes attached as a private File, and the retention date is set by
	the ``before_insert`` hook on that doctype.

	A typed list has no file and none is invented: the intake's own rows *are* the record, and
	the opening entry points at the intake (``nyabo_primary_document_ref``).
	"""
	if ctx.document:
		document = ctx.document
		content, mime, name = files.download_telegram_file(
			ctx.bot,
			document.get("file_id"),
			document.get("mime_type"),
			document.get("file_name") or "inventory.xlsx",
		)
		# Parsed first: an unreadable file is answered with the step's own message and leaves
		# no Nyabo Document behind for an admin to wonder about.
		items = _deps.inventory_parse_table(content, name)
		return items, "excel", _save_inventory_file(ctx, content, name, mime)
	return _deps.inventory_parse_text(ctx.text), "text", None


def _save_inventory_file(ctx: Ctx, content: bytes, name: str, mime: str | None) -> str | None:
	"""The stock workbook as a Nyabo Document; returns its ``file_url`` for the intake."""
	try:
		doc = files.save_document(
			ctx.company or "",
			ctx.sender,
			"inventory",
			content,
			name,
			mime=mime,
			telegram_file_id=(ctx.document or {}).get("file_id"),
			chat_id=ctx.chat_id,
			message_id=ctx.message_id,
			sender_user=ctx.user,
		)
	except files.DuplicateDocument as dup:
		# The same workbook sent twice (Буцах, then send it again): the first Nyabo Document is
		# the record, so the intake points at that one rather than storing a second copy.
		log_event("telegram.onboarding.inventory_file_duplicate", existing=dup.existing_name)
		return frappe.db.get_value(files.DOCUMENT, dup.existing_name, "file")
	log_event("telegram.onboarding.inventory_file_saved", document=doc.name, company=ctx.company)
	return doc.file


def _inventory_prompt() -> dict[str, Any]:
	"""What a refused inventory line is answered with: the shape wanted, and the ways out.

	UX-13: the step used to reply with a bare sentence and leave the state untouched with no
	keyboard, so a user whose line could not be read had nothing on screen to press.
	"""
	return keyboards.onboarding_text_step("inv_wait", back=True, skip=True)


def _on_inventory_input(ctx: Ctx, payload: dict[str, Any]) -> Any:
	if not ctx.document and not ctx.text:
		ctx.reply(mn.MSG_ONBOARDING_INVENTORY_NEED_FILE, _inventory_prompt())
		return None
	if ctx.document:
		# "We only recommend using this method when a response from the bot will take a
		# noticeable amount of time to arrive" (sendChatAction): downloading and parsing a
		# workbook does, typing a line does not.
		_typing(ctx)
	# The guard covers the write, not only the read: ``create_intake`` re-validates the rows
	# it is handed (``as_rows``) and raises the same IntakeParseError from there, which used to
	# leave the step through the router's generic apology.
	try:
		items, source, file_url = _inventory_from_message(ctx)
		if not items:
			ctx.reply(
				mn.ONB_INVENTORY_PARSE_ERROR.format(error=mn.MSG_ONBOARDING_INVENTORY_NEED_FILE),
				_inventory_prompt(),
			)
			return None
		intake = _deps.inventory_create_intake(
			ctx.company or payload.get("company") or "", items, source, ctx.user, file_url=file_url
		)
	except DependencyMissing:
		raise
	except _deps.intake_parse_error() as exc:
		# Nyabo's own Mongolian sentence about the line it could not read: it says more than the
		# generic message, and it is safe to show (SEC-09 — the module builds it, not the file).
		log_event(
			"telegram.onboarding.inventory_refused",
			level="warning",
			company=ctx.company,
			source="excel" if ctx.document else "text",
		)
		ctx.reply(
			mn.ONB_INVENTORY_PARSE_ERROR.format(error=getattr(exc, "message_mn", "") or str(exc)),
			_inventory_prompt(),
		)
		return None
	except Exception as exc:
		# SEC-09: a parser exception carries file paths, sheet names and library internals,
		# and the file itself is untrusted input. The user gets the Mongolian instruction;
		# the detail goes to the log, where an admin can read it.
		log_error(
			"telegram.onboarding.inventory_parse_failed",
			exc,
			company=ctx.company,
			user=ctx.user,
			source="excel" if ctx.document else "text",
		)
		# The state stands and the buttons come back with the message: a step that cannot read
		# the input must still be answerable (UX-13).
		ctx.reply(mn.ONB_INVENTORY_PARSE_FAILED, _inventory_prompt())
		return None
	payload["intake"] = intake
	payload["inventory_count"] = len(items)
	payload["inventory_total"] = str(cards.inventory_total(items))
	# A list given after Алгасах (Буцах brings the step back) undoes the skip.
	payload.pop("inventory_skipped", None)
	_advance(ctx, payload, "inv_confirm")
	ctx.reply(cards.inventory_preview(items), keyboards.intake_confirm(intake))
	return {"intake": intake, "items": len(items)}


def handle_intake_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``i:<NYI>:confirm|cancel`` — post the opening stock, or go back to the file/text prompt."""
	if len(parts) < 3:
		return None
	intake, action = parts[1], parts[2]
	state, payload = ctx.get_state()
	if state != _state("inv_confirm") or payload.get("intake") != intake:
		ctx.answer(mn.MSG_CANCELLED)
		return None
	if action == "cancel":
		ctx.bot.edit_message_reply_markup(ctx.chat_id, ctx.callback_message_id, keyboards.empty_markup())
		_ask_inventory_list(ctx, payload)
		return {"cancelled": True}
	result = _deps.inventory_post_intake(intake, ctx.user) or {}
	docs = result.get("created") or result.get("docs") or list(result.values())
	ctx.edit(
		ctx.callback_message_id,
		mn.ONB_INVENTORY_POSTED.format(docs=", ".join(str(d) for d in docs) if docs else intake),
		keyboards.empty_markup(),
	)
	payload["inventory_posted"] = True
	return _ask_accountant(ctx, payload)


# --- typed answers -----------------------------------------------------------------------------------


def handle_state(ctx: Ctx, state: str, payload: dict[str, Any]) -> Any:
	step = state.split(":", 1)[1] if ":" in state else ""
	if step == "acct":
		return _store_account_number(ctx, payload, ctx.text.strip()[:60] or None)
	if step == "cur_other":
		code = _currency_code(ctx.text)
		selected = list(payload.get("cur_selected") or [])
		custom = list(payload.get("cur_custom") or [])
		bank = payload["banks"][payload["bank_index"]]["bank"]
		if not code:
			_advance(ctx, payload, "cur")
			ctx.reply(mn.ONB_CURRENCY_CODE_INVALID, keyboards.onboarding_currencies(selected, custom))
			return {"selected": selected}
		if code not in selected:
			selected.append(code)
		if code not in custom:
			custom.append(code)
		payload["cur_selected"] = selected
		payload["cur_custom"] = custom
		_advance(ctx, payload, "cur")
		# UX-11: say the code landed, and redraw the keyboard so it is there to untoggle.
		ctx.reply(
			mn.ONB_CURRENCY_ADDED.format(currency=code) + "\n" + mn.ONB_ASK_CURRENCIES.format(bank=bank),
			keyboards.onboarding_currencies(selected, custom),
		)
		return {"selected": selected}
	if step == "inv_wait":
		return _on_inventory_input(ctx, payload)
	if step == "acc_name":
		payload["accountant_name"] = ctx.text.strip()[:140]
		return _ask_micpa(ctx, payload)
	if step == "micpa":
		payload["micpa"] = ctx.text.strip()[:60]
		return _show_summary(ctx, payload)
	# A button step got text: repeat the question.
	return _repeat(ctx, step, payload)


def _ask_micpa(ctx: Ctx, payload: dict[str, Any]) -> Any:
	_advance(ctx, payload, "micpa")
	ctx.reply(mn.ONB_ASK_MICPA, keyboards.onboarding_skip("micpa"))
	return {"step": "micpa"}


def _repeat(ctx: Ctx, step: str, payload: dict[str, Any]) -> Any:
	"""Re-offer the question the chat is on, with its buttons.

	Every waiting step is covered, not only the button ones: this is what Буцах re-draws and
	what a step answers with when it cannot read what was typed, so a user is never left with
	a message they have no way to answer (UX-13).
	"""
	if step == "vat":
		ctx.reply(mn.ONB_ASK_VAT, keyboards.onboarding_yes_no("vat", back=False))
	elif step == "400m":
		ctx.reply(mn.ONB_ASK_UNDER_400M, keyboards.onboarding_yes_no("400m"))
	elif step == "banks":
		ctx.reply(mn.ONB_ASK_BANKS, keyboards.onboarding_banks(payload.get("selected_banks") or []))
	elif step == "cur":
		bank = payload["banks"][payload["bank_index"]]["bank"]
		ctx.reply(
			mn.ONB_ASK_CURRENCIES.format(bank=bank),
			keyboards.onboarding_currencies(
				payload.get("cur_selected") or [], payload.get("cur_custom") or []
			),
		)
	elif step == "cur_other":
		ctx.reply(mn.ONB_ASK_CURRENCY_CODE, keyboards.onboarding_text_step("cur_other"))
	elif step == "acct":
		queue: list[str] = payload.get("acct_queue") or []
		bank = payload["banks"][payload.get("bank_index", 0)]["bank"]
		ctx.reply(
			mn.ONB_ASK_ACCOUNT_NUMBER.format(bank=bank, currency=queue[0] if queue else DEFAULT_CURRENCY),
			keyboards.onboarding_skip("acct"),
		)
	elif step == "inv":
		ctx.reply(mn.ONB_ASK_INVENTORY, keyboards.onboarding_yes_no("inv"))
	elif step == "inv_wait":
		ctx.reply(mn.ONB_INVENTORY_HOW, keyboards.onboarding_text_step("inv_wait", back=True, skip=True))
	elif step == "inv_confirm":
		ctx.reply(mn.ONB_CONFIRM_SUMMARY, keyboards.intake_confirm(payload.get("intake", "")))
	elif step == "acc_name":
		ctx.reply(mn.ONB_ASK_ACCOUNTANT_NAME, keyboards.onboarding_text_step("acc_name", skip=True))
	elif step == "micpa":
		ctx.reply(mn.ONB_ASK_MICPA, keyboards.onboarding_skip("micpa"))
	elif step == "summary":
		return _show_summary(ctx, payload)
	else:
		ctx.clear_state()
	return None


# --- escapes (UX-13) ---------------------------------------------------------------------------------

# Буцах: the question each step goes back to. A step that is not here has nothing to return to
# (the first question), or sits inside a queue the wizard walks per bank and per currency, where
# "the previous question" is the one the queue is already re-asking.
BACK_STEPS = {
	"400m": "vat",
	"banks": "400m",
	"cur": "banks",
	"cur_other": "cur",
	"acct": "cur",
	"inv": "banks",
	"inv_wait": "inv",
	"inv_confirm": "inv_wait",
	"acc_name": "inv",
	"micpa": "acc_name",
	"summary": "micpa",
}


def _back_target(step: str, payload: dict[str, Any]) -> str | None:
	"""The step Буцах returns to, for a wizard whose shape depends on the answers so far.

	``acc_name`` is the one branching step: the accountant's name is reached from the stock
	list when the company said Тийм and from the Тийм/Үгүй question itself when it said Үгүй,
	so a static table would send half the users to a question they never saw. It was drawn
	with Буцах and had no entry at all, which answered «this is the first step» — false, and
	the reason this walk is now tested button by button.

	A list that has already been posted is not offered again: the opening stock is in the
	ledger and only a reversal takes it back (principle 5), so Буцах goes to the question.
	"""
	if step == "acc_name":
		if payload.get("has_inventory") and not payload.get("inventory_posted"):
			return "inv_wait"
		return "inv"
	return BACK_STEPS.get(step)


def _go_to(ctx: Ctx, payload: dict[str, Any], step: str) -> Any:
	_advance(ctx, payload, step)
	return _repeat(ctx, step, payload)


def handle_escape(ctx: Ctx, state: str, payload: dict[str, Any], verb: str) -> bool:
	"""Цуцлах / Буцах / Алгасах inside the wizard; False leaves it to the plain cancel.

	Cancel is left to the caller on purpose: nothing is written to the company until the
	summary is confirmed, so abandoning the wizard needs no clean-up beyond the chat state.
	"""
	step = state.split(":", 1)[1] if ":" in state else ""
	if verb == keyboards.ESCAPE_BACK:
		target = _back_target(step, payload)
		if not target:
			return False
		_go_to(ctx, payload, target)
		return True
	if verb == keyboards.ESCAPE_SKIP:
		return _skip_step(ctx, payload, step)
	return False


def _skip_step(ctx: Ctx, payload: dict[str, Any], step: str) -> bool:
	"""True when the step is genuinely optional; the VAT regime and the summary never are."""
	if step == "banks":
		payload["selected_banks"] = []
		payload["banks"] = []
		payload["bank_index"] = 0
		_ask_inventory(ctx, payload)
		return True
	if step == "cur":
		bank = payload["banks"][payload.get("bank_index", 0)]
		bank["currencies"] = [DEFAULT_CURRENCY]
		payload["acct_queue"] = list(bank["currencies"])
		_ask_account_number(ctx, payload)
		return True
	if step == "cur_other":
		_go_to(ctx, payload, "cur")
		return True
	if step == "acct":
		_store_account_number(ctx, payload, None)
		return True
	if step == "inv":
		payload["has_inventory"] = False
		ctx.reply(mn.ONB_INVENTORY_SKIPPED)
		_ask_accountant(ctx, payload)
		return True
	if step in ("inv_wait", "inv_confirm"):
		# The founder's case: «алгасах» here leaves the opening stock for later and the wizard
		# goes on. ``has_inventory`` keeps the answer they gave — the company does hold stock,
		# it is the list that is missing — so provisioning still sets the inventory accounts up.
		# The numbers of a list that was parsed but never filed go with it: a summary that
		# still read them would report an opening stock the company does not have.
		payload["inventory_skipped"] = True
		_forget_inventory_list(payload)
		ctx.reply(mn.ONB_INVENTORY_SKIPPED)
		_ask_accountant(ctx, payload)
		return True
	if step == "acc_name":
		payload["accountant_name"] = ""
		_ask_micpa(ctx, payload)
		return True
	if step == "micpa":
		payload["micpa"] = ""
		_show_summary(ctx, payload)
		return True
	return False


def _typing(ctx: Ctx) -> None:
	"""Best-effort ``sendChatAction``; a missing status line must never cost the answer."""
	try:
		ctx.bot.send_chat_action(ctx.chat_id)
	except Exception as exc:
		log_event("telegram.chat_action_failed", level="warning", error=type(exc).__name__)


# --- finish ------------------------------------------------------------------------------------------


def fiscal_year_start(on: dt.date | None = None) -> dt.date:
	"""Fiscal year = calendar year (Law on Accounting art. 9); the regime row starts 1 January."""
	day = on or getdate(today())
	return dt.date(day.year, 1, 1)


def bank_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for bank in payload.get("banks") or []:
		for currency in bank.get("currencies") or [DEFAULT_CURRENCY]:
			rows.append(
				{
					"bank": bank["bank"],
					"currency": currency,
					"account_number": (bank.get("accounts") or {}).get(currency) or "",
				}
			)
	return rows


def persist_settings(company: str, payload: dict[str, Any]) -> Any:
	"""Write the answers to Nyabo Company Settings; idempotent on regime and bank rows."""
	settings = _settings_doc(company)
	regime = Regime.VAT_PAYER if payload.get("vat_registered") else Regime.SIMPLIFIED_1PCT
	effective_from = fiscal_year_start()
	try:
		_deps.set_regime(company, regime.value, effective_from)
		settings.reload()
	except DependencyMissing:
		if not any(
			r.regime == regime.value and getdate(r.effective_from) == effective_from
			for r in settings.get("regimes") or []
		):
			settings.append(
				"regimes", {"regime": regime.value, "effective_from": effective_from, "note": "onboarding"}
			)
	settings.expects_under_400m_2027 = 1 if payload.get("under_400m") else 0
	existing = {(r.bank, r.currency, r.account_number or "") for r in settings.get("bank_accounts") or []}
	for row in bank_rows(payload):
		key = (row["bank"], row["currency"], row["account_number"])
		if key not in existing:
			settings.append("bank_accounts", row)
			existing.add(key)
	settings.has_inventory = 1 if payload.get("has_inventory") else 0
	settings.accountant_of_record_name = payload.get("accountant_name") or settings.accountant_of_record_name
	settings.accountant_micpa_permit = payload.get("micpa") or settings.accountant_micpa_permit
	settings.onboarding_completed = 1
	settings.onboarding_state = None
	settings.flags.ignore_permissions = True
	settings.save()
	return settings


def finish(ctx: Ctx, payload: dict[str, Any]) -> Any:
	company = payload.get("company") or ctx.company or ""
	ctx.clear_state()
	persist_settings(company, payload)
	applied: dict[str, Any] | None = None
	try:
		applied = _deps.apply_onboarding(
			company,
			bool(payload.get("vat_registered")),
			bank_rows(payload),
			bool(payload.get("has_inventory")),
			payload.get("accountant_name") or "",
			payload.get("micpa") or "",
		)
	except DependencyMissing as exc:
		log_event("telegram.onboarding.apply_missing", level="warning", company=company, error=str(exc))
		ctx.reply(mn.MSG_ONBOARDING_APPLY_PENDING)
	ctx.reply(cards.onboarding_summary(payload, company))
	log_event("telegram.onboarding.done", company=company, user=ctx.user, applied=bool(applied))
	return {"company": company, "applied": applied, "payload": payload}
