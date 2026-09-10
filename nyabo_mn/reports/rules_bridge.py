"""Tax-parameter rows and the verified guard for the report side.

A thin bridge over ``nyabo_mn.rules.params`` / ``nyabo_mn.rules.guard`` that keeps the
report-side signature (``parameter_on`` throws a Mongolian ``frappe.throw`` on a rule
error). ``UnverifiedRuleError`` is the rules package's class, so callers catching either
name behave the same.

``require_verified`` takes no ``simulation`` argument (F-11): it used to, and a desk
report filter passed one, so anyone who could open the report could switch off the
verified guard on a statutory figure. The only bypass is ``frappe.flags.nyabo_simulation``
- set by the simulator and the tests, never by user input - which ``rules.guard`` reads
itself. ``is_simulation()`` is re-exported so a report can *label* a figure without being
able to change how it was guarded.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import frappe

from nyabo_mn.core.rules_engine import ParameterRow, RuleError
from nyabo_mn.rules import guard, params
from nyabo_mn.rules.guard import UnverifiedRuleError

__all__ = [
	"UnverifiedRuleError",
	"is_simulation",
	"parameter_on",
	"require_verified",
	"row_summary",
	"tax_parameter_rows",
]


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


def is_simulation() -> bool:
	"""True while ``frappe.flags.nyabo_simulation`` is set - for labelling a figure, not for guarding it."""
	return guard.is_simulation()


def require_verified(row: ParameterRow, company: str | None = None) -> None:
	"""Refuse an unverified parameter for a statutory figure (F-11).

	No caller-supplied bypass: ``rules.guard.require_verified`` decides, and its only
	exemption is ``frappe.flags.nyabo_simulation``. A number nobody checked must not reach
	a tax return because someone ticked a box on a report.

	``company`` is not a bypass either: it lets through exactly the rows *that company's own
	accountant* has accepted for their books (DECISIONS ACC-01), which is a named person on the
	record — the same standard the flag itself holds a site admin to.
	"""
	guard.require_verified(row, company=company)


def row_summary(row: ParameterRow, company: str | None = None) -> dict[str, Any]:
	"""The row as a report prints it, including *which* of the two clearances let it through.

	``verified`` alone stopped being the whole answer with DECISIONS ACC-01. The report renders
	only figures ``require_verified`` let through, so an unverified row reaching it is one this
	company's accountant accepted — and printing «Баталгаажаагүй» beside it told the reader the
	number rests on nothing, in the one artefact a tax reviewer actually reads. ``accepted`` is
	what makes the third provenance visible (VER-07); without a company it stays False, which is
	what a core-only or site-wide caller means.
	"""
	return {
		"key": row.key,
		"value": row.value,
		"unit": row.unit,
		"effective_from": row.effective_from.isoformat(),
		"effective_to": row.effective_to.isoformat() if row.effective_to else None,
		"verified": bool(row.verified),
		"accepted": bool(company) and not row.verified and guard.accepted_for(row, company),
		"source_text": row.source_text,
		"article": row.article,
	}
