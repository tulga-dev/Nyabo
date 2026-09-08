"""The bot token must never reach a log line, the desk Error Log or an admin chat (SEC-03).

A transport failure inside ``requests`` carries the request URL in its message, and the
request URL is ``https://api.telegram.org/bot<token>/<method>``, so ``repr(exc)`` leaks the
credential under a field name (``error``) that key-based redaction does not catch.
"""

from __future__ import annotations

import pytest

from nyabo_mn import log
from nyabo_mn.telegram import api

TOKEN = "7712345678:AAHfakefakefakefakefakefakefakefake00"
URL_ERROR = (
	"ConnectionError(MaxRetryError(\"HTTPSConnectionPool(host='api.telegram.org', port=443): "
	f'Max retries exceeded with url: /bot{TOKEN}/sendMessage"))'
)


def test_scrub_masks_a_token_anywhere_in_a_string():
	assert TOKEN not in log.scrub(URL_ERROR)
	assert log.REDACTED in log.scrub(URL_ERROR)
	assert log.scrub("nothing to hide here") == "nothing to hide here"


def test_redact_scrubs_values_not_only_secret_looking_keys():
	fields = log.redact({"error": URL_ERROR, "bot_token": TOKEN, "chat_id": 4242})
	assert TOKEN not in fields["error"]
	assert fields["bot_token"] == log.REDACTED
	assert fields["chat_id"] == 4242  # non-strings pass through untouched


def test_log_error_scrubs_the_desk_error_log(monkeypatch):
	"""frappe.log_error rows are readable by anyone with desk access."""
	import frappe

	rows: list[dict] = []
	monkeypatch.setattr(log, "log_event", lambda *a, **k: None)
	monkeypatch.setattr(frappe, "get_traceback", lambda *a, **k: f"Traceback...\n  url: /bot{TOKEN}/x")
	monkeypatch.setattr(frappe, "log_error", lambda title, message: rows.append({title: message}))
	log.log_error("telegram.handler_failed", ConnectionError(URL_ERROR), chat_id=4242)
	assert rows and TOKEN not in str(rows[0])


class _ExplodingSession:
	"""Stands in for ``requests``: the exception message carries the URL it was given."""

	def post(self, url, **kwargs):
		raise ConnectionError(f"Max retries exceeded with url: {url}")

	def get(self, url, **kwargs):
		raise ConnectionError(f"Max retries exceeded with url: {url}")


def test_transport_error_never_carries_the_token(monkeypatch):
	events: list[dict] = []
	monkeypatch.setattr(log, "log_event", lambda event, **f: events.append({"event": event, **f}))
	monkeypatch.setattr(api, "log_event", lambda event, **f: events.append({"event": event, **f}))
	bot = api.BotApi(TOKEN, session=_ExplodingSession())

	with pytest.raises(api.TelegramApiError) as call_error:
		bot.call("sendMessage", {"chat_id": 1, "text": "сайн уу"})
	with pytest.raises(api.TelegramApiError) as download_error:
		bot.download("photos/file_1.jpg")

	for error in (call_error, download_error):
		assert TOKEN not in str(error.value)
		assert TOKEN not in repr(error.value)
		assert "ConnectionError" in str(error.value)  # the class name still says what happened
	assert events and all(TOKEN not in str(event) for event in events)
