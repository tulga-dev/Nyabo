"""Telegram webhook endpoint (docs/ARCHITECTURE.md §5.1).

``/api/method/nyabo_mn.telegram.webhook.webhook`` is guest-callable, so the only thing
standing between the internet and the router is the secret token Telegram echoes in
``X-Telegram-Bot-Api-Secret-Token``. It is compared in constant time, a mismatch is a
403, and after that the endpoint always answers 200 so Telegram stops retrying: the
update is deduplicated by ``update_id`` per chat and handed to the ``short`` queue.
Nothing else happens in the request, which keeps the webhook under Telegram's timeout
even when ERPNext is busy.
"""

from __future__ import annotations

import hmac
import json
from typing import Any

import frappe

from nyabo_mn.config import get_settings
from nyabo_mn.log import log_event
from nyabo_mn.telegram import state

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
ROUTER_METHOD = "nyabo_mn.telegram.router.handle_update"
WEBHOOK_PATH = "/api/method/nyabo_mn.telegram.webhook.webhook"


def chat_id_of(update: dict[str, Any]) -> int | None:
	"""The chat an update belongs to (message or callback), used as the dedup key."""
	message = update.get("message") or update.get("edited_message")
	if not message and update.get("callback_query"):
		message = (update["callback_query"] or {}).get("message")
	chat = (message or {}).get("chat") or {}
	return chat.get("id")


def _parse_update() -> dict[str, Any] | None:
	request = frappe.request
	raw = request.get_data(as_text=True) if hasattr(request, "get_data") else request.data
	if isinstance(raw, bytes):
		raw = raw.decode("utf-8", errors="replace")
	try:
		payload = json.loads(raw or "null")
	except ValueError:
		return None
	return payload if isinstance(payload, dict) else None


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook() -> dict[str, Any]:
	settings = get_settings()
	expected = settings.telegram_webhook_secret
	provided = frappe.request.headers.get(SECRET_HEADER) or ""
	if not expected or not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
		frappe.local.response["http_status_code"] = 403
		log_event("telegram.webhook.forbidden", level="warning")
		return {"ok": False}

	update = _parse_update()
	if not update:
		return {"ok": True, "ignored": "not an update"}
	update_id = update.get("update_id")
	chat_id = chat_id_of(update)
	if state.is_duplicate_update(chat_id, update_id):
		log_event("telegram.webhook.duplicate", update_id=update_id, chat_id=chat_id)
		return {"ok": True, "duplicate": True}

	frappe.enqueue(ROUTER_METHOD, queue="short", update=update, enqueue_after_commit=True)
	return {"ok": True}


def webhook_url(site_url: str) -> str:
	return site_url.rstrip("/") + WEBHOOK_PATH


def setup_webhook(site_url: str | None = None) -> dict[str, Any]:
	"""``bench --site <site> execute nyabo_mn.telegram.webhook.setup_webhook --kwargs '{"site_url": "https://…"}'``"""
	from nyabo_mn.telegram.api import get_bot

	settings = get_settings()
	settings.require("telegram")
	url = webhook_url(site_url or frappe.utils.get_url())
	result = get_bot().set_webhook(url, settings.telegram_webhook_secret, ["message", "callback_query"])
	log_event("telegram.webhook.set", url=url)
	return {"url": url, "result": result}
