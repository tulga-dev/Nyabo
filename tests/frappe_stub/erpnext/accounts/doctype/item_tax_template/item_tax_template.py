"""Item Tax Template: ``<title> - <abbr>``; each row's tax_type must be a ledger of the company."""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document


class ItemTaxTemplate(Document):
	def autoname(self) -> None:
		import frappe

		if self.company and self.title:
			abbr = frappe.get_cached_value("Company", self.company, "abbr")
			self.name = f"{self.title} - {abbr}"

	def validate(self) -> None:
		import frappe

		if not self.taxes:
			raise ValidationError("Taxes table cannot be empty")
		seen: set[str] = set()
		for row in self.taxes:
			account = frappe.db.get_value("Account", row.tax_type, ["is_group", "company"], as_dict=True)
			if account and account.is_group:
				raise ValidationError(
					f"Item Tax Row {row.idx} must have account of type Tax or Income or Expense or Chargeable"
				)
			if account and self.company and account.company != self.company:
				raise ValidationError(f"Account {row.tax_type} does not belong to company {self.company}")
			if row.tax_type in seen:
				raise ValidationError(f"{row.tax_type} entered twice in Item Tax")
			seen.add(row.tax_type)
