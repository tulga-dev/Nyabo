"""Test doubles for the Telegram layer: a recording bot and Update builders.

``FakeBotApi`` mirrors the ``BotApi`` surface the handlers call and records every call
so a test can assert on what the user would have seen, without any network.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from nyabo_mn.telegram import api, router
from nyabo_mn.telegram import state as chat_state


class FakeBotApi:
	def __init__(self, files: dict[str, bytes] | None = None):
		self.calls: list[tuple[str, dict[str, Any]]] = []
		self.files = dict(files or {})
		self._next_message_id = 100

	# --- recording -----------------------------------------------------------------------------

	def _record(self, method: str, **kwargs: Any) -> None:
		self.calls.append((method, kwargs))

	def sent(self, method: str) -> list[dict[str, Any]]:
		return [kw for m, kw in self.calls if m == method]

	def texts(self) -> list[str]:
		"""Every text the user saw, in order (sends and edits)."""
		return [kw["text"] for m, kw in self.calls if m in ("send_message", "edit_message_text")]

	@property
	def last_text(self) -> str:
		texts = self.texts()
		return texts[-1] if texts else ""

	def last_markup(self) -> dict[str, Any] | None:
		for m, kw in reversed(self.calls):
			if m in ("send_message", "edit_message_text", "edit_message_reply_markup") and kw.get(
				"reply_markup"
			):
				return kw["reply_markup"]
		return None

	def callback_datas(self) -> list[str]:
		markup = self.last_markup() or {}
		return [b["callback_data"] for row in markup.get("inline_keyboard", []) for b in row]

	def clear(self) -> None:
		self.calls.clear()

	# --- BotApi surface ------------------------------------------------------------------------

	def send_message(self, chat_id, text, reply_markup=None, parse_mode=None, disable_web_page_preview=True):
		self._next_message_id += 1
		self._record("send_message", chat_id=chat_id, text=text, reply_markup=reply_markup)
		return {"message_id": self._next_message_id, "chat": {"id": chat_id}, "text": text}

	def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode=None):
		self._record(
			"edit_message_text", chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup
		)
		return {"message_id": message_id, "chat": {"id": chat_id}, "text": text}

	def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
		self._record(
			"edit_message_reply_markup", chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
		)
		return True

	def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
		self._record(
			"answer_callback_query", callback_query_id=callback_query_id, text=text, show_alert=show_alert
		)
		return True

	def send_document(self, chat_id, content, filename, caption=None):
		self._record("send_document", chat_id=chat_id, content=content, filename=filename, caption=caption)
		self._next_message_id += 1
		return {"message_id": self._next_message_id}

	def send_photo(self, chat_id, content, filename="photo.jpg", caption=None):
		self._record("send_photo", chat_id=chat_id, content=content, filename=filename, caption=caption)
		return {"message_id": 0}

	def get_file(self, file_id):
		self._record("get_file", file_id=file_id)
		content = self.files.get(file_id, b"")
		return {"file_id": file_id, "file_path": f"documents/{file_id}", "file_size": len(content)}

	def download(self, file_path):
		self._record("download", file_path=file_path)
		file_id = file_path.rsplit("/", 1)[-1]
		return self.files[file_id]

	def set_webhook(self, url, secret_token, allowed_updates=None):
		self._record("set_webhook", url=url, allowed_updates=allowed_updates)
		return True

	def delete_webhook(self, drop_pending_updates=False):
		self._record("delete_webhook")
		return True

	def get_me(self):
		return {"id": 1, "is_bot": True, "username": "nyabo_bot"}

	def set_my_commands(self, commands, scope=None, language_code=None):
		self._record("set_my_commands", commands=commands, scope=scope, language_code=language_code)
		return True

	def set_chat_menu_button(self, chat_id=None, menu_button=None):
		self._record("set_chat_menu_button", chat_id=chat_id, menu_button=menu_button)
		return True


# --- update builders ---------------------------------------------------------------------------------

_update_counter = [1000]


def _next_update_id() -> int:
	_update_counter[0] += 1
	return _update_counter[0]


def sender(user_id: int, first_name: str = "Бат", username: str | None = "bat") -> dict[str, Any]:
	return {"id": user_id, "is_bot": False, "first_name": first_name, "username": username}


def message_update(
	user_id: int,
	text: str | None = None,
	*,
	chat_id: int | None = None,
	photo_file_id: str | None = None,
	document: dict[str, Any] | None = None,
	update_id: int | None = None,
	message_id: int = 1,
) -> dict[str, Any]:
	message: dict[str, Any] = {
		"message_id": message_id,
		"from": sender(user_id),
		"chat": {"id": chat_id or user_id, "type": "private"},
		"date": 1_700_000_000,
	}
	if text is not None:
		message["text"] = text
	if photo_file_id:
		message["photo"] = [
			{
				"file_id": photo_file_id + "-s",
				"file_unique_id": "u1",
				"width": 90,
				"height": 120,
				"file_size": 100,
			},
			{
				"file_id": photo_file_id,
				"file_unique_id": "u2",
				"width": 900,
				"height": 1200,
				"file_size": 1000,
			},
		]
	if document:
		message["document"] = document
	return {"update_id": update_id or _next_update_id(), "message": message}


def callback_update(
	user_id: int,
	data: str,
	*,
	chat_id: int | None = None,
	message_id: int = 101,
	update_id: int | None = None,
) -> dict[str, Any]:
	return {
		"update_id": update_id or _next_update_id(),
		"callback_query": {
			"id": f"cq{update_id or _update_counter[0]}",
			"from": sender(user_id),
			"message": {"message_id": message_id, "chat": {"id": chat_id or user_id, "type": "private"}},
			"chat_instance": "1",
			"data": data,
		},
	}


def run(bot: FakeBotApi, update: dict[str, Any]) -> dict[str, Any]:
	"""Drive the router as the webhook would, with the fake bot installed."""
	with api.use_bot(bot):
		return router.handle_update(update)


def post_webhook(bot: FakeBotApi, update: dict[str, Any], secret: str | None = "test-webhook-secret") -> Any:
	"""Call the whitelisted endpoint with a fake request; returns its response dict."""
	from nyabo_mn.telegram import webhook

	headers = {"Content-Type": "application/json"}
	if secret is not None:
		headers["X-Telegram-Bot-Api-Secret-Token"] = secret
	frappe.local.request = frappe.Request(data=json.dumps(update), headers=headers)
	frappe.local.response = frappe._dict(docs=[])
	previous = frappe.session.user
	frappe.set_user("Guest")
	try:
		with api.use_bot(bot):
			return webhook.webhook()
	finally:
		frappe.set_user(previous)


def link_user(user_id: int, role: str, company: str | None, first_name: str = "Бат") -> Any:
	"""Issue and consume a link code as Administrator; returns the Nyabo User Link."""
	previous = frappe.session.user
	frappe.set_user("Administrator")
	try:
		code = chat_state.issue_link_code(role, company, issued_by="Administrator")
		return chat_state.consume_link_code(code.code, sender(user_id, first_name=first_name))
	finally:
		frappe.set_user(previous)


def make_proposal(company: str, **overrides: Any) -> Any:
	"""A minimal proposed receipt entry for card and approval tests."""
	values: dict[str, Any] = {
		"doctype": "Nyabo Proposal",
		"company": company,
		"kind": "receipt",
		"status": "proposed",
		"needs_accountant": 0,
		"posting_date": "2026-08-14",
		"total": 85000,
		"vat_amount": 7727.27,
		"vat_treatment": "in_expense",
		"account_code": "6210",
		"explanation": "Шатахуун авсан тул 6210 дебетлэж, касс кредитлэв.",
		"citation": "purchase_expense_non_vat · Заавар 116, 3.2",
		"extracted_json": {"seller_name": "Петровис ХХК", "vat_rate": 0.1},
		"verification_json": {"seller_found": True, "status": "unsupported"},
		"warnings_json": [],
	}
	values.update(overrides)
	previous = frappe.session.user
	frappe.set_user("Administrator")
	try:
		doc = frappe.get_doc(values)
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc
	finally:
		frappe.set_user(previous)
