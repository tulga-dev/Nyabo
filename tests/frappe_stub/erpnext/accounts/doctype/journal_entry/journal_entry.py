"""Journal Entry (erpnext/accounts/doctype/journal_entry/journal_entry.py, version-16).

Validate: amounts in company currency from ``*_in_account_currency * exchange_rate``
(rate defaults to 1; a row given only ``debit``/``credit`` is treated as company
currency), no row with both sides or neither, totals equal
("Total Debit must be equal to Total Credit. The difference is {0}"), at least one row,
title from ``pay_to_recd_from`` or the first account. Submit writes GL Entry rows from
``build_gl_map``; cancel reverses them. ``make_reverse_journal_entry`` is the quoted
source with the same guards, field map and ``reversal_of`` post-processing.
"""

from __future__ import annotations

from typing import Any

from frappe._stub.dictlike import _dict
from frappe.exceptions import PermissionError, ValidationError
from frappe.utils.data import flt

from erpnext.controllers.accounts_controller import AccountsController


class JournalEntry(AccountsController):
	def validate(self) -> None:
		if not self.accounts:
			raise ValidationError("Accounts table cannot be blank.")
		self.set_account_currency()
		self.set_amounts_in_company_currency()
		self.validate_debit_credit_amount()
		self.set_total_debit_credit()
		self.validate_total_debit_and_credit()
		self.set_against_account()
		if not self.title or (self.is_new() and self.amended_from):
			self.title = self.get_title()

	def get_title(self) -> str:
		return self.pay_to_recd_from or self.accounts[0].account

	def set_account_currency(self) -> None:
		from erpnext.accounts.utils import get_account_currency

		company_currency = self.get_company_currency()
		for d in self.accounts:
			d.account_currency = get_account_currency(d.account) or company_currency
			if not d.exchange_rate:
				d.exchange_rate = 1.0
			if d.account_currency != company_currency and flt(d.exchange_rate) == 1.0:
				raise ValidationError(
					f"Row {d.idx}: Exchange Rate is mandatory for account {d.account} in {d.account_currency}"
				)
			# a row entered in company currency only: mirror it into the account-currency columns
			if not flt(d.debit_in_account_currency) and flt(d.debit):
				d.debit_in_account_currency = flt(d.debit) / flt(d.exchange_rate)
			if not flt(d.credit_in_account_currency) and flt(d.credit):
				d.credit_in_account_currency = flt(d.credit) / flt(d.exchange_rate)

	def set_amounts_in_company_currency(self) -> None:
		for d in self.accounts:
			d.debit_in_account_currency = flt(
				d.debit_in_account_currency, d.precision("debit_in_account_currency")
			)
			d.credit_in_account_currency = flt(
				d.credit_in_account_currency, d.precision("credit_in_account_currency")
			)
			d.debit = flt(d.debit_in_account_currency * flt(d.exchange_rate), d.precision("debit"))
			d.credit = flt(d.credit_in_account_currency * flt(d.exchange_rate), d.precision("credit"))

	def validate_debit_credit_amount(self) -> None:
		for d in self.accounts:
			if not flt(d.debit) and not flt(d.credit):
				raise ValidationError(f"Row {d.idx}: Both Debit and Credit values cannot be zero")

	def set_total_debit_credit(self) -> None:
		self.total_debit, self.total_credit, self.difference = 0, 0, 0
		for d in self.accounts:
			if d.debit and d.credit:
				raise ValidationError("You cannot credit and debit same account at the same time")
			self.total_debit = flt(self.total_debit) + flt(d.debit, d.precision("debit"))
			self.total_credit = flt(self.total_credit) + flt(d.credit, d.precision("credit"))
		self.difference = flt(self.total_debit, self.precision("total_debit")) - flt(
			self.total_credit, self.precision("total_credit")
		)

	def validate_total_debit_and_credit(self) -> None:
		if self.difference:
			raise ValidationError(
				f"Total Debit must be equal to Total Credit. The difference is {self.difference}"
			)

	def set_against_account(self) -> None:
		accounts_debited = [d.account for d in self.accounts if flt(d.debit) > 0]
		accounts_credited = [d.account for d in self.accounts if flt(d.credit) > 0]
		for d in self.accounts:
			if flt(d.debit) > 0:
				d.against_account = ", ".join(a for a in accounts_credited if a != d.account) or None
			if flt(d.credit) > 0:
				d.against_account = ", ".join(a for a in accounts_debited if a != d.account) or None

	def on_submit(self) -> None:
		self.make_gl_entries()

	def on_cancel(self) -> None:
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		self.make_gl_entries(1)

	def make_gl_entries(self, cancel: int = 0, adv_adj: int = 0) -> None:  # type: ignore[override]
		from erpnext.accounts.general_ledger import make_gl_entries

		gl_map = self.build_gl_map()
		if gl_map:
			make_gl_entries(gl_map, cancel=bool(cancel), adv_adj=bool(adv_adj), merge_entries=False)

	def build_gl_map(self) -> list[_dict]:
		gl_map: list[_dict] = []
		for d in self.accounts:
			if flt(d.debit) or flt(d.credit):
				gl_map.append(
					self.get_gl_dict(
						{
							"account": d.account,
							"party_type": d.party_type,
							"due_date": self.due_date,
							"party": d.party,
							"against": d.against_account,
							"debit": flt(d.debit, d.precision("debit")),
							"credit": flt(d.credit, d.precision("credit")),
							"account_currency": d.account_currency,
							"debit_in_account_currency": flt(
								d.debit_in_account_currency, d.precision("debit_in_account_currency")
							),
							"credit_in_account_currency": flt(
								d.credit_in_account_currency, d.precision("credit_in_account_currency")
							),
							"against_voucher_type": d.reference_type,
							"against_voucher": d.reference_name,
							"remarks": self.user_remark or self.remark or "No Remarks",
							"voucher_detail_no": d.reference_detail_no,
							"cost_center": d.cost_center,
							"project": d.project,
							"finance_book": self.finance_book,
						},
						item=d,
					)
				)
		return gl_map


