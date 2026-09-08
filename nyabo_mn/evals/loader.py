"""Load golden cases from JSON and validate them against the Nyabo Eval Case DocType.

The JSON files under ``evals/golden/`` use the Eval Case field names so a case can be
inserted into the DocType unchanged (``to_doc``) and a DocType row can be run like a
golden case (``from_doc``). The Select options are read from the committed DocType JSON
rather than duplicated here, so a new kind added in ``scripts/doctype_specs.py`` is
accepted by the loader without a code change.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
DOCTYPE_JSON = (
	Path(__file__).resolve().parents[1] / "nyabo" / "doctype" / "nyabo_eval_case" / "nyabo_eval_case.json"
)
RULES_KINDS: tuple[str, ...] = ("rules", "period_lock", "document_required", "correction", "fx")
MODEL_KINDS: tuple[str, ...] = ("extraction", "classification", "vat", "injection")
ALL_KINDS: tuple[str, ...] = MODEL_KINDS + RULES_KINDS + ("matching",)


class GoldenCaseError(ValueError):
	"""A case that does not fit the Eval Case DocType; the message names the case and field."""


@lru_cache(maxsize=1)
def field_options() -> dict[str, tuple[str, ...]]:
	"""``{fieldname: options}`` for every Select field of Nyabo Eval Case (empty option kept)."""
	with DOCTYPE_JSON.open(encoding="utf-8") as fh:
		meta = json.load(fh)
	out: dict[str, tuple[str, ...]] = {}
	for df in meta["fields"]:
		if df.get("fieldtype") == "Select":
			out[df["fieldname"]] = tuple((df.get("options") or "").split("\n"))
	return out


@lru_cache(maxsize=1)
def fieldnames() -> frozenset[str]:
	with DOCTYPE_JSON.open(encoding="utf-8") as fh:
		meta = json.load(fh)
	return frozenset(
		df["fieldname"]
		for df in meta["fields"]
		if df.get("fieldtype") not in ("Section Break", "Column Break")
	)


@dataclass(frozen=True)
class EvalCase:
	case_id: str
	kind: str
	source: str
	regime: str
	on_date: dt.date | None
	input_json: Mapping[str, Any]
	expected_json: Mapping[str, Any]
	notes: str = ""
	company: str | None = None
	input_document: str | None = None
	name: str | None = None  # DocType row name when loaded from the site
	path: str = ""
	extra: Mapping[str, Any] = field(default_factory=dict)

	def to_doc(self) -> dict[str, Any]:
		"""The dict for ``frappe.get_doc``; ``case_id`` travels in ``notes`` (no such column)."""
		notes = self.notes
		if self.case_id and f"case_id:{self.case_id}" not in notes:
			notes = f"case_id:{self.case_id}\n{notes}".strip()
		return {
			"doctype": "Nyabo Eval Case",
			"kind": self.kind,
			"source": self.source,
			"company": self.company,
			"regime": self.regime or "",
			"on_date": self.on_date.isoformat() if self.on_date else None,
			"input_document": self.input_document,
			"input_json": json.dumps(dict(self.input_json), ensure_ascii=False),
			"expected_json": json.dumps(dict(self.expected_json), ensure_ascii=False),
			"notes": notes,
		}

	@classmethod
	def from_doc(cls, doc: Any) -> EvalCase:
		"""A Nyabo Eval Case document (or its dict) as a runnable case."""
		get = doc.get if hasattr(doc, "get") else lambda k, d=None: getattr(doc, k, d)
		notes = str(get("notes") or "")
		case_id = get("name") or ""
		for line in notes.splitlines():
			if line.startswith("case_id:"):
				case_id = line[len("case_id:") :].strip()
				break
		return validate_case(
			{
				"case_id": case_id,
				"kind": get("kind"),
				"source": get("source") or "golden",
				"company": get("company"),
				"regime": get("regime") or "",
				"on_date": get("on_date"),
				"input_document": get("input_document"),
				"input_json": _parse_json(get("input_json"), "input_json", case_id),
				"expected_json": _parse_json(get("expected_json"), "expected_json", case_id),
				"notes": notes,
			},
			path=f"Nyabo Eval Case/{get('name')}",
			name=get("name"),
		)


def _parse_json(value: Any, fieldname: str, case_id: str) -> dict[str, Any]:
	if value in (None, ""):
		return {}
	if isinstance(value, Mapping):
		return dict(value)
	try:
		parsed = json.loads(value)
	except (TypeError, ValueError) as exc:
		raise GoldenCaseError(f"{case_id}: {fieldname} is not valid JSON: {exc}") from exc
	if not isinstance(parsed, dict):
		raise GoldenCaseError(f"{case_id}: {fieldname} must be a JSON object")
	return parsed


def validate_case(raw: Mapping[str, Any], *, path: str = "", name: str | None = None) -> EvalCase:
	"""Check the DocType shape: known fields, Select options, ISO date, JSON objects."""
	case_id = str(raw.get("case_id") or name or "")
	if not case_id:
		raise GoldenCaseError(f"{path}: case without case_id")
	unknown = set(raw) - fieldnames() - {"case_id"}
	if unknown:
		raise GoldenCaseError(f"{case_id}: unknown fields {sorted(unknown)} (not on Nyabo Eval Case)")
	options = field_options()
	for fieldname in ("kind", "source", "regime"):
		value = raw.get(fieldname) or ""
		if fieldname == "kind" and not value:
			raise GoldenCaseError(f"{case_id}: kind is required")
		if value not in options[fieldname]:
			raise GoldenCaseError(f"{case_id}: {fieldname}={value!r} not in {options[fieldname]}")
	on_date_raw = raw.get("on_date")
	on_date: dt.date | None = None
	if on_date_raw not in (None, ""):
		if isinstance(on_date_raw, dt.datetime):
			on_date = on_date_raw.date()
		elif isinstance(on_date_raw, dt.date):
			on_date = on_date_raw
		else:
			try:
				on_date = dt.date.fromisoformat(str(on_date_raw))
			except ValueError as exc:
				raise GoldenCaseError(f"{case_id}: on_date {on_date_raw!r} is not YYYY-MM-DD") from exc
	input_json = _parse_json(raw.get("input_json"), "input_json", case_id)
	expected_json = _parse_json(raw.get("expected_json"), "expected_json", case_id)
	if not expected_json:
		raise GoldenCaseError(f"{case_id}: expected_json is empty")
	kind = str(raw["kind"])
	if kind in ("classification", "vat", "correction", "rules", "injection") and not raw.get("regime"):
		raise GoldenCaseError(f"{case_id}: kind {kind} needs a regime")
	if kind != "matching" and on_date is None:
		raise GoldenCaseError(f"{case_id}: kind {kind} needs on_date")
	return EvalCase(
		case_id=case_id,
		kind=kind,
		source=str(raw.get("source") or "golden"),
		regime=str(raw.get("regime") or ""),
		on_date=on_date,
		input_json=input_json,
		expected_json=expected_json,
		notes=str(raw.get("notes") or ""),
		company=raw.get("company") or None,
		input_document=raw.get("input_document") or None,
		name=name,
		path=path,
	)


def load_file(path: Path) -> list[EvalCase]:
	with path.open(encoding="utf-8") as fh:
		payload = json.load(fh)
	rows = payload["cases"] if isinstance(payload, Mapping) else payload
	cases = [validate_case(row, path=f"{path.name}#{i}") for i, row in enumerate(rows)]
	seen: set[str] = set()
	for c in cases:
		if c.case_id in seen:
			raise GoldenCaseError(f"{path.name}: duplicate case_id {c.case_id}")
		seen.add(c.case_id)
	return cases


def load_golden(kinds: Iterable[str] | None = None, golden_dir: Path | str = GOLDEN_DIR) -> list[EvalCase]:
	"""Every case of the given kinds (all when ``kinds`` is None), in file order."""
	wanted = set(kinds) if kinds else None
	unknown = (wanted or set()) - set(ALL_KINDS)
	if unknown:
		raise GoldenCaseError(f"unknown kinds {sorted(unknown)}; known: {ALL_KINDS}")
	cases: list[EvalCase] = []
	ids: set[str] = set()
	for path in sorted(Path(golden_dir).glob("*.json")):
		for c in load_file(path):
			if c.case_id in ids:
				raise GoldenCaseError(f"duplicate case_id across files: {c.case_id}")
			ids.add(c.case_id)
			if wanted is None or c.kind in wanted:
				cases.append(c)
	return cases


__all__ = [
	"ALL_KINDS",
	"GOLDEN_DIR",
	"MODEL_KINDS",
	"RULES_KINDS",
	"EvalCase",
	"GoldenCaseError",
	"field_options",
	"load_file",
	"load_golden",
	"validate_case",
]
