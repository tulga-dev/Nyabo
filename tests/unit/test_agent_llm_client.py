from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from nyabo_mn.agent import llm_client
from nyabo_mn.agent.llm_client import (
	BaseClient,
	CallRecord,
	ImagePart,
	LlmProviderError,
	LlmRateLimited,
	LlmResult,
	LlmSchemaError,
	LlmTimeout,
	RetryPolicy,
	TextPart,
	ToolSpec,
	check_against_schema,
	get_client,
	hash_parts,
	model_warning,
	parse_json_object,
	run_tool_handler,
)
from nyabo_mn.agent.mock_client import MockLlmClient
from nyabo_mn.config import MissingSettingError, Settings


class FlakyClient(BaseClient):
	"""Adapter whose raw request fails a scripted number of times."""

	provider = "fake"

	def __init__(self, failures: list[Exception], **kwargs):
		super().__init__("fake-model", **kwargs)
		self.failures = list(failures)
		self.attempts = 0

	def _raw(self):
		self.attempts += 1
		if self.failures:
			raise self.failures.pop(0)
		return {"ok": True}

	def _structured_once(self, *, system, user, schema, schema_name, temperature):
		data = self._request(self._raw)
		return LlmResult(
			data=data,
			text="{}",
			tokens_in=10,
			tokens_out=5,
			latency_ms=0,
			model=self.model,
			provider=self.provider,
		)

	def _with_tools_once(self, *, system, user, tools, handler, max_turns):
		data = self._request(self._raw)
		return LlmResult(
			data=data,
			text="ok",
			tokens_in=1,
			tokens_out=1,
			latency_ms=0,
			model=self.model,
			provider=self.provider,
		)


def _policy(sleeps: list[float]) -> RetryPolicy:
	return RetryPolicy(
		max_retries=3, backoff_base_s=1.0, backoff_max_s=20.0, sleep=sleeps.append, rng=lambda: 0.5
	)


def _call(client: BaseClient) -> LlmResult:
	return client.structured(purpose="extract", system="s", user=[TextPart("u")], schema={}, schema_name="x")


def test_retries_on_rate_limit_timeout_and_5xx_then_succeeds():
	sleeps: list[float] = []
	client = FlakyClient(
		[LlmRateLimited("429"), LlmTimeout("slow"), LlmProviderError("boom", status_code=503)],
		retry=_policy(sleeps),
	)
	result = _call(client)
	assert result.data == {"ok": True} and client.attempts == 4
	assert sleeps == [1.0, 2.0, 4.0]  # base * 2**attempt, jitter factor 1.0 with rng=0.5


def test_gives_up_after_max_retries():
	sleeps: list[float] = []
	client = FlakyClient([LlmRateLimited("429")] * 5, retry=_policy(sleeps))
	with pytest.raises(LlmRateLimited):
		_call(client)
	assert client.attempts == 4 and len(sleeps) == 3


def test_no_retry_on_4xx_or_schema_error():
	sleeps: list[float] = []
	client = FlakyClient([LlmProviderError("bad request", status_code=400)], retry=_policy(sleeps))
	with pytest.raises(LlmProviderError):
		_call(client)
	assert client.attempts == 1 and sleeps == []
	client = FlakyClient([LlmSchemaError("nope")], retry=_policy(sleeps))
	with pytest.raises(LlmSchemaError):
		_call(client)
	assert client.attempts == 1 and sleeps == []


def test_unknown_exception_is_not_swallowed():
	client = FlakyClient([KeyError("x")], retry=_policy([]))
	with pytest.raises(KeyError):
		_call(client)


def test_builtin_timeout_error_is_translated():
	client = FlakyClient([TimeoutError("t")], retry=_policy([]))
	assert _call(client).data == {"ok": True}


def test_backoff_is_capped_and_jittered():
	policy = RetryPolicy(backoff_base_s=1.0, backoff_max_s=5.0, rng=lambda: 0.0)
	assert policy.delay_for(10) == 2.5  # 5.0 cap * 0.5 jitter floor
	policy = RetryPolicy(backoff_base_s=1.0, backoff_max_s=5.0, rng=lambda: 0.999)
	assert 7.49 < policy.delay_for(10) < 7.5


