"""Sales Invoice (erpnext/accounts/doctype/sales_invoice/sales_invoice.py, version-16).

Mirror of the Purchase Invoice stub on the income side: ``debit_to`` from
``Company.default_receivable_account`` (debit, party Customer), ``income_account`` from
``Company.default_income_account`` (credit per item), tax ``account_head`` credit; the
price-list fields ERPNext marks mandatory are defaulted ("Standard Selling", company
currency, rate 1). Status: Unpaid / Return / Credit Note Issued / Cancelled.
"""

from __future__ import annotations

from typing import Any

from frappe._stub.dictlike import _dict
from frappe.exceptions import ValidationError
from frappe.utils.data import flt

from erpnext.controllers.accounts_controller import AccountsController


class SalesInvoice(AccountsController):
	def validate(self) -> None:
		if not self.items:
			raise ValidationError("Items table cannot be blank.")
		self.set_missing_values()
		self.calculate_taxes_and_totals()
		self.validate_return()
		self.set_status()

	def set_missing_values(self) -> None:
		import frappe

		if not self.company:
			raise ValidationError("Company is mandatory")
		self.set_missing_currency_values()
		if not self.customer_name:
			self.customer_name = frappe.db.get_value("Customer", self.customer, "customer_name")
		if not self.debit_to:
			self.debit_to = self.get_company_default("default_receivable_account")
		if not self.party_account_currency:
			self.party_account_currency = self.company_currency
		if not self.selling_price_list:
			self.selling_price_list = "Standard Selling"
		if not self.price_list_currency:
			self.price_list_currency = self.currency
		if not self.plc_conversion_rate:
			self.plc_conversion_rate = 1.0
		if not self.cost_center:
			self.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		default_income = frappe.get_cached_value("Company", self.company, "default_income_account")
		for item in self.items:
			if not item.income_account:
				if not default_income:
					raise ValidationError(
						f"Row {item.idx}: Income Account is mandatory (no default on Company {self.company})"
					)
				item.income_account = default_income
			if not item.cost_center:
				item.cost_center = self.cost_center
		for tax in self.taxes:
			if not tax.charge_type:
				tax.charge_type = "On Net Total"
			if not tax.description:
				tax.description = tax.account_head
			if not tax.cost_center:
				tax.cost_center = self.cost_center
		self.against_income_account = ", ".join(dict.fromkeys(i.income_account for i in self.items))
		if not self.title:
			self.title = self.customer_name or self.customer

	def validate_return(self) -> None:
		import frappe

		if self.is_return and self.return_against:
			original = frappe.db.get_value(
				"Sales Invoice", self.return_against, ["docstatus", "customer"], as_dict=True
			)
			if not original or int(original.docstatus) != 1:
				raise ValidationError(
					f"Return Against Sales Invoice {self.return_against} must exist and be submitted"
				)
			if original.customer != self.customer:
				raise ValidationError(
					f"Return Against Sales Invoice {self.return_against} belongs to another customer"
				)

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
				"Sales Invoice", {"is_return": 1, "return_against": self.name, "docstatus": 1}
			):
				self.status = "Credit Note Issued"
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
			frappe.get_doc("Sales Invoice", self.return_against).set_status(update=True)

	def on_cancel(self) -> None:
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		self.make_gl_entries()
		self.set_status(update=True)

	def get_gl_entries(self) -> list[_dict]:
		gl_entries: list[_dict] = []
		self.make_customer_gl_entry(gl_entries)
		self.make_tax_gl_entries(gl_entries)
		self.make_item_gl_entries(gl_entries)
		return gl_entries

	def make_customer_gl_entry(self, gl_entries: list[_dict]) -> None:
		grand_total = self.grand_total
		base_grand_total = flt(self.base_grand_total, self.precision("base_grand_total"))
		if grand_total:
			against_voucher = self.name
			if self.is_return and self.return_against and not self.get("update_outstanding_for_self"):
				against_voucher = self.return_against
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": self.debit_to,
						"party_type": "Customer",
						"party": self.customer,
						"due_date": self.due_date,
						"against": self.against_income_account,
						"debit": base_grand_total,
						"debit_in_account_currency": base_grand_total
						if self.party_account_currency == self.company_currency
						else grand_total,
						"debit_in_transaction_currency": grand_total,
						"against_voucher": against_voucher,
						"against_voucher_type": self.doctype,
						"cost_center": self.cost_center,
					},
					self.party_account_currency,
					item=self,
				)
			)

	def make_tax_gl_entries(self, gl_entries: list[_dict]) -> None:
		from erpnext.accounts.utils import get_account_currency

		for tax in self.taxes:
			base_amount = flt(tax.base_tax_amount_after_discount_amount)
			if not base_amount:
				continue
			account_currency = get_account_currency(tax.account_head)
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": tax.account_head,
						"against": self.customer,
						"credit": base_amount,
						"credit_in_account_currency": base_amount
						if account_currency == self.company_currency
						else flt(tax.tax_amount_after_discount_amount),
						"credit_in_transaction_currency": flt(tax.tax_amount_after_discount_amount),
						"cost_center": tax.cost_center,
					},
					account_currency,
					item=tax,
				)
			)

	def make_item_gl_entries(self, gl_entries: list[_dict]) -> None:
		from erpnext.accounts.utils import get_account_currency

		if self.update_stock:
			raise NotImplementedError(
				"frappe stub: Sales Invoice with update_stock (stock GL) is not implemented"
			)
		for item in self.items:
			if not flt(item.base_net_amount):
				continue
			account_currency = get_account_currency(item.income_account)
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": item.income_account,
						"against": self.customer,
						"credit": flt(item.base_net_amount, item.precision("base_net_amount")),
						"credit_in_transaction_currency": flt(item.net_amount, item.precision("net_amount")),
						"cost_center": item.cost_center,
						"project": item.project,
					},
					account_currency,
					item=item,
				)
			)


def make_sales_return(source_name: str, target_doc: Any = None) -> Any:
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	return make_return_doc("Sales Invoice", source_name, target_doc)
