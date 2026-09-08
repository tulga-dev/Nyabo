from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from nyabo_mn.agent.llm_client import ImagePart, LlmRateLimited, LlmSchemaError, RetryPolicy, TextPart, ToolSpec
from nyabo_mn.agent.openai_client import OpenAIClient

SCHEMA = {
	"type": "object",
	"properties": {"a": {"type": "integer"}},
	"required": ["a"],
	"additionalProperties": False,
}


def _response(*, text: str | None = None, calls: list[dict] | None = None, refusal: str | None = None, status="completed"):
	output = []
	if refusal is not None:
		output.append({"type": "message", "content": [{"type": "refusal", "refusal": refusal}]})
	if text is not None:
		output.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
	for call in calls or []:
		output.append({"type": "function_call", **call})
	return SimpleNamespace(
		id="resp_1",
		model="gpt-5.6-terra",
		status=status,
		incomplete_details=None,
		output=output,
		usage=SimpleNamespace(input_tokens=120, output_tokens=30),
	)


class FakeTransport:
	def __init__(self, responses):
		self.responses = list(responses)
		self.requests: list[dict] = []

	@property
	def responses_api(self):
		return self

	# mimics client.responses.create
	@property
	def responses(self):  # noqa: D401 - property named after the SDK attribute
		return self

	def create(self, **kwargs):
		self.requests.append(kwargs)
		item = self._next()
		if isinstance(item, Exception):
			raise item
		return item

	def _next(self):
		return self._queue.pop(0)

	@property
	def _queue(self):
		return self.__dict__["responses"]


def _client(transport, **kwargs) -> OpenAIClient:
	return OpenAIClient(api_key="k", model="gpt-5.6-terra", transport=transport, retry=RetryPolicy(sleep=lambda s: None), **kwargs)


def test_structured_request_shape_and_result():
	transport = FakeTransport([_response(text='{"a": 1}')])
	client = _client(transport)
	result = client.structured(
		purpose="extract",
		system="SYS",
		user=[TextPart("hello"), ImagePart(b"\x89PNG", "image/png")],
		schema=SCHEMA,
		schema_name="thing",
		temperature=0,
	)
	req = transport.requests[0]
	assert req["model"] == "gpt-5.6-terra"
	assert req["text"] == {"format": {"type": "json_schema", "name": "thing", "schema": SCHEMA, "strict": True}}
	assert req["temperature"] == 0 and "tools" not in req
	assert req["input"][0] == {"role": "system", "content": [{"type": "input_text", "text": "SYS"}]}
	user = req["input"][1]
	assert user["role"] == "user" and user["content"][0] == {"type": "input_text", "text": "hello"}
	image = user["content"][1]
	assert image["type"] == "input_image" and image["detail"] == "high"
	assert image["image_url"] == "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode()
	assert result.data == {"a": 1} and result.tokens_in == 120 and result.tokens_out == 30
	assert result.raw_id == "resp_1" and result.provider == "openai" and result.purpose == "extract"


def test_structured_refusal_and_bad_shape_are_schema_errors():
	client = _client(FakeTransport([_response(refusal="no")]))
	with pytest.raises(LlmSchemaError, match="refused"):
		client.structured(purpose="extract", system="s", user=[TextPart("u")], schema=SCHEMA, schema_name="t")
	client = _client(FakeTransport([_response(text='{"b": 1}')]))
	with pytest.raises(LlmSchemaError, match="missing"):
		client.structured(purpose="extract", system="s", user=[TextPart("u")], schema=SCHEMA, schema_name="t")
	client = _client(FakeTransport([_response(text="{", status="incomplete")]))
	with pytest.raises(LlmSchemaError, match="incomplete"):
		client.structured(purpose="extract", system="s", user=[TextPart("u")], schema=SCHEMA, schema_name="t")


def test_structured_retries_transport_rate_limit():
	transport = FakeTransport([LlmRateLimited("429"), _response(text='{"a": 2}')])
	result = _client(transport).structured(purpose="extract", system="s", user=[TextPart("u")], schema=SCHEMA, schema_name="t")
	assert result.data == {"a": 2} and len(transport.requests) == 2


