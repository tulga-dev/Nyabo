"""Tax-parameter rows and the verified guard for the report side.

A thin bridge over ``nyabo_mn.rules.params`` / ``nyabo_mn.rules.guard`` that keeps the
report-side signatures (``parameter_on`` throws a Mongolian ``frappe.throw`` on a rule
error; ``require_verified`` takes an explicit ``simulation`` flag for the report filter).
``UnverifiedRuleError`` is the rules package's class, so callers catching either name
behave the same.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import frappe

from nyabo_mn.core.rules_engine import ParameterRow, RuleError
from nyabo_mn.rules import guard, params
from nyabo_mn.rules.guard import UnverifiedRuleError

__all__ = ["UnverifiedRuleError", "parameter_on", "require_verified", "row_summary", "tax_parameter_rows"]


def tax_parameter_rows(key: str) -> list[ParameterRow]:
	"""Rows of one key: the DocType table when synced, else the seed file (``rules.params.load_rows``)."""
	return [row for row in params.load_rows() if row.key == key]


def parameter_on(key: str, on_date: dt.date) -> ParameterRow:
	"""The row in force on the date; rule errors surface as Mongolian ``frappe.throw``.

	The verified check is left to ``require_verified`` so a report can show an unverified
	figure under the Simulation label.
	"""
	try:
		return params.get(key, on_date, allow_unverified=True)
	except RuleError as exc:
		frappe.throw(exc.message_mn)
		raise  # unreachable


def require_verified(row: ParameterRow, *, simulation: bool = False) -> None:
	"""Refuse an unverified parameter unless the caller is a simulation (the report filter, dry runs).

	``rules.guard.require_verified`` also honours ``frappe.flags.nyabo_simulation`` (tests,
	the simulator).
	"""
	if simulation:
		return
	guard.require_verified(row)


def row_summary(row: ParameterRow) -> dict[str, Any]:
	return {
		"key": row.key,
		"value": row.value,
		"unit": row.unit,
		"effective_from": row.effective_from.isoformat(),
		"effective_to": row.effective_to.isoformat() if row.effective_to else None,
		"verified": bool(row.verified),
		"source_text": row.source_text,
		"article": row.article,
	}
