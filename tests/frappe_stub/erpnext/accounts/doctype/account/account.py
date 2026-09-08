"""Account controller (erpnext/accounts/doctype/account/account.py, version-16).

Name ``<number> - <account_name> - <abbr>`` (``get_autoname_with_number``); the parent
must exist, be a group and belong to the same company; root_type / report_type are
inherited from the parent; a root must be a group; the currency defaults to the company
currency. Nested-set columns (lft/rgt) are not maintained: ``get_balance_on`` walks
``parent_account`` instead.
"""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document
from frappe.utils.data import cint

BALANCE_SHEET_ROOT_TYPES = ("Asset", "Liability", "Equity")


class RootNotEditable(ValidationError):
	pass


class BalanceMismatchError(ValidationError):
	pass


class Account(Document):
	def autoname(self) -> None:
		from erpnext.accounts.utils import get_autoname_with_number

		self.name = get_autoname_with_number(self.account_number, self.account_name, self.company)

	def validate(self) -> None:
		import frappe

		if frappe.local.flags.allow_unverified_charts:
			return
		self.validate_parent()
		self.validate_root_details()
		self.validate_group_or_ledger()
		self.set_root_and_report_type()
		self.validate_mandatory()
		self.validate_account_currency()

	def validate_parent(self) -> None:
		import frappe

		if not self.parent_account:
			return
		par = frappe.get_cached_value("Account", self.parent_account, ["name", "is_group", "company"], as_dict=1)
		if not par:
			raise ValidationError(f"Account {self.name}: Parent account {self.parent_account} does not exist")
		if par.name == self.name:
			raise ValidationError(f"Account {self.name}: You can not assign itself as parent account")
		if not par.is_group:
			raise ValidationError(f"Account {self.name}: Parent account {self.parent_account} can not be a ledger")
		if par.company != self.company:
			raise ValidationError(
				f"Account {self.name}: Parent account {self.parent_account} does not belong to company: {self.company}"
			)

	def validate_root_details(self) -> None:
		before = self.get_doc_before_save()
		if before and not before.parent_account:
			raise RootNotEditable("Root cannot be edited.")
		if not self.parent_account and not cint(self.is_group):
			raise ValidationError(f"The root account <b>{self.name}</b> must be a group")

	def validate_group_or_ledger(self) -> None:
		import frappe

		before = self.get_doc_before_save()
		if not before or cint(before.is_group) == cint(self.is_group):
			return
		if frappe.db.exists("GL Entry", {"account": self.name}):
			raise ValidationError("Account with existing transaction cannot be converted to ledger")
		if not cint(self.is_group) and frappe.db.exists("Account", {"parent_account": self.name}):
			raise ValidationError("Account with child nodes cannot be set as ledger")

	def set_root_and_report_type(self) -> None:
		import frappe

		if self.parent_account:
			par = frappe.get_cached_value("Account", self.parent_account, ["report_type", "root_type"], as_dict=1)
			if par.report_type:
				self.report_type = par.report_type
			if par.root_type:
				self.root_type = par.root_type
		if self.root_type and not self.report_type:
			self.report_type = "Balance Sheet" if self.root_type in BALANCE_SHEET_ROOT_TYPES else "Profit and Loss"

	def validate_mandatory(self) -> None:
		if not self.root_type:
			raise ValidationError("Root Type is mandatory")
		if not self.report_type:
			raise ValidationError("Report Type is mandatory")

	def validate_account_currency(self) -> None:
		import frappe

		if not self.account_currency:
			self.account_currency = frappe.get_cached_value("Company", self.company, "default_currency")
		gl_currency = frappe.db.get_value("GL Entry", {"account": self.name, "is_cancelled": 0}, "account_currency")
		if gl_currency and self.account_currency != gl_currency:
			raise ValidationError("Currency can not be changed after making entries using some other currency")

	def on_trash(self) -> None:
		import frappe

		if frappe.db.exists("GL Entry", {"account": self.name}):
			raise ValidationError("Account with existing transaction can not be deleted")
		if frappe.db.exists("Account", {"parent_account": self.name}):
			raise ValidationError("Child accounts exist for this account. You can not delete this account.")


def get_account_currency(account: str | None) -> str | None:
	from erpnext.accounts.utils import get_account_currency as _get

	return _get(account)
