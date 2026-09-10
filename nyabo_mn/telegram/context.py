"""Per-update context handed to every handler.

One object carries the parsed update, the linked user, the active company and the bot,
so handler signatures stay ``handle(ctx, ...)`` and a test can build the context from a
dict without going through the webhook. Reply helpers live here rather than on the bot
because they know the chat id and record what was sent for the error path.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import frappe

from nyabo_mn.config import Settings
from nyabo_mn.telegram import state as chat_state

ACCOUNTANT_ROLES = ("Accountant", "Admin")


@dataclasses.dataclass
class Ctx:
	bot: Any
	settings: Settings
	update: dict[str, Any]
	chat_id: int | str
	telegram_id: int | str
	sender: dict[str, Any]
	message: dict[str, Any] | None = None
	callback: dict[str, Any] | None = None
	text: str = ""
	link: Any | None = None
	company: str | None = None
	answered: bool = False

	# --- identity ------------------------------------------------------------------------------

	@property
	def role(self) -> str | None:
		"""The role on the *active* company: someone may own one company and keep another's books."""
		return chat_state.role_for(self.link, self.company) if self.link is not None else None

	@property
	def is_accountant(self) -> bool:
		return self.role in ACCOUNTANT_ROLES

	@property
	def is_owner(self) -> bool:
		return self.role == "Owner"

	@property
	def is_admin(self) -> bool:
		"""Admin by link role or by ``ADMIN_TELEGRAM_IDS`` (bootstrap before any link exists)."""
		return self.role == "Admin" or self.is_site_admin

	@property
	def is_site_admin(self) -> bool:
		"""In ``ADMIN_TELEGRAM_IDS``: an admin of the *site*, not of one company (VER-08).

		``is_admin`` is per company, because ``/link admin <company>`` grants the role on that
		company's books. Anything that is one row for every company on the site — a posting
		pattern, a tax parameter — needs this stronger check instead.
		"""
		try:
			admin_ids = self.settings.admin_telegram_ids
		except ValueError:
			admin_ids = frozenset()
		return int(self.telegram_id) in admin_ids

	@property
	def user(self) -> str:
		return frappe.session.user

	@property
	def companies(self) -> list[str]:
		return chat_state.user_companies(self.link) if self.link is not None else []

	# --- update shape --------------------------------------------------------------------------

	@property
	def is_callback(self) -> bool:
		return self.callback is not None

	@property
	def callback_data(self) -> str:
		return (self.callback or {}).get("data") or ""

	@property
	def callback_message_id(self) -> int | None:
		return ((self.callback or {}).get("message") or {}).get("message_id")

	@property
	def message_id(self) -> int | None:
		return (self.message or {}).get("message_id")

	@property
	def photo(self) -> dict[str, Any] | None:
		"""The largest PhotoSize (Telegram lists sizes ascending)."""
		sizes = (self.message or {}).get("photo") or []
		return sizes[-1] if sizes else None

	@property
	def document(self) -> dict[str, Any] | None:
		return (self.message or {}).get("document")

	@property
	def command(self) -> str | None:
		"""``/хаалт@nyabo_bot 2026-08`` -> ``/хаалт``; None for ordinary text."""
		if self.is_callback or not self.text.startswith("/"):
			return None
		head = self.text.split(maxsplit=1)[0]
		return head.split("@", 1)[0].lower()

	@property
	def args(self) -> str:
		parts = self.text.split(maxsplit=1)
		return parts[1].strip() if len(parts) > 1 else ""

	# --- replies -------------------------------------------------------------------------------

	def reply(self, text: str, reply_markup: dict[str, Any] | None = None) -> dict[str, Any]:
		return self.bot.send_message(self.chat_id, text, reply_markup=reply_markup)

	def edit(self, message_id: int | None, text: str, reply_markup: dict[str, Any] | None = None) -> Any:
		"""Edit in place when we know the message, else send a new one (Telegram refuses edits
		of identical text and of messages older than 48 h; both fall back to a fresh message)."""
		if message_id is None:
			return self.reply(text, reply_markup)
		try:
			return self.bot.edit_message_text(self.chat_id, message_id, text, reply_markup=reply_markup)
		except Exception as exc:  # TelegramApiError or a transport failure: never lose the reply
			from nyabo_mn.log import log_event

			log_event("telegram.edit_failed", level="warning", message_id=message_id, error=repr(exc))
			return self.reply(text, reply_markup)

	# --- rich cards (telegram.rich) ---------------------------------------------------------------

	def reply_card(self, card: Any, reply_markup: dict[str, Any] | None = None) -> dict[str, Any]:
		"""Send a ``rich.Card``; the bot falls back to its plain-text twin when it has to.

		``reply_markup`` is a classic inline keyboard under the card, for a card whose buttons
		are toggled with ``editMessageReplyMarkup`` (the onboarding wizard); most cards carry
		their buttons in the body instead.
		"""
		from nyabo_mn.telegram import rich

		text, markup = rich.render_text(card)
		return self.bot.send_rich_message(
			self.chat_id,
			rich.render_html(card),
			fallback_text=text,
			fallback_markup=markup,
			reply_markup=reply_markup,
		)

	def edit_card(self, message_id: int | None, card: Any, reply_markup: dict[str, Any] | None = None) -> Any:
		"""Redraw a card in place, else send it fresh — the same rule as ``edit``."""
		from nyabo_mn.telegram import rich

		if message_id is None:
			return self.reply_card(card, reply_markup)
		text, markup = rich.render_text(card)
		try:
			return self.bot.edit_rich_message(
				self.chat_id,
				message_id,
				rich.render_html(card),
				fallback_text=text,
				fallback_markup=markup,
				reply_markup=reply_markup,
			)
		except Exception as exc:  # TelegramApiError or a transport failure: never lose the reply
			from nyabo_mn.log import log_event

			log_event("telegram.edit_failed", level="warning", message_id=message_id, error=repr(exc))
			return self.reply_card(card, reply_markup)

	def draft(self, card: Any, draft_id: int, can_stop: bool = False) -> bool:
		"""Stream a preview (``sendRichMessageDraft``); a refusal costs nothing but the preview."""
		from nyabo_mn.telegram import rich

		return bool(self.bot.send_rich_draft(self.chat_id, draft_id, rich.render_html(card), can_stop))

	def send_document(self, content: bytes, filename: str, caption: str | None = None) -> Any:
		return self.bot.send_document(self.chat_id, content, filename, caption=caption)

	def answer(self, text: str | None = None, show_alert: bool = False) -> None:
		"""Answer the callback query once; Telegram ignores a second answer, so the first wins."""
		if not self.callback or not self.callback.get("id") or self.answered:
			return
		self.answered = True
		self.bot.answer_callback_query(self.callback["id"], text=text, show_alert=show_alert)

	# --- state ---------------------------------------------------------------------------------

	def set_state(self, name: str, payload: dict[str, Any] | None = None) -> None:
		chat_state.set_state(self.chat_id, name, payload, telegram_id=self.telegram_id)

	def get_state(self) -> tuple[str | None, dict[str, Any]]:
		return chat_state.get_state(self.chat_id)

	def clear_state(self) -> None:
		chat_state.clear_state(self.chat_id)


def from_update(update: dict[str, Any], bot: Any, settings: Settings) -> Ctx | None:
	"""Build a context from a Telegram Update; None for update kinds Nyabo ignores."""
	if update.get("callback_query"):
		callback = update["callback_query"]
		message = callback.get("message") or {}
		chat = message.get("chat") or {}
		sender = callback.get("from") or {}
		if chat.get("id") is None or sender.get("id") is None:
			return None
		return Ctx(
			bot=bot,
			settings=settings,
			update=update,
			chat_id=chat["id"],
			telegram_id=sender["id"],
			sender=sender,
			message=None,
			callback=callback,
			text="",
		)
	message = update.get("message")
	if not message:  # edited_message, channel posts, service updates: nothing to do
		return None
	chat = message.get("chat") or {}
	sender = message.get("from") or {}
	if chat.get("id") is None or sender.get("id") is None:
		return None
	text = (message.get("text") or message.get("caption") or "").strip()
	return Ctx(
		bot=bot,
		settings=settings,
		update=update,
		chat_id=chat["id"],
		telegram_id=sender["id"],
		sender=sender,
		message=message,
		callback=None,
		text=text,
	)