def test_record_call_receives_success_and_failure_records():
	records: list[CallRecord] = []
	ticks = iter([0.0, 0.25, 1.0, 1.5])
	client = FlakyClient([], record_call=records.append, retry=_policy([]), clock=lambda: next(ticks))
	result = client.structured(
		purpose="classify",
		system="s",
		user=[TextPart("u")],
		schema={},
		schema_name="x",
		prompt_version="classify.v1",
	)
	assert (
		result.latency_ms == 250 and result.purpose == "classify" and result.prompt_version == "classify.v1"
	)
	assert records[0].ok and records[0].tokens_in == 10 and records[0].prompt_version == "classify.v1"

	client = FlakyClient(
		[LlmProviderError("bad", status_code=400)], record_call=records.append, retry=_policy([])
	)
	with pytest.raises(LlmProviderError):
		_call(client)
	assert (
		not records[1].ok and records[1].error_class == "LlmProviderError" and records[1].purpose == "extract"
	)


def test_record_call_failure_does_not_break_the_call(caplog):
	def broken(_record):
		raise RuntimeError("db down")

	client = FlakyClient([], record_call=broken, retry=_policy([]))
	with caplog.at_level(logging.ERROR, logger="nyabo.agent"):
		assert _call(client).data == {"ok": True}
	assert "record_call failed" in caplog.text


def test_with_tools_requires_positive_max_turns():
	client = FlakyClient([], retry=_policy([]))
	with pytest.raises(ValueError):
		client.with_tools(
			purpose="question",
			system="s",
			user=[TextPart("u")],
			tools=[],
			handler=lambda n, a: {},
			max_turns=0,
		)


def test_hash_parts_is_stable_and_sensitive():
	a = hash_parts([TextPart("hello"), ImagePart(b"\x00\x01", "image/png")])
	assert a == hash_parts([TextPart("hello"), ImagePart(b"\x00\x01", "image/jpeg")])  # mime is not hashed
	assert a != hash_parts([TextPart("hello!"), ImagePart(b"\x00\x01")])
	assert a != hash_parts([TextPart("hello"), ImagePart(b"\x00\x02")])
	assert len(a) == 64


def test_image_part_rejects_non_image_mime():
	with pytest.raises(ValueError):
		ImagePart(b"x", "application/pdf")


def test_parse_json_object_and_schema_check():
	assert parse_json_object('{"a": 1}') == {"a": 1}
	with pytest.raises(LlmSchemaError):
		parse_json_object("[1]")
	with pytest.raises(LlmSchemaError):
		parse_json_object("not json")
	schema = {"properties": {"a": {}, "b": {}}, "required": ["a", "b"], "additionalProperties": False}
	check_against_schema({"a": 1, "b": 2}, schema)
	with pytest.raises(LlmSchemaError, match="missing"):
		check_against_schema({"a": 1}, schema)
	with pytest.raises(LlmSchemaError, match="unexpected"):
		check_against_schema({"a": 1, "b": 2, "c": 3}, schema)


def test_run_tool_handler_guards_unknown_tools_and_exceptions():
	def handler(name, args):
		if name == "boom":
			raise RuntimeError("x")
		return {"echo": args}

	call = run_tool_handler(handler, {"echo", "boom"}, "echo", '{"q": 1}')
	assert call.result == {"echo": {"q": 1}} and not call.is_error
	assert run_tool_handler(handler, {"echo"}, "other", {}).result == {"error": "unknown_tool"}
	boom = run_tool_handler(handler, {"echo", "boom"}, "boom", {})
	assert boom.is_error and "RuntimeError" in boom.result["error"]
	assert run_tool_handler(handler, {"echo"}, "echo", "not json").arguments == {"_raw": "not json"}


def test_model_warning_only_outside_allowlist(caplog):
	assert model_warning("openai", "gpt-5.6-terra") is None
	assert model_warning("anthropic", "claude-sonnet-5") is None
	assert "2026-09-08" in (model_warning("openai", "gpt-9-nonexistent") or "")
	assert model_warning("mock", "anything") is None
	from nyabo_mn.agent.openai_client import OpenAIClient

	with caplog.at_level(logging.WARNING, logger="nyabo.agent"):
		OpenAIClient(api_key="k", model="gpt-9-nonexistent", transport=object())
	assert "not in the allowlist" in caplog.text


