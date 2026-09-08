"""The browser-callable diagnostics answer a System Manager and no one else, and leak nothing.

They exist because a Frappe Cloud site has no shell on the plans Nyabo targets. That makes
them a new permission surface: these tests pin who may call them and what comes back. The
parsing rules themselves (upper/lowercase keys, defaults, which key belongs to which
feature) are ``Settings``' own, and live in tests/test_config.py.
"""

from __future__ import annotations

import frappe
import pytest

from nyabo_mn import api

TOKEN = "12345:a-token-that-must-never-be-echoed"


def _set(monkeypatch, key: str, value: str) -> None:
	"""The site config is read by either case, so a test that clears a key must clear both."""
	monkeypatch.setitem(frappe.conf, key, value)
	monkeypatch.setitem(frappe.conf, key.lower(), value)


def test_config_check_says_a_secret_is_set_without_echoing_it(site, monkeypatch):
	_set(monkeypatch, "TELEGRAM_BOT_TOKEN", TOKEN)
	answer = api.config_check()
	assert set(answer) == {"missing_by_feature", "values"}
	assert answer["values"]["TELEGRAM_BOT_TOKEN"] == "<set>"
	assert TOKEN not in repr(answer)
	assert answer["missing_by_feature"]["telegram"] == []


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


def test_the_diagnostics_are_whitelisted(site):
	# Only read-only checks belong in nyabo_mn.api; anything that writes stays a bench entry point.
	assert getattr(api.config_check, "is_whitelisted", False)
	assert getattr(api.readiness, "is_whitelisted", False)
