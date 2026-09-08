"""Nyabo Bank Layout: validation of the column mapping an admin or the bot saves.

A wrong column map silently swaps debits and credits, so the row is checked on every
save: JSON fields must parse, roles must be known, date and narrative columns must be
present, the amount style must match the mapped columns, date formats must be valid
strftime patterns, and a placeholder (no signature, no columns) can never be verified.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import frappe
from frappe.model.document import Document

from nyabo_mn.core.statements import AMOUNT_STYLES, COLUMN_ROLES
from nyabo_mn.i18n import mn


def _parse_json(value: Any, field: str) -> Any:
	if value in (None, ""):
		return None
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		frappe.throw(mn.MSG_LAYOUT_BAD_JSON.format(field=field))
	return None


class NyaboBankLayout(Document):
	def validate(self) -> None:
		signature = _parse_json(self.header_signature_json, "header_signature_json") or []
		column_map = _parse_json(self.column_map_json, "column_map_json") or {}
		keywords = _parse_json(self.keywords_json, "keywords_json") or {}
		self._validate_roles(column_map, keywords)
		self._validate_amount_style(column_map)
		self._validate_date_formats()
		if self.verified and not keywords and (not signature or not column_map):
			frappe.throw(mn.MSG_LAYOUT_VERIFY_NEEDS_COLUMNS)
		# Store canonical JSON so header texts compare the same way everywhere.
		if signature:
			self.header_signature_json = json.dumps(list(signature), ensure_ascii=False)
		if column_map:
			self.column_map_json = json.dumps(dict(column_map), ensure_ascii=False)

	def _validate_roles(self, column_map: Any, keywords: Any) -> None:
		if not isinstance(column_map, dict):
			frappe.throw(mn.MSG_LAYOUT_BAD_JSON.format(field="column_map_json"))
		for role in list(column_map) + list(keywords or {}):
			if role not in COLUMN_ROLES:
				frappe.throw(mn.MSG_LAYOUT_ROLE_UNKNOWN.format(role=role, roles=", ".join(COLUMN_ROLES)))
		if column_map and ("date" not in column_map or "description" not in column_map):
			frappe.throw(mn.MSG_LAYOUT_NEEDS_DATE_DESCRIPTION)

	def _validate_amount_style(self, column_map: dict[str, Any]) -> None:
		style = self.amount_style or "separate_debit_credit"
		if style not in AMOUNT_STYLES:
			frappe.throw(mn.MSG_LAYOUT_AMOUNT_STYLE_MISMATCH.format(style=style))
		if not column_map:
			return
		if style == "signed_amount" and "amount" not in column_map:
			frappe.throw(mn.MSG_LAYOUT_AMOUNT_STYLE_MISMATCH.format(style=style))
		if style == "separate_debit_credit" and "debit" not in column_map and "credit" not in column_map:
			frappe.throw(mn.MSG_LAYOUT_AMOUNT_STYLE_MISMATCH.format(style=style))

	def _validate_date_formats(self) -> None:
		probe = dt.datetime(2026, 1, 31, 12, 30)
		for fmt in (self.date_formats or "").splitlines():
			fmt = fmt.strip()
			if not fmt:
				continue
			try:
				rendered = probe.strftime(fmt)
				dt.datetime.strptime(rendered, fmt)
			except (ValueError, TypeError):
				frappe.throw(mn.MSG_LAYOUT_BAD_DATE_FORMAT.format(fmt=fmt))
