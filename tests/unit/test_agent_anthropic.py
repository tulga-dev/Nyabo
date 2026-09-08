from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from nyabo_mn.agent.anthropic_client import MAX_TOKENS, AnthropicClient
from nyabo_mn.agent.llm_client import ImagePart, LlmSchemaError, RetryPolicy, TextPart, ToolSpec

SCHEMA = {
	"type": "object",
	"properties": {"a": {"type": "integer"}},
	"required": ["a"],
	"additionalProperties": False,
}


def _message(*, text: str | None = None, tool_uses: list[dict] | None = None, stop_reason: str = "end_turn"):
	content = []
	if text is not None:
		content.append(SimpleNamespace(type="text", text=text))
	for use in tool_uses or []:
		content.append(SimpleNamespace(type="tool_use", **use))
	return SimpleNamespace(
		id="msg_1",
		model="claude-sonnet-5",
		stop_reason=stop_reason,
		content=content,
		usage=SimpleNamespace(input_tokens=200, output_tokens=40),
	)


class FakeMessages:
	def __init__(self, responses):
		self.queue = list(responses)
		self.requests: list[dict] = []

	def create(self, **kwargs):
		self.requests.append(kwargs)
		item = self.queue.pop(0)
		if isinstance(item, Exception):
			raise item
		return item


class FakeTransport:
	def __init__(self, responses):
		self.messages = FakeMessages(responses)


def _client(transport) -> AnthropicClient:
	return AnthropicClient(api_key="k", model="claude-sonnet-5", transport=transport, retry=RetryPolicy(sleep=lambda s: None))


def test_structured_forces_one_tool_and_reads_its_input():
	transport = FakeTransport([_message(tool_uses=[{"id": "tu1", "name": "thing", "input": {"a": 7}}], stop_reason="tool_use")])
	result = _client(transport).structured(
		purpose="extract",
		system="SYS",
		user=[TextPart("hello"), ImagePart(b"\xff\xd8", "image/jpeg")],
		schema=SCHEMA,
		schema_name="thing",
		temperature=0,
	)
	req = transport.messages.requests[0]
	assert req["model"] == "claude-sonnet-5" and req["max_tokens"] == MAX_TOKENS and req["system"] == "SYS"
	assert "temperature" not in req  # claude-sonnet-5 rejects non-default sampling parameters
	assert req["tool_choice"] == {"type": "tool", "name": "thing", "disable_parallel_tool_use": True}
	assert req["tools"][0]["name"] == "thing" and req["tools"][0]["input_schema"] == SCHEMA
	blocks = req["messages"][0]["content"]
	assert req["messages"][0]["role"] == "user" and blocks[0] == {"type": "text", "text": "hello"}
	assert blocks[1] == {
		"type": "image",
		"source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b"\xff\xd8").decode()},
	}
	assert result.data == {"a": 7} and result.tokens_in == 200 and result.tokens_out == 40 and result.raw_id == "msg_1"


def test_structured_without_tool_use_or_refusal_is_schema_error():
	client = _client(FakeTransport([_message(text="I would rather not")]))
	with pytest.raises(LlmSchemaError):
		client.structured(purpose="extract", system="s", user=[TextPart("u")], schema=SCHEMA, schema_name="t")
	client = _client(FakeTransport([_message(stop_reason="refusal")]))
	with pytest.raises(LlmSchemaError, match="refused"):
		client.structured(purpose="extract", system="s", user=[TextPart("u")], schema=SCHEMA, schema_name="t")
	client = _client(FakeTransport([_message(stop_reason="max_tokens")]))
	with pytest.raises(LlmSchemaError, match="max_tokens"):
		client.structured(purpose="extract", system="s", user=[TextPart("u")], schema=SCHEMA, schema_name="t")


def test_with_tools_loop_replays_transcript_with_tool_results():
	transport = FakeTransport(
		[
			_message(text="let me check", tool_uses=[{"id": "tu1", "name": "lookup", "input": {"q": "x"}}], stop_reason="tool_use"),
			_message(text="Хариулт: 3"),
		]
	)
	tools = [ToolSpec(name="lookup", description="d", parameters=SCHEMA)]
	result = _client(transport).with_tools(
		purpose="question", system="s", user=[TextPart("q")], tools=tools, handler=lambda n, a: {"count": 3}
	)
	assert result.text == "Хариулт: 3" and result.turns == 2 and result.tokens_in == 400
	first = transport.messages.requests[0]
	assert first["tool_choice"] == {"type": "auto"}
	assert first["tools"] == [{"name": "lookup", "description": "d", "input_schema": SCHEMA}]
	second = transport.messages.requests[1]["messages"]
	assert second[1] == {
		"role": "assistant",
		"content": [
			{"type": "text", "text": "let me check"},
			{"type": "tool_use", "id": "tu1", "name": "lookup", "input": {"q": "x"}},
		],
	}
	assert second[2] == {
		"role": "user",
		"content": [{"type": "tool_result", "tool_use_id": "tu1", "content": json.dumps({"count": 3}, ensure_ascii=False)}],
	}


def test_with_tools_marks_handler_errors_and_stops_at_max_turns():
	use = {"id": "tu", "name": "lookup", "input": {}}
	transport = FakeTransport([_message(tool_uses=[use], stop_reason="tool_use") for _ in range(3)])
	tools = [ToolSpec(name="lookup", description="d", parameters=SCHEMA)]

	def handler(name, args):
		raise RuntimeError("ledger offline")

	result = _client(transport).with_tools(
		purpose="question", system="s", user=[TextPart("q")], tools=tools, handler=handler, max_turns=2
	)
	assert len(transport.messages.requests) == 2 and result.data["exhausted"] is True
	assert all(call.is_error for call in result.tool_calls)
	assert transport.messages.requests[1]["messages"][2]["content"][0]["is_error"] is True
