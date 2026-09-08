"""Fixture-driven LLM client for tests and the simulator (no network, deterministic).

Canned answers live in ``tests/fixtures/llm/<purpose>/<key>.json`` where ``key`` is
``hash_parts(user)`` (sha256 over the text parts, images by their bytes) and
``default.json`` answers anything without a keyed fixture. Fixture shape::

    {"data": {...}}                                                       # structured()
    {"text": "...", "tool_calls": [{"name": "...", "arguments": {...}}]}  # with_tools()

Programmatic answers (``add`` / ``add_for``) take precedence over files so a test can
script one call without touching the fixture tree. Every call is appended to ``calls``
so tests can assert on purposes, prompts and the fenced content.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyabo_mn.agent.llm_client import (
	BaseClient,
	ImagePart,
	LlmResult,
	LlmSchemaError,
	Part,
	RecordCall,
	TextPart,
	ToolCall,
	ToolHandler,
	ToolSpec,
	check_against_schema,
	hash_parts,
	run_tool_handler,
	trace_as_dicts,
)

DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"
DEFAULT_KEY = "default"


@dataclass
class RecordedCall:
	purpose: str
	key: str
	system: str
	user_text: str
	image_count: int
	schema_name: str | None = None
	tools: tuple[str, ...] = ()
	fixture: str | None = None
	prompt_version: str | None = None


class MockLlmClient(BaseClient):
	"""See module docstring."""

	provider = "mock"

	def __init__(
		self,
		*,
		fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
		record_call: RecordCall | None = None,
		model: str = "mock-model",
		strict: bool = False,
	):
		super().__init__(model, record_call=record_call)
		self.fixtures_dir = Path(fixtures_dir)
		self.strict = strict
		self.calls: list[RecordedCall] = []
		self._scripted: dict[tuple[str, str], dict[str, Any]] = {}
		self._purpose = "other"
		self._prompt_version: str | None = None

	# -- scripting --

	def add(self, purpose: str, payload: Mapping[str, Any], *, key: str = DEFAULT_KEY) -> None:
		"""Register a canned answer; ``key`` is a ``hash_parts`` digest or ``"default"``."""
		self._scripted[(purpose, key)] = dict(payload)

	def add_for(self, purpose: str, user: list[Part], payload: Mapping[str, Any]) -> None:
		self.add(purpose, payload, key=hash_parts(user))

	def clear(self) -> None:
		self._scripted.clear()
		self.calls.clear()

	# -- lookup --

	def _lookup(self, purpose: str, key: str) -> tuple[dict[str, Any], str]:
		for k in (key, DEFAULT_KEY):
			if (purpose, k) in self._scripted:
				return dict(self._scripted[(purpose, k)]), f"scripted:{k}"
		for k in (key, DEFAULT_KEY):
			path = self.fixtures_dir / purpose / f"{k}.json"
			if path.is_file():
				with path.open(encoding="utf-8") as fh:
					return json.load(fh), str(path)
		raise LlmSchemaError(
			f"no mock fixture for purpose={purpose!r} key={key[:12]}… in {self.fixtures_dir}"
		)

	@staticmethod
	def _tokens(system: str, user: list[Part], out: Any) -> tuple[int, int]:
		"""Rough counts (4 chars per token, 1000 per image) so simulator cost estimates are non-zero."""
		text_in = len(system) + sum(len(p.text) for p in user if isinstance(p, TextPart))
		images = sum(1 for p in user if isinstance(p, ImagePart))
		return text_in // 4 + images * 1000, len(json.dumps(out, ensure_ascii=False)) // 4

	def _remember(self, key: str, system: str, user: list[Part], **extra: Any) -> None:
		self.calls.append(
			RecordedCall(
				purpose=self._purpose,
				key=key,
				system=system,
				user_text="\n".join(p.text for p in user if isinstance(p, TextPart)),
				image_count=sum(1 for p in user if isinstance(p, ImagePart)),
				prompt_version=self._prompt_version,
				**extra,
			)
		)

	# -- BaseClient hooks --

	def _timed(self, purpose: str, prompt_version: str | None, fn: Any) -> LlmResult:
		# The adapter hooks do not receive purpose/version; keep them for the fixture lookup.
		self._purpose = purpose
		self._prompt_version = prompt_version
		return super()._timed(purpose, prompt_version, fn)

	def _structured_once(
		self, *, system: str, user: list[Part], schema: dict, schema_name: str, temperature: float
	) -> LlmResult:
		del temperature
		key = hash_parts(user)
		payload, source = self._lookup(self._purpose, key)
		self._remember(key, system, user, schema_name=schema_name, fixture=source)
		data = payload.get("data")
		if not isinstance(data, dict):
			raise LlmSchemaError(f"fixture {source} has no 'data' object")
		if self.strict:
			check_against_schema(data, schema)
		tokens_in, tokens_out = self._tokens(system, user, data)
		return LlmResult(
			data=data,
			text=json.dumps(data, ensure_ascii=False),
			tokens_in=tokens_in,
			tokens_out=tokens_out,
			latency_ms=0,
			model=self.model,
			provider=self.provider,
			raw_id=f"mock-{key[:12]}",
		)

	def _with_tools_once(
		self, *, system: str, user: list[Part], tools: list[ToolSpec], handler: ToolHandler, max_turns: int
	) -> LlmResult:
		key = hash_parts(user)
		payload, source = self._lookup(self._purpose, key)
		self._remember(key, system, user, tools=tuple(t.name for t in tools), fixture=source)
		known = {t.name for t in tools}
		trace: list[ToolCall] = []
		for scripted in list(payload.get("tool_calls") or [])[:max_turns]:
			trace.append(
				run_tool_handler(handler, known, str(scripted.get("name")), scripted.get("arguments") or {})
			)
		text = payload.get("text")
		tokens_in, tokens_out = self._tokens(system, user, payload)
		return LlmResult(
			data={"tool_calls": trace_as_dicts(trace)},
			text=str(text) if text is not None else None,
			tokens_in=tokens_in,
			tokens_out=tokens_out,
			latency_ms=0,
			model=self.model,
			provider=self.provider,
			raw_id=f"mock-{key[:12]}",
			tool_calls=tuple(trace),
			turns=max(1, len(trace)),
		)


__all__ = ["DEFAULT_FIXTURES_DIR", "DEFAULT_KEY", "MockLlmClient", "RecordedCall", "hash_parts"]
