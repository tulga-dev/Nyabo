"""Nyabo Rule: "this supplier / this description / this amount band -> this account".

Validation keeps a rule from silently never matching or from matching everything: a
pattern rule needs a value that compiles when it looks like a regex, an amount band
needs a coherent range, and a learned rule must remember the corrections it came from
(the accountant confirming it wants to see why it exists).
"""

from __future__ import annotations

import re

from frappe.model.document import Document

PATTERN_TYPES = ("supplier_name_pattern", "description_pattern", "bank_fee")
VALUE_TYPES = ("supplier_register_no",) + PATTERN_TYPES


class NyaboRule(Document):
	def validate(self) -> None:
		from frappe import ValidationError

		match_type = self.match_type
		value = (self.match_value or "").strip()
		if match_type in VALUE_TYPES and not value:
			raise ValidationError(f"Nyabo Rule: match_type {match_type} needs a match_value")
		if match_type in PATTERN_TYPES and _looks_like_regex(value):
			try:
				re.compile(value, re.IGNORECASE)
			except re.error as exc:
				raise ValidationError(f"Nyabo Rule: match_value is not a valid pattern: {exc}") from exc
		if match_type == "amount_band":
			low = float(self.amount_min or 0)
			high = float(self.amount_max or 0)
			if low <= 0 and high <= 0:
				raise ValidationError("Nyabo Rule: amount_band needs amount_min and/or amount_max")
			if high and low > high:
				raise ValidationError("Nyabo Rule: amount_min must not exceed amount_max")
		if self.source == "learned" and not self.created_from_corrections:
			raise ValidationError("Nyabo Rule: a learned rule must list created_from_corrections")
		if not self.status:
			self.status = "pending_confirmation" if self.source == "learned" else "active"


def _looks_like_regex(value: str) -> bool:
	return any(ch in value for ch in "|()[]*+?^$\\")
