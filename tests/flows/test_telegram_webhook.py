"""Webhook: secret check, dedup by update_id, enqueue of the router."""

from __future__ import annotations

import frappe

from nyabo_mn.i18n import mn
from tests.fixtures.telegram.fake_bot import FakeBotApi, message_update, post_webhook


def test_secret_mismatch_is_403_and_nothing_runs(site):
	bot = FakeBotApi()
	response = post_webhook(bot, message_update(555, "/start"), secret="wrong")
	assert frappe.local.response["http_status_code"] == 403
	assert response == {"ok": False}
	assert not frappe.local.enqueued
	assert bot.calls == []


def test_missing_secret_header_is_403(site):
	bot = FakeBotApi()
	post_webhook(bot, message_update(555, "/start"), secret=None)
	assert frappe.local.response["http_status_code"] == 403


def test_valid_secret_enqueues_router_on_short_queue(site):
	bot = FakeBotApi()
	update = message_update(555, "/start")
	response = post_webhook(bot, update)
	assert response == {"ok": True}
	assert frappe.local.response.get("http_status_code") is None
	job = frappe.local.enqueued[-1]
	assert job.method == "nyabo_mn.telegram.router.handle_update"
	assert job.queue == "short"
	assert job.enqueue_after_commit is True
	assert job.kwargs["update"] == update
	# the router ran inline (stub) and answered the unlinked sender
	assert mn.MSG_NOT_LINKED in bot.last_text


def test_duplicate_update_id_is_dropped(site):
	bot = FakeBotApi()
	update = message_update(555, "/start", update_id=42)
	assert post_webhook(bot, update) == {"ok": True}
	sends_before = len(bot.sent("send_message"))
	assert post_webhook(bot, update) == {"ok": True, "duplicate": True}
	assert len(bot.sent("send_message")) == sends_before
	assert len(frappe.local.enqueued) == 1
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "555"}, "last_update_id") == 42


def test_older_update_id_is_also_dropped(site):
	bot = FakeBotApi()
	post_webhook(bot, message_update(556, "/start", update_id=50))
	assert post_webhook(bot, message_update(556, "/start", update_id=49))["duplicate"] is True


def test_non_json_body_is_ignored_with_200(site):
	from nyabo_mn.telegram import webhook

	frappe.local.request = frappe.Request(
		data="not json", headers={"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"}
	)
	frappe.local.response = frappe._dict(docs=[])
	assert webhook.webhook()["ok"] is True
	assert not frappe.local.enqueued


def test_webhook_url_helper():
	from nyabo_mn.telegram import webhook

	assert (
		webhook.webhook_url("https://nyabo.s.frappe.cloud/")
		== "https://nyabo.s.frappe.cloud/api/method/nyabo_mn.telegram.webhook.webhook"
	)


# --- command menu (UX-12) ----------------------------------------------------------------------


def test_setup_commands_registers_ascii_names_and_the_menu_button(site):
	"""Telegram accepts only lowercase Latin command names, so the Cyrillic ones cannot go here."""
	from nyabo_mn.telegram import commands

	bot = FakeBotApi()
	result = commands.setup_commands(bot=bot)
	call = bot.sent("set_my_commands")[0]
	names = [c["command"] for c in call["commands"]]
	assert names == list(commands.MENU_COMMANDS) == result["commands"]
	for entry in call["commands"]:
		assert entry["command"].isascii() and entry["command"].islower()
		assert entry["command"].replace("_", "").isalnum() and 1 <= len(entry["command"]) <= 32
		assert not entry["command"].startswith("/")
		assert entry["description"] and len(entry["description"]) <= commands.MAX_DESCRIPTION_CHARS
	assert call["scope"] == {"type": "all_private_chats"}
	assert bot.sent("set_chat_menu_button")[0]["menu_button"] == {"type": "commands"}


def test_every_registered_command_is_routable_and_the_cyrillic_aliases_still_work(site):
	from nyabo_mn.telegram import commands, router

	routed = router._commands()
	for name in commands.MENU_COMMANDS:
		assert f"/{name}" in routed, name
	# The Cyrillic spelling and its Latin twin reach the same handler.
	for cyrillic, latin in (
		("/данс", "/bank"),
		("/хаалт", "/close"),
		("/чанар", "/quality"),
		("/бодлого", "/policy"),
		("/компани", "/company"),
		("/эхлэх", "/setup"),
		("/меню", "/menu"),
		("/тусламж", "/help"),
	):
		assert routed[cyrillic] is routed[latin], cyrillic


def test_menu_text_lists_every_command_a_linked_user_can_run(site):
	"""UX-12: MSG_MENU omitted /компани and /меню."""
	from nyabo_mn.telegram import router

	admin_or_bootstrap = {"/link", "/status", "/whoami", "/start"}
	cyrillic = {c for c in router._commands() if c not in admin_or_bootstrap and not c.isascii()}
	assert sorted(c for c in cyrillic if c not in mn.MSG_MENU) == []
