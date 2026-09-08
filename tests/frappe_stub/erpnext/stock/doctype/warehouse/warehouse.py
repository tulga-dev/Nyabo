"""Warehouse: ``<warehouse_name> - <abbr>`` (erpnext/stock/doctype/warehouse/warehouse.py)."""

from __future__ import annotations

from frappe.model.document import Document


class Warehouse(Document):
	def autoname(self) -> None:
		import frappe

		if self.company:
			suffix = " - " + frappe.get_cached_value("Company", self.company, "abbr")
			if not self.warehouse_name.endswith(suffix):
				self.name = self.warehouse_name + suffix
				return
		self.name = self.warehouse_name
