"""Bank Transaction (erpnext/accounts/doctype/bank_transaction/bank_transaction.py, version-16).

The methods Nyabo's matcher relies on are mirrored from the source quoted in SOURCES.md:
``add_payment_entries(vouchers, is_new_voucher=False)`` appends rows with zero
allocation, ``before_update_after_submit`` / ``before_submit`` run
``allocate_payment_entries`` which takes the voucher's bank-account GL amount minus what
other Bank Transactions already allocated, caps it at the unallocated amount, clears the
voucher (``clearance_date``) when fully allocated, and ``set_status`` moves the row to
Reconciled / Unreconciled / Cancelled. The SQL of ``get_total_allocated_amount`` and
``get_related_bank_gl_entries`` is re-expressed over the stub tables.
"""

from __future__ import annotations

from typing import Any

from frappe.exceptions import ValidationError
from frappe.model.document import Document
from frappe.utils.data import flt, getdate


class BankTransaction(Document):
	def before_validate(self) -> None:
		self.update_allocated_amount()

	def validate(self) -> None:
		self.validate_included_fee()
		self.validate_duplicate_references()
		self.validate_currency()

	def validate_included_fee(self) -> None:
		if self.included_fee and self.withdrawal and flt(self.included_fee) > flt(self.withdrawal):
			raise ValidationError("Included fee is bigger than the withdrawal itself.")

	def validate_currency(self) -> None:
		import frappe

		if self.currency and self.bank_account:
			account = frappe.get_cached_value("Bank Account", self.bank_account, "account")
			if account:
				account_currency = frappe.get_cached_value("Account", account, "account_currency")
				if account_currency and self.currency != account_currency:
					raise ValidationError(
						"Transaction currency: {0} cannot be different from Bank Account({1}) currency: {2}".format(
							frappe.bold(self.currency), frappe.bold(self.bank_account), frappe.bold(account_currency)
						)
					)

	def validate_duplicate_references(self) -> None:
		"""Make sure the same voucher is not allocated twice within the same Bank Transaction"""
		if not self.payment_entries:
			return
		references: set[tuple[str, str]] = set()
		for row in self.payment_entries:
			reference = (row.payment_document, row.payment_entry)
			if reference in references:
				raise ValidationError(f"{row.payment_document} {row.payment_entry} is allocated twice in this Bank Transaction")
			references.add(reference)

	def set_status(self) -> None:
		if self.docstatus == 2:
			self.db_set("status", "Cancelled")
		elif self.docstatus == 1:
			if flt(self.unallocated_amount) > 0:
				self.db_set("status", "Unreconciled")
			elif flt(self.unallocated_amount) <= 0:
				self.db_set("status", "Reconciled")

	def update_allocated_amount(self) -> None:
		allocated_amount = sum(flt(p.allocated_amount) for p in self.payment_entries) if self.payment_entries else 0.0
		unallocated_amount = abs(flt(self.withdrawal) - flt(self.deposit)) - allocated_amount
		self.allocated_amount = flt(allocated_amount, self.precision("allocated_amount"))
		self.unallocated_amount = flt(unallocated_amount, self.precision("unallocated_amount"))

	def before_submit(self) -> None:
		self.allocate_payment_entries()
		self.set_status()

	def before_update_after_submit(self) -> None:
		self.validate_duplicate_references()
		self.update_allocated_amount()
		self.allocate_payment_entries()
		self.set_status()

	def on_cancel(self) -> None:
		self.ignore_linked_doctypes = ["GL Entry"]
		for payment_entry in self.payment_entries:
			self.delink_payment_entry(payment_entry)
		self.set_status()

	def add_payment_entries(self, vouchers: list[dict[str, Any]], is_new_voucher: bool = False) -> None:
		"""
		Add the vouchers with zero allocation. Save() will perform the allocations and clearance

		is_new_voucher - is used to set the reonciliation type - whether the voucher was added as a result of "Matching" or a new voucher was created.
		Used in bank reconciliation
		"""
		if 0.0 >= flt(self.unallocated_amount):
			raise ValidationError(f"Bank Transaction {self.name} is already fully reconciled")
		for voucher in vouchers:
			self.append(
				"payment_entries",
				{
					"payment_document": voucher["payment_doctype"],
					"payment_entry": voucher["payment_name"],
					"allocated_amount": 0.0,  # Temporary
					"reconciliation_type": "Voucher Created" if is_new_voucher else "Matched",
				},
			)

	def allocate_payment_entries(self) -> None:
		"""Refactored from bank reconciliation tool.
		Non-zero allocations must be amended/cleared manually
		Get the bank transaction amount (b) and remove as we allocate
		For each payment_entry if allocated_amount == 0:
		- get the amount already allocated against all transactions (t), need latest date
		- get the voucher amount (from gl) (v)
		- allocate (a = v - t)
		    - a = 0: should already be cleared, so clear & remove payment_entry
		    - 0 < a <= u: allocate a & clear
		    - 0 < a, a > u: allocate u
		    - 0 > a: Error: already over-allocated
		- clear means: set the latest transaction date as clearance date
		"""
		import frappe

		if self.flags.updating_linked_bank_transaction or not self.payment_entries:
			return
		remaining_amount = flt(self.unallocated_amount)
		payment_entry_docs = [(pe.payment_document, pe.payment_entry) for pe in self.payment_entries]
		pe_bt_allocations = get_total_allocated_amount(payment_entry_docs)
		gl_entries = get_related_bank_gl_entries(payment_entry_docs)
		gl_bank_account = frappe.db.get_value("Bank Account", self.bank_account, "account")

		for payment_entry in list(self.payment_entries):
			if flt(payment_entry.allocated_amount) != 0:
				continue
			allocable_amount, should_clear, clearance_date = get_clearance_details(
				self,
				payment_entry,
				pe_bt_allocations.get((payment_entry.payment_document, payment_entry.payment_entry)) or {},
				gl_entries.get((payment_entry.payment_document, payment_entry.payment_entry)) or {},
				gl_bank_account,
			)
			if allocable_amount < 0:
				raise ValidationError(f"Voucher {payment_entry.payment_entry} is over-allocated by {allocable_amount}")
			if remaining_amount <= 0:
				self.remove(payment_entry)
				continue
			if allocable_amount == 0:
				if should_clear:
					self.clear_linked_payment_entry(payment_entry, clearance_date=clearance_date)
				self.remove(payment_entry)
				continue
			should_clear = should_clear and allocable_amount <= remaining_amount
			payment_entry.allocated_amount = min(allocable_amount, remaining_amount)
			remaining_amount = flt(remaining_amount - payment_entry.allocated_amount, self.precision("unallocated_amount"))
			if payment_entry.payment_document == "Bank Transaction":
				self.update_linked_bank_transaction(payment_entry.payment_entry, payment_entry.allocated_amount)
			elif should_clear:
				self.clear_linked_payment_entry(payment_entry, clearance_date=clearance_date)
		self.update_allocated_amount()

	def update_linked_bank_transaction(self, bank_transaction_name: str, allocated_amount: float | None = None) -> None:
		"""For when a second bank transaction has fixed another, e.g. refund"""
		import frappe

		bt = frappe.get_doc(self.doctype, bank_transaction_name)
		if allocated_amount:
			bt.append(
				"payment_entries",
				{"payment_document": self.doctype, "payment_entry": self.name, "allocated_amount": allocated_amount},
			)
		else:
			pe = next(
				(pe for pe in bt.payment_entries if pe.payment_document == self.doctype and pe.payment_entry == self.name),
				None,
			)
			if not pe:
				return
			bt.flags.updating_linked_bank_transaction = True
			bt.remove(pe)
		bt.save()

	def remove_payment_entries(self) -> None:
		for payment_entry in list(self.payment_entries):
			self.remove_payment_entry(payment_entry)
		self.save()  # runs before_update_after_submit

	def remove_payment_entry(self, payment_entry: Any) -> None:
		"Clear payment entry and clearance"
		self.delink_payment_entry(payment_entry)
		self.remove(payment_entry)

	def delink_payment_entry(self, payment_entry: Any) -> None:
		if payment_entry.payment_document == "Bank Transaction":
			self.update_linked_bank_transaction(payment_entry.payment_entry, allocated_amount=None)
		else:
			self.clear_linked_payment_entry(payment_entry, clearance_date=None)

	def clear_linked_payment_entry(self, payment_entry: Any, clearance_date: Any = None) -> None:
		import frappe

		doctype = payment_entry.payment_document
		docname = payment_entry.payment_entry
		if doctype not in get_doctypes_for_bank_reconciliation():
			return
		if doctype == "Sales Invoice":
			frappe.db.set_value("Sales Invoice Payment", dict(parenttype=doctype, parent=docname), "clearance_date", clearance_date)
			return
		if not frappe.get_meta(doctype).has_field("clearance_date"):
			raise NotImplementedError(f"frappe stub: {doctype} has no clearance_date column in the reduced meta")
		frappe.db.set_value(doctype, docname, "clearance_date", clearance_date)


