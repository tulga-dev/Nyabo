"""Payment Entry (erpnext/accounts/doctype/payment_entry/payment_entry.py, version-16).

The slice Nyabo needs: one party (Supplier / Customer), one bank or cash account, one
reference row pointing at a Purchase Invoice or a Sales Invoice, company currency on both
sides. Mirrored from the source quoted in SOURCES.md:

* ``setup_party_account_field`` — ``paid_to`` is the party account when paying,
  ``paid_from`` when receiving;
* ``set_amounts`` — ``set_received_amount`` -> ``set_amounts_in_company_currency`` ->
  ``set_total_allocated_amount`` -> ``set_unallocated_amount``;
* ``validate_allocated_amount`` — "Row #{0}: Allocated Amount cannot be greater than
  outstanding amount.";
* ``build_gl_map`` — ``add_party_gl_entries`` (one row per reference, debit when paying,
  ``against_voucher`` the invoice) then ``add_bank_gl_entries`` (credit ``paid_from`` when
  paying, debit ``paid_to`` when receiving);
* ``on_submit`` — GL entries, then ``update_outstanding_amounts``, then ``set_status``.

Reductions, all raising ``NotImplementedError`` rather than guessing: a second currency
(``paid_from_account_currency != paid_to_account_currency`` or either differing from the
company currency), taxes, deductions, advances (a reference row is always an invoice),
payment terms, payment requests and Internal Transfer. Outstanding amounts: version-16
maintains them through the Payment Ledger, which this stub does not have, so
``update_outstanding_amounts`` calls ``erpnext.accounts.utils.update_voucher_outstanding``
(the GL formula of ``gl_entry.update_outstanding_amt``, which yields the same number for
the single-currency invoices the stub supports).
"""

from __future__ import annotations

from typing import Any

from frappe._stub.dictlike import _dict
from frappe.exceptions import ValidationError
from frappe.utils.data import flt, getdate, nowdate

from erpnext.controllers.accounts_controller import AccountsController

INVOICE_DOCTYPES = ("Purchase Invoice", "Sales Invoice")
PARTY_TYPE_BY_DOCTYPE = {"Purchase Invoice": "Supplier", "Sales Invoice": "Customer"}
PARTY_FIELD = {"Supplier": "supplier", "Customer": "customer"}


