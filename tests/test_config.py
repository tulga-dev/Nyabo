from __future__ import annotations

import pytest

from nyabo_mn.config import DEFAULT_OPENAI_MODEL, MissingSettingError, Settings, parse_id_list


def test_empty_config_reports_every_required_key():
	settings = Settings.from_mapping({})
	assert settings.missing("telegram") == [
		"TELEGRAM_BOT_TOKEN",
		"TELEGRAM_WEBHOOK_SECRET",
		"ADMIN_TELEGRAM_IDS",
	]
	assert settings.missing("llm") == ["OPENAI_API_KEY"]
	assert settings.missing("ebarimt") == ["EBARIMT_API_BASE"]
	assert settings.openai_model == DEFAULT_OPENAI_MODEL


def test_lowercase_keys_are_accepted():
	settings = Settings.from_mapping(
		{"telegram_bot_token": "t", "telegram_webhook_secret": "s", "admin_telegram_ids": "1"}
	)
	assert settings.missing("telegram") == []
	assert settings.telegram_bot_token == "t"
	assert settings.admin_telegram_ids == frozenset({1})


def test_require_names_the_missing_key():
	settings = Settings.from_mapping({"OPENAI_API_KEY": "k"})
	settings.require("llm")
	with pytest.raises(MissingSettingError) as exc:
		settings.require("telegram", "llm")
	assert "TELEGRAM_BOT_TOKEN" in str(exc.value)
	assert "OPENAI_API_KEY" not in str(exc.value)


def test_unknown_feature_is_an_error():
	with pytest.raises(ValueError):
		Settings.from_mapping({}).missing("payments")


@pytest.mark.parametrize(
	"raw, expected",
	[
		("123", {123}),
		("1, 2;3", {1, 2, 3}),
		([1, "2"], {1, 2}),
		(42, {42}),
		("", set()),
		(None, set()),
	],
)
def test_admin_ids_parsing(raw, expected):
	assert parse_id_list(raw) == frozenset(expected)


def test_admin_ids_reject_usernames():
	with pytest.raises(ValueError):
		parse_id_list("@battulga2999")


def test_redacted_never_shows_secrets():
	settings = Settings.from_mapping({"OPENAI_API_KEY": "sk-very-secret", "OPENAI_MODEL": "gpt-x"})
	shown = settings.redacted()
	assert shown["OPENAI_API_KEY"] == "<set>"
	assert shown["OPENAI_MODEL"] == "gpt-x"
	assert "sk-very-secret" not in str(shown)
