"""Anthropic adapter on the Messages API.

Verified on 2026-09-08 against https://platform.claude.com/docs/en/api/messages,
https://platform.claude.com/docs/en/docs/build-with-claude/tool-use/overview and
https://platform.claude.com/docs/en/docs/about-claude/models/overview:

- request: ``model``, ``max_tokens`` (required), ``system`` (string), ``messages`` of
  ``{"role": user|assistant, "content": [blocks]}``; blocks ``{"type": "text", "text"}`` and
  ``{"type": "image", "source": {"type": "base64", "media_type": image/jpeg|png|gif|webp, "data"}}``;
- tools: ``{"name", "description", "input_schema", "strict": true}`` (strict tool use is GA,
  no beta header; requires ``additionalProperties: false`` and a full ``required`` list); ``tool_choice`` is
  ``{"type": "auto"}`` / ``{"type": "any"}`` / ``{"type": "tool", "name": ...}``, each
  accepting ``disable_parallel_tool_use``. Forcing one tool whose ``input_schema`` is the
  output schema is the documented way to get JSON; the model answers with a
  ``{"type": "tool_use", "id", "name", "input"}`` block and ``stop_reason == "tool_use"``;
- tool results go back as a user message of ``{"type": "tool_result", "tool_use_id",
  "content", "is_error"}`` blocks;
- response: ``id``, ``model``, ``stop_reason`` (end_turn | max_tokens | stop_sequence |
  tool_use | refusal), ``content`` blocks, ``usage.input_tokens`` / ``usage.output_tokens``;
- errors: 429 ``rate_limit_error``, 529 ``overloaded_error``, 5xx retryable; 4xx not.

Two model-specific facts drive the request shape: the default ``claude-sonnet-5`` rejects
non-default sampling parameters (``temperature`` is documented as deprecated after Opus
4.6, "other values rejected"), so ``temperature`` is never sent; and forced
``tool_choice`` is refused only by ``claude-fable-5-1``, so that id is allowed in the
allowlist but would need the ``output_config.format`` path (UNVERIFIED here, not
implemented) - see ``model_warning``.

SDK: ``anthropic`` (PyPI 1.4.0 on the check date; 0.40+ has the same ``messages.create``
and exception classes). Imported lazily; tests inject a fake ``transport``.
"""

from __future__ import annotations

import base64
import json
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
	run_tool_handler,
	trace_as_dicts,
)

MAX_TOKENS = 4096
STRUCTURED_TOOL_DESCRIPTION = "Record the extracted fields. Call this exactly once with every field filled."


def _field(obj: Any, key: str, default: Any = None) -> Any:
	if isinstance(obj, dict):
		return obj.get(key, default)
	return getattr(obj, key, default)


def to_content_blocks(parts: list[Part]) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	for part in parts:
		if isinstance(part, TextPart):
			out.append({"type": "text", "text": part.text})
		elif isinstance(part, ImagePart):
			out.append(
				{
					"type": "image",
					"source": {
						"type": "base64",
						"media_type": part.mime,
						"data": base64.b64encode(part.data).decode("ascii"),
					},
				}
			)
		else:  # pragma: no cover - defensive
			raise TypeError(f"unsupported part {type(part).__name__}")
	return out


def to_tool_defs(tools: list[ToolSpec]) -> list[dict[str, Any]]:
	"""``strict: true`` makes the API guarantee ``tool_use.input`` validates against the schema.

	Documented (tool-use overview, "Strict tool use", no beta header) for schemas with
	``additionalProperties: false`` and a full ``required`` list, which ``schemas.json_schema``
	produces; without it the model may omit a key or add one and the pydantic validation
	downstream would reject an otherwise good answer.
	"""
	return [
		{
			"name": tool.name,
			"description": tool.description,
			"strict": True,
			"input_schema": dict(tool.parameters),
		}
		for tool in tools
	]


def _block_to_param(block: Any) -> dict[str, Any]:
	"""Re-encode a response block as a request block so the transcript can be replayed."""
	kind = _field(block, "type")
	if kind == "text":
		return {"type": "text", "text": str(_field(block, "text") or "")}
	if kind == "tool_use":
		return {
			"type": "tool_use",
			"id": str(_field(block, "id") or ""),
			"name": str(_field(block, "name") or ""),
			"input": dict(_field(block, "input") or {}),
		}
	if isinstance(block, dict):
		return dict(block)
	dump = getattr(block, "model_dump", None)
	return dump() if callable(dump) else {"type": str(kind)}


