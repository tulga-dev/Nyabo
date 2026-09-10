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

	def send_chat_action(self, chat_id: int | str, action: str = "typing") -> Any:
		"""sendChatAction (Bot API, read 2026-09-09).

		"Use this method when you need to tell the user that something is happening on the bot's
		side. The status is set for 5 seconds or less (when a message arrives from your bot,
		Telegram clients clear its typing status)." The docs add: "We only recommend using this
		method when a response from the bot will take a noticeable amount of time to arrive" —
		so this is for the two steps that do their work before replying (matching a bank line
		against the ledger, parsing an uploaded stock list), not for every prompt.
		"""
		return self.call("sendChatAction", {"chat_id": chat_id, "action": action})

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

	# --- rich messages (Bot API 10.1+, read 2026-09-10) ----------------------------------------
	#
	# ``sendRichMessage`` takes ``rich_message`` (InputRichMessage: "Exactly one of the fields
	# html, markdown, or blocks must be used") and returns the Message; ``editMessageText``
	# accepts the same ``rich_message`` in place of ``text``; ``sendRichMessageDraft`` streams
	# "a temporary 30-second preview" under ``draft_id`` and "once the output is finalized, you
	# must call sendRichMessage with the complete message to persist it". Every rich send here
	# carries the card's plain-text twin (``rich.render_text``), because a card the user never
	# sees is worse than a plain one: a bot server older than 10.1 answers 404 to the method,
	# and a malformed body answers 400. The 404 is learned once per process; a 400 is logged
	# with Telegram's description and that one message goes out plain.

	def send_rich_message(
		self,
		chat_id: int | str,
		html: str,
		*,
		fallback_text: str,
		fallback_markup: dict[str, Any] | None = None,
		reply_markup: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		"""``reply_markup`` is an ordinary inline keyboard under the rich body (``sendRichMessage``
		and ``editMessageText`` both take one); the wizard uses it so its toggle buttons keep going
		through ``editMessageReplyMarkup``. In the plain fallback it is the keyboard, unless the
		card's own buttons (``fallback_markup``) already are."""
		if not _rich_unsupported():
			try:
				return self.call(
					"sendRichMessage",
					{"chat_id": chat_id, "rich_message": {"html": html}, "reply_markup": reply_markup},
				)
			except TelegramApiError as exc:
				_note_rich_refusal(exc, "sendRichMessage")
		return self.send_message(chat_id, fallback_text, reply_markup=fallback_markup or reply_markup)

	def edit_rich_message(
		self,
		chat_id: int | str,
		message_id: int,
		html: str,
		*,
		fallback_text: str,
		fallback_markup: dict[str, Any] | None = None,
		reply_markup: dict[str, Any] | None = None,
	) -> Any:
		if not _rich_unsupported():
			try:
				return self.call(
					"editMessageText",
					{
						"chat_id": chat_id,
						"message_id": message_id,
						"rich_message": {"html": html},
						"reply_markup": reply_markup,
					},
				)
			except TelegramApiError as exc:
				_note_rich_refusal(exc, "editMessageText")
		return self.edit_message_text(
			chat_id, message_id, fallback_text, reply_markup=fallback_markup or reply_markup
		)

	def send_rich_draft(self, chat_id: int | str, draft_id: int, html: str, can_stop: bool = False) -> bool:
		"""A streamed preview under ``draft_id``; never raises, because it is only a sign of life."""
		if _rich_unsupported():
			return False
		try:
			self.call(
				"sendRichMessageDraft",
				{
					"chat_id": chat_id,
					"draft_id": draft_id,
					"rich_message": {"html": html},
					"can_stop": can_stop,
				},
			)
			return True
		except TelegramApiError as exc:
			_note_rich_refusal(exc, "sendRichMessageDraft")
			return False

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
		"""setWebhook. ``allowed_updates`` names ``callback_query`` explicitly and must keep doing so.

		"Specify an empty list to receive all update types except chat_member, message_reaction,
		and message_reaction_count (default). If not specified, the previous setting will be
		used." An explicit list that dropped ``callback_query`` would stop every button tap with
		no error anywhere — the bot would simply never hear a tap again.
		"""
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


# --- rich message support, learned at runtime -----------------------------------------------------

_rich_refused_for_process = False


def _rich_unsupported() -> bool:
	return _rich_refused_for_process


def forget_rich_refusal() -> None:
	"""Clear what has been learned. For tests; a process learns this once and keeps it."""
	global _rich_refused_for_process
	_rich_refused_for_process = False


def _note_rich_refusal(exc: TelegramApiError, method: str) -> None:
	"""404 means the bot server predates the method: stop asking. Anything else: this card only.

	A 400 is almost always our HTML (a tag the reference does not list, a table cell with a
	block in it), so the description is logged in full — it is Telegram's own text, and it is
	what fixes the card. A rate limit or a server error is re-raised: the plain send would
	meet the same wall, and the caller's retry policy is the right one for it.
	"""
	global _rich_refused_for_process
	if exc.error_code == 404:
		_rich_refused_for_process = True
		log_event("telegram.rich.unsupported", level="warning", method=method, description=exc.description)
		return
	if exc.error_code == 400:
		log_event("telegram.rich.rejected", level="warning", method=method, description=exc.description)
		return
	raise exc


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


def notify_admins(summary: str, company: str = "") -> None:
	"""Push one escalated question to the admin chats (``agent.pipeline.escalate_handler``).

	The pipeline may not import the Telegram layer eagerly, so it looks this name up on this
	module at call time; the signature is therefore the pipeline's ``(summary, company)`` and
	not ``router.notify_admins(bot, settings, text)``, which is what this builds the bot and
	the settings for. It exists as a named function rather than a duck-typed guess because
	the user has already been told an admin was asked: a notifier that resolves to ``None``
	turns that sentence into a lie, silently.
	"""
	from nyabo_mn.config import get_settings
	from nyabo_mn.i18n import mn
	from nyabo_mn.telegram.router import notify_admins as router_notify_admins

	text = mn.MSG_ADMIN_QUESTION_ESCALATED.format(company=company or "-", summary=summary)
	router_notify_admins(get_bot(), get_settings(), text)


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
