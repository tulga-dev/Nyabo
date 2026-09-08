"""Nyabo Tax Parameter: one dated value of a rule key (docs/seed/README.md).

Validation guards the invariants the engine relies on: a period that ends before it
starts or overlaps another row of the same key would make `resolve_parameter` raise
AmbiguousRuleError on every posting; an active row without a value would silently
mean "zero". The admin flips `verified` here after reading the primary text.
"""

from __future__ import annotations

import json

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from nyabo_mn.i18n import mn


class NyaboTaxParameter(Document):
	def validate(self) -> None:
		self.validate_dates()
		self.validate_value()
		self.validate_no_overlap()

	def on_update(self) -> None:
		from nyabo_mn.rules import params

		params.clear_cache()

	def validate_dates(self) -> None:
		if self.effective_to and getdate(self.effective_to) < getdate(self.effective_from):
			frappe.throw(
				mn.MSG_TAX_PARAM_DATES.format(
					effective_to=self.effective_to, effective_from=self.effective_from
				)
			)

	def validate_value(self) -> None:
		"""value_json must parse; only a pending row may leave it empty (D-003)."""
		raw = self.value_json
		if isinstance(raw, str) and raw.strip():
			try:
				value = json.loads(raw)
			except ValueError as exc:
				frappe.throw(mn.MSG_TAX_PARAM_JSON_INVALID.format(error=exc))
				return
		else:
			value = raw if raw not in ("",) else None
		if value is None and (self.status or "active") != "pending":
			frappe.throw(mn.MSG_TAX_PARAM_VALUE_REQUIRED)

	def validate_no_overlap(self) -> None:
		start = getdate(self.effective_from)
		end = getdate(self.effective_to) if self.effective_to else None
		others = frappe.get_all(
			self.doctype,
			filters={"key": self.key, "name": ["!=", self.name or ""]},
			fields=["name", "effective_from", "effective_to"],
		)
		for other in others:
			other_start = getdate(other.effective_from)
			other_end = getdate(other.effective_to) if other.effective_to else None
			starts_before_other_ends = other_end is None or start <= other_end
			other_starts_before_end = end is None or other_start <= end
			if starts_before_other_ends and other_starts_before_end:
				frappe.throw(mn.MSG_TAX_PARAM_OVERLAP.format(key=self.key, other=other.name))