class PaymentEntry(AccountsController):
	_stub_extra_fields = frozenset(
		{"company_currency", "party_account_field", "party_account", "party_account_currency"}
	)

	def setup_party_account_field(self) -> None:
		self.party_account_field = None
		self.party_account = None
		self.party_account_currency = None
		if self.payment_type == "Receive":
			self.party_account_field = "paid_from"
			self.party_account = self.paid_from
			self.party_account_currency = self.paid_from_account_currency
		elif self.payment_type == "Pay":
			self.party_account_field = "paid_to"
			self.party_account = self.paid_to
			self.party_account_currency = self.paid_to_account_currency

	def validate(self) -> None:
		self.validate_payment_type()
		self.set_missing_values()
		self.setup_party_account_field()
		self.validate_single_currency()
		self.validate_mandatory()
		self.validate_reference_documents()
		self.set_amounts()
		self.set_title()
		self.set_remarks()
		self.validate_allocated_amount()
		self.set_status()

	def validate_payment_type(self) -> None:
		if self.payment_type == "Internal Transfer":
			raise NotImplementedError(
				"frappe stub: Payment Entry of type Internal Transfer is not implemented"
			)
		if self.payment_type not in ("Receive", "Pay"):
			raise ValidationError("Payment Type must be one of Receive, Pay")
		if self.get("taxes") or self.get("deductions"):
			raise NotImplementedError("frappe stub: Payment Entry taxes / deductions are not implemented")

	def set_missing_values(self) -> None:
		import frappe

		if not self.company:
			raise ValidationError("Company is mandatory")
		self.company_currency = self.get_company_currency()
		if not self.posting_date:
			self.posting_date = nowdate()
		if not self.cost_center:
			self.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		for field, account in (
			("paid_from_account_currency", self.paid_from),
			("paid_to_account_currency", self.paid_to),
		):
			if not self.get(field) and account:
				from erpnext.accounts.utils import get_account_currency

				self.set(field, get_account_currency(account))
		if not self.source_exchange_rate:
			self.source_exchange_rate = 1.0
		if not self.target_exchange_rate:
			self.target_exchange_rate = 1.0
		if self.party_type and self.party and not self.party_name:
			field = "supplier_name" if self.party_type == "Supplier" else "customer_name"
			self.party_name = frappe.db.get_value(self.party_type, self.party, field)
		if not self.paid_from_account_type and self.paid_from:
			self.paid_from_account_type = frappe.db.get_value("Account", self.paid_from, "account_type")
		if not self.paid_to_account_type and self.paid_to:
			self.paid_to_account_type = frappe.db.get_value("Account", self.paid_to, "account_type")

	def validate_single_currency(self) -> None:
		currencies = {self.paid_from_account_currency, self.paid_to_account_currency, self.company_currency}
		if len(currencies) > 1:
			raise NotImplementedError(
				f"frappe stub: multi-currency Payment Entry is not implemented ({sorted(currencies)})"
			)
		if flt(self.source_exchange_rate) != 1.0 or flt(self.target_exchange_rate) != 1.0:
			raise NotImplementedError(
				"frappe stub: Payment Entry exchange rates other than 1 are not implemented"
			)

	def validate_mandatory(self) -> None:
		for field in ("paid_amount", "received_amount", "paid_from", "paid_to"):
			if not self.get(field):
				raise ValidationError(f"{field} is mandatory")

	def validate_reference_documents(self) -> None:
		import frappe

		for row in self.get("references") or []:
			if row.reference_doctype not in INVOICE_DOCTYPES:
				raise NotImplementedError(
					f"frappe stub: Payment Entry reference {row.reference_doctype} is not implemented"
				)
			if row.payment_term or row.payment_request:
				raise NotImplementedError(
					"frappe stub: Payment Entry payment terms / payment requests are not implemented"
				)
			invoice = frappe.db.get_value(
				row.reference_doctype,
				row.reference_name,
				["docstatus", "company", "outstanding_amount"],
				as_dict=True,
			)
			if not invoice:
				raise ValidationError(f"{row.reference_doctype} {row.reference_name} does not exist")
			if int(invoice.docstatus) != 1:
				raise ValidationError(f"{row.reference_doctype} {row.reference_name} must be submitted")
			if invoice.company != self.company:
				raise ValidationError(
					f"{row.reference_doctype} {row.reference_name} belongs to another company"
				)
			row.outstanding_amount = flt(invoice.outstanding_amount)
			if not row.exchange_rate:
				row.exchange_rate = 1.0

	def set_amounts(self) -> None:
		self.set_received_amount()
		self.set_amounts_in_company_currency()
		self.set_total_allocated_amount()
		self.set_unallocated_amount()
		self.difference_amount = 0.0

	def set_received_amount(self) -> None:
		self.base_received_amount = self.base_paid_amount
		if self.paid_from_account_currency == self.paid_to_account_currency:
			self.received_amount = self.paid_amount

	def set_amounts_in_company_currency(self) -> None:
		self.base_paid_amount = flt(
			flt(self.paid_amount) * flt(self.source_exchange_rate), self.precision("base_paid_amount")
		)
		self.base_received_amount = flt(
			flt(self.received_amount) * flt(self.target_exchange_rate), self.precision("base_received_amount")
		)

	def set_total_allocated_amount(self) -> None:
		total = sum(flt(row.allocated_amount) for row in self.get("references") or [])
		self.total_allocated_amount = flt(abs(total), self.precision("total_allocated_amount"))
		self.base_total_allocated_amount = self.total_allocated_amount

	def set_unallocated_amount(self) -> None:
		self.unallocated_amount = 0.0
		if not self.party:
			return
		base = self.base_paid_amount if self.payment_type == "Receive" else self.base_received_amount
		if flt(self.base_total_allocated_amount) < flt(base):
			self.unallocated_amount = flt(
				flt(base) - flt(self.base_total_allocated_amount), self.precision("unallocated_amount")
			)

	def validate_allocated_amount(self) -> None:
		for row in self.get("references") or []:
			if flt(row.allocated_amount) > 0 and flt(row.allocated_amount) > flt(row.outstanding_amount):
				raise ValidationError(
					f"Row #{row.idx}: Allocated Amount cannot be greater than outstanding amount."
				)

	def set_title(self) -> None:
		if not self.title:
			self.title = self.party_name or self.party or self.paid_from

	def set_remarks(self) -> None:
		if self.remarks:
			return
		parts = [f"Amount {self.paid_amount} {self.paid_from_account_currency}"]
		if self.party:
			direction = "to" if self.payment_type == "Pay" else "from"
			parts.append(f"{direction} {self.party_type} {self.party}")
		for row in self.get("references") or []:
			parts.append(f"against {row.reference_doctype} {row.reference_name}")
		if self.reference_no:
			parts.append(f"reference no {self.reference_no}")
		self.remarks = " ".join(parts)

	def set_status(self) -> None:
		if int(self.docstatus) == 2:
			self.status = "Cancelled"
		elif int(self.docstatus) == 1:
			self.status = "Submitted"
		else:
			self.status = "Draft"

	def on_submit(self) -> None:
		if flt(self.difference_amount):
			raise ValidationError("Difference Amount must be zero")
		self.make_gl_entries()
		self.update_outstanding_amounts()
		self.set_status()
		self.db_set("status", self.status)

	def on_cancel(self) -> None:
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		self.make_gl_entries(cancel=1)
		self.update_outstanding_amounts()
		self.set_status()
		self.db_set("status", self.status)

	def update_outstanding_amounts(self) -> None:
		"""version-16 goes through the Payment Ledger; the stub recomputes from the GL rows."""
		from erpnext.accounts.utils import update_voucher_outstanding

		for row in self.get("references") or []:
			update_voucher_outstanding(
				row.reference_doctype, row.reference_name, self.party_account, self.party_type, self.party
			)

	def make_gl_entries(self, cancel: int = 0, adv_adj: int = 0) -> None:  # type: ignore[override]
		from erpnext.accounts.general_ledger import make_gl_entries

		gl_map = self.build_gl_map()
		if gl_map:
			make_gl_entries(gl_map, cancel=bool(cancel), adv_adj=bool(adv_adj), merge_entries=False)

	def build_gl_map(self) -> list[_dict]:
		# Unconditionally, not `if not self.party_account_field`: the attribute only exists once
		# the setter has run, and on cancel it has not (``validate`` does not run for a cancel),
		# so reading it first raised AttributeError and made the whole cancel path dead.
		self.setup_party_account_field()
		gl_entries: list[_dict] = []
		self.add_party_gl_entries(gl_entries)
		self.add_bank_gl_entries(gl_entries)
		return gl_entries

	def add_party_gl_entries(self, gl_entries: list[_dict]) -> None:
		if not self.party_account:
			return
		against_account = self.paid_to if self.payment_type == "Receive" else self.paid_from
		dr_or_cr = "credit" if self.payment_type == "Receive" else "debit"
		for row in self.get("references") or []:
			amount = flt(row.allocated_amount, self.precision("paid_amount"))
			if not amount:
				continue
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": self.party_account,
						"party_type": self.party_type,
						"party": self.party,
						"against": against_account,
						"cost_center": self.cost_center,
						dr_or_cr: amount,
						dr_or_cr + "_in_account_currency": amount,
						dr_or_cr + "_in_transaction_currency": amount,
						"against_voucher_type": row.reference_doctype,
						"against_voucher": row.reference_name,
					},
					self.party_account_currency,
					item=self,
				)
			)
		if flt(self.unallocated_amount):
			amount = flt(self.unallocated_amount, self.precision("unallocated_amount"))
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": self.party_account,
						"party_type": self.party_type,
						"party": self.party,
						"against": against_account,
						"cost_center": self.cost_center,
						dr_or_cr: amount,
						dr_or_cr + "_in_account_currency": amount,
						dr_or_cr + "_in_transaction_currency": amount,
					},
					self.party_account_currency,
					item=self,
				)
			)

	def add_bank_gl_entries(self, gl_entries: list[_dict]) -> None:
		if self.payment_type == "Pay":
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": self.paid_from,
						"against": self.party,
						"credit": self.base_paid_amount,
						"credit_in_account_currency": self.paid_amount,
						"credit_in_transaction_currency": self.paid_amount,
						"cost_center": self.cost_center,
						"post_net_value": True,
					},
					self.paid_from_account_currency,
					item=self,
				)
			)
		else:
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": self.paid_to,
						"against": self.party,
						"debit": self.base_received_amount,
						"debit_in_account_currency": self.received_amount,
						"debit_in_transaction_currency": self.received_amount,
						"cost_center": self.cost_center,
					},
					self.paid_to_account_currency,
					item=self,
				)
			)


