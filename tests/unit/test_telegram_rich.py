"""Rich cards render to Telegram's Rich HTML and to their plain twin, and the API falls back.

What is pinned: the tags are the ones the Bot API reference lists under "Rich HTML style";
untrusted text is escaped; a button's callback data is the same bytes in both drawings; the
API learns a 404 once and logs a 400 per card, and in both cases the user still gets the
plain message. The token never appears anywhere on these paths either.
"""

from __future__ import annotations

import json

import pytest

from nyabo_mn.telegram import api, rich

TOKEN = "12345:token-that-must-not-leak"


def _card() -> rich.Card:
	return rich.card(
		rich.Heading("Хамгийн том зардал · 9-р сар"),
		rich.Paragraph(["Энэ сард хамгийн их мөнгө ", rich.mark("түрээсэнд"), " гарсан."]),
		rich.Table(
			[
				[rich.Cell("Данс", header=True), rich.Cell("Дүн", header=True, align=rich.ALIGN_RIGHT)],
				["Түрээс <ХХК> & Co", rich.Cell("4 200 000₮", align=rich.ALIGN_RIGHT)],
			],
			striped=True,
		),
		rich.Details("Түрээсийн 2 бичилт", [rich.Paragraph("09-01 · 2 100 000₮")], open=True),
		rich.Checklist([rich.CheckItem("3 баримт", checked=False), rich.CheckItem("тулгасан", checked=True)]),
		rich.Buttons(
			[
				rich.Button("← 8-р сар", data="q:spd:6210:2026-08"),
				rich.Button("Тайлан", data="d:rep", style=rich.STYLE_PRIMARY),
				rich.Button("Самбар", web_app="https://nyabo.example/app"),
			]
		),
		rich.Footer("Тоо бүрийг дэвтрээс тооцов"),
	)


def test_the_html_uses_only_the_tags_the_reference_lists_and_escapes_text():
	html = rich.render_html(_card())
	assert html.startswith("<h4>Хамгийн том зардал · 9-р сар</h4>")
	assert "<p>Энэ сард хамгийн их мөнгө <mark>түрээсэнд</mark> гарсан.</p>" in html
	assert "<table bordered striped compact>" in html
	assert '<th align="right">Дүн</th>' in html
	assert "<td>Түрээс &lt;ХХК&gt; &amp; Co</td>" in html  # untrusted text cannot open a tag
	assert "<details open><summary>Түрээсийн 2 бичилт</summary><p>09-01 · 2 100 000₮</p></details>" in html
	assert (
		'<ul><li><input type="checkbox">3 баримт</li><li><input type="checkbox" checked>тулгасан</li></ul>'
		in html
	)
	assert (
		"<tg-button-row>"
		'<tg-button type="callback_data" data="q:spd:6210:2026-08">← 8-р сар</tg-button>'
		'<tg-button type="callback_data" style="primary" data="d:rep">Тайлан</tg-button>'
		'<tg-button type="web_app" url="https://nyabo.example/app">Самбар</tg-button>'
		"</tg-button-row>"
	) in html
	assert html.endswith("<footer>Тоо бүрийг дэвтрээс тооцов</footer>")


def test_the_plain_twin_carries_the_same_words_and_the_same_callback_data():
	text, markup = rich.render_text(_card())
	assert text.splitlines()[0] == "Хамгийн том зардал · 9-р сар"
	assert "Энэ сард хамгийн их мөнгө түрээсэнд гарсан." in text
	assert "Данс | Дүн" in text and "Түрээс <ХХК> & Co | 4 200 000₮" in text
	assert "☐ 3 баримт" in text and "☑ тулгасан" in text
	assert text.endswith("Тоо бүрийг дэвтрээс тооцов")
	assert markup == {
		"inline_keyboard": [
			[
				{"text": "← 8-р сар", "callback_data": "q:spd:6210:2026-08"},
				{"text": "Тайлан", "style": "primary", "callback_data": "d:rep"},
				{"text": "Самбар", "web_app": {"url": "https://nyabo.example/app"}},
			]
		]
	}
	assert [b.data for b in rich.buttons_of(_card()) if b.data] == ["q:spd:6210:2026-08", "d:rep"]


def test_a_card_without_buttons_has_no_keyboard():
	text, markup = rich.render_text(rich.card(rich.Paragraph("Сайн уу"), None))
	assert text == "Сайн уу" and markup is None


def test_a_disabled_button_is_drawn_dead_in_both_renderings():
	button = rich.Button("Батлах", style=rich.STYLE_SUCCESS, disabled=True)
	html = rich.render_html(rich.card(rich.Buttons([button])))
	assert (
		html == '<tg-button-row><tg-button type="disabled" style="success">Батлах</tg-button></tg-button-row>'
	)
	_text, markup = rich.render_text(rich.card(rich.Buttons([button])))
	assert markup == {"inline_keyboard": [[{"text": "Батлах", "style": "success", "disabled": {}}]]}


def test_a_link_style_button_is_a_plain_keyboard_button_in_the_twin():
	"""InlineKeyboardButton.style knows danger/success/primary only; ``link`` is rich-only."""
	_text, markup = rich.render_text(
		rich.card(rich.Buttons([rich.Button("Хаах", data="d:x", style=rich.STYLE_LINK)]))
	)
	assert markup == {"inline_keyboard": [[{"text": "Хаах", "callback_data": "d:x"}]]}


