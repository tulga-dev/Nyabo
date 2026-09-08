"""Sales Taxes and Charges Template: ``<title> - <abbr>``, one default per company."""

from __future__ import annotations

from frappe.model.document import Document


class SalesTaxesandChargesTemplate(Document):
	def autoname(self) -> None:
		import frappe

		if self.company and self.title:
			abbr = frappe.get_cached_value("Company", self.company, "abbr")
			self.name = f"{self.title} - {abbr}"

	def validate(self) -> None:
		import frappe

		if self.is_default:
			for name in frappe.get_all(
				self.doctype, filters={"is_default": 1, "company": self.company, "name": ["!=", self.name]}, pluck="name"
			):
				frappe.db.set_value(self.doctype, name, "is_default", 0)