def set_party_type(dt: str) -> str:
	"""erpnext payment_entry.set_party_type, reduced to the two invoice doctypes."""
	party_type = PARTY_TYPE_BY_DOCTYPE.get(dt)
	if not party_type:
		raise NotImplementedError(f"frappe stub: get_payment_entry against {dt} is not implemented")
	return party_type


def set_party_account(dt: str, dn: str, doc: Any, party_type: str) -> Any:
	if dt == "Sales Invoice":
		return doc.debit_to
	return doc.credit_to


def set_payment_type(dt: str, doc: Any) -> str:
	if dt == "Sales Invoice" and flt(doc.outstanding_amount) > 0:
		return "Receive"
	if dt == "Purchase Invoice" and flt(doc.outstanding_amount) < 0:
		return "Receive"
	return "Pay"


def get_bank_cash_account(doc: Any, bank_account: str | None) -> Any:
	"""erpnext payment_entry.get_bank_cash_account: ``bank_account`` is a GL Account name."""
	from erpnext.accounts.doctype.journal_entry.journal_entry import get_default_bank_cash_account

	bank = get_default_bank_cash_account(
		doc.company,
		"Bank",
		mode_of_payment=doc.get("mode_of_payment"),
		account=bank_account,
		fetch_balance=False,
	)
	if not bank:
		bank = get_default_bank_cash_account(
			doc.company,
			"Cash",
			mode_of_payment=doc.get("mode_of_payment"),
			account=bank_account,
			fetch_balance=False,
		)
	return bank


