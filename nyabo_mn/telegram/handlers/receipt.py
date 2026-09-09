"""Receipt intake and proposal cards (docs/ARCHITECTURE.md §5.3).

A photo becomes a Nyabo Document (sha256 dedup per company) and the pipeline is
enqueued on the ``long`` queue; the reply is immediate. When the pipeline has a
proposal it calls ``send_proposal_card`` / ``update_card`` from here, so the card
anatomy and the keyboard live in one place for every entry point (receipt, bank line,
correction).
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram import api, cards, files, keyboards
from nyabo_mn.telegram.context import Ctx

PIPELINE_METHOD = "nyabo_mn.telegram._deps.process_receipt"
PROPOSAL = "Nyabo Proposal"


# --- intake ------------------------------------------------------------------------------------------


def handle_photo(ctx: Ctx) -> Any:
	photo = ctx.photo or {}
	return _intake(
		ctx,
		photo.get("file_id"),
		declared_mime="image/jpeg",
		filename=f"{photo.get('file_unique_id') or 'photo'}.jpg",
	)


def handle_image_document(ctx: Ctx) -> Any:
	document = ctx.document or {}
	return _intake(
		ctx,
		document.get("file_id"),
		declared_mime=document.get("mime_type"),
		filename=document.get("file_name") or "image.jpg",
	)


def _intake(ctx: Ctx, file_id: str | None, declared_mime: str | None, filename: str) -> Any:
	if not ctx.company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	if not file_id:
		ctx.reply(mn.MSG_SEND_PHOTO_HINT)
		return None
	try:
		content, mime, name = files.download_telegram_file(ctx.bot, file_id, declared_mime, filename)
		doc = files.save_document(
			ctx.company,
			ctx.sender,
			"receipt",
			content,
			name,
			mime=mime,
			telegram_file_id=file_id,
			chat_id=ctx.chat_id,
			message_id=ctx.message_id,
			sender_user=ctx.user,
		)
	except files.FileTooLarge:
		ctx.reply(mn.MSG_FILE_TOO_LARGE.format(mb=files.MAX_FILE_BYTES // (1024 * 1024)))
		return None
	except files.DuplicateDocument as dup:
		log_event("telegram.document.duplicate", existing=dup.existing_name, company=ctx.company)
		ctx.reply(mn.MSG_DUPLICATE_DOCUMENT)
		return {"duplicate": dup.existing_name}
	ctx.reply(mn.MSG_RECEIVED_PROCESSING)
	frappe.enqueue(
		PIPELINE_METHOD, queue="long", timeout=600, document_name=doc.name, enqueue_after_commit=True
	)
	return {"document": doc.name}


# --- cards -------------------------------------------------------------------------------------------


def proposal_to_dict(proposal: Any) -> dict[str, Any]:
	"""What ``cards.receipt_card`` needs, with the supplier and account display names resolved."""
	data = proposal.as_dict() if hasattr(proposal, "as_dict") else dict(proposal)
	for key in ("extracted_json", "verification_json", "confidence_json", "warnings_json", "entry_json"):
		value = data.get(key)
		if isinstance(value, str) and value:
			try:
				data[key] = json.loads(value)
			except ValueError:
				data[key] = None
	if data.get("supplier") and frappe.db.exists("Supplier", data["supplier"]):
		data["supplier_name"] = (
			frappe.db.get_value("Supplier", data["supplier"], "supplier_name") or data["supplier"]
		)
	if data.get("account") and frappe.db.exists("Account", data["account"]):
		data["account_name"] = frappe.db.get_value("Account", data["account"], "account_name") or None
	return data


def card_for(proposal: Any) -> tuple[str, dict[str, Any]]:
	"""Text and keyboard for the proposal's current status."""
	data = proposal_to_dict(proposal)
	status = data.get("status") or "proposed"
	if status == "posted":
		approver = _display_name(data.get("approved_by"))
		return (
			cards.posted_card(data, data.get("posted_name") or "—", approver),
			keyboards.posted_keyboard(data.get("posted_doctype") or "", data.get("posted_name") or ""),
		)
	if status == "rejected":
		return cards.rejected_card(
			data, data.get("rejection_reason") or mn.REJECT_OTHER
		), keyboards.empty_markup()
	if status == "approved":
		return cards.receipt_card(data) + "\n" + mn.MSG_APPROVED_POSTING, keyboards.empty_markup()
	if status == "failed":
		# No keyboard on a card, and the pipeline's failure path writes a Nyabo Event and a log
		# line but notifies nobody, so this is the variant that promises neither (UX-13).
		return cards.receipt_card(data) + "\n" + mn.MSG_ERROR_NO_BUTTON, keyboards.empty_markup()
	return cards.receipt_card(data), keyboards.receipt_keyboard(data["name"])


def _display_name(user: str | None) -> str:
	if not user:
		return "—"
	link = frappe.db.get_value(
		"Nyabo User Link", {"user": user}, ["first_name", "telegram_username"], as_dict=True
	)
	if link and (link.first_name or link.telegram_username):
		return link.first_name or f"@{link.telegram_username}"
	return frappe.db.get_value("User", user, "full_name") or user


def chat_id_for(proposal: Any) -> str | None:
	"""The chat the card belongs to: where the receipt came from, else the accountant's chat."""
	if proposal.card_chat_id:
		return proposal.card_chat_id
	if proposal.document:
		chat_id = frappe.db.get_value("Nyabo Document", proposal.document, "telegram_chat_id")
		if chat_id:
			return chat_id
	if proposal.company:
		name = frappe.db.exists("Nyabo Company Settings", {"company": proposal.company})
		if name:
			settings = frappe.db.get_value(
				"Nyabo Company Settings", name, ["accountant_telegram_id", "owner_telegram_id"], as_dict=True
			)
			return settings.accountant_telegram_id or settings.owner_telegram_id
	return None


def send_proposal_card(
	proposal_name: str, chat_id: int | str | None = None, bot: Any | None = None
) -> dict[str, Any]:
	"""Send the card and remember where it is so approval can edit it in place."""
	bot = bot or api.get_bot()
	proposal = frappe.get_doc(PROPOSAL, proposal_name)
	target = chat_id or chat_id_for(proposal)
	if not target:
		log_event("telegram.card.no_chat", level="warning", proposal=proposal_name)
		return {"sent": False}
	text, markup = card_for(proposal)
	message = bot.send_message(target, text, reply_markup=markup)
	proposal.db_set({"card_chat_id": str(target), "card_message_id": str(message.get("message_id") or "")})
	log_event("telegram.card.sent", proposal=proposal_name, chat_id=target)
	return {"sent": True, "chat_id": target, "message_id": message.get("message_id")}


def update_card(proposal_name: str, bot: Any | None = None, footer: str | None = None) -> dict[str, Any]:
	"""Re-render the card at its known position; falls back to a new message."""
	bot = bot or api.get_bot()
	proposal = frappe.get_doc(PROPOSAL, proposal_name)
	text, markup = card_for(proposal)
	if footer:
		text = text + "\n" + footer
	if proposal.card_chat_id and proposal.card_message_id:
		try:
			bot.edit_message_text(
				proposal.card_chat_id, int(proposal.card_message_id), text, reply_markup=markup
			)
			return {"edited": True}
		except Exception as exc:
			log_event("telegram.card.edit_failed", level="warning", proposal=proposal_name, error=repr(exc))
	return send_proposal_card(proposal_name, bot=bot)
