"""``frappe.model.docstatus.DocStatus``: an int with the three predicates Frappe adds."""

from __future__ import annotations


class DocStatus(int):
	DRAFT = 0
	SUBMITTED = 1
	CANCELLED = 2

	def is_draft(self) -> bool:
		return self == DocStatus.DRAFT

	def is_submitted(self) -> bool:
		return self == DocStatus.SUBMITTED

	def is_cancelled(self) -> bool:
		return self == DocStatus.CANCELLED

	@classmethod
	def draft(cls) -> DocStatus:
		return cls(cls.DRAFT)

	@classmethod
	def submitted(cls) -> DocStatus:
		return cls(cls.SUBMITTED)

	@classmethod
	def cancelled(cls) -> DocStatus:
		return cls(cls.CANCELLED)