class AnthropicClient(BaseClient):
	provider = "anthropic"

	def __init__(self, *, api_key: str, model: str, transport: Any | None = None, **kwargs: Any):
		super().__init__(model, **kwargs)
		self._api_key = api_key
		self._transport = transport

	@property
	def transport(self) -> Any:
		if self._transport is None:
			from anthropic import Anthropic  # lazy: optional dependency

			self._transport = Anthropic(api_key=self._api_key, timeout=self.timeout_s, max_retries=0)
		return self._transport

	def _translate(self, exc: BaseException) -> LlmError | None:
		base = super()._translate(exc)
		if base is not None:
			return base
		try:
			import anthropic
		except ImportError:  # pragma: no cover - SDK absent in unit tests
			return None
		if isinstance(exc, anthropic.APITimeoutError):
			return LlmTimeout(str(exc))
		if isinstance(exc, anthropic.RateLimitError):
			return LlmRateLimited(str(exc), status_code=429)
		if isinstance(exc, anthropic.APIStatusError):
			status = int(getattr(exc, "status_code", 0) or 0)
			return LlmProviderError(str(exc), status_code=status, retryable=status >= 500)
		if isinstance(exc, anthropic.APIConnectionError):
			return LlmProviderError(str(exc), retryable=True)
		return None

	def _create(self, **kwargs: Any) -> Any:
		return self._request(
			lambda: self.transport.messages.create(model=self.model, max_tokens=MAX_TOKENS, **kwargs)
		)

	@staticmethod
	def _usage(response: Any) -> tuple[int, int]:
		usage = _field(response, "usage") or {}
		return int(_field(usage, "input_tokens", 0) or 0), int(_field(usage, "output_tokens", 0) or 0)

	@staticmethod
	def _check_stop(response: Any) -> None:
		stop = _field(response, "stop_reason")
		if stop == "refusal":
			raise LlmSchemaError("model refused", raw_id=_field(response, "id"))
		if stop == "max_tokens":
			raise LlmSchemaError("response truncated at max_tokens", raw_id=_field(response, "id"))

	def _structured_once(
		self, *, system: str, user: list[Part], schema: dict, schema_name: str, temperature: float
	) -> LlmResult:
		del temperature  # never sent: claude-sonnet-5 rejects non-default sampling parameters
		response = self._create(
			system=system,
			messages=[{"role": "user", "content": to_content_blocks(user)}],
			tools=to_tool_defs(
				[ToolSpec(name=schema_name, description=STRUCTURED_TOOL_DESCRIPTION, parameters=schema)]
			),
			tool_choice={"type": "tool", "name": schema_name, "disable_parallel_tool_use": True},
		)
		self._check_stop(response)
		data = None
		for block in _field(response, "content") or []:
			if _field(block, "type") == "tool_use" and _field(block, "name") == schema_name:
				data = _field(block, "input")
				break
		if not isinstance(data, dict):
			raise LlmSchemaError("no tool_use block with the requested schema", raw_id=_field(response, "id"))
		check_against_schema(data, schema)
		tokens_in, tokens_out = self._usage(response)
		return LlmResult(
			data=data,
			text=json.dumps(data, ensure_ascii=False),
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
		messages: list[dict[str, Any]] = [{"role": "user", "content": to_content_blocks(user)}]
		tool_defs = to_tool_defs(tools)
		trace: list[ToolCall] = []
		total_in = total_out = 0
		last_text = ""
		raw_id: str | None = None
		model_name = self.model
		for turn in range(1, max_turns + 1):
			response = self._create(
				system=system,
				messages=messages,
				tools=tool_defs,
				tool_choice={"type": "auto"},
			)
			tokens_in, tokens_out = self._usage(response)
			total_in += tokens_in
			total_out += tokens_out
			raw_id = _field(response, "id") or raw_id
			model_name = str(_field(response, "model") or model_name)
			self._check_stop(response)
			blocks = list(_field(response, "content") or [])
			texts = [str(_field(b, "text") or "") for b in blocks if _field(b, "type") == "text"]
			if any(texts):
				last_text = "".join(texts)
			uses = [b for b in blocks if _field(b, "type") == "tool_use"]
			if not uses or _field(response, "stop_reason") != "tool_use":
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
			messages.append({"role": "assistant", "content": [_block_to_param(b) for b in blocks]})
			results: list[dict[str, Any]] = []
			for use in uses:
				call = run_tool_handler(
					handler, known, str(_field(use, "name") or ""), _field(use, "input") or {}
				)
				trace.append(call)
				result_block: dict[str, Any] = {
					"type": "tool_result",
					"tool_use_id": str(_field(use, "id") or ""),
					"content": json.dumps(call.result, ensure_ascii=False, default=str),
				}
				if call.is_error:
					result_block["is_error"] = True
				results.append(result_block)
			messages.append({"role": "user", "content": results})
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


__all__ = ["AnthropicClient", "to_content_blocks", "to_tool_defs"]
