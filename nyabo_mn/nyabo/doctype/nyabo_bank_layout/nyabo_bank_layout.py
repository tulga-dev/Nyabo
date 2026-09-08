"""Nyabo Bank Layout: how one bank's statement export is laid out (docs/seed/README.md).

JSON columns must parse and the column map may only name the roles the parser knows;
a wrong map silently swaps debits and credits (D-008), which is why the row also
carries `verified` and the guard refuses an unverified layout for a real import.
"""

from __future__ import annotations

import json

import frappe
from frappe.model.document import Document

from nyabo_mn.i18n import mn

COLUMN_ROLES = frozenset(
	{"date", "description", "debit", "credit", "amount", "balance", "reference", "currency"}
)


class NyaboBankLayout(Document):
	def validate(self) -> None:
		signature = self._parse("header_signature_json", default=[])
		column_map = self._parse("column_map_json", default={})
		self._parse("keywords_json", default={})
		if not isinstance(signature, list):
			frappe.throw(mn.MSG_TAX_PARAM_JSON_INVALID.format(error="header_signature_json must be a list"))
		if not isinstance(column_map, dict):
			frappe.throw(mn.MSG_TAX_PARAM_JSON_INVALID.format(error="column_map_json must be an object"))
		unknown = sorted(set(column_map) - COLUMN_ROLES)
		if unknown:
			frappe.throw(mn.MSG_TAX_PARAM_JSON_INVALID.format(error=f"unknown column roles {unknown}"))

	def _parse(self, fieldname: str, default: object) -> object:
		raw = self.get(fieldname)
		if raw in (None, ""):
			return default
		if isinstance(raw, str):
			try:
				return json.loads(raw)
			except ValueError as exc:
				frappe.throw(mn.MSG_TAX_PARAM_JSON_INVALID.format(error=f"{fieldname}: {exc}"))
		return raw
