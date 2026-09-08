"""Every seeded value must fit the MariaDB column its field type creates.

Frappe stores Data, Link, Select and Read Only as ``varchar(140)``. The in-memory test
stub has no column widths, so a citation longer than 140 characters passes every test and
then fails the real install with MariaDB 1406 ("Data too long for column"). That is what
happened to ``Nyabo Tax Parameter.source_text`` on the first Frappe Cloud install: ten
seeded rows carried legal references of 148-215 characters. This test measures the seed
against the generated DocType JSON so the failure surfaces here instead.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from nyabo_mn.rules import seed

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTYPE_DIR = REPO_ROOT / "nyabo_mn" / "nyabo" / "doctype"
SEED_DIR = REPO_ROOT / "nyabo_mn" / "nyabo" / "seed"

#: Frappe's varchar length for these field types (frappe/database/mariadb/database.py).
VARCHAR_LEN = 140
VARCHAR_TYPES = frozenset(
	{"Data", "Link", "Select", "Read Only", "Dynamic Link", "Password", "Attach", "Attach Image"}
)

#: doctype, seed file, value builder, name builder - the three sets ``seed.sync`` upserts.
SEEDED: tuple[
	tuple[str, str, Callable[[Mapping[str, Any]], dict[str, Any]], Callable[[Mapping[str, Any]], str]], ...
] = (
	(seed.TAX_PARAMETER, "tax_parameters", seed.tax_parameter_values, seed.tax_parameter_name),
	(seed.POSTING_PATTERN, "posting_patterns", seed.posting_pattern_values, lambda row: row["pattern_id"]),
	(seed.BANK_LAYOUT, "bank_layouts", seed.bank_layout_values, lambda row: row["layout_id"]),
)


def _declared_fields(doctype: str) -> dict[str, str]:
	"""fieldname -> fieldtype from the generated DocType JSON, which is what a bench installs."""
	folder = doctype.lower().replace(" ", "_")
	path = DOCTYPE_DIR / folder / f"{folder}.json"
	data = json.loads(path.read_text(encoding="utf-8"))
	return {f["fieldname"]: f["fieldtype"] for f in data["fields"] if f.get("fieldname")}


@pytest.mark.parametrize(("doctype", "seed_name", "values_of", "name_of"), SEEDED, ids=lambda v: str(v)[:30])
def test_no_seeded_value_overflows_its_column(
	doctype: str,
	seed_name: str,
	values_of: Callable[[Mapping[str, Any]], dict[str, Any]],
	name_of: Callable[[Mapping[str, Any]], str],
) -> None:
	declared = _declared_fields(doctype)
	rows = json.loads((SEED_DIR / f"{seed_name}.json").read_text(encoding="utf-8"))["rows"]
	assert rows, f"{seed_name}.json is empty"
	overflows: list[str] = []
	for row in rows:
		name = name_of(row)
		# The document name is varchar(140) too, whatever the naming rule.
		if len(name) > VARCHAR_LEN:
			overflows.append(f"{doctype} name is {len(name)} characters: {name[:60]}")
		for field, value in values_of(row).items():
			fieldtype = declared.get(field)
			assert fieldtype is not None, f"{doctype}.{field} is written by the seed but not declared"
			if isinstance(value, str) and fieldtype in VARCHAR_TYPES and len(value) > VARCHAR_LEN:
				overflows.append(
					f"{doctype}.{field} ({fieldtype}) is {len(value)} characters in {name}: {value[:60]}"
				)
	assert not overflows, "widen the field in scripts/doctype_specs.py:\n" + "\n".join(overflows)
