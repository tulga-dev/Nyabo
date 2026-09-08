"""Flow tests never reach a model: the simulation flag makes every client the fixture mock.

The stub's site config carries a placeholder ``openai_api_key`` for the modules that test
key handling, so auto-detection alone would try to build a real client here.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _simulation_flag() -> Iterator[None]:
	try:
		import frappe
	except ImportError:  # pure-Python run without the stub on the path
		yield
		return
	previous = frappe.local.flags.get("nyabo_simulation")
	frappe.local.flags.nyabo_simulation = True
	try:
		yield
	finally:
		if previous is None:
			frappe.local.flags.pop("nyabo_simulation", None)
		else:
			frappe.local.flags.nyabo_simulation = previous
