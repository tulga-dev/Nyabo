"""Telegram Bot API client (https://core.telegram.org/bots/api, read 2026-09-08).

Only the methods Nyabo uses, with the exact parameter names of the API. Text is sent
plain (no ``parse_mode``) unless the caller escapes it, because card text carries
supplier names and model-written explanations that would otherwise break Markdown.
Messages longer than 4096 characters are refused by Telegram, so ``send_message`` chunks
at 4000 on a line boundary. The token never reaches a log line, the desk Error Log or an
admin chat: request URLs are built here and never repr()'d into an error (a transport
exception carries the URL), and ``log.scrub`` masks anything token-shaped as a backstop.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from typing import Any

from nyabo_mn.log import log_event

API_BASE = "https://api.telegram.org"
TIMEOUT_SECONDS = 15
MAX_TEXT_CHARS = 4000  # Telegram's hard limit is 4096; keep headroom for the chunk marker
MAX_CALLBACK_DATA_BYTES = 64


class TelegramApiError(RuntimeError):
	"""``ok: false`` from Telegram or a transport failure; ``description`` is Telegram's text."""

	def __init__(self, description: str, error_code: int | None = None, method: str | None = None):
		super().__init__(f"{method or 'telegram'}: {description}")
		self.description = description
		self.error_code = error_code
		self.method = method


def chunk_text(text: str, limit: int = MAX_TEXT_CHARS) -> list[str]:
	"""Split on the last newline before ``limit`` so a card line is never cut in half."""
	if len(text) <= limit:
		return [text]
	chunks: list[str] = []
	rest = text
	while len(rest) > limit:
		cut = rest.rfind("\n", 0, limit)
		if cut <= 0:
			cut = limit
		chunks.append(rest[:cut])
		rest = rest[cut:].lstrip("\n")
	if rest:
		chunks.append(rest)
	return chunks


