"""Provider-neutral LLM client contract (docs/ARCHITECTURE.md §6).

The pipeline only ever sees ``LlmClient``: two call shapes (``structured`` for
schema-validated extraction/classification without tools, ``with_tools`` for the
read-only question loop), one result type and one error hierarchy. Providers are
adapters (``openai_client``, ``anthropic_client``, ``mock_client``) built on
``BaseClient``, which owns retries, the per-call timeout, latency measurement and the
``record_call`` hook that writes ``Nyabo LLM Call`` (through ``frappe_log``; this module
never imports frappe so the simulator and tests can use it).

Model ids are read from settings. The defaults were given by the founder; the small
allowlist below was checked against the vendors' model pages on ``MODEL_ALLOWLIST_CHECKED_ON``
(https://developers.openai.com/api/docs/models lists gpt-6-astra, gpt-5.6-sol, gpt-5.6-terra
and gpt-5.6-luna; https://platform.claude.com/docs/en/docs/about-claude/models/overview lists
claude-fable-5-1, claude-opus-5, claude-sonnet-5 and claude-haiku-4-5, all without date
suffixes). An id outside the allowlist is still used, but a warning is logged at
construction so a typo in site config is noticed before the first receipt fails; the
allowlist is a hint, never a gate, because the vendors add ids faster than we redeploy.
"""

from __future__ import annotations

import abc
import json
import logging
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("nyabo.agent")

DEFAULT_OPENAI_MODEL = "gpt-5.6-terra"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"