def make_reverse_journal_entry(source_name: str, target_doc: Any = None) -> Any:
	import frappe
	from frappe.model.mapper import get_mapped_doc
	from frappe.utils.data import get_link_to_form

	if not frappe.has_permission("Journal Entry", doc=source_name):
		raise PermissionError("Not permitted")

	reversal_of = frappe.db.get_value("Journal Entry", source_name, "reversal_of")
	if reversal_of:
		raise ValidationError(
			"{} is already a Reverse Journal Entry of {}. Cancel it instead of reversing it.".format(
				get_link_to_form("Journal Entry", source_name), get_link_to_form("Journal Entry", reversal_of)
			)
		)
	existing_reverse = frappe.db.exists("Journal Entry", {"reversal_of": source_name, "docstatus": 1})
	if existing_reverse:
		raise ValidationError(
			"A Reverse Journal Entry {} already exists for this Journal Entry.".format(
				get_link_to_form("Journal Entry", existing_reverse)
			)
		)

	def post_process(source: Any, target: Any) -> None:
		target.reversal_of = source.name

	return get_mapped_doc(
		"Journal Entry",
		source_name,
		{
			"Journal Entry": {"doctype": "Journal Entry", "validation": {"docstatus": ["=", 1]}},
			"Journal Entry Account": {
				"doctype": "Journal Entry Account",
				"field_map": {
					"account_currency": "account_currency",
					"exchange_rate": "exchange_rate",
					"debit_in_account_currency": "credit_in_account_currency",
					"debit": "credit",
					"credit_in_account_currency": "debit_in_account_currency",
					"credit": "debit",
					"reference_type": "reference_type",
					"reference_name": "reference_name",
				},
			},
		},
		target_doc,
		post_process,
	)
