"""Bank statement intake and the column-mapping conversation (docs/ARCHITECTURE.md §5.4).

An xlsx/csv/pdf becomes a ``Nyabo Document(bank_statement)`` and ``import_statement``
runs on the ``long`` queue. When the importer does not recognise the layout it returns
``status = "unknown_layout"`` with the header row and a preview; the accountant is then
asked, one column at a time, which role the column plays, and the answer is saved as a
``Nyabo Bank Layout`` with ``verified = 0`` so nothing is imported on a guessed mapping
(CORE-08). The accountant who mapped the columns is then asked to confirm them for their own
company (DECISIONS ACC-02) — they read the file, so they are the person who can say whether the
mapping is right, and nothing waits on an admin who never saw it. A layout that was already
mapped but not confirmed comes back as ``status = "unverified_layout"``: the same confirmation
card is sent, and the accountant is not asked the column questions a second time. Anything the
importer refuses (no bank account, unreadable file) arrives as an exception whose ``message_mn``
is the reply.
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
from nyabo_mn.telegram.handlers import escape

IMPORT_METHOD = "nyabo_mn.telegram.handlers.statement.run_import"
STATE_PREFIX = "layout"
BANK_LAYOUT = "Nyabo Bank Layout"
LAYOUT_BANKS = ("Khan Bank", "TDB", "Golomt Bank", "Trans Bank", "XacBank")
#: ``rules.verify.KIND_LAYOUT`` — the kind a bank layout rides under in the acceptance callback
#: datum, so the confirmation tap lands in the same handler as a posting pattern's (ACC-02).
LAYOUT_KIND = "b"
MAX_PREVIEW_ROWS = 3
# The money columns: any one of them carries an amount into a BankLine.
AMOUNT_ROLES = ("amount", "debit", "credit")


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
	"""Worker: import, then report or start the mapping conversation. Never raises into RQ.

	This runs on the ``long`` queue with no ``Ctx``, so nothing here draws a keyboard and
	nothing here notifies the admins: the replies are the ``_NO_BUTTON`` variants, which name
	/меню as a command to type and claim no notification (UX-13).
	"""
	bot = api.get_bot()
	try:
		summary = _deps.import_statement(document_name) or {}
	except DependencyMissing as exc:
		log_error("telegram.statement.dependency_missing", exc, document=document_name)
		bot.send_message(chat_id, mn.MSG_FEATURE_UNAVAILABLE_NO_BUTTON)
		return {"ok": False}
	except _deps.bank_import_error() as exc:
		# The importer's own Mongolian text says what the accountant has to fix.
		log_event("telegram.statement.import_refused", level="warning", document=document_name)
		bot.send_message(chat_id, str(exc) or mn.MSG_ERROR_NO_BUTTON)
		return {"ok": False, "refused": str(exc)}
	except Exception as exc:
		# BankImportError (no bank account, unreadable file, no lines) carries the card text.
		log_error("telegram.statement.import_failed", exc, document=document_name)
		bot.send_message(chat_id, getattr(exc, "message_mn", None) or mn.MSG_ERROR_NO_BUTTON)
		return {"ok": False}
	# The importer sets ``unknown_layout`` for both cases, so the more specific one is asked
	# first: a layout that was mapped once but is not verified must not re-ask the accountant,
	# it needs an admin to tick Баталгаажсан on the Nyabo Bank Layout row.
	status = summary.get("status")
	if status == "unverified_layout":
		layout_id = str(summary.get("layout") or "")
		bot.send_message(chat_id, mn.MSG_STATEMENT_LAYOUT_UNVERIFIED.format(layout=layout_id))
		_record_layout_block(
			layout_id, summary.get("company"), document_name, _sender_of(document_name) or chat_id
		)
		ask_layout_confirmation(bot, chat_id, layout_id, summary.get("company"))
		return {"ok": True, "unverified": True, "layout": layout_id}
	# The importer sets both keys; a caller (or a test double) may send only ``status``.
	if status == "unknown_layout" or summary.get("unknown_layout"):
		start_layout_mapping(bot, chat_id, document_name, summary)
		return {"ok": True, "mapping": True}
	bank_name = summary.get("bank") or ""
	bot.send_message(
		chat_id,
		mn.MSG_STATEMENT_IMPORTED.format(
			bank=mn.BANK_NAMES_MN.get(bank_name, bank_name) or "—",
			count=summary.get("count", 0),
			new=summary.get("new", 0),
			dup=summary.get("dup", 0),
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


def header_row(summary: dict[str, Any]) -> int | None:
	"""Index into ``preview_rows`` of the row that holds the column headers.

	The header is rarely the first row - Mongolian statements open with a title block - so
	the generic guess's ``header_row_hint`` is used when it points inside the preview, and
	otherwise the fullest row wins.
	"""
	rows = summary.get("preview_rows") or []
	hint = (summary.get("guess") or {}).get("header_row_hint")
	if isinstance(hint, int) and 0 <= hint < len(rows) and any(str(c).strip() for c in rows[hint]):
		return hint
	best, best_filled = None, 1
	for index, row in enumerate(rows):
		filled = sum(1 for cell in row if str(cell).strip())
		if filled > best_filled:
			best, best_filled = index, filled
	return best


def start_layout_mapping(bot: Any, chat_id: int | str, document_name: str, summary: dict[str, Any]) -> None:
	headers = [str(h) for h in (summary.get("headers") or [])]
	preview = [list(row) for row in (summary.get("preview") or [])]
	if not headers:
		index = header_row(summary)
		if index is not None:
			rows = summary.get("preview_rows") or []
			headers = [str(cell) for cell in rows[index]]
			preview = [list(row) for row in rows[index + 1 :]]
	while headers and not headers[-1].strip():
		headers.pop()
	if len(headers) < 2:
		# Refused here, where the file is read, rather than after every column is answered.
		# ``missing_for_import`` wants a date column *and* one of amount/debit/credit, and a
		# column carries exactly one role, so a file with fewer than two columns has no answer
		# that would ever be accepted: each role the accountant picked would come back to the
		# same refusal — one that names Буцах, which is not drawn on the first column. A loop
		# with no exit but Цуцлах is not a question, so the question is not asked.
		#
		# «The file cannot be read at all» is a different sentence from «the file does not carry
		# the columns an import needs», and the preview rows are what tells them apart.
		bot.send_message(
			chat_id,
			mn.MSG_STATEMENT_LAYOUT_TOO_FEW_COLUMNS
			if summary.get("preview_rows")
			else mn.MSG_UNSUPPORTED_FILE,
		)
		log_event(
			"telegram.layout.too_few_columns",
			level="warning",
			document=document_name,
			headers=len(headers),
		)
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
		mn.MSG_STATEMENT_LAYOUT_UNKNOWN.format(preview=_preview_text(headers, preview)),
	)
	_ask_column(bot, chat_id, headers, 0)


def _ask_column(bot: Any, chat_id: int | str, headers: list[str], index: int) -> None:
	"""Буцах appears from the second column on; the first has nothing behind it (UX-13)."""
	bot.send_message(
		chat_id,
		mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header=headers[index]),
		reply_markup=keyboards.layout_column_roles(index, back=index > 0),
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
	ctx.edit(
		ctx.callback_message_id,
		mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header=headers[index]) + " " + mn.COLUMN_ROLES[role],
		keyboards.empty_markup(),
	)
	return _answer_column(ctx, payload, headers, index, role)


def missing_for_import(mapping: dict[str, str]) -> list[str]:
	"""What a mapping still needs before any statement can be read through it, in Mongolian.

	``core.statements.parse_rows`` skips a row whose date cell does not parse ("if date is
	None: continue") and, for either amount style, a row with no amount in it — so a mapping
	without a date column, or without one of ``amount``/``debit``/``credit``, produces zero
	lines from every file. Requiring one money column rather than a debit *and* a credit is
	deliberate: a statement with only a Зарлага column still imports, and refusing it would
	trap the accountant in a question with no acceptable answer.
	"""
	missing: list[str] = []
	if "date" not in mapping:
		missing.append(mn.MSG_STATEMENT_LAYOUT_NEEDS_DATE)
	if not any(role in mapping for role in AMOUNT_ROLES):
		missing.append(mn.MSG_STATEMENT_LAYOUT_NEEDS_AMOUNT)
	return missing


def _answer_column(
	ctx: Ctx, payload: dict[str, Any], headers: list[str], index: int, role: str
) -> dict[str, Any]:
	"""Record one column's role and move on; the last column saves the layout (unverified)."""
	mapping: dict[str, str] = dict(payload.get("mapping") or {})
	# The header may already hold a role from an answer being re-taken (Буцах, or a refused
	# last column); it keeps only the role it is being given now.
	mapping = {r: h for r, h in mapping.items() if h != headers[index]}
	if role != "ignore":
		mapping[role] = headers[index]
	payload["mapping"] = mapping
	next_index = index + 1
	if next_index < len(headers):
		ctx.set_state(f"{STATE_PREFIX}:{next_index}", payload)
		_ask_column(ctx.bot, ctx.chat_id, headers, next_index)
		return {"next": next_index}
	missing = missing_for_import(mapping)
	if missing:
		# Every column is answered and the mapping still cannot read a line. Saving it would
		# key an empty mapping to this bank's header signature and re-use it for every future
		# import of that format, and would ask an admin to verify a layout that reads nothing.
		# So the last question stands, with what it is waiting for.
		ctx.set_state(f"{STATE_PREFIX}:{index}", payload)
		ctx.reply(mn.MSG_STATEMENT_LAYOUT_INCOMPLETE.format(missing=", ".join(missing)))
		_ask_column(ctx.bot, ctx.chat_id, headers, index)
		log_event(
			"telegram.layout.incomplete",
			level="warning",
			document=payload.get("document"),
			mapped=sorted(mapping),
		)
		return {"incomplete": sorted(mapping)}
	ctx.clear_state()
	return save_layout(ctx, payload)


def save_layout(ctx: Ctx, payload: dict[str, Any]) -> Any:
	headers: list[str] = payload.get("headers") or []
	mapping: dict[str, str] = payload.get("mapping") or {}
	missing = missing_for_import(mapping)
	if missing:
		# The second lock on the same door: whoever calls this, a layout that reads no lines is
		# never written and no admin is asked to verify one.
		ctx.reply(mn.MSG_STATEMENT_LAYOUT_INCOMPLETE.format(missing=", ".join(missing)))
		log_event("telegram.layout.refused", level="warning", document=payload.get("document"))
		return {"refused": sorted(mapping)}
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
	# The confirmation is asked of the person who just read the file and answered every column —
	# nobody is sent away to wait (ACC-02). The site admins are told a new format exists because
	# they may want it for every client, which is a different decision and stays theirs.
	_record_layout_block(layout_id, ctx.company, payload.get("document"), ctx.telegram_id, user=ctx.user)
	ask_layout_confirmation(ctx.bot, ctx.chat_id, layout_id, ctx.company, mapping=mapping)
	from nyabo_mn.telegram.router import notify_admins

	notify_admins(
		ctx.bot,
		ctx.settings,
		mn.MSG_STATEMENT_ADMIN_VERIFY.format(layout=layout_id, company=ctx.company or mn.VALUE_UNKNOWN),
	)
	log_event("telegram.layout.saved", layout=layout_id, document=payload.get("document"))
	return {"layout": layout_id, "mapping": mapping}


def _sender_of(document_name: str) -> str | None:
	"""The Telegram id of the person who uploaded this document, or ``None``.

	``run_import`` is a worker with a chat id and no ``Ctx``, and the chat id used to go into the
	block row's ``telegram_id`` — the field ``save_layout`` fills with ``ctx.telegram_id``. In a
	one-to-one chat the two numbers are equal, so it worked; in a group they are not, and the row
	would then name a conversation where it claims to name a person. It is read back to finish
	*that person's* own upload (``verify.blocked_document``), so the difference is not cosmetic.
	``Nyabo Document.sender_telegram_id`` is who really sent the file.
	"""
	try:
		sender = frappe.db.get_value("Nyabo Document", document_name, "sender_telegram_id")
	except Exception as exc:  # noqa: BLE001 - a missing row must not lose the refusal itself
		log_event(
			"telegram.statement.sender_unknown", level="warning", document=document_name, error=repr(exc)
		)
		return None
	return str(sender).strip() or None if sender else None


def _record_layout_block(
	layout_id: str, company: Any, document: Any, telegram_id: Any, user: str | None = None
) -> None:
	"""Record which file this layout is holding up, so confirming it re-reads that very file.

	Asking the accountant to send the statement again would be a promise Nyabo cannot keep: the
	sha256 dedup answers a second upload of the same file with «this document is already here»
	(§5.3). The stored document is the one that gets read, and this row is how the confirmation
	finds it — the same trail a refused [Батлах] leaves for a posting.
	"""
	if not layout_id or not document:
		return
	_deps.record_rule_block(
		layout_id, company=company, document=str(document), telegram_id=telegram_id, user=user
	)


def ask_layout_confirmation(
	bot: Any,
	chat_id: int | str,
	layout_id: str,
	company: str | None,
	mapping: dict[str, str] | None = None,
) -> None:
	"""Show the mapping and ask the accountant to confirm it for their own company (ACC-02).

	The buttons are ``rules.verify``'s own, with the layout riding as kind ``b``: a bank layout, a
	posting pattern and a tax parameter are all rules the guard refuses, so confirming one leaves
	the same audit row and is read back by the same code. Drawn without the site-admin button
	because this runs on the import worker, where there is no reader to check — a site admin who
	wants the row verified for every client does that from ``/дүрэм`` or the desk.
	"""
	if not layout_id:
		return
	if mapping is None:
		mapping = _layout_mapping(layout_id)
	mapping_text = ", ".join(f"{mn.COLUMN_ROLES.get(r, r)} = «{h}»" for r, h in mapping.items())
	bot.send_message(
		chat_id,
		mn.MSG_STATEMENT_LAYOUT_CONFIRM_ASK.format(
			layout=layout_id, company=company or mn.VALUE_UNKNOWN, mapping=mapping_text
		),
		reply_markup=keyboards.rule_decision(LAYOUT_KIND, layout_id, may_accept=True),
	)


def _layout_mapping(layout_id: str) -> dict[str, str]:
	"""``{role: header}`` off the stored row; an unreadable mapping shows as none rather than raising."""
	raw = frappe.db.get_value(BANK_LAYOUT, layout_id, "column_map_json")
	if isinstance(raw, str):
		try:
			raw = json.loads(raw) if raw.strip() else {}
		except ValueError:
			return {}
	return {str(role): str(header) for role, header in (raw or {}).items()} if isinstance(raw, dict) else {}


def handle_state(ctx: Ctx, state: str, payload: dict[str, Any]) -> Any:
	"""Text while mapping: repeat the current column question (buttons are the only answer)."""
	index = _column_index(state)
	if index is None:
		ctx.clear_state()
		return None
	headers = payload.get("headers") or []
	if index < len(headers):
		_ask_column(ctx.bot, ctx.chat_id, headers, index)
	return None


def _column_index(state: str) -> int | None:
	try:
		return int(state.split(":", 1)[1])
	except (IndexError, ValueError):
		return None


# --- escapes (UX-13) ---------------------------------------------------------------------------------


def handle_escape(ctx: Ctx, state: str, payload: dict[str, Any], verb: str) -> bool | str:
	"""Буцах re-asks the previous column, Алгасах marks this one unused, Цуцлах drops the mapping.

	Cancelling is safe at any point: the layout row is only written once every column has been
	answered, so nothing was imported on a half-made guess (CORE-08). Skipping every column is
	not a way to leave — it would write a mapping that reads nothing — and is refused where the
	mapping is completed, not here.

	Буцах and Алгасах are gated on the accountant the way ``handle_layout_callback``'s own
	buttons are, because they do the same work: Алгасах *is* the «Ашиглахгүй» answer, and on the
	last column it saves a Nyabo Bank Layout and asks the admins to verify it. The escape row is
	drawn beside those buttons and the words are typed into the same step, so an Owner — who may
	send a statement, and therefore reaches this conversation — used to walk round the check.
	Цуцлах is deliberately not gated: leaving a step is never a permission, and the owner who
	opened the question is entitled to close it. Nothing has been written at that point.
	"""
	index = _column_index(state)
	headers: list[str] = payload.get("headers") or []
	if index is None or index >= len(headers):
		return False
	if verb in (keyboards.ESCAPE_BACK, keyboards.ESCAPE_SKIP) and not ctx.is_accountant:
		escape.refuse(ctx, mn.MSG_NO_PERMISSION)
		log_event(
			"telegram.layout.escape_refused",
			level="warning",
			verb=verb,
			user=ctx.user,
			document=payload.get("document"),
		)
		return True
	if verb == keyboards.ESCAPE_BACK:
		if index == 0:
			return False
		# The answer being re-taken is dropped, or the column would keep the role it was given.
		mapping = {r: h for r, h in (payload.get("mapping") or {}).items() if h != headers[index - 1]}
		payload["mapping"] = mapping
		ctx.set_state(f"{STATE_PREFIX}:{index - 1}", payload)
		_ask_column(ctx.bot, ctx.chat_id, headers, index - 1)
		return True
	if verb == keyboards.ESCAPE_SKIP:
		# "Ашиглахгүй" is already one of the roles, so skipping a column is simply that answer —
		# and ``_answer_column`` is where skipping every column is refused, in Mongolian, with
		# the question left standing.
		_answer_column(ctx, payload, headers, index, "ignore")
		return True
	if verb == keyboards.ESCAPE_CANCEL:
		ctx.clear_state()
		# This line is the goodbye — it says the statement was not imported, which the generic
		# one does not — so the caller is told not to say it again.
		ctx.reply(mn.MSG_STATEMENT_LAYOUT_CANCELLED)
		log_event("telegram.layout.cancelled", document=payload.get("document"), column=index)
		return escape.CANCEL_ANNOUNCED
	return False
