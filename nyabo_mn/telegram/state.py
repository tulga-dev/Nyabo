"""Conversation state, update dedup and link codes (docs/ARCHITECTURE.md §4, §5.1).

``Nyabo Chat State`` is one row per chat: the current conversation step, a JSON payload
and the last Telegram ``update_id`` seen. Telegram retries a webhook until it gets 200,
so the same update can arrive twice; the router drops anything at or below the stored
id. Link codes are six digits and expire after thirty minutes so a code read out loud
over the phone cannot be replayed a day later.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from nyabo_mn.log import log_event

CHAT_STATE = "Nyabo Chat State"
LINK_CODE = "Nyabo Link Code"
USER_LINK = "Nyabo User Link"
LINK_CODE_MINUTES = 30

# Link Code / User Link ``role`` (Select) -> Frappe Role (fixtures in nyabo_mn/fixtures/role.json)
ROLE_TO_FRAPPE_ROLE = {"Owner": "Nyabo Owner", "Accountant": "Nyabo Accountant", "Admin": "Nyabo Admin"}
# Words an admin may type in ``/link <role> <company>``; ASCII aliases for admins on Latin keyboards
ROLE_WORDS = {
	"нягтлан": "Accountant",
	"accountant": "Accountant",
	"эзэмшигч": "Owner",
	"owner": "Owner",
	"админ": "Admin",
	"admin": "Admin",
}


class LinkCodeInvalid(ValueError):
	"""Unknown, used or expired code; the handler replies MSG_LINK_CODE_INVALID."""


# --- chat state ------------------------------------------------------------------------------------


def _chat_doc(chat_id: int | str, create: bool = False) -> Any | None:
	name = frappe.db.exists(CHAT_STATE, {"chat_id": str(chat_id)})
	if name:
		return frappe.get_doc(CHAT_STATE, name)
	if not create:
		return None
	doc = frappe.get_doc({"doctype": CHAT_STATE, "chat_id": str(chat_id)})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def get_state(chat_id: int | str) -> tuple[str | None, dict[str, Any]]:
	"""``(state, payload)``; ``(None, {})`` when the chat has no open conversation."""
	doc = _chat_doc(chat_id)
	if doc is None or not doc.state:
		return None, {}
	payload = doc.payload_json
	if isinstance(payload, str):
		try:
			payload = json.loads(payload) if payload else {}
		except ValueError:
			payload = {}
	return doc.state, dict(payload or {})


def set_state(
	chat_id: int | str, state: str, payload: dict[str, Any] | None = None, telegram_id: Any = None
) -> None:
	doc = _chat_doc(chat_id, create=True)
	doc.state = state
	doc.payload_json = json.dumps(payload or {}, ensure_ascii=False, default=str)
	doc.updated_at = now_datetime()
	if telegram_id is not None:
		doc.telegram_id = str(telegram_id)
	doc.flags.ignore_permissions = True
	doc.save()


def update_payload(chat_id: int | str, **changes: Any) -> dict[str, Any]:
	"""Merge into the payload without touching the state name."""
	state, payload = get_state(chat_id)
	payload.update(changes)
	set_state(chat_id, state or "", payload)
	return payload


def clear_state(chat_id: int | str) -> None:
	doc = _chat_doc(chat_id)
	if doc is None:
		return
	doc.state = None
	doc.payload_json = None
	doc.updated_at = now_datetime()
	doc.flags.ignore_permissions = True
	doc.save()


def is_duplicate_update(chat_id: int | str, update_id: int | None) -> bool:
	"""True when ``update_id`` was already recorded for the chat; records it otherwise.

	Telegram's ids are monotonic per bot, so anything at or below the last seen id is a retry.
	Updates without a chat (rare service updates) are never deduplicated.
	"""
	if update_id is None or chat_id is None:
		return False
	doc = _chat_doc(chat_id, create=True)
	last = cint(doc.last_update_id)
	if last and cint(update_id) <= last:
		return True
	doc.last_update_id = cint(update_id)
	doc.flags.ignore_permissions = True
	doc.save()
	return False


# --- link codes ------------------------------------------------------------------------------------


def issue_link_code(role: str, company: str | None, issued_by: str, minutes: int = LINK_CODE_MINUTES) -> Any:
	"""A fresh six-digit code; collisions with an open code are retried (10^6 space, few open rows)."""
	if role not in ROLE_TO_FRAPPE_ROLE:
		raise ValueError(f"unknown link role {role!r}")
	if company and not frappe.db.exists("Company", company):
		raise frappe.DoesNotExistError(f"Company {company} not found")
	for _attempt in range(20):
		code = f"{secrets.randbelow(1_000_000):06d}"
		if not frappe.db.exists(LINK_CODE, code):
			break
	else:  # pragma: no cover - astronomically unlikely
		raise RuntimeError("could not allocate a unique link code")
	doc = frappe.get_doc(
		{
			"doctype": LINK_CODE,
			"code": code,
			"role": role,
			"company": company,
			"issued_by": issued_by,
			"expires_at": add_to_date(now_datetime(), minutes=minutes),
			"status": "open",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	log_event("telegram.link_code.issued", role=role, company=company, issued_by=issued_by)
	return doc


def expire_link_codes() -> None:
	"""Scheduler (daily): mark open codes past ``expires_at`` as expired; consumption also checks the time."""
	now = now_datetime()
	for name in frappe.get_all(LINK_CODE, filters={"status": "open"}, pluck="name"):
		doc = frappe.get_doc(LINK_CODE, name)
		if get_datetime(doc.expires_at) and get_datetime(doc.expires_at) < now:
			doc.status = "expired"
			doc.flags.ignore_permissions = True
			doc.save()


def telegram_user_email(telegram_id: int | str) -> str:
	return f"tg-{telegram_id}@nyabo.local"


def ensure_frappe_user(telegram_user: dict[str, Any], role: str) -> str:
	"""``tg-<id>@nyabo.local``, enabled, with the Nyabo role; no password is ever set, so the
	account cannot log into the desk — it exists to own documents and carry permissions."""
	email = telegram_user_email(telegram_user["id"])
	frappe_role = ROLE_TO_FRAPPE_ROLE[role]
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		user.flags.ignore_permissions = True
		if not cint(user.enabled):
			user.enabled = 1
			user.save()
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": (telegram_user.get("first_name") or f"tg-{telegram_user['id']}")[:140],
				"last_name": (telegram_user.get("last_name") or "")[:140] or None,
				"enabled": 1,
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		)
		user.flags.ignore_permissions = True
		user.flags.no_welcome_mail = True
		user.insert()
	if frappe_role not in frappe.get_roles(email):
		user.add_roles(frappe_role)
	return email


def consume_link_code(code: str, telegram_user: dict[str, Any]) -> Any:
	"""Turn a code into an active ``Nyabo User Link`` (created or extended with the company)."""
	code = (code or "").strip()
	if not frappe.db.exists(LINK_CODE, code):
		raise LinkCodeInvalid(code)
	link_code = frappe.get_doc(LINK_CODE, code)
	expires = get_datetime(link_code.expires_at)
	if link_code.status != "open" or (expires and expires < now_datetime()):
		if link_code.status == "open":
			link_code.status = "expired"
			link_code.flags.ignore_permissions = True
			link_code.save()
		raise LinkCodeInvalid(code)

	telegram_id = str(telegram_user["id"])
	user = ensure_frappe_user(telegram_user, link_code.role)
	if frappe.db.exists(USER_LINK, telegram_id):
		link = frappe.get_doc(USER_LINK, telegram_id)
	else:
		link = frappe.get_doc({"doctype": USER_LINK, "telegram_id": telegram_id, "user": user})
	link.telegram_username = telegram_user.get("username")
	link.first_name = telegram_user.get("first_name")
	link.user = user
	link.role = _highest_role(link.role, link_code.role)
	link.status = "active"
	link.linked_at = now_datetime()
	if link_code.company:
		if link_code.company not in {row.company for row in link.get("companies") or []}:
			link.append("companies", {"company": link_code.company})
		if not link.active_company:
			link.active_company = link_code.company
	link.flags.ignore_permissions = True
	link.save()

	link_code.status = "used"
	link_code.used_by_telegram_id = telegram_id
	link_code.used_at = now_datetime()
	link_code.flags.ignore_permissions = True
	link_code.save()
	_note_company_person(link_code.company, link_code.role, telegram_id, user)
	log_event(
		"telegram.link.consumed", telegram_id=telegram_id, role=link_code.role, company=link_code.company
	)
	return link


def _highest_role(current: str | None, new: str) -> str:
	order = {"Owner": 1, "Accountant": 2, "Admin": 3}
	if not current:
		return new
	return current if order.get(current, 0) >= order.get(new, 0) else new


def _note_company_person(company: str | None, role: str, telegram_id: str, user: str) -> None:
	"""Record the owner / accountant Telegram id on the company settings for card routing."""
	if not company or not frappe.db.exists("DocType", "Nyabo Company Settings"):
		return
	name = frappe.db.exists("Nyabo Company Settings", {"company": company})
	if not name:
		return
	doc = frappe.get_doc("Nyabo Company Settings", name)
	if role == "Owner":
		doc.owner_telegram_id = telegram_id
	elif role == "Accountant":
		doc.accountant_telegram_id = telegram_id
		doc.accountant_user = user
	else:
		return
	doc.flags.ignore_permissions = True
	doc.save()


def get_link(telegram_id: int | str) -> Any | None:
	"""Active ``Nyabo User Link`` for a Telegram id, else None."""
	name = frappe.db.exists(USER_LINK, str(telegram_id))
	if not name:
		return None
	link = frappe.get_doc(USER_LINK, name)
	return link if link.status == "active" else None


def user_companies(link: Any) -> list[str]:
	return [row.company for row in (link.get("companies") or []) if row.company]


def active_company(link: Any) -> str | None:
	companies = user_companies(link)
	if link.active_company and link.active_company in companies:
		return link.active_company
	return companies[0] if companies else None


def set_active_company(link: Any, company: str) -> None:
	if company not in user_companies(link):
		raise frappe.PermissionError(company)
	link.active_company = company
	link.flags.ignore_permissions = True
	link.save()
