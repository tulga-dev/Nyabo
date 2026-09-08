"""Telegram file download and ``Nyabo Document`` creation (docs/ARCHITECTURE.md §5.3, §5.4).

Every incoming receipt or statement becomes a Nyabo Document with the original bytes
attached as a private File, because the Law on Accounting requires the primary document
to be kept ten years and every posting to link back to it (principle 4). The sha256 of
the bytes is stored so the same photo sent twice is refused before any model call is
paid for. Telegram's own bot download limit is 20 MB; we refuse earlier than that.
"""

from __future__ import annotations

import hashlib
import mimetypes
import posixpath
from typing import Any

import frappe
from frappe.utils import now_datetime

from nyabo_mn.log import log_event

MAX_FILE_BYTES = 20 * 1024 * 1024
DOCUMENT = "Nyabo Document"

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
TABLE_MIMES = {
	"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	"application/vnd.ms-excel",
	"text/csv",
	"application/csv",
}
PDF_MIME = "application/pdf"
TABLE_EXTENSIONS = {".xlsx", ".xls", ".csv"}


class FileTooLarge(ValueError):
	pass


class DuplicateDocument(ValueError):
	"""The same bytes were already stored for this company; carries the existing name."""

	def __init__(self, existing_name: str):
		super().__init__(existing_name)
		self.existing_name = existing_name


class UnsupportedFile(ValueError):
	pass


def sha256(content: bytes) -> str:
	return hashlib.sha256(content).hexdigest()


def guess_mime(filename: str, declared: str | None = None) -> str:
	if declared:
		return declared
	guessed, _enc = mimetypes.guess_type(filename)
	if guessed:
		return guessed
	if filename.lower().endswith(".csv"):
		return "text/csv"
	return "application/octet-stream"


def kind_for(mime: str, filename: str) -> str:
	"""Nyabo Document ``doc_type`` from the file: images are receipts, tables are statements."""
	ext = posixpath.splitext(filename.lower())[1]
	if mime in IMAGE_MIMES or mime.startswith("image/"):
		return "receipt"
	if mime in TABLE_MIMES or ext in TABLE_EXTENSIONS:
		return "bank_statement"
	if mime == PDF_MIME or ext == ".pdf":
		return "bank_statement"
	raise UnsupportedFile(mime)


def download_telegram_file(
	bot: Any, file_id: str, declared_mime: str | None = None, filename: str | None = None
) -> tuple[bytes, str, str]:
	"""``(bytes, mime, filename)`` via getFile + the file URL; refuses > 20 MB before downloading."""
	info = bot.get_file(file_id)
	size = int(info.get("file_size") or 0)
	if size > MAX_FILE_BYTES:
		raise FileTooLarge(str(size))
	file_path = info.get("file_path") or ""
	content = bot.download(file_path)
	if len(content) > MAX_FILE_BYTES:
		raise FileTooLarge(str(len(content)))
	name = filename or posixpath.basename(file_path) or f"{file_id}.bin"
	return content, guess_mime(name, declared_mime), name


def find_duplicate(company: str | None, file_hash: str) -> str | None:
	filters: dict[str, Any] = {"file_hash": file_hash}
	if company:
		filters["company"] = company
	return frappe.db.exists(DOCUMENT, filters)


def save_document(
	company: str | None,
	sender: dict[str, Any],
	kind: str,
	content: bytes,
	filename: str,
	*,
	mime: str | None = None,
	telegram_file_id: str | None = None,
	chat_id: int | str | None = None,
	message_id: int | str | None = None,
	sender_user: str | None = None,
) -> Any:
	"""Insert the Nyabo Document, attach the bytes as a private File, return the document."""
	if len(content) > MAX_FILE_BYTES:
		raise FileTooLarge(str(len(content)))
	file_hash = sha256(content)
	existing = find_duplicate(company, file_hash)
	if existing:
		raise DuplicateDocument(existing)
	mime = mime or guess_mime(filename)
	doc = frappe.get_doc(
		{
			"doctype": DOCUMENT,
			"company": company,
			"doc_type": kind,
			"status": "received",
			"file_hash": file_hash,
			"mime_type": mime,
			"size_bytes": len(content),
			"sender_telegram_id": str(sender.get("id")) if sender.get("id") is not None else None,
			"sender_user": sender_user or frappe.session.user,
			"telegram_file_id": telegram_file_id,
			"telegram_chat_id": str(chat_id) if chat_id is not None else None,
			"telegram_message_id": str(message_id) if message_id is not None else None,
			"received_at": now_datetime(),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	attachment = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": _safe_filename(filename, doc.name),
			"content": content,
			"is_private": 1,
			"attached_to_doctype": DOCUMENT,
			"attached_to_name": doc.name,
			"attached_to_field": "file",
		}
	)
	attachment.flags.ignore_permissions = True
	attachment.insert()
	doc.db_set("file", attachment.file_url)
	log_event("telegram.document.saved", document=doc.name, company=company, kind=kind, size=len(content))
	return doc


def _safe_filename(filename: str, doc_name: str) -> str:
	base = posixpath.basename(filename or "").strip() or "file"
	base = "".join(ch for ch in base if ch not in '\\/:*?"<>|')
	return f"{doc_name}-{base}"[:140]


def load_document_bytes(doc_name: str) -> bytes:
	"""Bytes of the attached File (statement re-parsing, inventory intake)."""
	file_name = frappe.db.get_value(
		"File", {"attached_to_doctype": DOCUMENT, "attached_to_name": doc_name}, "name"
	)
	if not file_name:
		raise frappe.DoesNotExistError(f"no File attached to {doc_name}")
	return frappe.get_doc("File", file_name).get_content()