def test_with_tools_loop_calls_handler_and_feeds_results_back():
	transport = FakeTransport(
		[
			_response(calls=[{"call_id": "c1", "name": "lookup", "arguments": '{"q": "x"}'}]),
			_response(text="Хариулт: 3"),
		]
	)
	seen = []

	def handler(name, args):
		seen.append((name, args))
		return {"count": 3}

	tools = [ToolSpec(name="lookup", description="d", parameters=SCHEMA)]
	result = _client(transport).with_tools(purpose="question", system="s", user=[TextPart("q")], tools=tools, handler=handler)
	assert seen == [("lookup", {"q": "x"})]
	assert result.text == "Хариулт: 3" and result.turns == 2 and result.tokens_in == 240
	assert result.tool_calls[0].name == "lookup" and result.tool_calls[0].result == {"count": 3}
	first = transport.requests[0]
	assert first["tools"] == [{"type": "function", "name": "lookup", "description": "d", "parameters": SCHEMA, "strict": True}]
	assert first["tool_choice"] == "auto"
	second = transport.requests[1]["input"]
	assert second[-2] == {"type": "function_call", "call_id": "c1", "name": "lookup", "arguments": '{"q": "x"}'}
	assert second[-1] == {"type": "function_call_output", "call_id": "c1", "output": json.dumps({"count": 3}, ensure_ascii=False)}


def test_with_tools_is_bounded_by_max_turns():
	call = {"call_id": "c", "name": "lookup", "arguments": "{}"}
	transport = FakeTransport([_response(calls=[call]) for _ in range(5)])
	tools = [ToolSpec(name="lookup", description="d", parameters=SCHEMA)]
	result = _client(transport).with_tools(
		purpose="question", system="s", user=[TextPart("q")], tools=tools, handler=lambda n, a: {}, max_turns=2
	)
	assert len(transport.requests) == 2 and result.data["exhausted"] is True and result.text is None


def test_unknown_tool_name_is_refused_without_calling_handler():
	transport = FakeTransport(
		[_response(calls=[{"call_id": "c", "name": "delete_everything", "arguments": "{}"}]), _response(text="ok")]
	)
	called = []
	tools = [ToolSpec(name="lookup", description="d", parameters=SCHEMA)]
	result = _client(transport).with_tools(
		purpose="question", system="s", user=[TextPart("q")], tools=tools, handler=lambda n, a: called.append(n) or {}
	)
	assert called == [] and result.tool_calls[0].is_error
	assert '"unknown_tool"' in transport.requests[1]["input"][-1]["output"]


def test_sdk_exceptions_are_translated(monkeypatch):
	"""Simulate the openai SDK exception classes so the translation table is exercised without the package."""
	import sys
	import types

	fake = types.ModuleType("openai")

	class APIStatusError(Exception):
		def __init__(self, msg, status_code):
			super().__init__(msg)
			self.status_code = status_code

	class RateLimitError(APIStatusError):
		pass

	class APITimeoutError(Exception):
		pass

	class APIConnectionError(Exception):
		pass

	fake.APIStatusError = APIStatusError
	fake.RateLimitError = RateLimitError
	fake.APITimeoutError = APITimeoutError
	fake.APIConnectionError = APIConnectionError
	monkeypatch.setitem(sys.modules, "openai", fake)

	transport = FakeTransport(
		[RateLimitError("429", 429), APITimeoutError("t"), APIConnectionError("c"), APIStatusError("503", 503), _response(text='{"a": 1}')]
	)
	client = _client(transport, )
	client.retry = RetryPolicy(max_retries=4, sleep=lambda s: None)
	assert client.structured(purpose="extract", system="s", user=[TextPart("u")], schema=SCHEMA, schema_name="t").data == {"a": 1}

	transport = FakeTransport([APIStatusError("400", 400)])
	client = _client(transport)
	from nyabo_mn.agent.llm_client import LlmProviderError

	with pytest.raises(LlmProviderError) as exc:
		client.structured(purpose="extract", system="s", user=[TextPart("u")], schema=SCHEMA, schema_name="t")
	assert exc.value.status_code == 400 and len(transport.requests) == 1
