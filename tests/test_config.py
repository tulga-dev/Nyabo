from __future__ import annotations

import pytest

from nyabo_mn.config import (
	DEFAULT_OPENAI_MODEL,
	KEY_SPECS,
	MissingSettingError,
	Settings,
	model_routing,
	parse_id_list,
)


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


def test_every_per_purpose_model_key_is_declared_here():
	"""``llm_client`` names the keys; ``KEY_SPECS`` is what ``Settings`` keeps and redacts.

	The two lists are written out separately (a key name should grep), so this keeps them
	in step: a routed key that is not declared here would be dropped by ``from_mapping``
	and the site would silently ignore it.
	"""
	from nyabo_mn.agent.llm_client import PURPOSE_MODEL_KEYS

	assert set(PURPOSE_MODEL_KEYS) <= {spec.name for spec in KEY_SPECS}
	settings = Settings.from_mapping({"openai_model_classify": "gpt-5.6-sol"})
	assert settings.get("OPENAI_MODEL_CLASSIFY") == "gpt-5.6-sol"
	assert settings.redacted()["OPENAI_MODEL_CLASSIFY"] == "gpt-5.6-sol"
	assert settings.redacted()["OPENAI_MODEL_EXTRACT"] == "<missing>"
	assert settings.missing("llm") == ["OPENAI_API_KEY"]  # a model key never blocks a feature


def test_model_routing_answers_the_resolved_model_and_what_decided_it():
	settings = Settings.from_mapping({"OPENAI_MODEL": "gpt-5.6-luna"})
	routing = model_routing(settings)["by_purpose"]
	assert routing["extract"]["model"] == "gpt-5.6-terra"
	assert routing["classify"]["model"] == "gpt-6-astra"
	assert routing["other"] == {"model": "gpt-5.6-luna", "source": "OPENAI_MODEL", "warning": None}
	anthropic = model_routing(settings, "anthropic")["by_purpose"]
	assert {row["model"] for row in anthropic.values()} == {"claude-sonnet-5"}


def test_redacted_never_shows_secrets():
	settings = Settings.from_mapping({"OPENAI_API_KEY": "sk-very-secret", "OPENAI_MODEL": "gpt-x"})
	shown = settings.redacted()
	assert shown["OPENAI_API_KEY"] == "<set>"
	assert shown["OPENAI_MODEL"] == "gpt-x"
	assert "sk-very-secret" not in str(shown)
