"""Company (erpnext/setup/doctype/company/company.py, version-16), the parts provisioning hits.

``validate_abbr`` (derived from the name when empty, must be unique), ``on_update``
creating the Standard chart unless ``frappe.local.flags.ignore_chart_of_accounts`` is
set (the stub raises NotImplementedError there: the Standard template is not shipped),
``create_default_warehouses`` (the five warehouses, ``ignore_mandatory``) and
``create_default_cost_center`` (company group + "Main", then the three cost-center
defaults via ``db_set``).
"""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document


class Company(Document):
	def validate(self) -> None:
		import frappe

		self.validate_abbr()
		if self.default_currency and frappe.db.table("Currency") and not frappe.db.exists("Currency", self.default_currency):
			raise ValidationError(f"Currency {self.default_currency} does not exist")

	def validate_abbr(self) -> None:
		import frappe

		if not self.abbr:
			self.abbr = "".join(c[0] for c in self.company_name.split()).upper()
		self.abbr = self.abbr.strip()
		if not self.abbr.strip():
			raise ValidationError("Abbreviation is mandatory")
		if frappe.db.exists("Company", {"name": ["!=", self.name], "abbr": self.abbr}):
			raise ValidationError("Abbreviation already used for another company")

	def on_update(self) -> None:
		import frappe

		if not frappe.db.exists("Account", {"company": self.name, "docstatus": ["<", 2]}):
			if not frappe.local.flags.ignore_chart_of_accounts:
				raise NotImplementedError(
					"frappe stub: ERPNext would create the Standard chart of accounts here; the template is not shipped. "
					"Set frappe.local.flags.ignore_chart_of_accounts = True around Company.insert() and call "
					"create_charts(company, custom_chart=...) like nyabo_mn.setup.provision_company does."
				)
		if not frappe.db.get_value("Cost Center", {"is_group": 0, "company": self.name}):
			self.create_default_cost_center()

	def create_default_warehouses(self) -> None:
		import frappe

		parent_warehouse = None
		for wh_detail in [
			{"warehouse_name": "All Warehouses", "is_group": 1},
			{"warehouse_name": "Stores", "is_group": 0},
			{"warehouse_name": "Work In Progress", "is_group": 0},
			{"warehouse_name": "Finished Goods", "is_group": 0},
			{"warehouse_name": "Goods In Transit", "is_group": 0, "warehouse_type": "Transit"},
		]:
			if frappe.db.exists("Warehouse", {"warehouse_name": wh_detail["warehouse_name"], "company": self.name}):
				continue
			warehouse = frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": wh_detail["warehouse_name"],
					"is_group": wh_detail["is_group"],
					"company": self.name,
					"parent_warehouse": parent_warehouse,
					"warehouse_type": wh_detail.get("warehouse_type"),
				}
			)
			warehouse.flags.ignore_permissions = True
			warehouse.flags.ignore_mandatory = True
			warehouse.flags.ignore_inventory_account_validation = True
			warehouse.insert()
			if wh_detail["is_group"]:
				parent_warehouse = warehouse.name

	def create_default_cost_center(self) -> None:
		import frappe

		cc_list = [
			{"cost_center_name": self.name, "company": self.name, "is_group": 1, "parent_cost_center": None},
			{"cost_center_name": "Main", "company": self.name, "is_group": 0, "parent_cost_center": self.name + " - " + self.abbr},
		]
		for cc in cc_list:
			cc.update({"doctype": "Cost Center"})
			cc_doc = frappe.get_doc(cc)
			cc_doc.flags.ignore_permissions = True
			if cc.get("cost_center_name") == self.name:
				cc_doc.flags.ignore_mandatory = True
			cc_doc.insert()
		self.db_set("cost_center", "Main - " + self.abbr)
		self.db_set("round_off_cost_center", "Main - " + self.abbr)
		self.db_set("depreciation_cost_center", "Main - " + self.abbr)

	def on_trash(self) -> None:
		import frappe

		if frappe.db.exists("GL Entry", {"company": self.name}):
			raise ValidationError("Cannot delete a Company with transactions")
