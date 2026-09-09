"""Provider-neutral LLM client contract (docs/ARCHITECTURE.md §6).

The pipeline only ever sees ``LlmClient``: two call shapes (``structured`` for
schema-validated extraction/classification without tools, ``with_tools`` for the
read-only question loop), one result type and one error hierarchy. Providers are
adapters (``openai_client``, ``anthropic_client``, ``mock_client``) built on
``BaseClient``, which owns retries, the per-call timeout, latency measurement and the
``record_call`` hook that writes ``Nyabo LLM Call`` (through ``frappe_log``; this module
never imports frappe so the simulator and tests can use it).

Model ids are read from settings, one per purpose: ``get_client`` returns a
``PurposeRouter`` that picks the model from the ``purpose`` every call already carries
(``OPENAI_PURPOSE_MODELS`` holds the routing, ``resolve_model`` the precedence), so the
model written to ``Nyabo LLM Call`` is the one that answered. The defaults were given by
the founder - extraction reads the photograph on ``gpt-5.6-terra``, classification and the
question loop reason on ``gpt-6-astra`` - and the small
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


@dataclass(frozen=True)
class PurposeModel:
	"""How one purpose picks its OpenAI model.

	``key`` is the site-config key that overrides it; ``None`` means the purpose has no key
	of its own and follows ``OPENAI_MODEL``. ``default`` is the model the founder chose for
	that purpose, used when the key is unset; ``None`` means "whatever ``OPENAI_MODEL``
	says". Separate keys rather than one JSON map because Frappe Cloud's Site Config is the
	only door the founder has (no shell), it edits one key at a time, and a key name greps.
	"""

	key: str | None
	default: str | None


#: The founder's routing - "Astra for reasoning and chat, terra for receipt parsing" - with
#: one entry per member of ``PURPOSES``, so a new purpose cannot be added without deciding
#: which model runs it (tests/unit/test_agent_llm_client.py pins that). ``extract`` reads a
#: photograph; ``classify`` and ``question`` reason in text, and classify is the judgement
#: call: see docs/DECISIONS.md LLM-02.
OPENAI_PURPOSE_MODELS: Mapping[str, PurposeModel] = {
	"extract": PurposeModel("OPENAI_MODEL_EXTRACT", "gpt-5.6-terra"),
	"classify": PurposeModel("OPENAI_MODEL_CLASSIFY", "gpt-6-astra"),
	"question": PurposeModel("OPENAI_MODEL_QUESTION", "gpt-6-astra"),
	"eval": PurposeModel(None, None),
	"other": PurposeModel(None, None),
}

#: The per-purpose keys, in ``PURPOSES`` order. ``nyabo_mn.config.KEY_SPECS`` declares the
#: same names (a test keeps the two in step) so ``config_check`` lists them.
PURPOSE_MODEL_KEYS: tuple[str, ...] = tuple(
	route.key for route in OPENAI_PURPOSE_MODELS.values() if route.key
)


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


@dataclass(frozen=True)
class ModelChoice:
	"""The model one purpose will actually use, and where the id came from.

	``source`` is the site-config key that supplied the id (``OPENAI_MODEL_CLASSIFY``,
	``OPENAI_MODEL``, ``ANTHROPIC_MODEL``), ``"purpose default"`` for the founder's routing
	in ``OPENAI_PURPOSE_MODELS``, or ``"built-in default"`` when nothing is configured at
	all. ``nyabo_mn.api.config_check`` prints it, so the founder sees *why* a purpose runs
	the model it runs instead of inferring it from the keys he set; ``warning`` repeats the
	allowlist warning there too, so a typo shows before the next receipt fails.
	"""

	purpose: str
	model: str
	source: str
	warning: str | None = None


def resolve_model(settings: Any, purpose: str, provider: str = "openai") -> ModelChoice:
	"""Which model ``purpose`` runs on: its own key, then its routing default, then the fallback.

	The precedence matters (docs/DECISIONS.md LLM-01): a purpose with a default of its own
	ignores ``OPENAI_MODEL``, because a site that pins ``OPENAI_MODEL`` - as the live one
	does - would otherwise keep answering questions on the extraction model and the routing
	would quietly do nothing. ``eval`` and ``other`` have no default, so they are exactly
	what ``OPENAI_MODEL`` says. An unknown purpose is treated as ``other`` rather than
	raising: a model call must never fail over its own label. Anthropic is the spare
	provider and has no per-purpose keys; it answers ``ANTHROPIC_MODEL`` for every purpose.
	"""
	if purpose not in OPENAI_PURPOSE_MODELS:
		purpose = "other"
	if provider == "anthropic":
		configured = _setting(settings, "ANTHROPIC_MODEL")
		model = str(configured) if configured else DEFAULT_ANTHROPIC_MODEL
		source = "ANTHROPIC_MODEL" if configured else "built-in default"
		return ModelChoice(purpose, model, source, model_warning("anthropic", model))

	route = OPENAI_PURPOSE_MODELS[purpose]
	model = ""
	source = ""
	if route.key:
		configured = _setting(settings, route.key)
		if configured:
			model, source = str(configured), route.key
	if not model and route.default:
		model, source = route.default, "purpose default"
	if not model:
		configured = _setting(settings, "OPENAI_MODEL")
		if configured:
			model, source = str(configured), "OPENAI_MODEL"
		else:
			model, source = DEFAULT_OPENAI_MODEL, "built-in default"
	return ModelChoice(purpose, model, source, model_warning("openai", model))


def resolve_models(settings: Any, provider: str = "openai") -> dict[str, ModelChoice]:
	"""Every purpose in ``PURPOSES``, resolved. What ``nyabo_mn.api.config_check`` answers."""
	return {purpose: resolve_model(settings, purpose, provider) for purpose in PURPOSES}


def pin_models(values: Mapping[str, Any], provider: str, model: str) -> dict[str, Any]:
	"""A copy of ``values`` in which every purpose resolves to ``model``.

	For the eval sweep, which asks "how does *this* model do on the golden set". Setting
	``OPENAI_MODEL`` alone would not do it: the per-purpose defaults outrank it, so the
	sweep would name one model in its report while extraction and classification quietly
	ran on the routed ones.
	"""
	pinned = dict(values)
	if provider == "anthropic":
		pinned["ANTHROPIC_MODEL"] = model
		return pinned
	pinned["OPENAI_MODEL"] = model
	for key in PURPOSE_MODEL_KEYS:
		pinned[key] = model
	return pinned


class PurposeRouter:
	"""One adapter per purpose behind the single ``LlmClient`` a caller holds.

	The model cannot be chosen once at construction, because one client serves several
	purposes in a run: ``agent.pipeline`` extracts and then classifies through the same
	object. Every caller already says what a call is for (``structured(purpose=...)``), so
	the router dispatches on that and no caller changes. Adapters are shared by model id,
	and each one records its own calls, so ``Nyabo LLM Call.model`` is the model that
	actually answered - the only way to check the routing on a live site.
	"""

	def __init__(self, provider: str, clients: Mapping[str, LlmClient], *, default_purpose: str = "other"):
		if default_purpose not in clients:
			raise ValueError(f"no client for the default purpose {default_purpose!r}")
		self.provider = provider
		self._clients = dict(clients)
		self._default_purpose = default_purpose

	@property
	def model(self) -> str:
		"""The fallback purpose's model; a call's own model is ``client_for(purpose).model``."""
		return self._clients[self._default_purpose].model

	@property
	def record_call(self) -> RecordCall | None:
		return getattr(self._clients[self._default_purpose], "record_call", None)

	@record_call.setter
	def record_call(self, value: RecordCall | None) -> None:
		"""Callers attach the recorder after construction; every adapter must get it (§6)."""
		for client in self._clients.values():
			client.record_call = value  # type: ignore[attr-defined]

	def client_for(self, purpose: str) -> LlmClient:
		"""The adapter for ``purpose``; an unknown label falls back like ``resolve_model``."""
		return self._clients.get(purpose, self._clients[self._default_purpose])

	def models(self) -> dict[str, str]:
		"""purpose -> model id, for a caller that wants to log or show the routing."""
		return {purpose: client.model for purpose, client in self._clients.items()}

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
		return self.client_for(purpose).structured(
			purpose=purpose,
			system=system,
			user=user,
			schema=schema,
			schema_name=schema_name,
			temperature=temperature,
			prompt_version=prompt_version,
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
		return self.client_for(purpose).with_tools(
			purpose=purpose,
			system=system,
			user=user,
			tools=tools,
			handler=handler,
			max_turns=max_turns,
			prompt_version=prompt_version,
		)


def _one_or_router(
	settings: Any, provider: str, purpose: str | None, build: Callable[[str], LlmClient]
) -> LlmClient:
	"""A single adapter pinned to ``purpose``, or a router over every purpose.

	Adapters are built once per distinct model id, so the founder's routing costs two.
	"""
	if purpose is not None:
		return build(resolve_model(settings, purpose, provider).model)
	by_model: dict[str, LlmClient] = {}
	clients: dict[str, LlmClient] = {}
	for name, choice in resolve_models(settings, provider).items():
		client = by_model.get(choice.model)
		if client is None:
			client = build(choice.model)
			by_model[choice.model] = client
		clients[name] = client
	return PurposeRouter(provider, clients)


def get_client(
	settings: Any,
	provider: str = "auto",
	*,
	purpose: str | None = None,
	record_call: RecordCall | None = None,
) -> LlmClient:
	"""Build the configured client.

	``provider="anthropic"`` uses Anthropic when ``ANTHROPIC_API_KEY`` is set; everything
	else (including ``"auto"``) uses OpenAI, which is the founder's primary provider.
	``provider="mock"`` returns the fixture-driven client for the simulator.

	``purpose=None`` - what every existing caller passes - returns a :class:`PurposeRouter`
	that picks the model per call from the purpose the caller already names. Passing a
	purpose returns one adapter pinned to that purpose's model, for a caller that makes only
	one kind of call and wants to hold the model id.
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

		def anthropic_adapter(model: str) -> LlmClient:
			return AnthropicClient(api_key=anthropic_key, model=model, record_call=record_call)

		return _one_or_router(settings, "anthropic", purpose, anthropic_adapter)

	if provider not in ("auto", "openai"):
		raise ValueError(f"unknown LLM provider {provider!r}; expected auto, openai, anthropic or mock")

	openai_key = str(_setting(settings, "OPENAI_API_KEY", "") or "")
	if not openai_key:
		from nyabo_mn.config import MissingSettingError

		raise MissingSettingError("Site config is missing OPENAI_API_KEY (needed for the llm feature).")
	from nyabo_mn.agent.openai_client import OpenAIClient

	def openai_adapter(model: str) -> LlmClient:
		return OpenAIClient(api_key=openai_key, model=model, record_call=record_call)

	return _one_or_router(settings, "openai", purpose, openai_adapter)


__all__ = [
	"DEFAULT_ANTHROPIC_MODEL",
	"DEFAULT_OPENAI_MODEL",
	"MODEL_ALLOWLIST",
	"MODEL_ALLOWLIST_CHECKED_ON",
	"OPENAI_PURPOSE_MODELS",
	"PURPOSES",
	"PURPOSE_MODEL_KEYS",
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
	"ModelChoice",
	"Part",
	"PurposeModel",
	"PurposeRouter",
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
	"pin_models",
	"resolve_model",
	"resolve_models",
	"run_tool_handler",
	"trace_as_dicts",
]
