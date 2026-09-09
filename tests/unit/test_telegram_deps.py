"""Every ``_deps`` shim must call a function that exists, with arguments that fit it.

The handlers only ever reach a sibling module through ``nyabo_mn/telegram/_deps.py``, and
``_call`` resolves the dotted path at call time, so a wrong module name stays invisible until
an accountant taps a button - and invisible to the flow tests too, which monkeypatch the shim
attributes. This walks the source for every ``_call("module", "function", ...)`` literal and
imports the target for real.

Existence alone was not enough: the live bot crashed twice on shims whose *arguments* had
drifted from a target that was right there and importable - ``parse_table`` was handed a file
and a filename when it takes read cells, and ``create_intake`` was handed the chat's argument
order, which put a Telegram user id in a date field. So each site is also bound against
``inspect.signature`` of the target. Binding checks the shape (how many positionals, which
keywords), never the values; an order swap between same-typed parameters still binds, which is
why the inventory chain also has an end-to-end flow test (tests/flows/test_inventory_chain.py).
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from typing import Any

import pytest

DEPS = Path(__file__).resolve().parents[2] / "nyabo_mn" / "telegram" / "_deps.py"


class _Anything:
	"""A stand-in argument: only the shape of a call is under test here, never its values."""

	def __repr__(self) -> str:
		return "<any>"


ANY = _Anything()


def _is_call(node: ast.AST) -> bool:
	return isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_call"


def _site(wrapper: str, node: ast.Call) -> tuple[str, int, str, str, int, tuple[str, ...]]:
	module, function = node.args[0], node.args[1]
	assert isinstance(module, ast.Constant) and isinstance(function, ast.Constant), (
		f"_deps.py:{node.lineno}: _call target is not a literal"
	)
	assert not any(isinstance(arg, ast.Starred) for arg in node.args), (
		f"_deps.py:{node.lineno}: *args hides the arity this test exists to check"
	)
	keywords: list[str] = []
	for keyword in node.keywords:
		assert keyword.arg is not None, (
			f"_deps.py:{node.lineno}: **kwargs hides the keywords this test exists to check"
		)
		keywords.append(keyword.arg)
	return (wrapper, node.lineno, module.value, function.value, len(node.args) - 2, tuple(keywords))


def _call_sites() -> list[tuple[str, int, str, str, int, tuple[str, ...]]]:
	tree = ast.parse(DEPS.read_text(encoding="utf-8"), filename=str(DEPS))
	sites = []
	for definition in ast.walk(tree):
		if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
			continue
		sites.extend(_site(definition.name, node) for node in ast.walk(definition) if _is_call(node))
	# Nothing may hide outside a shim function, or it would never be checked.
	assert len(sites) == len([node for node in ast.walk(tree) if _is_call(node)])
	return sites


def _id(site: tuple[str, int, str, str, int, tuple[str, ...]]) -> str:
	return f"{site[0]}:{site[1]}->{site[3]}"


SITES = _call_sites()
CASES = pytest.mark.parametrize(
	("wrapper", "lineno", "module", "function", "positional", "keywords"), SITES, ids=[_id(s) for s in SITES]
)


def test_every_call_site_was_found() -> None:
	assert len(SITES) >= 25
	assert ("nyabo_mn.agent.post", "post_proposal") in [(m, f) for _, _, m, f, _, _ in SITES]
	# The two shapes the shims must keep straight, both of which shipped broken.
	assert ("nyabo_mn.parsers.excel", "read_rows") in [(m, f) for _, _, m, f, _, _ in SITES]
	assert ("inventory_create_intake", "create_intake") in [(w, f) for w, _, _, f, _, _ in SITES]


@CASES
def test_call_target_exists(
	wrapper: str, lineno: int, module: str, function: str, positional: int, keywords: tuple[str, ...]
) -> None:
	mod = importlib.import_module(module)
	assert callable(getattr(mod, function, None)), f"_deps.py:{lineno}: {module}.{function} is missing"


@CASES
def test_call_arguments_bind_to_the_target(
	wrapper: str, lineno: int, module: str, function: str, positional: int, keywords: tuple[str, ...]
) -> None:
	target = getattr(importlib.import_module(module), function)
	signature = inspect.signature(target)
	arguments: list[Any] = [ANY] * positional
	try:
		signature.bind(*arguments, **dict.fromkeys(keywords, ANY))
	except TypeError as exc:
		pytest.fail(
			f"_deps.py:{lineno}: {wrapper} -> {function}{signature} : "
			f"{positional} positional + {list(keywords)} does not bind: {exc}"
		)
