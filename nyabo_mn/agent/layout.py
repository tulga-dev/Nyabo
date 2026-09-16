"""Reading an unrecognised bank statement layout: the model reads, the file itself proves it.

Before this module, an export nobody had mapped was answered with one question per column
(«Огноо» багана юу вэ?) — to a founder who had just watched a general-accountant model draft
journal entries from a sentence. The columns of a Mongolian bank export are obvious to an
accountant, and the model is one; so the harness now hands the model the first rows and the
Mongolian vocabulary of the roles and lets it say how the file reads. What stays with code is the
proof: every candidate mapping — the free keyword guess first, the model's reading when the
guess fails — is applied to the whole file by ``core.statements.check_layout``, and only a
reading that produces lines and agrees with the file's own running balance reaches the accountant,
as one card with the mapping, the figures the check found, and [Манай компанид хамаарна]
(DECISIONS PRO-04). A reading the file refutes falls back to the column questions, which still
exist for the export nobody can read.

Nothing is imported here. The accepted layout is saved unverified, the accountant's tap writes
the same ``Nyabo Rule Acceptance`` a manual mapping earns (ACC-02), and the next statement in
that format imports without a question — that is the memory.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import ValidationError

from nyabo_mn.agent import prompts
from nyabo_mn.agent.llm_client import LlmError, TextPart
from nyabo_mn.agent.schemas import StatementLayoutRead, json_schema
from nyabo_mn.core.quarantine import fence
from nyabo_mn.core.statements import (
	COLUMN_ROLES,
	DEFAULT_DATE_FORMATS,
	HEADER_SCAN_ROWS,
	LayoutCheck,
	LayoutError,
	LayoutSpec,
	cell_text,
	check_layout,
)
from nyabo_mn.log import log_event

PROMPT_NAME = "statement_layout"
PURPOSE = "classify"
SCHEMA_NAME = "statement_layout_read"
SOURCE_KEYWORD = "keyword"
SOURCE_MODEL = "model"
#: Rows the model sees: the title block, the header and enough lines to tell the columns apart.
MODEL_ROWS = HEADER_SCAN_ROWS + 5
MODEL_CELL_CHARS = 40
KNOWN_BANKS = ("Khan Bank", "TDB", "Golomt Bank", "Trans Bank", "XacBank")


@dataclass(frozen=True)
class Reading:
	"""One way to read the file that the file itself agreed with."""

	spec: LayoutSpec
	headers: list[str]
	mapping: dict[str, str]
	check: LayoutCheck
	source: str
	confidence: float
	date_format: str | None = None

	@property
	def header_row(self) -> int:
		return int(self.spec.header_row_hint or 0)


def rows_text(rows: Sequence[Sequence[Any]], limit: int = MODEL_ROWS) -> str:
	"""The first rows as ``row <i>: cell | cell``; long cells are cut so a narrative cannot flood it."""
	lines = []
	for index, row in enumerate(list(rows)[:limit]):
		cells = [cell_text(c)[:MODEL_CELL_CHARS] for c in (row or [])]
		while cells and not cells[-1]:
			cells.pop()
		lines.append(f"row {index}: " + " | ".join(cells))
	return "\n".join(lines)


def _headers_of(rows: Sequence[Sequence[Any]], index: int) -> list[str]:
	headers = [cell_text(c) for c in (rows[index] if 0 <= index < len(rows) else [])]
	while headers and not headers[-1].strip():
		headers.pop()
	return headers


def mapping_by_header(headers: Sequence[str], column_map: dict[str, int | str]) -> dict[str, str]:
	"""``{role: header text}`` the way a Telegram mapping is stored; an unnamed column keeps its index."""
	out: dict[str, str] = {}
	for role, ref in column_map.items():
		if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
			col = int(ref)
			text = headers[col].strip() if 0 <= col < len(headers) else ""
			out[role] = text or str(col)
		else:
			out[role] = str(ref)
	return out


def _reading(
	rows: Sequence[Sequence[Any]], spec: LayoutSpec, source: str, confidence: float, date_format: str | None
) -> Reading | None:
	"""Apply ``spec`` to the file; ``None`` when the file does not bear the reading out."""
	try:
		check = check_layout(rows, spec)
	except LayoutError as exc:
		log_event("layout.candidate_unreadable", level="warning", source=source, error=str(exc)[:200])
		return None
	if not check.ok:
		log_event("layout.candidate_refuted", level="warning", source=source, **check.facts())
		return None
	headers = _headers_of(rows, int(spec.header_row_hint or 0))
	return Reading(
		spec=spec,
		headers=headers,
		mapping=mapping_by_header(headers, dict(spec.column_map)),
		check=check,
		source=source,
		confidence=confidence,
		date_format=date_format,
	)


def keyword_reading(rows: Sequence[Sequence[Any]], guess: LayoutSpec | None) -> Reading | None:
	"""The free candidate: the keyword guess, kept only if the file agrees with it."""
	if guess is None or guess.header_row_hint is None:
		return None
	return _reading(rows, guess, SOURCE_KEYWORD, 0.0, None)


def spec_from_read(read: StatementLayoutRead, bank_hint: str | None) -> LayoutSpec:
	"""The model's answer as a LayoutSpec; the bank is the model's when it named one we know."""
	column_map: dict[str, int | str] = {}
	for column in read.columns:
		if column.role in COLUMN_ROLES and column.role not in column_map:
			column_map[column.role] = int(column.index)
	formats = tuple(DEFAULT_DATE_FORMATS)
	if read.date_format:
		formats = (read.date_format, *formats)
	bank = read.bank if read.bank in KNOWN_BANKS else (bank_hint if bank_hint in KNOWN_BANKS else "Other")
	return LayoutSpec(
		layout_id="model_read",
		bank=bank,
		column_map=column_map,
		amount_style=read.amount_style,
		date_formats=formats,
		header_row_hint=int(read.header_row),
		verified=False,
	)


def default_client(company: str) -> Any:
	from nyabo_mn.agent import frappe_log
	from nyabo_mn.agent.llm_client import get_client
	from nyabo_mn.agent.pipeline import _settings_obj, _simulation

	return get_client(
		_settings_obj(), "mock" if _simulation() else "auto", record_call=frappe_log.recorder(company=company)
	)


def model_reading(
	rows: Sequence[Sequence[Any]],
	company: str,
	bank_hint: str | None,
	*,
	client: Any = None,
	now: dt.datetime | None = None,
) -> Reading | None:
	"""Ask the model how the file reads, then let the file answer whether it was right."""
	try:
		client = client or default_client(company)
		prompt_text, version = prompts.load(PROMPT_NAME)
		system, user_template = prompts.split(prompt_text)
		user = prompts.fill(
			user_template,
			COMPANY_CONTEXT=fence(
				f"company: {company}\nbank_hint: {bank_hint or 'unknown'}", label="company"
			),
			UNTRUSTED=fence(rows_text(rows), label="statement_rows"),
			NOW=(now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="minutes"),
		)
		result = client.structured(
			purpose=PURPOSE,
			system=system,
			user=[TextPart(user)],
			schema=json_schema(StatementLayoutRead),
			schema_name=SCHEMA_NAME,
			prompt_version=prompts.version_tag(PROMPT_NAME, version),
		)
		read = StatementLayoutRead.model_validate(result.data or {})
	except (LlmError, ValidationError, Exception) as exc:  # noqa: BLE001 - the questions are the fallback
		log_event("layout.model_read_failed", level="warning", company=company, error=type(exc).__name__)
		return None
	spec = spec_from_read(read, bank_hint)
	return _reading(rows, spec, SOURCE_MODEL, read.confidence, read.date_format)


def read_layout(
	rows: Sequence[Sequence[Any]],
	company: str,
	guess: LayoutSpec | None,
	bank_hint: str | None,
	*,
	client: Any = None,
) -> Reading | None:
	"""The reading the accountant is shown: the keyword guess if the file agrees, else the model's."""
	found = keyword_reading(rows, guess)
	if found is not None:
		if found.spec.bank == "Other" and bank_hint in KNOWN_BANKS:
			found = replace(found, spec=replace(found.spec, bank=bank_hint))
		return found
	return model_reading(rows, company, bank_hint, client=client)


__all__ = [
	"PROMPT_NAME",
	"PURPOSE",
	"SOURCE_KEYWORD",
	"SOURCE_MODEL",
	"Reading",
	"default_client",
	"keyword_reading",
	"mapping_by_header",
	"model_reading",
	"read_layout",
	"rows_text",
	"spec_from_read",
]
