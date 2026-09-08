"""The slice of erpnext.controllers.accounts_controller that Purchase / Sales Invoice share.

Totals follow erpnext/controllers/taxes_and_totals.py for the two charge types Nyabo
uses (``Actual`` and ``On Net Total``; anything else raises), a single currency (the
conversion rate defaults to 1) and no rounding adjustment. ``get_gl_dict`` fills the GL
Entry columns like ``AccountsController.get_gl_dict`` does.
"""

from __future__ import annotations

from typing import Any

from frappe._stub.dictlike import _dict
from frappe.exceptions import ValidationError
from frappe.model.document import Document
from frappe.utils.data import flt, getdate, nowdate

SUPPORTED_CHARGE_TYPES = ("Actual", "On Net Total")


class AccountsController(Document):
	_stub_extra_fields = frozenset({"company_currency"})

	def get_company_currency(self) -> str:
		import frappe

		return frappe.get_cached_value("Company", self.company, "default_currency")

	def get_company_default(self, fieldname: str, ignore_validation: bool = False) -> Any:
		from erpnext.accounts.utils import get_company_default

		return get_company_default(self.company, fieldname, ignore_validation=ignore_validation)

	def set_missing_currency_values(self) -> None:
		company_currency = self.get_company_currency()
		self.company_currency = company_currency
		if not self.currency:
			self.currency = company_currency
		if not self.conversion_rate:
			self.conversion_rate = 1.0
		if self.currency != company_currency and flt(self.conversion_rate) == 1.0:
			raise ValidationError(
				f"Conversion rate is required for {self.currency} -> {company_currency} (frappe stub does not fetch rates)"
			)
		if not self.posting_date:
			self.posting_date = nowdate()
		if not self.due_date:
			self.due_date = self.posting_date
		if getdate(self.due_date) < getdate(self.posting_date):
			raise ValidationError("Due Date cannot be before Posting / Supplier Invoice Date")

	def calculate_item_values(self) -> None:
		for item in self.get("items") or []:
			if not item.item_name:
				item.item_name = item.item_code or item.description or "Item"
			if not item.uom:
				item.uom = item.stock_uom or "Nos"
			if not item.stock_uom:
				item.stock_uom = item.uom
			if not item.conversion_factor:
				item.conversion_factor = 1.0
			item.qty = flt(item.qty)
			item.rate = flt(item.rate, item.precision("rate"))
			item.amount = flt(item.qty * item.rate, item.precision("amount"))
			item.net_rate = item.rate
			item.net_amount = item.amount
			item.base_rate = flt(item.rate * flt(self.conversion_rate), item.precision("base_rate"))
			item.base_amount = flt(item.amount * flt(self.conversion_rate), item.precision("base_amount"))
			item.base_net_rate = item.base_rate
			item.base_net_amount = item.base_amount
			if item.meta.has_field("stock_qty"):
				item.stock_qty = flt(item.qty * flt(item.conversion_factor))

	def calculate_taxes_and_totals(self) -> None:
		self.calculate_item_values()
		items = self.get("items") or []
		self.total = flt(sum(flt(i.amount) for i in items), self.precision("total"))
		self.net_total = self.total
		self.base_total = flt(self.total * flt(self.conversion_rate), self.precision("base_total"))
		self.base_net_total = self.base_total
		running = self.net_total
		total_taxes = 0.0
		for tax in self.get("taxes") or []:
			if tax.meta.has_field("category") and tax.category not in (None, "", "Total"):
				raise NotImplementedError(
					f"frappe stub: Purchase Taxes and Charges category {tax.category!r} (valuation) is not implemented"
				)
			if tax.charge_type not in SUPPORTED_CHARGE_TYPES:
				raise NotImplementedError(
					f"frappe stub: charge_type {tax.charge_type!r} is not implemented; use Actual or On Net Total"
				)
			if tax.charge_type == "Actual":
				amount = flt(tax.tax_amount, tax.precision("tax_amount"))
			else:
				amount = flt(self.net_total * flt(tax.rate) / 100.0, tax.precision("tax_amount"))
			sign = -1 if tax.meta.has_field("add_deduct_tax") and tax.add_deduct_tax == "Deduct" else 1
			tax.tax_amount = amount
			tax.tax_amount_after_discount_amount = amount
			tax.base_tax_amount = flt(amount * flt(self.conversion_rate), tax.precision("base_tax_amount"))
			tax.base_tax_amount_after_discount_amount = tax.base_tax_amount
			running = flt(running + sign * amount, tax.precision("total"))
			tax.total = running
			tax.base_total = flt(running * flt(self.conversion_rate), tax.precision("base_total"))
			total_taxes += sign * amount
		self.total_taxes_and_charges = flt(total_taxes, self.precision("total_taxes_and_charges"))
		self.grand_total = flt(self.net_total + self.total_taxes_and_charges, self.precision("grand_total"))
		self.base_grand_total = flt(self.grand_total * flt(self.conversion_rate), self.precision("base_grand_total"))
		self.rounded_total = self.grand_total
		self.base_rounded_total = self.base_grand_total
		if self.meta.has_field("rounding_adjustment"):
			self.rounding_adjustment = 0.0
			self.base_rounding_adjustment = 0.0
		if self.meta.has_field("outstanding_amount") and self.docstatus == 0:
			self.outstanding_amount = self.base_grand_total if self.party_account_currency == self.company_currency else self.grand_total

	def get_gl_dict(self, args: dict[str, Any], account_currency: str | None = None, item: Any = None) -> _dict:
		from erpnext.accounts.utils import get_account_currency, get_fiscal_year

		company_currency = self.get_company_currency()
		posting_date = self.get("posting_date") or nowdate()
		fiscal_year = get_fiscal_year(posting_date, company=self.company)[0]
		gl_dict = _dict(
			{
				"company": self.company,
				"posting_date": posting_date,
				"fiscal_year": fiscal_year,
				"voucher_type": self.doctype,
				"voucher_no": self.name,
				"voucher_subtype": self.get("voucher_subtype"),
				"remarks": self.get("remarks") or self.get("user_remark") or "No Remarks",
				"debit": 0,
				"credit": 0,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": 0,
				"is_opening": self.get("is_opening") or "No",
				"party_type": None,
				"party": None,
				"project": self.get("project"),
				"post_net_value": args.get("post_net_value"),
				"voucher_detail_no": item.name if item is not None and hasattr(item, "name") else None,
				"is_cancelled": 0,
			}
		)
		gl_dict.update(args)
		account_currency = account_currency or get_account_currency(gl_dict.account)
		gl_dict.account_currency = account_currency
		if account_currency == company_currency:
			gl_dict.debit_in_account_currency = gl_dict.debit_in_account_currency or gl_dict.debit
			gl_dict.credit_in_account_currency = gl_dict.credit_in_account_currency or gl_dict.credit
		elif not gl_dict.debit_in_account_currency and not gl_dict.credit_in_account_currency:
			raise NotImplementedError(
				f"frappe stub: account {gl_dict.account} is in {account_currency}; pass *_in_account_currency amounts"
			)
		gl_dict.transaction_currency = self.get("currency") or company_currency
		gl_dict.transaction_exchange_rate = flt(self.get("conversion_rate")) or 1.0
		gl_dict.debit_in_transaction_currency = gl_dict.get("debit_in_transaction_currency") or gl_dict.debit
		gl_dict.credit_in_transaction_currency = gl_dict.get("credit_in_transaction_currency") or gl_dict.credit
		return gl_dict

	def make_gl_entries(self, gl_entries: list[Any] | None = None, from_repost: bool = False) -> None:
		from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries

		if self.docstatus == 1:
			make_gl_entries(gl_entries or self.get_gl_entries(), merge_entries=False)
		elif self.docstatus == 2:
			make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

	def get_gl_entries(self) -> list[_dict]:  # pragma: no cover - overridden
		raise NotImplementedError

	def is_internal_transfer(self) -> bool:
		return False
