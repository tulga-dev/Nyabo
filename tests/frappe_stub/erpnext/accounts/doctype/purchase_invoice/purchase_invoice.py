"""Purchase Invoice (erpnext/accounts/doctype/purchase_invoice/purchase_invoice.py, version-16).

Defaults the way ``set_missing_values`` does for a plain service invoice: currency and
rate from the company, ``credit_to`` from ``Company.default_payable_account``,
``expense_account`` from ``Company.default_expense_account``, ``supplier_name`` from the
Supplier. Submit writes GL Entry rows: ``expense_account`` debit per item,
``account_head`` debit (Add) / credit (Deduct) per tax row, ``credit_to`` credit for the
grand total against the Supplier. Cancel reverses them. Status follows ``set_status``
(Unpaid / Return / Debit Note Issued / Cancelled). ``make_debit_note`` delegates to
``make_return_doc`` as in the source.
"""

from __future__ import annotations

from typing import Any

from frappe._stub.dictlike import _dict
from frappe.exceptions import ValidationError
from frappe.utils.data import flt

from erpnext.controllers.accounts_controller import AccountsController


class PurchaseInvoice(AccountsController):
	def validate(self) -> None:
		if not self.items:
			raise ValidationError("Items table cannot be blank.")
		self.set_missing_values()
		self.calculate_taxes_and_totals()
		self.validate_return()
		if int(self.is_paid or 0) == 1:
			self.validate_cash()
			self.set_paid_amounts()
		self.set_status()

	def validate_cash(self) -> None:
		"""erpnext PurchaseInvoice.validate_cash (version-16), called from validate when is_paid."""
		if not self.cash_bank_account and flt(self.paid_amount):
			raise ValidationError("Cash or Bank Account is mandatory")
		if flt(self.paid_amount) + flt(self.write_off_amount) - flt(
			self.get("rounded_total") or self.grand_total
		) > 1 / (10 ** (self.precision("base_grand_total") + 1)):
			raise ValidationError("Paid amount + Write Off Amount cannot exceed Grand Total")

	def set_paid_amounts(self) -> None:
		"""Stub reduction of calculate_taxes_and_totals' paid-amount branch: base_paid_amount and
		outstanding follow paid_amount so a cash/bank-paid invoice shows as Paid after submit."""
		self.base_paid_amount = flt(flt(self.paid_amount) * flt(self.conversion_rate), self.precision("base_paid_amount"))
		if self.docstatus == 0:
			self.outstanding_amount = flt(
				flt(self.outstanding_amount) - flt(self.base_paid_amount), self.precision("outstanding_amount")
			)

	def set_missing_values(self) -> None:
		import frappe

		if not self.company:
			raise ValidationError("Company is mandatory")
		self.set_missing_currency_values()
		if not self.supplier_name:
			self.supplier_name = frappe.db.get_value("Supplier", self.supplier, "supplier_name")
		if not self.credit_to:
			self.credit_to = self.get_company_default("default_payable_account")
		if not self.party_account_currency:
			self.party_account_currency = self.company_currency
		if not self.cost_center:
			self.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		default_expense = frappe.get_cached_value("Company", self.company, "default_expense_account")
		for item in self.items:
			if not item.expense_account:
				if not default_expense:
					raise ValidationError(
						f"Row {item.idx}: Expense Account is mandatory (no default on Company {self.company})"
					)
				item.expense_account = default_expense
			if not item.cost_center:
				item.cost_center = self.cost_center
		for tax in self.taxes:
			if not tax.category:
				tax.category = "Total"
			if not tax.add_deduct_tax:
				tax.add_deduct_tax = "Add"
			if not tax.charge_type:
				tax.charge_type = "On Net Total"
			if not tax.description:
				tax.description = tax.account_head
			if not tax.cost_center:
				tax.cost_center = self.cost_center
		self.against_expense_account = ", ".join(dict.fromkeys(i.expense_account for i in self.items))
		if not self.title:
			self.title = self.supplier_name or self.supplier

	def validate_return(self) -> None:
		import frappe

		if self.is_return and self.return_against:
			original = frappe.db.get_value(
				"Purchase Invoice", self.return_against, ["docstatus", "supplier", "company"], as_dict=True
			)
			if not original:
				raise ValidationError(f"Return Against Purchase Invoice {self.return_against} does not exist")
			if int(original.docstatus) != 1:
				raise ValidationError(
					f"Return Against Purchase Invoice {self.return_against} must be submitted"
				)
			if original.supplier != self.supplier or original.company != self.company:
				raise ValidationError(
					f"Return Against Purchase Invoice {self.return_against} belongs to another party"
				)
			if flt(self.grand_total) > 0:
				raise ValidationError("A return (Debit Note) must have a negative grand total")

	def set_status(
		self, update: bool = False, status: str | None = None, update_modified: bool = True
	) -> None:
		import frappe

		if status:
			self.status = status
		elif int(self.docstatus) == 2:
			self.status = "Cancelled"
		elif int(self.docstatus) == 1:
			if self.is_return == 0 and frappe.db.get_value(
				"Purchase Invoice", {"is_return": 1, "return_against": self.name, "docstatus": 1}
			):
				self.status = "Debit Note Issued"
			elif self.is_return == 1:
				self.status = "Return"
			elif flt(self.outstanding_amount) <= 0:
				self.status = "Paid"
			else:
				self.status = "Unpaid"
		else:
			self.status = "Draft"
		if update:
			self.db_set("status", self.status, update_modified=update_modified)

	def on_submit(self) -> None:
		import frappe

		self.make_gl_entries()
		self.set_status(update=True)
		if self.is_return and self.return_against:
			original = frappe.get_doc("Purchase Invoice", self.return_against)
			original.set_status(update=True)

	def on_cancel(self) -> None:
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		self.make_gl_entries()
		self.set_status(update=True)

	def get_gl_entries(self) -> list[_dict]:
		gl_entries: list[_dict] = []
		self.make_supplier_gl_entry(gl_entries)
		self.make_item_gl_entries(gl_entries)
		self.make_tax_gl_entries(gl_entries)
		self.make_payment_gl_entries(gl_entries)
		return gl_entries

	def make_payment_gl_entries(self, gl_entries: list[_dict]) -> None:
		"""erpnext PurchaseInvoice.make_payment_gl_entries (version-16): a paid invoice credits the
		cash/bank account and debits the payable, which is what bank reconciliation allocates."""
		from erpnext.accounts.utils import get_account_currency

		if not (int(self.is_paid or 0) and self.cash_bank_account and flt(self.paid_amount)):
			return
		against_voucher = self.name
		if self.is_return and self.return_against and not self.update_outstanding_for_self:
			against_voucher = self.return_against
		bank_account_currency = get_account_currency(self.cash_bank_account)
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.credit_to,
					"party_type": "Supplier",
					"party": self.supplier,
					"against": self.cash_bank_account,
					"debit": self.base_paid_amount,
					"debit_in_account_currency": self.base_paid_amount
					if self.party_account_currency == self.company_currency
					else self.paid_amount,
					"debit_in_transaction_currency": self.paid_amount,
					"against_voucher": against_voucher,
					"against_voucher_type": self.doctype,
					"cost_center": self.cost_center,
					"project": self.project,
				},
				self.party_account_currency,
				item=self,
			)
		)
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.cash_bank_account,
					"against": self.supplier,
					"credit": self.base_paid_amount,
					"credit_in_account_currency": self.base_paid_amount
					if bank_account_currency == self.company_currency
					else self.paid_amount,
					"credit_in_transaction_currency": self.paid_amount,
					"cost_center": self.cost_center,
				},
				bank_account_currency,
				item=self,
			)
		)

	def make_supplier_gl_entry(self, gl_entries: list[_dict]) -> None:
		grand_total = self.grand_total
		base_grand_total = flt(self.base_grand_total, self.precision("base_grand_total"))
		if grand_total:
			against_voucher = self.name
			if self.is_return and self.return_against and not self.update_outstanding_for_self:
				against_voucher = self.return_against
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": self.credit_to,
						"party_type": "Supplier",
						"party": self.supplier,
						"due_date": self.due_date,
						"against": self.against_expense_account,
						"credit": base_grand_total,
						"credit_in_account_currency": base_grand_total
						if self.party_account_currency == self.company_currency
						else grand_total,
						"credit_in_transaction_currency": grand_total,
						"against_voucher": against_voucher,
						"against_voucher_type": self.doctype,
						"cost_center": self.cost_center,
					},
					self.party_account_currency,
					item=self,
				)
			)

	def make_item_gl_entries(self, gl_entries: list[_dict]) -> None:
		from erpnext.accounts.utils import get_account_currency

		if self.update_stock:
			raise NotImplementedError(
				"frappe stub: Purchase Invoice with update_stock (stock GL) is not implemented"
			)
		for item in self.items:
			if not flt(item.base_net_amount):
				continue
			account_currency = get_account_currency(item.expense_account)
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": item.expense_account,
						"against": self.supplier,
						"debit": flt(item.base_net_amount, item.precision("base_net_amount")),
						"debit_in_transaction_currency": flt(item.net_amount, item.precision("net_amount")),
						"cost_center": item.cost_center,
						"project": item.project,
					},
					account_currency,
					item=item,
				)
			)

	def make_tax_gl_entries(self, gl_entries: list[_dict]) -> None:
		from erpnext.accounts.utils import get_account_currency

		for tax in self.taxes:
			base_amount = flt(tax.base_tax_amount_after_discount_amount)
			if tax.category in ("Total", "Valuation and Total") and base_amount:
				account_currency = get_account_currency(tax.account_head)
				dr_or_cr = "debit" if tax.add_deduct_tax == "Add" else "credit"
				gl_entries.append(
					self.get_gl_dict(
						{
							"account": tax.account_head,
							"against": self.supplier,
							dr_or_cr: base_amount,
							dr_or_cr + "_in_account_currency": base_amount
							if account_currency == self.company_currency
							else flt(tax.tax_amount_after_discount_amount),
							dr_or_cr + "_in_transaction_currency": flt(tax.tax_amount_after_discount_amount),
							"cost_center": tax.cost_center,
						},
						account_currency,
						item=tax,
					)
				)


def make_debit_note(source_name: str, target_doc: Any = None) -> Any:
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	return make_return_doc("Purchase Invoice", source_name, target_doc)
