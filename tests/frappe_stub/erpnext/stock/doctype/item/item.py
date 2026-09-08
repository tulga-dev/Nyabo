"""Item: named by ``item_code`` (Stock Settings ``item_naming_by`` default "Item Code")."""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document


class Item(Document):
	def autoname(self) -> None:
		import frappe
		from frappe.model.naming import set_name_by_naming_series

		if frappe.defaults.get_global_default("item_naming_by") == "Naming Series":
			set_name_by_naming_series(self)
			self.item_code = self.name
		else:
			if not self.item_code:
				raise ValidationError("Item Code is mandatory because Item is not automatically numbered")
			self.item_code = self.item_code.strip()
			self.name = self.item_code

	def validate(self) -> None:
		if not self.item_name:
			self.item_name = self.item_code
		if not self.stock_uom:
			self.stock_uom = "Nos"
		if not self.item_group:
			self.item_group = "All Item Groups"
