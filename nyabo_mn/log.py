"""Structured logging: one JSON object per line in logs/nyabo.log (site-scoped).

    from nyabo_mn.log import log_event
    log_event("proposal.created", proposal=name, company=company, latency_ms=812)

Never pass message content, images, or secrets. Keys that look secret are redacted anyway.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

LOGGER_NAME = "nyabo"
_SECRET_MARKERS = ("token", "secret", "key", "password", "authorization")


def redact(fields: dict[str, Any]) -> dict[str, Any]:
	return {
		k: ("<redacted>" if any(m in k.lower() for m in _SECRET_MARKERS) else v) for k, v in fields.items()
	}


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
	message = frappe.get_traceback() if exc else json.dumps(redact(fields), default=str)
	frappe.log_error(title=f"nyabo: {event}", message=message)
