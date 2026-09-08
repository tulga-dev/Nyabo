"""Bank statement intake and the column-mapping conversation (docs/ARCHITECTURE.md §5.4).

An xlsx/csv/pdf becomes a ``Nyabo Document(bank_statement)`` and ``import_statement``
runs on the ``long`` queue. When the importer does not recognise the layout it returns
``status = "unknown_layout"`` with the header row and a preview; the accountant is then
asked, one column at a time, which role the column plays, and the answer is saved as a
``Nyabo Bank Layout`` with ``verified = 0`` so nothing is imported on a guessed mapping
(D-008). A layout that was already mapped but not verified comes back as
``status = "unverified_layout"``: the admin verifies that row, the accountant is not asked
the same questions again. Anything the importer refuses (no bank account, unreadable file)
arrives as an exception whose ``message_mn`` is the reply.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe

from nyabo_mn.i18n import mn
from nyabo_mn.log import log_error, log_event
from nyabo_mn.telegram import _deps, api, files, keyboards
from nyabo_mn.telegram._deps import DependencyMissing
from nyabo_mn.telegram.context import Ctx

IMPORT_METHOD = "nyabo_mn.telegram.handlers.statement.run_import"
STATE_PREFIX = "layout"
BANK_LAYOUT = "Nyabo Bank Layout"
LAYOUT_BANKS = ("Khan Bank", "TDB", "Golomt Bank", "Trans Bank", "XacBank")
MAX_PREVIEW_ROWS = 3


# --- intake ------------------------------------------------------------------------------------------


def handle_document(ctx: Ctx) -> Any:
	document = ctx.document or {}
	filename = document.get("file_name") or "statement"
	mime = (document.get("mime_type") or "").lower()
	if not ctx.company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	try:
		kind = files.kind_for(mime or files.guess_mime(filename), filename)
	except files.UnsupportedFile:
		ctx.reply(mn.MSG_UNSUPPORTED_FILE)
		return None
	if kind == "receipt":
		from nyabo_mn.telegram.handlers import receipt

		return receipt.handle_image_document(ctx)
	if int(document.get("file_size") or 0) > files.MAX_FILE_BYTES:
		ctx.reply(mn.MSG_FILE_TOO_LARGE.format(mb=files.MAX_FILE_BYTES // (1024 * 1024)))
		return None
	try:
		content, mime, name = files.download_telegram_file(
			ctx.bot, document.get("file_id"), mime or None, filename
		)
		doc = files.save_document(
			ctx.company,
			ctx.sender,
			"bank_statement",
			content,
			name,
			mime=mime,
			telegram_file_id=document.get("file_id"),
			chat_id=ctx.chat_id,
			message_id=ctx.message_id,
			sender_user=ctx.user,
		)
	except files.FileTooLarge:
		ctx.reply(mn.MSG_FILE_TOO_LARGE.format(mb=files.MAX_FILE_BYTES // (1024 * 1024)))
		return None
	except files.DuplicateDocument as dup:
		ctx.reply(mn.MSG_DUPLICATE_DOCUMENT)
		return {"duplicate": dup.existing_name}
	ctx.reply(mn.MSG_STATEMENT_RECEIVED)
	frappe.enqueue(
		IMPORT_METHOD,
		queue="long",
		timeout=900,
		document_name=doc.name,
		chat_id=ctx.chat_id,
		enqueue_after_commit=True,
	)
	return {"document": doc.name}


def run_import(document_name: str, chat_id: int | str) -> dict[str, Any]:
	"""Worker: import, then report or start the mapping conversation. Never raises into RQ."""
	bot = api.get_bot()
	try:
		summary = _deps.import_statement(document_name) or {}
	except DependencyMissing as exc:
		log_error("telegram.statement.dependency_missing", exc, document=document_name)
		bot.send_message(chat_id, mn.MSG_FEATURE_UNAVAILABLE)
		return {"ok": False}
	except Exception as exc:
		# BankImportError (no bank account, unreadable file, no lines) carries the card text.
		log_error("telegram.statement.import_failed", exc, document=document_name)
		bot.send_message(chat_id, getattr(exc, "message_mn", None) or mn.MSG_ERROR_ADMIN_NOTIFIED)
		return {"ok": False}
	status = summary.get("status")
	if status == "unknown_layout":
		start_layout_mapping(bot, chat_id, document_name, summary)
		return {"ok": True, "mapping": True}
	if status == "unverified_layout":
		bot.send_message(chat_id, mn.MSG_STATEMENT_LAYOUT_UNVERIFIED)
		return {"ok": True, "unverified": True}
	bot.send_message(
		chat_id,
		mn.MSG_STATEMENT_IMPORTED.format(
			bank=summary.get("bank") or "—",
			count=summary.get("count", 0),
			new=summary.get("new", 0),
			dup=summary.get("duplicates", summary.get("dup", 0)),
			matched=summary.get("matched", 0),
			unmatched=summary.get("unmatched", 0),
		),
	)
	# The unmatched lines are carded by matching.match.run while the import is still
	# running (it is what decides which line is unmatched); nothing to send here.
	return {"ok": True, "summary": summary}


# --- layout mapping ----------------------------------------------------------------------------------


def _preview_text(headers: list[str], rows: list[list[Any]]) -> str:
	lines = [" | ".join(str(h) for h in headers)]
	for row in rows[:MAX_PREVIEW_ROWS]:
		lines.append(" | ".join("" if cell is None else str(cell) for cell in row))
	return "\n".join(lines)


def start_layout_mapping(bot: Any, chat_id: int | str, document_name: str, summary: dict[str, Any]) -> None:
	headers = [str(h) for h in (summary.get("headers") or [])]
	if not headers:
		bot.send_message(chat_id, mn.MSG_UNSUPPORTED_FILE)
		return
	from nyabo_mn.telegram import state as chat_state

	chat_state.set_state(
		chat_id,
		f"{STATE_PREFIX}:0",
		{
			"document": document_name,
			"headers": headers,
			"mapping": {},
			"bank": summary.get("bank"),
			"company": summary.get("company"),
		},
	)
	bot.send_message(
		chat_id,
		mn.MSG_STATEMENT_LAYOUT_UNKNOWN.format(preview=_preview_text(headers, summary.get("preview") or [])),
	)
	_ask_column(bot, chat_id, headers, 0)


def _ask_column(bot: Any, chat_id: int | str, headers: list[str], index: int) -> None:
	bot.send_message(
		chat_id,
		mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header=headers[index]),
		reply_markup=keyboards.layout_column_roles(index),
	)


def handle_layout_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``l:<column index>:<role>``; roles come from ``mn.COLUMN_ROLES``."""
	state, payload = ctx.get_state()
	if not state or not state.startswith(STATE_PREFIX):
		ctx.answer(mn.MSG_CANCELLED)
		return None
	if not ctx.is_accountant:
		ctx.answer(mn.MSG_NO_PERMISSION, show_alert=True)
		return None
	try:
		index = int(parts[1])
		role = parts[2]
	except (IndexError, ValueError):
		return None
	headers: list[str] = payload.get("headers") or []
	if index >= len(headers) or role not in mn.COLUMN_ROLES:
		return None
	mapping: dict[str, str] = dict(payload.get("mapping") or {})
	if role != "ignore":
		mapping[role] = headers[index]
	payload["mapping"] = mapping
	ctx.edit(
		ctx.callback_message_id,
		mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header=headers[index]) + " " + mn.COLUMN_ROLES[role],
		keyboards.empty_markup(),
	)
	next_index = index + 1
	if next_index < len(headers):
		ctx.set_state(f"{STATE_PREFIX}:{next_index}", payload)
		_ask_column(ctx.bot, ctx.chat_id, headers, next_index)
		return {"next": next_index}
	ctx.clear_state()
	return save_layout(ctx, payload)


