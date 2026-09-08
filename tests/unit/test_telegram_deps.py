"""Every ``_deps`` shim must name a function that really exists.

The handlers only ever reach a sibling module through ``nyabo_mn/telegram/_deps.py``, and
``_call`` resolves the dotted path at call time, so a wrong module name stays invisible until
an accountant taps a button - and invisible to the flow tests too, which monkeypatch the shim
attributes. This walks the source for every ``_call("module", "function", ...)`` literal and
imports the target for real.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

DEPS = Path(__file__).resolve().parents[2] / "nyabo_mn" / "telegram" / "_deps.py"


def _call_sites() -> list[tuple[int, str, str]]:
	tree = ast.parse(DEPS.read_text(encoding="utf-8"), filename=str(DEPS))
	sites: list[tuple[int, str, str]] = []
	for node in ast.walk(tree):
		if not isinstance(node, ast.Call) or getattr(node.func, "id", None) != "_call":
			continue
		module, function = node.args[0], node.args[1]
		assert isinstance(module, ast.Constant) and isinstance(function, ast.Constant), (
			f"_deps.py:{node.lineno}: _call target is not a literal"
		)
		sites.append((node.lineno, module.value, function.value))
	return sites


def test_every_call_site_was_found() -> None:
	sites = _call_sites()
	assert len(sites) >= 25
	assert ("nyabo_mn.agent.post", "post_proposal") in [(m, f) for _, m, f in sites]


@pytest.mark.parametrize(("lineno", "module", "function"), _call_sites())
def test_call_target_exists(lineno: int, module: str, function: str) -> None:
	mod = importlib.import_module(module)
	assert callable(getattr(mod, function, None)), f"_deps.py:{lineno}: {module}.{function} is missing"
