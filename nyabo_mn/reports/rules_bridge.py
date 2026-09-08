"""Tax-parameter rows and the verified guard for the report side.

The rules package (``nyabo_mn.rules.params`` / ``nyabo_mn.rules.guard``) is owned by the
core+rules stage. Until it lands, this module reads Nyabo Tax Parameter rows itself
(falling back to the shipped seed before the first sync) and raises a local
``UnverifiedRuleError``; when the rules package exists its error class is reused so
callers catching either name behave the same. INTEGRATION: replace with the rules API.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import frappe

from nyabo_mn.core.rules_engine import ParameterRow, resolve_parameter
from nyabo_mn.i18n import mn
from nyabo_mn.nyabo.seed import load_seed

try:  # the rules stage defines the canonical class; reuse it when present
	from nyabo_mn.rules.guard import UnverifiedRuleError  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on which stage is merged

	class UnverifiedRuleError(frappe.ValidationError):  # type: ignore[no-redef]
		"""An unverified rule was about to drive a real posting or a statutory figure."""


def tax_parameter_rows(key: str) -> list[ParameterRow]:
	"""Rows of one key: the DocType table when synced, else the seed file (same shape)."""
	rows: list[ParameterRow] = []
	if frappe.db.exists("DocType", "Nyabo Tax Parameter"):
		for row in frappe.get_all(
			"Nyabo Tax Parameter",
			filters={"key": key},
			fields=[
				"key",
				"value_json",
				"unit",
				"effective_from",
				"effective_to",
				"status",
				"verified",
				"article",
			],
		):
			value = row.get("value_json")
			if isinstance(value, str):
				value = frappe.parse_json(value)
			rows.append(ParameterRow.from_dict({**row, "value": value}))
	if rows:
		return rows
	return [ParameterRow.from_dict(r) for r in load_seed("tax_parameters")["rows"] if r.get("key") == key]


def parameter_on(key: str, on_date: dt.date) -> ParameterRow:
	"""The row in force on the date; rule errors surface as Mongolian ``frappe.throw``."""
	from nyabo_mn.core.rules_engine import RuleError

	try:
		return resolve_parameter(tax_parameter_rows(key), key, on_date)
	except RuleError as exc:
		frappe.throw(exc.message_mn)
		raise  # unreachable


def require_verified(row: ParameterRow, *, simulation: bool = False) -> None:
	"""Refuse an unverified parameter unless the caller is a simulation (tests, dry runs)."""
	if row.verified or simulation:
		return
	raise UnverifiedRuleError(mn.MSG_UNVERIFIED_RULE_BLOCKED.format(rule=f"{row.key}:{row.effective_from}"))


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
