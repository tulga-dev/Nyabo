"""The floor guard in tests/conftest.py: which runs it judges, and what it judges them by.

The guard exists because a skip is silently green — with a real bench importable the
``site`` fixture skips every flow test and the suite still "passes". It must therefore
fire on a full run that shrank, and never on a deliberately narrowed one.
"""

from __future__ import annotations

import types
from typing import Any

from tests import conftest as bootstrap


def _config(args: list[str], testpaths: list[str] | None = None, **options: Any) -> Any:
	option = types.SimpleNamespace(
		keyword="", markexpr="", deselect=None, last_failed=False, failed_first=False, collectonly=False
	)
	for name, value in options.items():
		setattr(option, name, value)
	paths = ["tests"] if testpaths is None else testpaths
	return types.SimpleNamespace(
		args=list(args),
		option=option,
		getini=lambda name: paths if name == "testpaths" else None,
	)


def test_a_whole_suite_run_is_guarded():
	assert bootstrap._is_full_run(_config(["tests"])) is True


def test_a_narrowed_run_is_not_guarded():
	"""Running one file or filtering is normal work, not evidence that the suite shrank."""
	assert bootstrap._is_full_run(_config(["tests/unit/test_core_money.py"])) is False
	assert bootstrap._is_full_run(_config(["tests"], keyword="quarantine")) is False
	assert bootstrap._is_full_run(_config(["tests"], markexpr="slow")) is False
	assert bootstrap._is_full_run(_config(["tests"], deselect=["tests/flows"])) is False
	assert bootstrap._is_full_run(_config(["tests"], last_failed=True)) is False
	assert bootstrap._is_full_run(_config(["tests"], collectonly=True)) is False
	# no testpaths configured: nothing to compare against, so the guard stays quiet
	assert bootstrap._is_full_run(_config([], testpaths=[])) is False


def test_the_floor_is_set_and_plausible():
	assert bootstrap.MIN_PASSING_TESTS >= 600, "the floor must not be lowered to make a run pass"