def get_payment_entry(
	dt: str,
	dn: str,
	party_amount: float | None = None,
	bank_account: str | None = None,
	bank_amount: float | None = None,
	party_type: str | None = None,
	payment_type: str | None = None,
	reference_date: Any = None,
	created_from_payment_request: bool = False,
) -> Any:
	"""A draft Payment Entry for one submitted invoice (erpnext payment_entry.get_payment_entry).

	``bank_account`` is the *GL Account* the money moves on, not a Bank Account row: the
	source passes it to ``get_default_bank_cash_account(..., account=bank_account)``.
	The reduction keeps the invoice branch (references row with the whole outstanding
	amount allocated) and drops payment terms, Dunning, orders, early-payment discounts,
	payment requests and accounting dimensions.
	"""
	import frappe

	frappe.has_permission("Payment Entry", ptype="create", throw=True)
	doc = frappe.get_doc(dt, dn)
	doc.check_permission()
	if int(doc.docstatus) != 1:
		raise ValidationError(f"{dt} {dn} must be submitted before a payment can be made against it")

	party_type = party_type or set_party_type(dt)
	party_account = set_party_account(dt, dn, doc, party_type)
	party_account_currency = doc.get("party_account_currency") or _account_currency(party_account)
	payment_type = payment_type or set_payment_type(dt, doc)
	grand_total = flt(doc.base_rounded_total or doc.base_grand_total)
	outstanding_amount = flt(party_amount) if party_amount else flt(doc.outstanding_amount)
	bank = get_bank_cash_account(doc, bank_account)
	if not bank:
		raise ValidationError(f"No Bank or Cash account found for Company {doc.company}")
	paid_amount = received_amount = flt(bank_amount) if bank_amount else outstanding_amount

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = payment_type
	pe.company = doc.company
	pe.cost_center = doc.get("cost_center")
	pe.posting_date = nowdate()
	pe.reference_date = getdate(reference_date) if reference_date else None
	pe.mode_of_payment = doc.get("mode_of_payment")
	pe.party_type = party_type
	pe.party = doc.get(PARTY_FIELD[party_type])
	pe.paid_from = party_account if payment_type == "Receive" else bank.account
	pe.paid_to = party_account if payment_type == "Pay" else bank.account
	pe.paid_from_account_currency = (
		party_account_currency if payment_type == "Receive" else bank.account_currency
	)
	pe.paid_to_account_currency = party_account_currency if payment_type == "Pay" else bank.account_currency
	pe.paid_amount = paid_amount
	pe.received_amount = received_amount
	pe.project = doc.get("project")
	pe.append(
		"references",
		{
			"reference_doctype": dt,
			"reference_name": dn,
			"bill_no": doc.get("bill_no"),
			"due_date": doc.get("due_date"),
			"total_amount": grand_total,
			"outstanding_amount": outstanding_amount,
			"allocated_amount": outstanding_amount,
		},
	)
	pe.setup_party_account_field()
	pe.set_missing_values()
	return pe


def _account_currency(account: str | None) -> Any:
	from erpnext.accounts.utils import get_account_currency

	return get_account_currency(account)
