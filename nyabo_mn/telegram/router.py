"""Update dispatch (docs/ARCHITECTURE.md §5.1).

Order: callback query → command → conversation state → content type. Everything runs
as the linked Frappe user (``frappe.set_user``) so ERPNext permissions and the audit
trail name a real person, never Guest. Unlinked senders only get the link flow. A
handler exception never leaks a traceback into Telegram: the user sees
``MSG_ERROR_ADMIN_NOTIFIED`` and the admins get a one-line notice; a callback query is
always answered so the client stops its spinner.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import frappe

from nyabo_mn.config import get_settings
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_error, log_event
from nyabo_mn.telegram import api, keyboards
from nyabo_mn.telegram import state as chat_state
from nyabo_mn.telegram._deps import DependencyMissing
from nyabo_mn.telegram.context import Ctx, from_update

LINK_CODE_RE = re.compile(r"^\d{6}$")

# Commands a sender may use before being linked (§5.1) and admin bootstrap commands.
PUBLIC_COMMANDS = ("/start", "/whoami")
ADMIN_BOOTSTRAP_COMMANDS = ("/link", "/status", "/whoami", "/start")


def _commands() -> dict[str, Callable[[Ctx], Any]]:
	from nyabo_mn.telegram.handlers import (
		accounts,
		admin,
		close,
		company,
		menu,
		onboarding,
		policy,
		quality,
		start,
	)

	return {
		"/start": start.handle_start,
		"/whoami": start.handle_whoami,
		"/меню": menu.handle_menu,
		"/menu": menu.handle_menu,
		"/тусламж": menu.handle_help,
		"/help": menu.handle_help,
		"/хаалт": close.handle_command,
		"/данс": accounts.handle_command,
		"/чанар": quality.handle_command,
		"/бодлого": policy.handle_command,
		"/компани": company.handle_command,
		"/эхлэх": onboarding.handle_command,
		"/link": admin.handle_link,
		"/status": admin.handle_status,
	}


def _callback_handlers() -> dict[str, Callable[[Ctx, list[str]], Any]]:
	from nyabo_mn.telegram.handlers import approve, bank, close, company, correct, onboarding, statement

	return {
		keyboards.PREFIX_PROPOSAL: approve.handle_callback,
		keyboards.PREFIX_BANK: bank.handle_callback,
		keyboards.PREFIX_CLOSE: close.handle_callback,
		keyboards.PREFIX_CORRECTION: correct.handle_callback,
		keyboards.PREFIX_ONBOARDING: onboarding.handle_callback,
		keyboards.PREFIX_INTAKE: onboarding.handle_intake_callback,
		keyboards.PREFIX_LAYOUT: statement.handle_layout_callback,
		"k": company.handle_callback,
	}


def _state_handlers() -> dict[str, Callable[[Ctx, str, dict[str, Any]], Any]]:
	from nyabo_mn.telegram.handlers import approve, bank, correct, onboarding, statement

	return {
		"onb": onboarding.handle_state,
		"acc_search": approve.handle_state,
		"reject_text": approve.handle_state,
		"correct": correct.handle_state,
		"layout": statement.handle_state,
		"bank_find": bank.handle_state,
	}


def handle_update(update: dict[str, Any]) -> dict[str, Any]:
	"""Entry point for the ``short`` queue; returns a small dict for tests and job logs."""
	settings = get_settings()
	bot = api.get_bot()
	ctx = from_update(update, bot, settings)
	if ctx is None:
		return {"handled": False, "reason": "ignored update kind"}
	previous_user = frappe.session.user
	outcome: dict[str, Any] = {"handled": True}
	try:
		ctx.link = chat_state.get_link(ctx.telegram_id)
		if ctx.link is None:
			outcome["result"] = _handle_unlinked(ctx)
			return outcome
		frappe.set_user(ctx.link.user)
		ctx.company = chat_state.active_company(ctx.link)
		outcome["result"] = _dispatch(ctx)
		return outcome
	except DependencyMissing as exc:
		log_error("telegram.dependency_missing", exc, chat_id=ctx.chat_id)
		ctx.reply(mn.MSG_FEATURE_UNAVAILABLE)
		notify_admins(
			bot,
			settings,
			mn.MSG_ADMIN_ERROR_NOTICE.format(event="dependency", chat_id=ctx.chat_id, error=str(exc)[:200]),
		)
		outcome["error"] = "dependency_missing"
		return outcome
	except Exception as exc:
		log_error("telegram.handler_failed", exc, chat_id=ctx.chat_id, telegram_id=ctx.telegram_id)
		try:
			ctx.reply(mn.MSG_ERROR_ADMIN_NOTIFIED)
		except Exception as reply_exc:  # the bot itself may be down; nothing more to do here
			log_event("telegram.reply_failed", level="error", error=repr(reply_exc))
		notify_admins(
			bot,
			settings,
			mn.MSG_ADMIN_ERROR_NOTICE.format(event="handler", chat_id=ctx.chat_id, error=repr(exc)[:200]),
		)
		outcome["error"] = repr(exc)
		return outcome
	finally:
		try:
			ctx.answer()
		except Exception as answer_exc:
			log_event("telegram.answer_failed", level="warning", error=repr(answer_exc))
		frappe.set_user(previous_user)


def _handle_unlinked(ctx: Ctx) -> Any:
	from nyabo_mn.telegram.handlers import admin, link, start

	command = ctx.command
	if ctx.is_admin and command in ADMIN_BOOTSTRAP_COMMANDS:
		# Site admins listed in ADMIN_TELEGRAM_IDS can issue codes before anyone is linked.
		frappe.set_user("Administrator")
		return _commands()[command](ctx)
	if command == "/start":
		return start.handle_start(ctx)
	if command == "/whoami":
		return start.handle_whoami(ctx)
	if not ctx.is_callback and LINK_CODE_RE.match(ctx.text):
		return link.handle_code(ctx)
	if ctx.is_callback:
		return None
	ctx.reply(mn.MSG_NOT_LINKED)
	return admin.noop()


def _dispatch(ctx: Ctx) -> Any:
	if ctx.is_callback:
		parts = keyboards.decode(ctx.callback_data)
		handler = _callback_handlers().get(parts[0]) if parts else None
		if handler is None:
			log_event("telegram.callback.unknown", level="warning", data=ctx.callback_data[:64])
			return None
		return handler(ctx, parts)

	command = ctx.command
	if command:
		handler = _commands().get(command)
		if handler is None:
			ctx.reply(mn.MSG_UNKNOWN_COMMAND)
			return None
		# A command always leaves the previous conversation; otherwise /меню mid-onboarding
		# would be swallowed as an answer to the current question.
		ctx.clear_state()
		return handler(ctx)

	if not ctx.is_callback and LINK_CODE_RE.match(ctx.text):
		from nyabo_mn.telegram.handlers import link

		return link.handle_code(ctx)

	state_name, payload = ctx.get_state()
	if state_name:
		prefix = state_name.split(":", 1)[0]
		handler = _state_handlers().get(prefix)
		if handler is not None:
			return handler(ctx, state_name, payload)
		ctx.clear_state()

	from nyabo_mn.telegram.handlers import question, receipt, statement

	if ctx.photo:
		return receipt.handle_photo(ctx)
	if ctx.document:
		mime = (ctx.document.get("mime_type") or "").lower()
		if mime.startswith("image/"):
			return receipt.handle_image_document(ctx)
		return statement.handle_document(ctx)
	if ctx.text:
		return question.handle_text(ctx)
	ctx.reply(mn.MSG_SEND_PHOTO_HINT)
	return None


def notify_admins(bot: Any, settings: Any, text: str) -> None:
	"""Short plain-text notice to every ADMIN_TELEGRAM_IDS chat; failures are logged, not raised."""
	try:
		admin_ids = settings.admin_telegram_ids
	except ValueError as exc:
		log_event("telegram.admin_ids_invalid", level="warning", error=str(exc))
		return
	for admin_id in sorted(admin_ids):
		try:
			bot.send_message(admin_id, text)
		except Exception as exc:
			log_event("telegram.notify_admin_failed", level="warning", admin=admin_id, error=repr(exc))
