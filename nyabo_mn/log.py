"""Structured logging: one JSON object per line in logs/nyabo.log (site-scoped).

    from nyabo_mn.log import log_event
    log_event("proposal.created", proposal=name, company=company, latency_ms=812)

Never pass message content, images, or secrets. Keys that look secret are redacted anyway.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

LOGGER_NAME = "nyabo"
REDACTED = "<redacted>"
_SECRET_MARKERS = ("token", "secret", "key", "password", "authorization")
# A Telegram bot token: "<bot id>:<35 url-safe characters>". Transport errors carry the
# request URL (https://api.telegram.org/bot<token>/<method>) inside their message, under a
# field name like "error", so matching on the field name alone is not enough.
_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


def scrub(text: str) -> str:
	"""Mask anything token-shaped, wherever in a string it appears."""
	return _TOKEN_RE.sub(REDACTED, text)


def redact(fields: dict[str, Any]) -> dict[str, Any]:
	out: dict[str, Any] = {}
	for key, value in fields.items():
		if any(marker in key.lower() for marker in _SECRET_MARKERS):
			out[key] = REDACTED
		else:
			out[key] = scrub(value) if isinstance(value, str) else value
	return out


def _logger():
	import frappe

	return frappe.logger(LOGGER_NAME, allow_site=True, file_count=10)


def log_event(event: str, level: str = "info", **fields: Any) -> None:
	import frappe

	payload = {
		"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
		"event": event,
		"site": getattr(frappe.local, "site", None),
		**redact(fields),
	}
	line = json.dumps(payload, ensure_ascii=False, default=str)
	getattr(_logger(), level.lower())(line)


def log_error(event: str, exc: BaseException | None = None, **fields: Any) -> None:
	"""Structured error line plus a Frappe Error Log entry (visible in the desk)."""
	import frappe

	log_event(event, level="error", error=repr(exc) if exc else None, **fields)
	# The Frappe Error Log is desk-visible, so the traceback is scrubbed too.
	message = scrub(frappe.get_traceback()) if exc else json.dumps(redact(fields), default=str)
	frappe.log_error(title=f"nyabo: {event}", message=message)