class BotApi:
	"""Synchronous client over ``requests``; one instance per site, built from settings."""

	def __init__(self, token: str, session: Any | None = None):
		if not token:
			raise TelegramApiError("bot token is empty (TELEGRAM_BOT_TOKEN)", method="init")
		self._token = token
		if session is None:
			import requests  # Frappe ships requests; imported lazily so tests need not have it

			session = requests.Session()
		self._session = session

	# --- transport -----------------------------------------------------------------------------

	def _url(self, method: str) -> str:
		return f"{API_BASE}/bot{self._token}/{method}"

	def call(
		self, method: str, params: dict[str, Any] | None = None, files: dict[str, Any] | None = None
	) -> Any:
		"""POST one method; returns ``result``. JSON-encodes nested objects like reply_markup."""
		data: dict[str, Any] = {}
		for key, value in (params or {}).items():
			if value is None:
				continue
			data[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
		try:
			response = self._session.post(self._url(method), data=data, files=files, timeout=TIMEOUT_SECONDS)
		except Exception as exc:  # requests.RequestException and friends; the class is not imported here
			# Never repr() the exception: a requests transport error embeds the request URL,
			# which is /bot<token>/<method>, and this text reaches the log, the desk Error Log
			# and the admin chat. The class name says as much as we may say.
			log_event("telegram.api.transport_error", level="error", method=method, error=type(exc).__name__)
			raise TelegramApiError(f"transport error: {type(exc).__name__}", method=method) from exc
		try:
			payload = response.json()
		except ValueError as exc:
			raise TelegramApiError(f"non-JSON response (HTTP {response.status_code})", method=method) from exc
		if not isinstance(payload, dict) or not payload.get("ok"):
			description = str((payload or {}).get("description") or f"HTTP {response.status_code}")
			code = (payload or {}).get("error_code")
			log_event(
				"telegram.api.error", level="warning", method=method, description=description, code=code
			)
			raise TelegramApiError(description, error_code=code, method=method)
		return payload.get("result")

	# --- messages ------------------------------------------------------------------------------

	def send_message(
		self,
		chat_id: int | str,
		text: str,
		reply_markup: dict[str, Any] | None = None,
		parse_mode: str | None = None,
		disable_web_page_preview: bool = True,
	) -> dict[str, Any]:
		"""Send text, chunked; the keyboard goes on the last chunk. Returns the last Message."""
		result: dict[str, Any] = {}
		chunks = chunk_text(text)
		for index, chunk in enumerate(chunks):
			last = index == len(chunks) - 1
			params: dict[str, Any] = {"chat_id": chat_id, "text": chunk, "parse_mode": parse_mode}
			if disable_web_page_preview:
				# Bot API 7.0 replaced disable_web_page_preview with link_preview_options.
				params["link_preview_options"] = {"is_disabled": True}
			if last and reply_markup:
				params["reply_markup"] = reply_markup
			result = self.call("sendMessage", params)
		return result

	def edit_message_text(
		self,
		chat_id: int | str,
		message_id: int,
		text: str,
		reply_markup: dict[str, Any] | None = None,
		parse_mode: str | None = None,
	) -> Any:
		params: dict[str, Any] = {
			"chat_id": chat_id,
			"message_id": message_id,
			"text": chunk_text(text)[0],
			"parse_mode": parse_mode,
			"link_preview_options": {"is_disabled": True},
		}
		if reply_markup is not None:
			params["reply_markup"] = reply_markup
		return self.call("editMessageText", params)

	def edit_message_reply_markup(
		self, chat_id: int | str, message_id: int, reply_markup: dict[str, Any] | None
	) -> Any:
		return self.call(
			"editMessageReplyMarkup",
			{
				"chat_id": chat_id,
				"message_id": message_id,
				"reply_markup": reply_markup or {"inline_keyboard": []},
			},
		)

	def answer_callback_query(
		self, callback_query_id: str, text: str | None = None, show_alert: bool = False
	) -> Any:
		params: dict[str, Any] = {"callback_query_id": callback_query_id}
		if text:
			params["text"] = text[:200]
			params["show_alert"] = show_alert
		return self.call("answerCallbackQuery", params)

	def send_document(
		self, chat_id: int | str, content: bytes, filename: str, caption: str | None = None
	) -> dict[str, Any]:
		return self.call(
			"sendDocument",
			{"chat_id": chat_id, "caption": caption[:1024] if caption else None},
			files={"document": (filename, content)},
		)

	def send_photo(
		self, chat_id: int | str, content: bytes, filename: str = "photo.jpg", caption: str | None = None
	) -> dict[str, Any]:
		return self.call(
			"sendPhoto",
			{"chat_id": chat_id, "caption": caption[:1024] if caption else None},
			files={"photo": (filename, content)},
		)

	# --- files ---------------------------------------------------------------------------------

	def get_file(self, file_id: str) -> dict[str, Any]:
		"""File object: ``file_id``, ``file_path`` (relative), ``file_size``."""
		return self.call("getFile", {"file_id": file_id})

	def download(self, file_path: str) -> bytes:
		"""``https://api.telegram.org/file/bot<token>/<file_path>``; the path is valid for about an hour."""
		url = f"{API_BASE}/file/bot{self._token}/{file_path}"
		try:
			response = self._session.get(url, timeout=TIMEOUT_SECONDS)
		except Exception as exc:
			log_event(
				"telegram.api.transport_error", level="error", method="download", error=type(exc).__name__
			)
			raise TelegramApiError(f"transport error: {type(exc).__name__}", method="download") from exc
		if response.status_code != 200:
			raise TelegramApiError(f"download failed (HTTP {response.status_code})", method="download")
		return response.content

	# --- webhook and identity ------------------------------------------------------------------

	def set_webhook(self, url: str, secret_token: str, allowed_updates: list[str] | None = None) -> Any:
		return self.call(
			"setWebhook",
			{
				"url": url,
				"secret_token": secret_token,
				"allowed_updates": allowed_updates or ["message", "callback_query"],
			},
		)

	def delete_webhook(self, drop_pending_updates: bool = False) -> Any:
		return self.call("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

	def get_me(self) -> dict[str, Any]:
		return self.call("getMe")

	# --- command menu --------------------------------------------------------------------------

	def set_my_commands(
		self,
		commands: list[dict[str, str]],
		scope: dict[str, Any] | None = None,
		language_code: str | None = None,
	) -> Any:
		"""setMyCommands (Bot API, read 2026-09-09).

		``commands`` is an array of BotCommand: ``command`` is "1-32 characters. Can contain
		only lowercase English letters, digits and underscores" — no leading slash, and no
		Cyrillic, which is why ``nyabo_mn.telegram.commands`` registers Latin names for the
		Mongolian commands the router also accepts.
		"""
		return self.call(
			"setMyCommands", {"commands": commands, "scope": scope, "language_code": language_code}
		)

	def set_chat_menu_button(
		self, chat_id: int | str | None = None, menu_button: dict[str, Any] | None = None
	) -> Any:
		"""setChatMenuButton; ``chat_id`` omitted sets the default button for every private chat.

		``{"type": "commands"}`` is MenuButtonCommands, the button that opens the list
		``set_my_commands`` registered.
		"""
		return self.call(
			"setChatMenuButton",
			{"chat_id": chat_id, "menu_button": menu_button or {"type": "commands"}},
		)


# --- site-level accessor --------------------------------------------------------------------------

_override: Any | None = None


def get_bot() -> Any:
	"""The site's bot from settings, or the object installed with ``use_bot`` (tests)."""
	if _override is not None:
		return _override
	from nyabo_mn.config import get_settings

	settings = get_settings()
	settings.require("telegram")
	return BotApi(settings.telegram_bot_token)


@contextlib.contextmanager
def use_bot(bot: Any) -> Iterator[Any]:
	"""Install a bot object for the duration of a block (a FakeBotApi in tests)."""
	global _override
	previous = _override
	_override = bot
	try:
		yield bot
	finally:
		_override = previous
