"""Supplier: named by ``supplier_name`` (Buying Settings ``supp_master_name`` default)."""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document


class Supplier(Document):
	def autoname(self) -> None:
		import frappe
		from frappe.model.naming import set_name_by_naming_series

		if frappe.defaults.get_global_default("supp_master_name") == "Naming Series":
			set_name_by_naming_series(self)
		else:
			if not self.supplier_name:
				raise ValidationError("Supplier Name is mandatory")
			self.name = self.supplier_name.strip()

	def validate(self) -> None:
		if not self.supplier_type:
			self.supplier_type = "Company"
		if self.supplier_name:
			self.supplier_name = self.supplier_name.strip()
