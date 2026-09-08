"""Nyabo Posting Pattern: an entry shape from Заавар 116 with its lines and citation.

A pattern without both a debit and a credit line can never produce a balanced entry,
and one without document types can never be selected, so both are refused at save.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from nyabo_mn.i18n import mn


class NyaboPostingPattern(Document):
	def validate(self) -> None:
		sides = {(row.side or "").strip() for row in self.lines or []}
		if not {"debit", "credit"} <= sides:
			frappe.throw(mn.MSG_PATTERN_NEEDS_BOTH_SIDES)
		doc_types = [
			d.strip() for d in (self.document_types or "").replace("\n", ",").split(",") if d.strip()
		]
		if not doc_types:
			frappe.throw(mn.MSG_PATTERN_NEEDS_DOCUMENT_TYPES)
		self.document_types = ", ".join(doc_types)

	def on_update(self) -> None:
		from nyabo_mn.rules import patterns

		patterns.clear_cache()
