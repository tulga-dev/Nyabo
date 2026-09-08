"""F-12: the regime names are spelled in one module, and this test keeps them there.

``nyabo_mn/rules/regime.py`` (with the ``Regime`` enum it re-exports) owns "vat_payer" and
"simplified_1pct". Everything else asks it - ``regime.REGIME_VAT_PAYER``,
``regime.name_for_vat_status(...)``, ``Regime.VAT_PAYER.value`` - so a renamed or added
regime is a one-line change instead of a grep across the app.

The scan walks the Python source of ``nyabo_mn/`` and ``scripts/`` with ``ast`` and counts
string constants equal to a regime name. The seed JSON, the golden fixtures and the tests
are data and are not scanned; the owner module is excluded. Everything left is listed in
``ALLOWED`` with a reason, and the counts are exact: a new literal anywhere - including one
more in an allowlisted file - fails this test. If you are adding one, the fix is almost
always to import the constant; if the string genuinely means something else (see the
ebarimt entries below), add it here with a sentence saying so.
"""

from __future__ import annotations

import ast
from pathlib import Path

from nyabo_mn.core.models import Regime

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("nyabo_mn", "scripts")
OWNER = "nyabo_mn/rules/regime.py"
REGIME_NAMES = frozenset(r.value for r in Regime)

# path -> {literal: (count, why it is not a regime name here)}
ALLOWED: dict[str, dict[str, tuple[int, str]]] = {
	"nyabo_mn/core/models.py": {
		"vat_payer": (1, "the Regime enum: the one definition, re-exported by rules.regime"),
		"simplified_1pct": (1, "the Regime enum: the one definition, re-exported by rules.regime"),
	},
	# ebarimt's seller payload has a field called vat_payer ("is this seller registered for
	# VAT?"). It is a foreign API's field name that happens to be spelled like the regime.
	"nyabo_mn/ebarimt/mock.py": {"vat_payer": (4, "the ebarimt seller field name, not a regime")},
	"nyabo_mn/simulator/run.py": {"vat_payer": (1, "SellerInfo.vat_payer attribute name")},
	"nyabo_mn/telegram/cards.py": {"vat_payer": (1, "the seller-verification payload key")},
}


def _python_files() -> list[Path]:
	files: list[Path] = []
	for root in SCAN_ROOTS:
		for path in sorted((REPO_ROOT / root).rglob("*.py")):
			if "__pycache__" in path.parts:
				continue
			if path.relative_to(REPO_ROOT).as_posix() == OWNER:
				continue
			files.append(path)
	return files


def _regime_literals(path: Path) -> dict[str, int]:
	tree = ast.parse(path.read_text(encoding="utf-8"))
	counts: dict[str, int] = {}
	for node in ast.walk(tree):
		if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in REGIME_NAMES:
			counts[node.value] = counts.get(node.value, 0) + 1
	return counts


def test_regime_names_are_not_spelled_outside_rules_regime():
	found = {}
	for path in _python_files():
		counts = _regime_literals(path)
		if counts:
			found[path.relative_to(REPO_ROOT).as_posix()] = counts
	expected = {
		path: {literal: count for literal, (count, _reason) in entries.items()}
		for path, entries in ALLOWED.items()
	}
	assert found == expected, (
		"regime names belong in nyabo_mn/rules/regime.py: use regime.REGIME_VAT_PAYER / "
		"regime.REGIME_SIMPLIFIED / regime.name_for_vat_status(), or Regime.<X>.value where "
		f"Frappe is not importable.\nfound: {found}\nallowed: {expected}"
	)


def test_the_owner_module_still_defines_the_names():
	"""The allowlist above is only safe while rules.regime really is the definition."""
	from nyabo_mn.rules import regime

	assert regime.REGIME_VAT_PAYER == Regime.VAT_PAYER.value
	assert regime.REGIME_SIMPLIFIED == Regime.SIMPLIFIED_1PCT.value
	assert set(regime.REGIME_NAMES) == REGIME_NAMES
	assert regime.name_for_vat_status(True) == regime.REGIME_VAT_PAYER
	assert regime.name_for_vat_status(False) == regime.REGIME_SIMPLIFIED
	assert all(reason for entries in ALLOWED.values() for _count, reason in entries.values())
