"""Dated tax parameters from Nyabo Tax Parameter rows.

`get(key, on_date)` is the only way code reads a rate or a threshold: it passes the
transaction date to `core.rules_engine.resolve_parameter`, which refuses (never falls
back) when no row, two rows or a pending row covers the date. Rows are read once per
request (`frappe.local`) because a receipt pipeline asks for several keys in a row.

Unverified rows are refused by default through `rules.guard`; callers that only display
a value (a card, a checklist) pass `allow_unverified=True`. Tests and the simulator set
`frappe.flags.nyabo_simulation` instead.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from typing import Any

import frappe

from nyabo_mn.core.rules_engine import ParameterRow, resolve_parameter
from nyabo_mn.log import log_event
from nyabo_mn.nyabo.seed import load_seed
from nyabo_mn.rules import guard

DOCTYPE = "Nyabo Tax Parameter"
_CACHE_ATTR = "nyabo_tax_parameter_rows"
FIELDS = (
	"name",
	"key",
	"value_json",
	"unit",
	"effective_from",
	"effective_to",
	"status",
	"verified",
	"source_text",
	"source_url",
	"article",
	"note",
)


def decode_value(value_json: Any) -> Any:
	"""value_json is stored as JSON text; `null` and an empty field both mean "no value"."""
	if value_json in (None, ""):
		return None
	if isinstance(value_json, str):
		return json.loads(value_json)
	return value_json


def row_from_doc(data: Any) -> ParameterRow:
	"""A DocType row (dict or Document) as the core dataclass."""
	# frappe._dict answers every attribute with None, so test for a callable, not for presence.
	values = dict(data.as_dict()) if callable(getattr(data, "as_dict", None)) else dict(data)
	values["value"] = decode_value(values.get("value_json"))
	values.pop("value_json", None)
	return ParameterRow.from_dict(values)


def load_rows(*, refresh: bool = False) -> list[ParameterRow]:
	"""Every Nyabo Tax Parameter row, cached on frappe.local for the request.

	A site whose rows were never synced (install hook not run yet) reads the seed file
	directly and logs it: the data is the same, but the admin cannot have verified
	anything, so every row is unverified and the guard refuses real postings.
	"""
	cached = getattr(frappe.local, _CACHE_ATTR, None)
	if cached is not None and not refresh:
		return cached
	rows: list[ParameterRow] = []
	if frappe.db.exists("DocType", DOCTYPE):
		rows = [row_from_doc(r) for r in frappe.get_all(DOCTYPE, fields=list(FIELDS))]
	if not rows:
		log_event("rules.params.seed_fallback", level="warning", doctype=DOCTYPE)
		rows = [ParameterRow.from_dict(r) for r in load_seed("tax_parameters")["rows"]]
	setattr(frappe.local, _CACHE_ATTR, rows)
	return rows


def clear_cache() -> None:
	"""Called by the Tax Parameter controller after a save so a request sees its own edit."""
	if hasattr(frappe.local, _CACHE_ATTR):
		delattr(frappe.local, _CACHE_ATTR)


def get(key: str, on_date: dt.date, *, allow_unverified: bool = False) -> ParameterRow:
	"""The row of `key` in force on `on_date` (raises MissingRuleError / PendingRuleError / AmbiguousRuleError).

	With `allow_unverified=False` an unverified row raises UnverifiedRuleError unless the
	simulation flag is set (see rules.guard).
	"""
	row = resolve_parameter(load_rows(), key, on_date)
	if not allow_unverified:
		guard.require_verified(row)
	return row


def get_decimal(key: str, on_date: dt.date, *, allow_unverified: bool = False) -> Decimal:
	"""Numeric parameters (rates as fractions, thresholds as tögrög)."""
	return get(key, on_date, allow_unverified=allow_unverified).as_decimal()


def history(key: str) -> list[ParameterRow]:
	"""All rows of a key, oldest first (for the admin checklist and the eval reports)."""
	return sorted((r for r in load_rows() if r.key == key), key=lambda r: r.effective_from)
