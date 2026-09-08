"""Customer: named by ``customer_name`` (Selling Settings ``cust_master_name`` default)."""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document


class Customer(Document):
	def autoname(self) -> None:
		import frappe
		from frappe.model.naming import set_name_by_naming_series

		if frappe.defaults.get_global_default("cust_master_name") == "Naming Series":
			set_name_by_naming_series(self)
		else:
			if not self.customer_name:
				raise ValidationError("Customer Name is mandatory")
			self.name = self.customer_name.strip()

	def validate(self) -> None:
		if not self.customer_type:
			self.customer_type = "Company"
		if self.customer_name:
			self.customer_name = self.customer_name.strip()
