"""UX-08 / ARCHITECTURE principle 7: every string a user reads lives in ``nyabo_mn/i18n/mn.py``.

A Mongolian literal outside i18n is invisible to whoever edits the wording, so this test
walks the source with ``ast`` and fails on any Cyrillic string constant in a module that is
not on the allow-list below. Docstrings and comments are exempt — they are for us, not for
the accountant.

The allow-list is for Cyrillic that is *input*, not output: words Nyabo reads (statement
column headers, command names the user types, injection patterns) and fixture data. Each
entry carries the reason, and a stale entry fails too, so the list cannot rot.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "nyabo_mn"
CYRILLIC = re.compile(r"[Ѐ-ӿ]")

# Modules exempt as a whole, with the reason. Anything else that a user reads belongs in mn.py.
ALLOWED: dict[str, str] = {
	"agent/schemas.py": "field descriptions handed to the model; they quote what a receipt prints",
	"core/matching.py": "normalisation keywords (ХХК, хураамж…) matched against supplier text",
	"core/money.py": "the currency-mark regex that strips ₮/төг from a parsed amount",
	"core/quarantine.py": "injection patterns matched against untrusted document text",
	"core/statements.py": "bank statement column header keywords",
	"ebarimt/mock.py": "fixture sellers for the simulator and tests",
	"evals/golden/_generate.py": "golden eval fixtures (receipts, statements, expectations)",
	"evals/harness.py": "eval fixture company name",
	"evals/runners.py": "eval fixture company name",
	"hooks.py": "Frappe app metadata, read by bench before the app is importable",
	"matching/bank_import.py": "bank-name keywords matched against statement text",
	"matching/rules.py": "the legal citation carried by a seeded rule",
	"setup/chart_csv.py": "CSV column header aliases in the accountant's own file",
	"setup/inventory_intake.py": "inventory column header aliases in the accountant's own file",
	"telegram/router.py": "the Cyrillic command names a user types",
	"telegram/state.py": "the role words a user types in /link",
}


def _docstring_ids(tree: ast.Module) -> set[int]:
	ids = set()
	for node in ast.walk(tree):
		if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
			body = node.body
			first = body[0] if body else None
			if (
				isinstance(first, ast.Expr)
				and isinstance(first.value, ast.Constant)
				and isinstance(first.value.value, str)
			):
				ids.add(id(first.value))
	return ids


def cyrillic_literals(path: Path) -> list[tuple[int, str]]:
	"""(line, text) for every Cyrillic string constant in the file that is not a docstring."""
	tree = ast.parse(path.read_text(encoding="utf-8"))
	docstrings = _docstring_ids(tree)
	return [
		(node.lineno, node.value)
		for node in ast.walk(tree)
		if isinstance(node, ast.Constant)
		and isinstance(node.value, str)
		and id(node) not in docstrings
		and CYRILLIC.search(node.value)
	]


def test_no_user_facing_mongolian_outside_i18n():
	offenders: list[str] = []
	for path in sorted(ROOT.rglob("*.py")):
		rel = path.relative_to(ROOT).as_posix()
		if rel.startswith("i18n/") or rel in ALLOWED:
			continue
		offenders += [f"{rel}:{line}: {text[:60]!r}" for line, text in cyrillic_literals(path)]
	assert offenders == [], (
		"Mongolian text outside nyabo_mn/i18n/mn.py — move it there and refer to it by name "
		"(add to ALLOWED only when the Cyrillic is input Nyabo reads, never output):\n" + "\n".join(offenders)
	)


@pytest.mark.parametrize("rel", sorted(ALLOWED))
def test_allow_list_has_no_stale_entry(rel: str):
	"""An exemption that no longer applies must be deleted, not left to hide a new literal."""
	path = ROOT / rel
	assert path.exists(), f"{rel} is on the allow-list but does not exist"
	assert cyrillic_literals(path), f"{rel} has no Cyrillic literal left; drop it from ALLOWED"
	assert ALLOWED[rel].strip(), f"{rel} needs a reason"
