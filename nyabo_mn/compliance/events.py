"""Nyabo Event: the append-only audit log (ARCHITECTURE §4, "on_trash throws").

ERPNext keeps Version rows for tracked doctypes, but a Version can be deleted with the
document and says nothing about *why* something happened. Nyabo writes its own row for
every decision that the law wants traceable (period locked/reopened, entry reversed,
injection suspected, ...). The DocType is never edited or deleted after insert; the
hook handlers below enforce that regardless of who holds which role.

An event points at its document with a Dynamic Link, and an undeletable event made every
document it named undeletable too - a draft proposal, a test receipt, a mistyped journal
entry - because Frappe refuses to delete a row another row links to (F11).
``allow_delete_despite_events`` is the fix, and it changes nothing about the audit trail:
the event still exists and still names the document. Which documents may be deleted at
all stays where it belongs, in ``compliance.hooks`` (retention, posted documents).
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from nyabo_mn.i18n import mn

EVENT_DOCTYPE = "Nyabo Event"


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
			"doctype": EVENT_DOCTYPE,
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


def allow_delete_despite_events(doc: Any, method: str | None = None) -> None:
	"""on_trash of every doctype: an audit event must not be what keeps a document alive (F11).

	``frappe.model.delete_doc.check_if_doc_is_linked`` refuses to delete a row that another
	row links to, and skips the doctypes named in the document's ``ignore_linked_doctypes``
	(the same attribute ERPNext's controllers set for GL Entry and Payment Ledger Entry).
	Because a Nyabo Event can never be deleted, without this every document an event has
	ever named would be undeletable for ever - drafts, rejected proposals, test data.

	This does not decide what may be deleted. The retention and posted-document guards in
	``compliance.hooks`` run as ``on_trash`` handlers too and still refuse; all this says is
	that once they have allowed a deletion, the audit log will not veto it. The event row
	survives with the document's type and name still written on it, which is exactly what an
	audit trail is for: it records what happened, it does not hold the world in place.
	"""
	ignored = list(doc.get("ignore_linked_doctypes") or [])
	if EVENT_DOCTYPE not in ignored:
		ignored.append(EVENT_DOCTYPE)
	doc.ignore_linked_doctypes = ignored