def test_the_model_refuses_what_telegram_would_refuse():
	with pytest.raises(ValueError, match="64 bytes"):
		rich.Button("x", data="d:" + "ү" * 40)
	with pytest.raises(ValueError, match="exactly one"):
		rich.Button("x")
	with pytest.raises(ValueError, match="exactly one"):
		rich.Button("x", data="d:a", url="https://t.me")
	with pytest.raises(ValueError, match="style"):
		rich.Button("x", data="d:a", style="blue")
	with pytest.raises(ValueError, match="1-8"):
		rich.Buttons([])
	with pytest.raises(ValueError, match="20 cells"):
		rich.render_html(rich.card(rich.Table([["c"] * 21])))
	with pytest.raises(ValueError, match="32768"):
		rich.render_html(rich.card(rich.Paragraph("х" * 40000)))


def test_thinking_renders_the_draft_only_tag():
	assert (
		rich.render_html(rich.card(rich.Thinking("Бодож байна…")))
		== "<tg-thinking>Бодож байна…</tg-thinking>"
	)


# --- the API: rich first, plain when it must ---------------------------------------------------------


class _Response:
	def __init__(self, payload: dict, status: int = 200):
		self._payload = payload
		self.status_code = status

	def json(self) -> dict:
		return self._payload


class _Session:
	"""Answers ``sendRichMessage`` as scripted and accepts everything else."""

	def __init__(self, rich_answer: dict):
		self.rich_answer = rich_answer
		self.posts: list[tuple[str, dict]] = []

	def post(self, url, data=None, files=None, timeout=None):
		method = url.rsplit("/", 1)[-1]
		self.posts.append((method, dict(data or {})))
		if method in ("sendRichMessage", "sendRichMessageDraft") or (
			method == "editMessageText" and "rich_message" in (data or {})
		):
			return _Response(self.rich_answer, 200 if self.rich_answer.get("ok") else 400)
		return _Response({"ok": True, "result": {"message_id": 7}})


@pytest.fixture(autouse=True)
def _fresh_process():
	api.forget_rich_refusal()
	yield
	api.forget_rich_refusal()


def test_a_supported_server_gets_the_rich_body_and_nothing_else():
	session = _Session({"ok": True, "result": {"message_id": 5}})
	bot = api.BotApi(TOKEN, session=session)
	result = bot.send_rich_message(1, "<p>x</p>", fallback_text="x", fallback_markup={"inline_keyboard": []})
	assert result == {"message_id": 5}
	assert [m for m, _ in session.posts] == ["sendRichMessage"]
	assert json.loads(session.posts[0][1]["rich_message"]) == {"html": "<p>x</p>"}


def test_a_404_is_learned_once_and_every_later_card_goes_out_plain(monkeypatch):
	events: list[dict] = []
	monkeypatch.setattr(api, "log_event", lambda event, **f: events.append({"event": event, **f}))
	session = _Session({"ok": False, "error_code": 404, "description": "Not Found"})
	bot = api.BotApi(TOKEN, session=session)
	bot.send_rich_message(1, "<p>x</p>", fallback_text="x plain", fallback_markup={"inline_keyboard": [[]]})
	bot.edit_rich_message(1, 9, "<p>y</p>", fallback_text="y plain")
	assert bot.send_rich_draft(1, 3, "<tg-thinking>…</tg-thinking>") is False
	assert [m for m, _ in session.posts] == ["sendRichMessage", "sendMessage", "editMessageText"]
	assert session.posts[1][1]["text"] == "x plain"
	assert "rich_message" not in session.posts[2][1] and session.posts[2][1]["text"] == "y plain"
	assert [e["event"] for e in events if e["event"].startswith("telegram.rich")] == [
		"telegram.rich.unsupported"
	]
	assert all(TOKEN not in str(e) for e in events)


def test_a_400_sends_that_card_plain_logs_the_description_and_keeps_trying(monkeypatch):
	events: list[dict] = []
	monkeypatch.setattr(api, "log_event", lambda event, **f: events.append({"event": event, **f}))
	session = _Session(
		{"ok": False, "error_code": 400, "description": "Bad Request: can't parse rich message"}
	)
	bot = api.BotApi(TOKEN, session=session)
	bot.send_rich_message(1, "<bad>", fallback_text="plain one")
	bot.send_rich_message(1, "<bad>", fallback_text="plain two")
	assert [m for m, _ in session.posts] == [
		"sendRichMessage",
		"sendMessage",
		"sendRichMessage",
		"sendMessage",
	]
	rejected = [e for e in events if e["event"] == "telegram.rich.rejected"]
	assert len(rejected) == 2 and "can't parse" in rejected[0]["description"]


def test_a_rate_limit_is_not_swallowed_by_the_fallback():
	session = _Session({"ok": False, "error_code": 429, "description": "Too Many Requests"})
	bot = api.BotApi(TOKEN, session=session)
	with pytest.raises(api.TelegramApiError, match="Too Many"):
		bot.send_rich_message(1, "<p>x</p>", fallback_text="x")
	assert [m for m, _ in session.posts] == ["sendRichMessage"]
