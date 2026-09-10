"""The Mini App endpoint: who it answers, what it answers, and the button that opens it."""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import frappe
import pytest

from nyabo_mn import miniapp
from nyabo_mn.core import dates
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.reports import dashboard as data
from nyabo_mn.setup import demo
from tests.fixtures.telegram.fake_bot import FakeBotApi, link_user, message_update, run

TOKEN = "12345:test-bot-token"
TODAY = dt.date.today()
PERIOD = dates.period_of(TODAY)


@pytest.fixture(autouse=True)
def _token(site, monkeypatch):
	monkeypatch.setitem(frappe.conf, "TELEGRAM_BOT_TOKEN", TOKEN)
	monkeypatch.setitem(frappe.conf, "telegram_bot_token", TOKEN)


def _init_data(telegram_id: int, token: str = TOKEN) -> str:
	return miniapp.sign_init_data(
		{
			"auth_date": int(time.time()) - 5,
			"query_id": "q1",
			"user": {"id": telegram_id, "first_name": "Бат"},
		},
		token,
	)


def test_a_linked_user_gets_their_companys_figures(books):
	demo.seed(books, today=TODAY)
	link_user(9501, "Accountant", books)
	answer = miniapp.data(_init_data(9501))
	assert answer["company"] == books and answer["period"] == PERIOD
	assert answer["month"]["empty"] is False
	assert answer["month"]["revenue"].endswith("₮") and answer["month"]["profit_negative"] is False
	assert [row["period"] for row in answer["trend"]] == [
		data.shift_period(PERIOD, -i) for i in range(5, -1, -1)
	]
	assert answer["top"][0]["amount"] == f"{fmt_mnt(demo.RENT[1])}₮"
	assert answer["vouchers"] and all(v["date"].startswith(PERIOD) for v in answer["vouchers"])
	assert answer["labels"]["export"] == mn.BTN_MINIAPP_EXPORT
	assert frappe.session.user != "Guest", "the request runs as the link's user"


def test_the_page_pages_by_month(books):
	demo.seed(books, today=TODAY)
	link_user(9502, "Accountant", books)
	previous = data.shift_period(PERIOD, -1)
	answer = miniapp.data(_init_data(9502), period=previous)
	assert answer["period"] == previous and answer["next_period"] == PERIOD
	assert miniapp.data(_init_data(9502), period="not-a-month")["period"] == PERIOD


def test_bad_init_data_and_unlinked_users_are_refused(books):
	link_user(9503, "Accountant", books)
	with pytest.raises(frappe.PermissionError, match="баталгаажсангүй"):
		miniapp.data(_init_data(9503, token="999:another-bot"))
	with pytest.raises(frappe.PermissionError, match="холбогдоогүй"):
		miniapp.data(_init_data(9599))
	link_user(9504, "Owner", None)
	with pytest.raises(frappe.PermissionError):
		miniapp.data(_init_data(9504))


def test_the_export_is_the_months_vouchers_as_xlsx(books):
	demo.seed(books, today=TODAY)
	link_user(9505, "Accountant", books)
	miniapp.export_xlsx(_init_data(9505), period=PERIOD)
	assert frappe.response["filename"] == f"nyabo_{PERIOD}.xlsx"
	assert frappe.response["type"] == "binary" and len(frappe.response["filecontent"]) > 100


def test_the_dashboard_offers_the_mini_app_only_on_https(books, monkeypatch):
	link_user(9506, "Accountant", books)
	monkeypatch.setattr(miniapp, "page_url", lambda: None)
	bot = FakeBotApi()
	run(bot, message_update(9506, "/меню"))
	assert mn.BTN_MINI_APP not in bot.last_text and "web_app" not in bot.last_html

	monkeypatch.setattr(miniapp, "page_url", lambda: "https://nyabo.example/nyabo_app")
	run(bot, message_update(9506, "/меню"))
	expected = '<tg-button type="web_app" url="https://nyabo.example/nyabo_app">' + mn.BTN_MINI_APP
	assert expected in bot.last_html
	buttons = [b for row in bot.last_markup()["inline_keyboard"] for b in row]
	assert {"text": mn.BTN_MINI_APP, "web_app": {"url": "https://nyabo.example/nyabo_app"}} in buttons


def test_page_url_is_none_off_https(monkeypatch):
	monkeypatch.setattr(frappe.utils, "get_url", lambda path=None: "http://test.localhost" + (path or ""))
	assert miniapp.page_url() is None
	monkeypatch.setattr(
		frappe.utils, "get_url", lambda path=None: "https://nyabo.s.frappe.cloud" + (path or "")
	)
	assert miniapp.page_url() == "https://nyabo.s.frappe.cloud/nyabo_app"


def test_the_page_is_a_standalone_document_with_no_jinja_outside_raw_blocks():
	page = Path(miniapp.__file__).parent / "www" / "nyabo_app.html"
	text = page.read_text(encoding="utf-8")
	assert text.startswith("<!-- no-base -->"), "Frappe must not wrap it in the website base template"
	assert text.count("{% raw %}") == text.count("{% endraw %}") == 2
	assert "nyabo_mn.miniapp.data" in text and "nyabo_mn.miniapp.export_xlsx" in text
	assert "telegram-web-app.js" in text
	assert "<!-- csrf_token -->" in text and "X-Frappe-CSRF-Token" in text
	outside = "".join(part.split("{% endraw %}", 1)[-1] for part in text.split("{% raw %}"))
	assert "{{" not in outside and "{%" not in outside.replace("{% raw %}", "")
