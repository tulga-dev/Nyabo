"""Seed data shipped with the app (docs/seed/README.md explains every file).

Pure Python: `load_seed("tax_parameters")` returns the parsed JSON so the core engine,
the Frappe-side `rules.seed.sync` and `scripts/seed_check.py` read the same files.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SEED_DIR = Path(__file__).parent

# A verified tax-parameter row carries the verbatim sentence it was read from: in `quote_mn`
# when the row has the key, otherwise as the first element of `note` (`«…» — remarks`, the
# shape the legal-citation pass used before `quote_mn` joined the schema).
QUOTE_NOTE_RE = re.compile(r"^\s*«(.+?)»\s*—", re.S)

SEED_FILES: tuple[str, ...] = (
	"tax_parameters",
	"posting_patterns",
	"chart_v03",
	"aliases_v1_to_v03",
	"code_roles",
	"bank_layouts",
	"rules_default",
)


def seed_path(name: str) -> Path:
	return SEED_DIR / f"{name}.json"


def load_seed(name: str) -> Any:
	with open(seed_path(name), encoding="utf-8") as f:
		return json.load(f)


def tax_parameter_quote(row: Mapping[str, Any]) -> str | None:
	"""The verbatim Mongolian quote of a tax-parameter seed row (`quote_mn`, else the note prefix)."""
	quote = row.get("quote_mn")
	if isinstance(quote, str) and quote.strip():
		return quote.strip()
	match = QUOTE_NOTE_RE.match(str(row.get("note") or ""))
	return match.group(1).strip() if match else None
