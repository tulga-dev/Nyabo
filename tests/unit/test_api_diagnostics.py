"""The browser-callable endpoints answer a System Manager and no one else, and leak nothing.

They exist because a Frappe Cloud site has no shell on the plans Nyabo targets. That makes
them a new permission surface: these tests pin who may call them and what comes back. The
parsing rules themselves (upper/lowercase keys, defaults, which key belongs to which
feature) are ``Settings``' own, and live in tests/test_config.py.
"""

from __future__ import annotations

import frappe
import pytest

from nyabo_mn import api
from tests.fixtures.telegram.fake_bot import FakeBotApi

TOKEN = "12345:a-token-that-must-never-be-echoed"


def _set(monkeypatch, key: str, value: str) -> None:
	"""The site config is read by either case, so a test that clears a key must clear both."""
	monkeypatch.setitem(frappe.conf, key, value)
	monkeypatch.setitem(frappe.conf, key.lower(), value)


def test_config_check_says_a_secret_is_set_without_echoing_it(site, monkeypatch):
	_set(monkeypatch, "TELEGRAM_BOT_TOKEN", TOKEN)
	answer = api.config_check()
	assert set(answer) == {"missing_by_feature", "values", "models"}
	assert answer["values"]["TELEGRAM_BOT_TOKEN"] == "<set>"
	assert TOKEN not in repr(answer)
	assert answer["missing_by_feature"]["telegram"] == []


def test_config_check_answers_the_model_each_purpose_will_run_on(site, monkeypatch):
	"""No shell: this is where the founder sees the routing resolved, key or no key."""
	from nyabo_mn.agent.llm_client import PURPOSES

	_set(monkeypatch, "OPENAI_MODEL", "gpt-5.6-sol")
	_set(monkeypatch, "OPENAI_MODEL_CLASSIFY", "")
	models = api.config_check()["models"]
	assert models["provider"] == "openai"
	assert set(models["by_purpose"]) == set(PURPOSES)
	assert models["by_purpose"]["extract"] == {
		"model": "gpt-5.6-terra",
		"source": "purpose default",
		"warning": None,
	}
	assert models["by_purpose"]["classify"]["model"] == "gpt-6-astra"
	assert models["by_purpose"]["question"]["model"] == "gpt-6-astra"
	# eval and other have no model of their own, so they are what OPENAI_MODEL says.
	assert models["by_purpose"]["eval"] == {
		"model": "gpt-5.6-sol",
		"source": "OPENAI_MODEL",
		"warning": None,
	}


def test_config_check_shows_a_typo_in_a_per_purpose_key(site, monkeypatch):
	_set(monkeypatch, "OPENAI_MODEL_QUESTION", "gpt-6-astro")
	question = api.config_check()["models"]["by_purpose"]["question"]
	assert question == {
		"model": "gpt-6-astro",
		"source": "OPENAI_MODEL_QUESTION",
		"warning": question["warning"],
	}
	assert "not in the allowlist" in question["warning"]


def test_config_check_names_the_key_a_feature_still_needs(site, monkeypatch):
	_set(monkeypatch, "TELEGRAM_BOT_TOKEN", "")
	answer = api.config_check()
	assert answer["missing_by_feature"]["telegram"] == ["TELEGRAM_BOT_TOKEN"]
	assert answer["values"]["TELEGRAM_BOT_TOKEN"] == "<missing>"


def test_a_user_without_system_manager_is_refused(site, as_user):
	email = "reader@example.com"
	if not frappe.db.exists("User", email):
		doc = frappe.get_doc({"doctype": "User", "email": email, "first_name": "Reader"})
		doc.flags.ignore_permissions = True
		doc.insert()
	with as_user(email):
		with pytest.raises(frappe.PermissionError):
			api.config_check()


def test_the_endpoints_are_whitelisted(site):
	assert getattr(api.config_check, "is_whitelisted", False)
	assert getattr(api.readiness, "is_whitelisted", False)
	assert getattr(api.setup_webhook, "is_whitelisted", False)
	assert getattr(api.setup_commands, "is_whitelisted", False)


def test_setup_webhook_points_telegram_at_this_site_without_echoing_the_secret(site, monkeypatch):
	"""The only route the founder has: a Frappe Cloud site on these plans has no shell."""
	from nyabo_mn.telegram import api as telegram_api

	_set(monkeypatch, "TELEGRAM_WEBHOOK_SECRET", "a-secret-that-must-not-come-back")
	bot = FakeBotApi()
	monkeypatch.setattr(telegram_api, "get_bot", lambda: bot)
	answer = api.setup_webhook()
	assert answer["url"].endswith("/api/method/nyabo_mn.telegram.webhook.webhook")
	assert bot.sent("set_webhook")[0]["url"] == answer["url"]
	assert "a-secret-that-must-not-come-back" not in repr(answer)


def test_setup_commands_registers_the_menu(site, monkeypatch):
	from nyabo_mn.telegram import api as telegram_api

	bot = FakeBotApi()
	monkeypatch.setattr(telegram_api, "get_bot", lambda: bot)
	answer = api.setup_commands()
	assert answer["commands"] == [c["command"] for c in bot.sent("set_my_commands")[0]["commands"]]
	assert bot.sent("set_chat_menu_button")


def test_setup_webhook_refuses_a_user_without_system_manager(site, as_user, monkeypatch):
	from nyabo_mn.telegram import api as telegram_api

	bot = FakeBotApi()
	monkeypatch.setattr(telegram_api, "get_bot", lambda: bot)
	email = "reader@example.com"
	if not frappe.db.exists("User", email):
		doc = frappe.get_doc({"doctype": "User", "email": email, "first_name": "Reader"})
		doc.flags.ignore_permissions = True
		doc.insert()
	with as_user(email):
		with pytest.raises(frappe.PermissionError):
			api.setup_webhook()
	assert bot.sent("set_webhook") == []


def test_setup_webhook_names_the_missing_key_instead_of_calling_telegram(site, monkeypatch):
	from nyabo_mn.config import MissingSettingError
	from nyabo_mn.telegram import api as telegram_api

	_set(monkeypatch, "TELEGRAM_BOT_TOKEN", "")
	bot = FakeBotApi()
	monkeypatch.setattr(telegram_api, "get_bot", lambda: bot)
	with pytest.raises(MissingSettingError, match="TELEGRAM_BOT_TOKEN"):
		api.setup_webhook()
	assert bot.sent("set_webhook") == []
