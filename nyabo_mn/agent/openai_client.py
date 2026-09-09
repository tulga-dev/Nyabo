"""OpenAI adapter on the Responses API.

Verified on 2026-09-08 against
https://developers.openai.com/api/docs/api-reference/responses/create and
https://developers.openai.com/api/docs/guides/structured-outputs:

- request ``input`` is a list of ``{"role": user|assistant|system|developer, "content": [...]}``
  with parts ``{"type": "input_text", "text": ...}`` and
  ``{"type": "input_image", "image_url": "<data URL>", "detail": low|high|auto|original}``;
- structured output via ``text={"format": {"type": "json_schema", "name": ..., "schema": ..., "strict": true}}``;
  a refusal comes back as a content part ``{"type": "refusal", "refusal": "..."}``;
- function tools are ``{"type": "function", "name", "description", "parameters", "strict": true}``;
  the model's calls are output items ``{"type": "function_call", "call_id", "name", "arguments"}``
  and results go back as input items ``{"type": "function_call_output", "call_id", "output"}``;
- the response carries ``id``, ``model``, ``status`` (completed|incomplete|in_progress),
  ``output`` items (``message`` with ``output_text`` parts) and
  ``usage.input_tokens`` / ``usage.output_tokens``.

The SDK (``openai``, PyPI ``info.version`` 3.8.0 on 2026-09-08, Python >= 3.10) is imported
lazily so this module loads without it; tests inject a fake ``transport`` exposing the same
``responses.create(**kwargs)`` method. Verified in the openai-python README the same day:
``OpenAI(api_key=..., timeout=..., max_retries=...)``, ``client.responses.create(model=...,
input=...)`` with ``output_text`` on the response, and the exception classes
``APIConnectionError`` (no status), ``RateLimitError`` (429), ``APIStatusError`` (4xx/5xx,
``.status_code``) and ``APITimeoutError``. The SDK's own retries are disabled
(``max_retries=0``) because ``BaseClient`` retries with the policy the architecture asks for.

Model ids: the founder's ``gpt-5.6-terra`` (default, "$2 / Input MTok, $12 / Output MTok",
"balances intelligence and cost") and ``gpt-5.6-luna`` ("$0.20 / $1.20", "optimized for
cost-sensitive workloads") are both listed on the models page on the check date, next to
``gpt-5.6-sol`` and ``gpt-6-astra``; all four share a 1.05M context window.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from nyabo_mn.agent.llm_client import (
	BaseClient,
	ImagePart,
	LlmError,
	LlmProviderError,
	LlmRateLimited,
	LlmResult,
	LlmSchemaError,
	LlmTimeout,
	Part,
	TextPart,
	ToolCall,
	ToolHandler,
	ToolSpec,
	check_against_schema,
	logger,
	parse_json_object,
	run_tool_handler,
	trace_as_dicts,
)

MAX_OUTPUT_TOKENS = 4096
IMAGE_DETAIL = "high"

#: Sampling parameters a model may refuse outright. The Responses API answers 400
#: ("Unsupported parameter: 'temperature' is not supported with this model."), so the whole
#: call fails until the parameter is dropped — which is how every receipt on the first live
#: site failed extraction. Which model refuses which parameter is not something the API
#: publishes, and a hard-coded list of model ids would rot, so it is learned per model at
#: runtime instead: send it once, and never again to that model. Dropping it costs only
#: determinism, and the JSON schema is what actually constrains the answer.
DROPPABLE_PARAMS: frozenset[str] = frozenset({"temperature", "top_p"})
_UNSUPPORTED_PARAM = re.compile(r"Unsupported parameter: '([A-Za-z0-9_.]+)'")
_unsupported_by_model: dict[str, set[str]] = {}


def unsupported_parameter(message: str) -> str | None:
	"""The parameter name in an "Unsupported parameter" 400, if the message names one."""
	match = _UNSUPPORTED_PARAM.search(message)
	return match.group(1) if match else None


def forget_unsupported_parameters() -> None:
	"""Clear what has been learned. For tests; a process learns this once and keeps it."""
	_unsupported_by_model.clear()


def _field(obj: Any, key: str, default: Any = None) -> Any:
	"""Read ``key`` from an SDK object or a plain dict (fakes in tests)."""
	if isinstance(obj, dict):
		return obj.get(key, default)
	return getattr(obj, key, default)


def to_input_parts(parts: list[Part]) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	for part in parts:
		if isinstance(part, TextPart):
			out.append({"type": "input_text", "text": part.text})
		elif isinstance(part, ImagePart):
			b64 = base64.b64encode(part.data).decode("ascii")
			out.append(
				{"type": "input_image", "image_url": f"data:{part.mime};base64,{b64}", "detail": IMAGE_DETAIL}
			)
		else:  # pragma: no cover - defensive
			raise TypeError(f"unsupported part {type(part).__name__}")
	return out


def to_tool_defs(tools: list[ToolSpec]) -> list[dict[str, Any]]:
	return [
		{
			"type": "function",
			"name": tool.name,
			"description": tool.description,
			"parameters": dict(tool.parameters),
			"strict": True,
		}
		for tool in tools
	]


class OpenAIClient(BaseClient):
	provider = "openai"

	def __init__(self, *, api_key: str, model: str, transport: Any | None = None, **kwargs: Any):
		super().__init__(model, **kwargs)
		self._api_key = api_key
		self._transport = transport

	@property
	def transport(self) -> Any:
		if self._transport is None:
			from openai import OpenAI  # lazy: optional dependency, installed on the bench only

			self._transport = OpenAI(api_key=self._api_key, timeout=self.timeout_s, max_retries=0)
		return self._transport

	# -- error translation --

	def _translate(self, exc: BaseException) -> LlmError | None:
		base = super()._translate(exc)
		if base is not None:
			return base
		try:
			import openai
		except ImportError:  # pragma: no cover - SDK absent in unit tests
			return None
		if isinstance(exc, openai.APITimeoutError):
			return LlmTimeout(str(exc))
		if isinstance(exc, openai.RateLimitError):
			return LlmRateLimited(str(exc), status_code=429)
		if isinstance(exc, openai.APIStatusError):
			status = int(getattr(exc, "status_code", 0) or 0)
			return LlmProviderError(str(exc), status_code=status, retryable=status >= 500)
		if isinstance(exc, openai.APIConnectionError):
			return LlmProviderError(str(exc), retryable=True)
		return None

	# -- request building --

	def _messages(self, system: str, user: list[Part]) -> list[dict[str, Any]]:
		return [
			{"role": "system", "content": [{"type": "input_text", "text": system}]},
			{"role": "user", "content": to_input_parts(user)},
		]

	def _create(self, **kwargs: Any) -> Any:
		"""One Responses call, retrying once without a parameter this model rejects.

		See ``DROPPABLE_PARAMS``: the refusal is a 400 naming the parameter, so the answer is
		to drop that one and repeat, then remember it for the life of the process. Only the
		named parameter is dropped, and only if it is one we are willing to lose; any other
		400 is a real error and is raised.
		"""
		known = _unsupported_by_model.setdefault(self.model, set())
		for name in known & set(kwargs):
			del kwargs[name]
		try:
			return self._request(lambda: self.transport.responses.create(model=self.model, **kwargs))
		except LlmProviderError as exc:
			name = unsupported_parameter(str(exc))
			if name is None or name not in kwargs or name not in DROPPABLE_PARAMS:
				raise
			known.add(name)
			del kwargs[name]
			logger.info("llm dropping unsupported parameter model=%s param=%s", self.model, name)
			return self._request(lambda: self.transport.responses.create(model=self.model, **kwargs))

	# -- response reading --

	@staticmethod
	def _usage(response: Any) -> tuple[int, int]:
		usage = _field(response, "usage") or {}
		return int(_field(usage, "input_tokens", 0) or 0), int(_field(usage, "output_tokens", 0) or 0)

	@staticmethod
	def _read_output(response: Any) -> tuple[str, list[dict[str, Any]]]:
		"""Concatenated text of message items plus the raw function_call items."""
		texts: list[str] = []
		calls: list[dict[str, Any]] = []
		for item in _field(response, "output") or []:
			kind = _field(item, "type")
			if kind == "message":
				for part in _field(item, "content") or []:
					part_kind = _field(part, "type")
					if part_kind == "output_text":
						texts.append(str(_field(part, "text") or ""))
					elif part_kind == "refusal":
						raise LlmSchemaError(f"model refused: {_field(part, 'refusal')}")
			elif kind == "function_call":
				calls.append(
					{
						"call_id": str(_field(item, "call_id") or ""),
						"name": str(_field(item, "name") or ""),
						"arguments": str(_field(item, "arguments") or "{}"),
					}
				)
		status = _field(response, "status")
		if status == "incomplete":
			reason = _field(_field(response, "incomplete_details") or {}, "reason")
			raise LlmSchemaError(f"response incomplete: {reason}", raw_id=_field(response, "id"))
		return "".join(texts), calls

	# -- adapter hooks --

	def _structured_once(
		self, *, system: str, user: list[Part], schema: dict, schema_name: str, temperature: float
	) -> LlmResult:
		response = self._create(
			input=self._messages(system, user),
			text={"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
			temperature=temperature,
			max_output_tokens=MAX_OUTPUT_TOKENS,
		)
		text, _calls = self._read_output(response)
		data = parse_json_object(text)
		check_against_schema(data, schema)
		tokens_in, tokens_out = self._usage(response)
		return LlmResult(
			data=data,
			text=text,
			tokens_in=tokens_in,
			tokens_out=tokens_out,
			latency_ms=0,
			model=str(_field(response, "model") or self.model),
			provider=self.provider,
			raw_id=_field(response, "id"),
		)

	def _with_tools_once(
		self, *, system: str, user: list[Part], tools: list[ToolSpec], handler: ToolHandler, max_turns: int
	) -> LlmResult:
		known = {tool.name for tool in tools}
		messages: list[dict[str, Any]] = self._messages(system, user)
		tool_defs = to_tool_defs(tools)
		trace: list[ToolCall] = []
		total_in = total_out = 0
		last_text = ""
		raw_id: str | None = None
		model_name = self.model
		for turn in range(1, max_turns + 1):
			response = self._create(
				input=messages,
				tools=tool_defs,
				tool_choice="auto",
				max_output_tokens=MAX_OUTPUT_TOKENS,
			)
			tokens_in, tokens_out = self._usage(response)
			total_in += tokens_in
			total_out += tokens_out
			raw_id = _field(response, "id") or raw_id
			model_name = str(_field(response, "model") or model_name)
			text, calls = self._read_output(response)
			if text:
				last_text = text
			if not calls:
				return LlmResult(
					data={"tool_calls": trace_as_dicts(trace)},
					text=last_text or None,
					tokens_in=total_in,
					tokens_out=total_out,
					latency_ms=0,
					model=model_name,
					provider=self.provider,
					raw_id=raw_id,
					tool_calls=tuple(trace),
					turns=turn,
				)
			for call in calls:
				messages.append({"type": "function_call", **call})
				tool_call = run_tool_handler(handler, known, call["name"], call["arguments"])
				trace.append(tool_call)
				messages.append(
					{
						"type": "function_call_output",
						"call_id": call["call_id"],
						"output": json.dumps(tool_call.result, ensure_ascii=False, default=str),
					}
				)
		return LlmResult(
			data={"tool_calls": trace_as_dicts(trace), "exhausted": True},
			text=last_text or None,
			tokens_in=total_in,
			tokens_out=total_out,
			latency_ms=0,
			model=model_name,
			provider=self.provider,
			raw_id=raw_id,
			tool_calls=tuple(trace),
			turns=max_turns,
		)


__all__ = ["OpenAIClient", "to_input_parts", "to_tool_defs"]