def test_get_client_factory_routes_by_provider():
	settings = Settings.from_mapping({"OPENAI_API_KEY": "sk", "ANTHROPIC_API_KEY": "ak"})
	auto = get_client(settings)
	assert auto.provider == "openai" and auto.model == llm_client.DEFAULT_OPENAI_MODEL
	anthropic = get_client(settings, provider="anthropic")
	assert anthropic.provider == "anthropic" and anthropic.model == llm_client.DEFAULT_ANTHROPIC_MODEL
	assert isinstance(get_client(settings, provider="mock"), MockLlmClient)


def test_get_client_reads_model_overrides_from_plain_mapping():
	conf = {
		"OPENAI_API_KEY": "sk",
		"OPENAI_MODEL": "gpt-5.6-luna",
		"ANTHROPIC_API_KEY": "ak",
		"ANTHROPIC_MODEL": "claude-opus-5",
	}
	assert get_client(conf).model == "gpt-5.6-luna"
	assert get_client(conf, provider="anthropic").model == "claude-opus-5"


def test_get_client_names_the_missing_key():
	with pytest.raises(MissingSettingError, match="OPENAI_API_KEY"):
		get_client(Settings.from_mapping({}))
	with pytest.raises(MissingSettingError, match="ANTHROPIC_API_KEY"):
		get_client(Settings.from_mapping({"OPENAI_API_KEY": "sk"}), provider="anthropic")
	with pytest.raises(ValueError):
		get_client(Settings.from_mapping({"OPENAI_API_KEY": "sk"}), provider="gemini")


#: The founder's routing (docs/DECISIONS.md LLM-02): reading the photograph is Terra's job,
#: reasoning about it - the account and the VAT treatment - and answering a question is
#: Astra's. Pinned here so a change to the table is a change to this test.
FOUNDERS_ROUTING = {
	"extract": "gpt-5.6-terra",
	"classify": "gpt-6-astra",
	"question": "gpt-6-astra",
	"eval": llm_client.DEFAULT_OPENAI_MODEL,
	"other": llm_client.DEFAULT_OPENAI_MODEL,
}

STRUCTURED_SCHEMA = {
	"type": "object",
	"properties": {"a": {"type": "integer"}},
	"required": ["a"],
	"additionalProperties": False,
}


class EchoTransport:
	"""Stands in for ``openai.OpenAI`` and answers with the model it was asked for."""

	def __init__(self):
		self.models: list[str] = []

	@property
	def responses(self):  # noqa: D401 - named after the SDK attribute
		return self

	def create(self, **kwargs):
		self.models.append(kwargs["model"])
		return SimpleNamespace(
			id="resp_1",
			model=kwargs["model"],
			status="completed",
			incomplete_details=None,
			output=[{"type": "message", "content": [{"type": "output_text", "text": '{"a": 1}'}]}],
			usage=SimpleNamespace(input_tokens=7, output_tokens=3),
		)


def test_every_purpose_resolves_to_the_model_the_founder_chose():
	"""No config at all: the routing lives in code, so an unconfigured site is already right."""
	choices = llm_client.resolve_models(Settings.from_mapping({"OPENAI_API_KEY": "sk"}))
	assert set(choices) == set(llm_client.PURPOSES)  # a new purpose must decide its model
	assert {purpose: choice.model for purpose, choice in choices.items()} == FOUNDERS_ROUTING
	assert all(choice.model in llm_client.MODEL_ALLOWLIST["openai"] for choice in choices.values())
	assert choices["classify"].source == "purpose default"


def test_a_per_purpose_key_overrides_and_an_unset_one_falls_back():
	conf = {
		"OPENAI_API_KEY": "sk",
		"OPENAI_MODEL": "gpt-5.6-luna",
		"OPENAI_MODEL_QUESTION": "gpt-5.6-sol",
		"OPENAI_MODEL_EXTRACT": "",  # a key added and then emptied is an unset key
	}
	choices = llm_client.resolve_models(conf)
	assert (choices["question"].model, choices["question"].source) == (
		"gpt-5.6-sol",
		"OPENAI_MODEL_QUESTION",
	)
	# Unset: the purpose keeps the model chosen for it in code, which outranks OPENAI_MODEL,
	# so pinning OPENAI_MODEL cannot silently move extraction off Terra (LLM-01) ...
	assert (choices["extract"].model, choices["extract"].source) == ("gpt-5.6-terra", "purpose default")
	# ... while a purpose with no model of its own is exactly what OPENAI_MODEL says.
	assert (choices["other"].model, choices["other"].source) == ("gpt-5.6-luna", "OPENAI_MODEL")
	assert llm_client.resolve_model({}, "other").source == "built-in default"
	assert llm_client.resolve_model(conf, "no-such-purpose").purpose == "other"


