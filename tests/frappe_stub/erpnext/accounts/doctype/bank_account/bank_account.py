"""Bank Account (erpnext/accounts/doctype/bank_account/bank_account.py): ``<account_name> - <bank>``."""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document


class BankAccount(Document):
	def autoname(self) -> None:
		self.name = self.account_name + " - " + self.bank

	def validate(self) -> None:
		self.validate_is_company_account()

	def validate_is_company_account(self) -> None:
		import frappe

		if self.is_company_account:
			if not self.company:
				raise ValidationError("Company is mandatory for company account")
			if not self.account:
				raise ValidationError("Company Account is mandatory")
			account = frappe.db.get_value("Account", self.account, ["company", "is_group"], as_dict=True)
			if account and account.company != self.company:
				raise ValidationError(f"Account {self.account} does not belong to company {self.company}")
