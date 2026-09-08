"""Cost Center: ``<number> - <name> - <abbr>`` like Account (erpnext/accounts/doctype/cost_center)."""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document


class CostCenter(Document):
	def autoname(self) -> None:
		from erpnext.accounts.utils import get_autoname_with_number

		self.name = get_autoname_with_number(self.cost_center_number, self.cost_center_name, self.company)

	def validate(self) -> None:
		import frappe

		if self.parent_cost_center:
			parent = frappe.db.get_value("Cost Center", self.parent_cost_center, ["is_group", "company"], as_dict=True)
			if not parent:
				raise ValidationError(f"Parent Cost Center {self.parent_cost_center} does not exist")
			if not parent.is_group:
				raise ValidationError(f"Parent Cost Center {self.parent_cost_center} is not a group")
			if parent.company != self.company:
				raise ValidationError(f"Parent Cost Center {self.parent_cost_center} belongs to another company")
