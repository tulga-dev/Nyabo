"""Nyabo Event: the append-only audit log (ARCHITECTURE §4, "on_trash throws").

ERPNext keeps Version rows for tracked doctypes, but a Version can be deleted with the
document and says nothing about *why* something happened. Nyabo writes its own row for
every decision that the law wants traceable (period locked/reopened, entry reversed,
injection suspected, ...). The DocType is never edited or deleted after insert; the two
hook handlers below enforce that regardless of who holds which role.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from nyabo_mn.i18n import mn


def log(
	event_type: str,
	company: str | None = None,
	ref_doctype: str | None = None,
	ref_name: str | None = None,
	reason: str | None = None,
	payload: dict[str, Any] | None = None,
	actor_telegram_id: str | int | None = None,
) -> str:
	"""Insert one Nyabo Event and return its name.

	``actor_user`` is always the session user so an event cannot claim another author;
	the Telegram id is extra context for bot-initiated actions. The payload is stored as
	JSON text (the field is JSON) with ``ensure_ascii=False`` so Cyrillic stays readable.
	"""
	doc = frappe.get_doc(
		{
			"doctype": "Nyabo Event",
			"event_type": event_type,
			"company": company,
			"actor_user": frappe.session.user,
			"actor_telegram_id": str(actor_telegram_id) if actor_telegram_id is not None else None,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"reason": reason,
			"payload_json": json.dumps(payload or {}, ensure_ascii=False, default=str),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def enforce_append_only(doc: Any, method: str | None = None) -> None:
	"""before_save: an existing event must never be saved again (edits are refused)."""
	if not doc.is_new():
		frappe.throw(mn.MSG_EVENT_APPEND_ONLY)


def block_delete(doc: Any, method: str | None = None) -> None:
	"""on_trash: events are never deleted, not even by Administrator."""
	frappe.throw(mn.MSG_EVENT_APPEND_ONLY)
