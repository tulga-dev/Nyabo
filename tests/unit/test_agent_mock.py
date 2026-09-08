from __future__ import annotations

import json

import pytest

from nyabo_mn.agent.llm_client import CallRecord, ImagePart, LlmSchemaError, TextPart, ToolSpec, hash_parts
from nyabo_mn.agent.mock_client import DEFAULT_FIXTURES_DIR, MockLlmClient

SCHEMA = {"type": "object", "properties": {"a": {}}, "required": ["a"], "additionalProperties": False}


def test_default_fixtures_exist_for_every_purpose():
	for purpose in ("extract", "classify", "question"):
		assert (DEFAULT_FIXTURES_DIR / purpose / "default.json").is_file()


def test_keyed_fixture_wins_over_default(tmp_path):
	user = [TextPart("what is 2+2"), ImagePart(b"img")]
	key = hash_parts(user)
	(tmp_path / "extract").mkdir()
	(tmp_path / "extract" / "default.json").write_text(
		json.dumps({"data": {"a": "default"}}), encoding="utf-8"
	)
	(tmp_path / "extract" / f"{key}.json").write_text(json.dumps({"data": {"a": "keyed"}}), encoding="utf-8")
	client = MockLlmClient(fixtures_dir=tmp_path)
	keyed = client.structured(purpose="extract", system="s", user=user, schema=SCHEMA, schema_name="t")
	other = client.structured(
		purpose="extract", system="s", user=[TextPart("other")], schema=SCHEMA, schema_name="t"
	)
	assert keyed.data == {"a": "keyed"} and other.data == {"a": "default"}
	assert client.calls[0].fixture.endswith(f"{key}.json") and client.calls[0].image_count == 1


def test_scripted_answers_take_precedence_and_calls_are_recorded(tmp_path):
	records: list[CallRecord] = []
	client = MockLlmClient(fixtures_dir=tmp_path, record_call=records.append)
	client.add("classify", {"data": {"a": 1}})
	user = [TextPart("x")]
	client.add_for("classify", user, {"data": {"a": 2}})
	assert client.structured(
		purpose="classify", system="s", user=user, schema=SCHEMA, schema_name="t"
	).data == {"a": 2}
	assert client.structured(
		purpose="classify", system="s", user=[TextPart("y")], schema=SCHEMA, schema_name="t"
	).data == {"a": 1}
	assert [c.purpose for c in client.calls] == ["classify", "classify"]
	assert len(records) == 2 and all(r.ok and r.provider == "mock" for r in records)


def test_missing_fixture_is_a_schema_error(tmp_path):
	client = MockLlmClient(fixtures_dir=tmp_path)
	with pytest.raises(LlmSchemaError, match="no mock fixture"):
		client.structured(purpose="eval", system="s", user=[TextPart("x")], schema=SCHEMA, schema_name="t")


def test_strict_mode_checks_fixture_against_schema(tmp_path):
	client = MockLlmClient(fixtures_dir=tmp_path, strict=True)
	client.add("extract", {"data": {"b": 1}})
	with pytest.raises(LlmSchemaError, match="missing"):
		client.structured(purpose="extract", system="s", user=[TextPart("x")], schema=SCHEMA, schema_name="t")


def test_with_tools_runs_scripted_calls_through_handler(tmp_path):
	client = MockLlmClient(fixtures_dir=tmp_path)
	client.add(
		"question",
		{
			"text": "3 гүйлгээ",
			"tool_calls": [{"name": "count", "arguments": {"k": 1}}, {"name": "nope", "arguments": {}}],
		},
	)
	seen = []
	result = client.with_tools(
		purpose="question",
		system="s",
		user=[TextPart("q")],
		tools=[ToolSpec(name="count", description="", parameters=SCHEMA)],
		handler=lambda n, a: seen.append((n, a)) or {"n": 3},
	)
	assert seen == [("count", {"k": 1})]
	assert (
		result.text == "3 гүйлгээ" and result.tool_calls[1].is_error and client.calls[0].tools == ("count",)
	)
