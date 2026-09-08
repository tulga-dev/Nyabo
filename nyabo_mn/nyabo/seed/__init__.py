"""Seed data shipped with the app (docs/seed/README.md explains every file).

Pure Python: `load_seed("tax_parameters")` returns the parsed JSON so the core engine,
the Frappe-side `rules.seed.sync` and `scripts/seed_check.py` read the same files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SEED_DIR = Path(__file__).parent

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