MODEL_ALLOWLIST_CHECKED_ON = date(2026, 9, 8)
MODEL_ALLOWLIST: Mapping[str, frozenset[str]] = {
	"openai": frozenset({"gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}),
	"anthropic": frozenset({"claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5", "claude-fable-5-1"}),
}

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_S = 1.0
DEFAULT_BACKOFF_MAX_S = 20.0

PURPOSES = ("extract", "classify", "question", "eval", "other")


# --- parts and specs -------------------------------------------------------------------


@dataclass(frozen=True)
class TextPart:
	text: str


@dataclass(frozen=True)
class ImagePart:
	data: bytes
	mime: str = "image/jpeg"

	def __post_init__(self) -> None:
		if not self.mime.startswith("image/"):
			raise ValueError(f"ImagePart.mime must be an image type, got {self.mime!r}")


Part = TextPart | ImagePart


@dataclass(frozen=True)
class ToolSpec:
	"""A function the model may call; ``parameters`` is a strict JSON Schema object."""

	name: str
	description: str
	parameters: Mapping[str, Any]


@dataclass(frozen=True)
class ToolCall:
	name: str
	arguments: Mapping[str, Any]
	result: Mapping[str, Any] | None = None
	is_error: bool = False


@dataclass(frozen=True)
class LlmResult:
	data: Mapping[str, Any] | None
	text: str | None
	tokens_in: int
	tokens_out: int
	latency_ms: int
	model: str
	provider: str
	prompt_version: str | None = None
	raw_id: str | None = None
	purpose: str = "other"
	tool_calls: tuple[ToolCall, ...] = ()
	turns: int = 1


# --- errors -----------------------------------------------------------------------------


class LlmError(RuntimeError):
	"""Base class; ``retryable`` decides whether BaseClient tries again."""

	retryable = False

	def __init__(self, message: str = "", *, status_code: int | None = None, raw_id: str | None = None):
		super().__init__(message)
		self.status_code = status_code
		self.raw_id = raw_id


class LlmTimeout(LlmError):
	retryable = True


class LlmRateLimited(LlmError):
	retryable = True


class LlmSchemaError(LlmError):
	"""The provider answered but not in the requested shape (or refused)."""

	retryable = False


class LlmProviderError(LlmError):
	"""Any other provider failure; 5xx and connection errors are retryable, 4xx are not."""

	def __init__(
		self,
		message: str = "",
		*,
		status_code: int | None = None,
		raw_id: str | None = None,
		retryable: bool | None = None,
	):
		super().__init__(message, status_code=status_code, raw_id=raw_id)
		if retryable is None:
			retryable = status_code is None or status_code >= 500
		self.retryable = retryable


# --- call records -----------------------------------------------------------------------


@dataclass(frozen=True)
class CallRecord:
	"""Everything ``Nyabo LLM Call`` stores: metadata only, never content."""

	purpose: str
	provider: str
	model: str
	prompt_version: str | None
	tokens_in: int
	tokens_out: int
	latency_ms: int
	ok: bool
	error_class: str | None = None
	cost_usd: Any = None
	company: str | None = None
	proposal: str | None = None
	raw_id: str | None = None


RecordCall = Callable[[CallRecord], None]
ToolHandler = Callable[[str, dict[str, Any]], dict[str, Any]]


# --- the contract -----------------------------------------------------------------------


@runtime_checkable
class LlmClient(Protocol):
	provider: str
	model: str

	def structured(
		self,
		*,
		purpose: str,
		system: str,
		user: list[Part],
		schema: dict,
		schema_name: str,
		temperature: float = 0,
		prompt_version: str | None = None,
	) -> LlmResult: ...

	def with_tools(
		self,
		*,
		purpose: str,
		system: str,
		user: list[Part],
		tools: list[ToolSpec],
		handler: ToolHandler,
		max_turns: int = 4,
		prompt_version: str | None = None,
	) -> LlmResult: ...


# --- helpers shared by adapters ---------------------------------------------------------


def hash_parts(parts: list[Part]) -> str:
	"""Stable key for a user message: text hashed as UTF-8, images by their bytes."""
	import hashlib

	digest = hashlib.sha256()
	for part in parts:
		if isinstance(part, TextPart):
			digest.update(b"text:")
			digest.update(part.text.encode("utf-8"))
		elif isinstance(part, ImagePart):
			digest.update(b"image:")
			digest.update(hashlib.sha256(part.data).hexdigest().encode("ascii"))
		else:  # pragma: no cover - defensive
			raise TypeError(f"unknown part {type(part).__name__}")
		digest.update(b"\x00")
	return digest.hexdigest()


def parse_json_object(text: str) -> dict[str, Any]:
	"""Parse the model's JSON text; a non-object or malformed text is a schema error."""
	try:
		data = json.loads(text)
	except (TypeError, ValueError) as exc:
		raise LlmSchemaError(f"model output is not valid JSON: {exc}") from exc
	if not isinstance(data, dict):
		raise LlmSchemaError("model output is not a JSON object")
	return data


def check_against_schema(data: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
	"""Cheap top-level check before pydantic sees the data.

	Full validation belongs to the pydantic model (extract/classify do it); this only
	turns the two most common provider failures (missing keys, extra keys) into an
	``LlmSchemaError`` with a useful message even when the caller validates later.
	"""
	props = schema.get("properties")
	if not isinstance(props, dict):
		return
	missing = [k for k in schema.get("required", []) if k not in data]
	if missing:
		raise LlmSchemaError(f"model output is missing required keys: {', '.join(missing)}")
	if schema.get("additionalProperties") is False:
		extra = [k for k in data if k not in props]
		if extra:
			raise LlmSchemaError(f"model output has unexpected keys: {', '.join(extra)}")


def run_tool_handler(handler: ToolHandler, known: set[str], name: str, arguments: Any) -> ToolCall:
	"""Call the injected handler; failures become an error result the model can read.

	The handler is the pipeline's read-only tool dispatcher. Its exceptions must not end
	the conversation (the model should get a chance to apologise or escalate), and an
	unknown tool name is refused here so no adapter ever forwards it. A handler that
	returns ``{"error": "<code>", ...}`` is treated as failed too (``is_error``), so the
	question layer can tell a real answer from a refused call without parsing text.
	"""
	if isinstance(arguments, str):
		try:
			args: Any = json.loads(arguments or "{}")
		except ValueError:
			args = {"_raw": arguments}
	elif isinstance(arguments, Mapping):
		args = dict(arguments)
	else:
		args = {"_raw": arguments}
	if not isinstance(args, dict):
		args = {"_raw": args}
	if name not in known:
		return ToolCall(name=name, arguments=args, result={"error": "unknown_tool"}, is_error=True)
	try:
		result = handler(name, args)
	except Exception as exc:  # noqa: BLE001 - reported to the model, never crashes the turn
		return ToolCall(
			name=name, arguments=args, result={"error": f"{type(exc).__name__}: {exc}"}, is_error=True
		)
	if not isinstance(result, Mapping):
		result = {"result": result}
	# Convention shared with the dispatchers: a mapping whose "error" is a non-empty
	# string reports a failure the handler chose to describe (bad arguments, unknown
	# tool) instead of raising, so it is flagged like an exception would be.
	is_error = isinstance(result.get("error"), str) and bool(result.get("error"))
	return ToolCall(name=name, arguments=args, result=dict(result), is_error=is_error)


def trace_as_dicts(trace: list[ToolCall]) -> list[dict[str, Any]]:
	return [asdict(call) for call in trace]


def model_warning(provider: str, model: str) -> str | None:
	"""Text of the startup warning for an id outside the allowlist, or None."""
	known = MODEL_ALLOWLIST.get(provider)
	if known is None or model in known:
		return None
	return (
		f"{provider} model {model!r} is not in the allowlist checked on "
		f"{MODEL_ALLOWLIST_CHECKED_ON.isoformat()} ({', '.join(sorted(known))}); "
		"using it anyway - check the site config if calls fail"
	)


# --- base client ------------------------------------------------------------------------


@dataclass
class RetryPolicy:
	max_retries: int = DEFAULT_MAX_RETRIES
	backoff_base_s: float = DEFAULT_BACKOFF_BASE_S
	backoff_max_s: float = DEFAULT_BACKOFF_MAX_S
	sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
	rng: Callable[[], float] = field(default=random.random, repr=False)

	def delay_for(self, attempt: int) -> float:
		"""Exponential backoff with full jitter in [0.5, 1.5) of the nominal delay."""
		nominal = min(self.backoff_max_s, self.backoff_base_s * (2**attempt))
		return nominal * (0.5 + self.rng())


class BaseClient(abc.ABC):
	"""Retries, timing and call recording; adapters implement the two ``_*_once`` hooks.

	Retries happen around each raw request (``_request``) rather than around the whole
	``with_tools`` loop, so a transient 429 in turn 3 does not re-run tool handlers.
	"""

	provider: str = "base"

	def __init__(
		self,
		model: str,
		*,
		record_call: RecordCall | None = None,
		timeout_s: float = DEFAULT_TIMEOUT_S,
		retry: RetryPolicy | None = None,
		clock: Callable[[], float] = time.monotonic,
	):
		self.model = model
		self.record_call = record_call
		self.timeout_s = timeout_s
		self.retry = retry or RetryPolicy()
		self._clock = clock
		warning = model_warning(self.provider, model)
		if warning:
			logger.warning(warning)

	# -- public contract --

	def structured(
		self,
		*,
		purpose: str,
		system: str,
		user: list[Part],
		schema: dict,
		schema_name: str,
		temperature: float = 0,
		prompt_version: str | None = None,
	) -> LlmResult:
		return self._timed(
			purpose,
			prompt_version,
			lambda: self._structured_once(
				system=system,
				user=user,
				schema=schema,
				schema_name=schema_name,
				temperature=temperature,
			),
		)

	def with_tools(
		self,
		*,
		purpose: str,
		system: str,
		user: list[Part],
		tools: list[ToolSpec],
		handler: ToolHandler,
		max_turns: int = 4,
		prompt_version: str | None = None,
	) -> LlmResult:
		if max_turns < 1:
			raise ValueError("max_turns must be >= 1")
		return self._timed(
			purpose,
			prompt_version,
			lambda: self._with_tools_once(
				system=system,
				user=user,
				tools=tools,
				handler=handler,
				max_turns=max_turns,
			),
		)

	# -- adapter hooks --

	@abc.abstractmethod
	def _structured_once(
		self, *, system: str, user: list[Part], schema: dict, schema_name: str, temperature: float
	) -> LlmResult: ...

	@abc.abstractmethod
	def _with_tools_once(
		self, *, system: str, user: list[Part], tools: list[ToolSpec], handler: ToolHandler, max_turns: int
	) -> LlmResult: ...

	def _translate(self, exc: BaseException) -> LlmError | None:
		"""Map an SDK exception to the LlmError hierarchy; None means 'not ours, re-raise'."""
		if isinstance(exc, LlmError):
			return exc
		if isinstance(exc, TimeoutError):
			return LlmTimeout(str(exc) or "timeout")
		return None

	# -- plumbing --

	def _request(self, fn: Callable[[], Any]) -> Any:
		"""Run one raw provider request with retries on rate-limit / 5xx / timeout only."""
		attempt = 0
		while True:
			try:
				return fn()
			except Exception as exc:  # noqa: BLE001 - translated below, unknown ones re-raised
				error = self._translate(exc)
				if error is None:
					raise
				if not error.retryable or attempt >= self.retry.max_retries:
					raise error from (exc if exc is not error else None)
				delay = self.retry.delay_for(attempt)
				logger.info(
					"llm retry provider=%s attempt=%d delay=%.2fs reason=%s",
					self.provider,
					attempt + 1,
					delay,
					type(error).__name__,
				)
				self.retry.sleep(delay)
				attempt += 1

	def _timed(self, purpose: str, prompt_version: str | None, fn: Callable[[], LlmResult]) -> LlmResult:
		started = self._clock()
		try:
			result = fn()
		except LlmError as exc:
			latency = int((self._clock() - started) * 1000)
			self._emit(
				CallRecord(
					purpose=purpose,
					provider=self.provider,
					model=self.model,
					prompt_version=prompt_version,
					tokens_in=0,
					tokens_out=0,
					latency_ms=latency,
					ok=False,
					error_class=type(exc).__name__,
					raw_id=exc.raw_id,
				)
			)
			raise
		latency = int((self._clock() - started) * 1000)
		result = replace(result, latency_ms=latency, purpose=purpose, prompt_version=prompt_version)
		self._emit(
			CallRecord(
				purpose=purpose,
				provider=result.provider,
				model=result.model,
				prompt_version=prompt_version,
				tokens_in=result.tokens_in,
				tokens_out=result.tokens_out,
				latency_ms=latency,
				ok=True,
				raw_id=result.raw_id,
			)
		)
		return result

	def _emit(self, record: CallRecord) -> None:
		if self.record_call is None:
			return
		try:
			self.record_call(record)
		except Exception:  # noqa: BLE001 - logging must never break a pipeline call
			logger.exception("record_call failed for purpose=%s", record.purpose)


# --- factory ----------------------------------------------------------------------------


def _setting(settings: Any, name: str, default: Any = None) -> Any:
	"""Read a key from ``nyabo_mn.config.Settings`` or any mapping (tests)."""
	value = None
	getter = getattr(settings, "get", None)
	if callable(getter):
		value = getter(name)
		if value in (None, ""):
			value = getter(name.lower())
	if value in (None, ""):
		return default
	return value


def get_client(settings: Any, provider: str = "auto", *, record_call: RecordCall | None = None) -> LlmClient:
	"""Build the configured client.

	``provider="anthropic"`` uses Anthropic when ``ANTHROPIC_API_KEY`` is set; everything
	else (including ``"auto"``) uses OpenAI, which is the founder's primary provider.
	``provider="mock"`` returns the fixture-driven client for the simulator.
	"""
	provider = (provider or "auto").lower()
	if provider == "mock":
		from nyabo_mn.agent.mock_client import MockLlmClient

		return MockLlmClient(record_call=record_call)

	anthropic_key = str(_setting(settings, "ANTHROPIC_API_KEY", "") or "")
	if provider == "anthropic":
		if not anthropic_key:
			from nyabo_mn.config import MissingSettingError

			raise MissingSettingError(
				"Site config is missing ANTHROPIC_API_KEY (needed for provider=anthropic)."
			)
		from nyabo_mn.agent.anthropic_client import AnthropicClient

		model = str(_setting(settings, "ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL))
		return AnthropicClient(api_key=anthropic_key, model=model, record_call=record_call)

	if provider not in ("auto", "openai"):
		raise ValueError(f"unknown LLM provider {provider!r}; expected auto, openai, anthropic or mock")

	openai_key = str(_setting(settings, "OPENAI_API_KEY", "") or "")
	if not openai_key:
		from nyabo_mn.config import MissingSettingError

		raise MissingSettingError("Site config is missing OPENAI_API_KEY (needed for the llm feature).")
	from nyabo_mn.agent.openai_client import OpenAIClient

	model = str(_setting(settings, "OPENAI_MODEL", DEFAULT_OPENAI_MODEL))
	return OpenAIClient(api_key=openai_key, model=model, record_call=record_call)


__all__ = [
	"DEFAULT_ANTHROPIC_MODEL",
	"DEFAULT_OPENAI_MODEL",
	"MODEL_ALLOWLIST",
	"MODEL_ALLOWLIST_CHECKED_ON",
	"PURPOSES",
	"BaseClient",
	"CallRecord",
	"ImagePart",
	"LlmClient",
	"LlmError",
	"LlmProviderError",
	"LlmRateLimited",
	"LlmResult",
	"LlmSchemaError",
	"LlmTimeout",
	"Part",
	"RecordCall",
	"RetryPolicy",
	"TextPart",
	"ToolCall",
	"ToolHandler",
	"ToolSpec",
	"check_against_schema",
	"get_client",
	"hash_parts",
	"model_warning",
	"parse_json_object",
	"run_tool_handler",
	"trace_as_dicts",
]