def save_layout(ctx: Ctx, payload: dict[str, Any]) -> Any:
	headers: list[str] = payload.get("headers") or []
	mapping: dict[str, str] = payload.get("mapping") or {}
	bank = payload.get("bank") if payload.get("bank") in LAYOUT_BANKS else "Other"
	digest = hashlib.sha256("|".join(headers).encode("utf-8")).hexdigest()[:8]
	layout_id = f"custom-{bank.lower().replace(' ', '_')}-{digest}"
	if not frappe.db.exists(BANK_LAYOUT, layout_id):
		layout = frappe.get_doc(
			{
				"doctype": BANK_LAYOUT,
				"layout_id": layout_id,
				"bank": bank,
				"verified": 0,
				"amount_style": "signed_amount" if "amount" in mapping else "separate_debit_credit",
				"header_signature_json": json.dumps(headers, ensure_ascii=False),
				"column_map_json": json.dumps(mapping, ensure_ascii=False),
				"notes": f"mapped in Telegram by {ctx.user} for {payload.get('document')}",
			}
		)
		layout.flags.ignore_permissions = True
		layout.insert()
	mapping_text = ", ".join(f"{mn.COLUMN_ROLES[r]} = «{h}»" for r, h in mapping.items())
	ctx.reply(mn.MSG_STATEMENT_LAYOUT_DONE.format(mapping=mapping_text))
	ctx.reply(mn.MSG_STATEMENT_LAYOUT_SAVED.format(layout=layout_id))
	from nyabo_mn.telegram.router import notify_admins

	notify_admins(ctx.bot, ctx.settings, mn.MSG_STATEMENT_ADMIN_VERIFY.format(layout=layout_id))
	log_event("telegram.layout.saved", layout=layout_id, document=payload.get("document"))
	return {"layout": layout_id, "mapping": mapping}


def handle_state(ctx: Ctx, state: str, payload: dict[str, Any]) -> Any:
	"""Text while mapping: repeat the current column question (buttons are the only answer)."""
	try:
		index = int(state.split(":", 1)[1])
	except (IndexError, ValueError):
		ctx.clear_state()
		return None
	headers = payload.get("headers") or []
	if index < len(headers):
		_ask_column(ctx.bot, ctx.chat_id, headers, index)
	return None
