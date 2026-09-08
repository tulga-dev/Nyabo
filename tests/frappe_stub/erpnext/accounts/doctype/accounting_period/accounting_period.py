"""Accounting Period (erpnext/accounts/doctype/accounting_period/accounting_period.py).

Verbatim semantics: name ``<period_name> - <abbr>``, start <= end, end not in the future,
no overlap per company, ``closed_documents`` bootstrapped from the
``period_closing_doctypes`` hook on insert, and ``validate_accounting_period_on_doc_save``
refusing a posting whose date falls in an enabled closed period unless the user holds
the period's ``exempted_role``.
"""

from __future__ import annotations

from typing import Any

from frappe.exceptions import ValidationError
from frappe.model.document import Document
from frappe.utils.data import formatdate, getdate, nowdate


class OverlapError(ValidationError):
	pass


class ClosedAccountingPeriod(ValidationError):
	pass


class AccountingPeriod(Document):
	def validate(self) -> None:
		self.validate_dates()
		self.validate_overlap()

	def validate_dates(self) -> None:
		import frappe

		if getdate(self.start_date) > getdate(self.end_date):
			raise ValidationError("Start Date cannot be after End Date")
		if getdate(self.end_date) > getdate(nowdate()):
			raise ValidationError(
				"Accounting Period cannot be created for a future date. End Date {0} is after today.".format(
					frappe.bold(formatdate(self.end_date))
				)
			)

	def before_insert(self) -> None:
		self.bootstrap_doctypes_for_closing()

	def autoname(self) -> None:
		import frappe

		company_abbr = frappe.get_cached_value("Company", self.company, "abbr")
		self.name = " - ".join([self.period_name, company_abbr])

	def validate_overlap(self) -> None:
		import frappe

		start, end = getdate(self.start_date), getdate(self.end_date)
		for row in frappe.get_all(
			"Accounting Period", fields=["name", "start_date", "end_date"], filters={"company": self.company}
		):
			if row.name == self.name:
				continue
			other_start, other_end = getdate(row.start_date), getdate(row.end_date)
			if (
				other_start <= start <= other_end
				or other_start <= end <= other_end
				or start <= other_start <= end
				or start <= other_end <= end
			):
				raise OverlapError(f"Accounting Period overlaps with {row.name}")

	def get_doctypes_for_closing(self) -> list[dict[str, Any]]:
		import frappe

		return [{"document_type": doctype, "closed": 1} for doctype in frappe.get_hooks("period_closing_doctypes")]

	def bootstrap_doctypes_for_closing(self) -> None:
		if len(self.closed_documents or []) == 0:
			for doctype_for_closing in self.get_doctypes_for_closing():
				self.append(
					"closed_documents",
					{"document_type": doctype_for_closing["document_type"], "closed": doctype_for_closing["closed"]},
				)


def validate_accounting_period_on_doc_save(doc: Any, method: str | None = None) -> None:
	import frappe

	if doc.doctype == "Bank Clearance":
		return
	if doc.doctype == "Asset":
		if doc.asset_type == "Existing Asset":
			return
		date = doc.available_for_use_date
	elif doc.doctype == "Asset Repair":
		date = doc.completion_date
	elif doc.doctype == "Period Closing Voucher":
		date = doc.period_end_date
	else:
		date = doc.posting_date
	if not date:
		return
	date = getdate(date)
	for period in frappe.get_all(
		"Accounting Period",
		fields=["name", "exempted_role", "start_date", "end_date"],
		filters={"company": doc.company, "disabled": 0},
	):
		if not (getdate(period.start_date) <= date <= getdate(period.end_date)):
			continue
		closed = frappe.get_all(
			"Closed Document",
			filters={"parent": period.name, "parenttype": "Accounting Period", "document_type": doc.doctype, "closed": 1},
		)
		if not closed:
			continue
		if period.exempted_role and period.exempted_role in frappe.get_roles():
			return
		raise ClosedAccountingPeriod(
			f"You cannot create a {doc.doctype} within the closed Accounting Period {frappe.bold(period.name)}"
		)