def test_get_client_routes_each_purpose_to_its_own_model():
	client = get_client({"OPENAI_API_KEY": "sk"})
	assert isinstance(client, llm_client.PurposeRouter) and isinstance(client, llm_client.LlmClient)
	assert client.models() == FOUNDERS_ROUTING
	assert client.model == llm_client.DEFAULT_OPENAI_MODEL  # the fallback purpose's model
	# One adapter per distinct model id, not one per purpose.
	assert client.client_for("classify") is client.client_for("question")
	assert len({id(client.client_for(p)) for p in llm_client.PURPOSES}) == 2
	assert client.client_for("no-such-purpose") is client.client_for("other")
	# A caller that only ever makes one kind of call can hold the pinned adapter instead.
	pinned = get_client({"OPENAI_API_KEY": "sk"}, purpose="question")
	assert pinned.model == "gpt-6-astra" and not isinstance(pinned, llm_client.PurposeRouter)


def test_the_router_hands_a_late_recorder_to_every_adapter():
	"""The pipeline attaches the recorder after construction; every call still writes (§6)."""

	def recorder(record: CallRecord) -> None: ...

	client = get_client({"OPENAI_API_KEY": "sk"})
	assert client.record_call is None
	client.record_call = recorder
	assert all(client.client_for(p).record_call is recorder for p in llm_client.PURPOSES)
	assert client.record_call is recorder


def test_the_recorded_call_carries_the_model_that_answered():
	records: list[CallRecord] = []
	client = get_client({"OPENAI_API_KEY": "sk"}, record_call=records.append)
	transports: dict[str, EchoTransport] = {}
	for purpose in ("extract", "classify"):
		adapter = client.client_for(purpose)
		adapter._transport = transports.setdefault(adapter.model, EchoTransport())
	for purpose in ("extract", "classify"):
		client.structured(
			purpose=purpose,
			system="s",
			user=[TextPart("u")],
			schema=STRUCTURED_SCHEMA,
			schema_name="n",
		)
	assert [(r.purpose, r.model) for r in records] == [
		("extract", "gpt-5.6-terra"),
		("classify", "gpt-6-astra"),
	]
	assert transports["gpt-6-astra"].models == ["gpt-6-astra"]  # the id that was requested


def test_an_unknown_model_id_still_builds_a_client_and_warns(caplog):
	"""A typo in a per-purpose key must not take the site down; it must be noisy (§6)."""
	with caplog.at_level(logging.WARNING, logger="nyabo.agent"):
		client = get_client({"OPENAI_API_KEY": "sk", "OPENAI_MODEL_CLASSIFY": "gpt-6-astro"})
	assert client.client_for("classify").model == "gpt-6-astro"
	assert client.client_for("extract").model == "gpt-5.6-terra"
	assert "not in the allowlist" in caplog.text
	typo = llm_client.resolve_model({"OPENAI_MODEL_CLASSIFY": "gpt-6-astro"}, "classify")
	assert "not in the allowlist" in (typo.warning or "")  # config_check shows it too
	assert llm_client.resolve_model({}, "classify").warning is None  # the routed id is known


def test_pin_models_beats_the_routing_for_a_sweep():
	"""The eval sweep names one model, so every purpose must actually run it."""
	pinned = llm_client.pin_models({"OPENAI_API_KEY": "sk"}, "openai", "gpt-5.6-luna")
	assert {p: c.model for p, c in llm_client.resolve_models(pinned).items()} == dict.fromkeys(
		llm_client.PURPOSES, "gpt-5.6-luna"
	)
	anthropic = llm_client.pin_models({}, "anthropic", "claude-haiku-4-5")
	assert llm_client.resolve_model(anthropic, "extract", "anthropic").model == "claude-haiku-4-5"


def test_tool_spec_is_frozen():
	spec = ToolSpec(name="a", description="b", parameters={"type": "object"})
	with pytest.raises(AttributeError):
		spec.name = "c"  # type: ignore[misc]