def get_doctypes_for_bank_reconciliation() -> list[str]:
	"""Get Bank Reconciliation doctypes from all the apps"""
	import frappe

	return frappe.get_hooks("bank_reconciliation_doctypes")


def get_total_allocated_amount(docs: list[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
	"""
	Gets the sum of allocations for a voucher on each bank GL account
	along with the latest bank transaction date
	NOTE: query may also include just saved vouchers/payments but with zero allocated_amount
	"""
	import frappe

	if not docs:
		return {}
	wanted = set(docs)
	out: dict[tuple[str, str], dict[str, Any]] = {}
	for row in frappe.get_all("Bank Transaction Payments", fields=["*"]):
		key = (row.payment_document, row.payment_entry)
		if key not in wanted:
			continue
		bt = frappe.db.get_value("Bank Transaction", row.parent, ["docstatus", "date", "bank_account"], as_dict=True)
		if not bt or int(bt.docstatus) != 1:
			continue
		gl_account = frappe.db.get_value("Bank Account", bt.bank_account, "account")
		bucket = out.setdefault(key, {}).setdefault(gl_account, {"total": 0.0, "latest_date": None, "gl_account": gl_account})
		bucket["total"] += flt(row.allocated_amount)
		date = getdate(bt.date)
		if bucket["latest_date"] is None or date > bucket["latest_date"]:
			bucket["latest_date"] = date
	return out


def get_related_bank_gl_entries(docs: list[tuple[str, str]]) -> dict[tuple[str, str], dict[str, float]]:
	import frappe

	if not docs:
		return {}
	wanted = set(docs)
	entries: dict[tuple[str, str], dict[str, float]] = {}
	for gle in frappe.get_all("GL Entry", fields=["*"], filters={"is_cancelled": 0}):
		key = (gle.voucher_type, gle.voucher_no)
		if key not in wanted:
			continue
		if frappe.db.get_value("Account", gle.account, "account_type") != "Bank":
			continue
		amount = abs(flt(gle.credit_in_account_currency) - flt(gle.debit_in_account_currency))
		entries.setdefault(key, {}).setdefault(gle.account, 0.0)
		entries[key][gle.account] += amount
	return entries


def get_clearance_details(
	transaction: Any, payment_entry: Any, bt_allocations: dict[str, Any], gl_entries: dict[str, float], gl_bank_account: str
) -> tuple[float, bool, Any]:
	"""
	There should only be one bank gl entry for a voucher, except for JE.
	For JE, there can be multiple bank gl entries for the same account.
	In this case, the allocable_amount will be the sum of amounts of all gl entries of the account.
	There will be no gl entry for a Bank Transaction so return the unallocated amount.
	Should only clear the voucher if all bank gl entries are allocated.
	"""
	import frappe

	transaction_date = getdate(transaction.date)
	if payment_entry.payment_document == "Bank Transaction":
		bt = frappe.db.get_value(
			"Bank Transaction", payment_entry.payment_entry, ("unallocated_amount", "bank_account"), as_dict=True
		)
		bt_bank_account = frappe.db.get_value("Bank Account", bt.bank_account, "account")
		if bt_bank_account != gl_bank_account:
			raise ValidationError(
				f"Bank Account {bt_bank_account} in Bank Transaction {payment_entry.payment_entry} is not matching with Bank Account {gl_bank_account}"
			)
		return abs(flt(bt.unallocated_amount)), True, transaction_date

	if gl_bank_account not in gl_entries:
		raise ValidationError(
			f"{payment_entry.payment_document} {payment_entry.payment_entry} is not affecting bank account {gl_bank_account}"
		)
	allocable_amount = gl_entries.pop(gl_bank_account) or 0
	if allocable_amount <= 0.0:
		raise ValidationError(
			f"Invalid amount in accounting entries of {payment_entry.payment_document} {payment_entry.payment_entry} for Account {gl_bank_account}: {allocable_amount}"
		)
	matching_bt_allocation = bt_allocations.pop(gl_bank_account, {})
	allocable_amount = flt(allocable_amount - matching_bt_allocation.get("total", 0), transaction.precision("unallocated_amount"))
	should_clear = all(
		gl_entries[gle_account] == bt_allocations.get(gle_account, {}).get("total", 0) for gle_account in gl_entries
	)
	bt_allocation_date = matching_bt_allocation.get("latest_date", None)
	clearance_date = transaction_date if not bt_allocation_date else max(transaction_date, bt_allocation_date)
	return allocable_amount, should_clear, clearance_date


def get_reconciled_bank_transactions(doctype: str, docname: str) -> list[str]:
	import frappe

	return frappe.get_all("Bank Transaction Payments", filters={"payment_document": doctype, "payment_entry": docname}, pluck="parent")
