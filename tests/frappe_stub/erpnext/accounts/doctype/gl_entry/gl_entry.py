"""GL Entry controller: the account checks of erpnext/accounts/doctype/gl_entry/gl_entry.py.

``validate_account_details`` refuses group accounts, cancelled (docstatus 2) accounts and
accounts of another company with ERPNext's wording; a GL Entry cannot be deleted.
"""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document
from frappe.utils.data import flt


class GLEntry(Document):
	def validate(self) -> None:
		self.validate_account_details()
		self.validate_amounts()

	def validate_account_details(self) -> None:
		"""Account must be ledger, active and not freezed"""
		import frappe

		account = frappe.get_cached_value("Account", self.account, fieldname=["is_group", "docstatus", "company", "disabled"], as_dict=True)
		if not account:
			raise ValidationError(f"{self.voucher_type} {self.voucher_no}: Account {self.account} does not exist")
		if account.is_group == 1:
			raise ValidationError(
				f"{self.voucher_type} {self.voucher_no}: Account {self.account} is a Group Account and group accounts cannot be used in transactions"
			)
		if account.docstatus == 2:
			raise ValidationError(f"{self.voucher_type} {self.voucher_no}: Account {self.account} is inactive")
		if account.company != self.company:
			raise ValidationError(
				f"{self.voucher_type} {self.voucher_no}: Account {self.account} does not belong to Company {self.company}"
			)
		if account.disabled:
			raise ValidationError(f"{self.voucher_type} {self.voucher_no}: Account {self.account} is disabled")

	def validate_amounts(self) -> None:
		if flt(self.debit) and flt(self.credit):
			raise ValidationError(f"{self.voucher_type} {self.voucher_no}: a GL Entry row cannot carry both debit and credit")

	def on_trash(self) -> None:
		raise ValidationError("GL Entry rows are never deleted; cancel the voucher instead")
