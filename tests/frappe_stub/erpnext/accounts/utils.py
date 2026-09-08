"""erpnext.accounts.utils: ``get_balance_on``, ``get_fiscal_year``, ``get_autoname_with_number``.

``get_balance_on`` sums the stub's GL Entry rows exactly as the SQL in
erpnext/accounts/utils.py (version-16) does: ``is_cancelled = 0``, ``posting_date <= date``
(default: everything up to today), the account or, for a group, all its descendants,
``debit_in_account_currency - credit_in_account_currency`` unless the group's currency is
the company currency. A date outside every Fiscal Year returns 0.0, as ERPNext does.
"""

from __future__ import annotations

from typing import Any

from frappe._stub.dictlike import _dict
from frappe.exceptions import ValidationError
from frappe.utils.data import cstr, flt, formatdate, getdate, nowdate


class FiscalYearError(ValidationError):
	pass


class PaymentEntryUnlinkError(ValidationError):
	pass


def get_autoname_with_number(number_value: Any, doc_title: str, company: str) -> str:
	"""append title with prefix as number and suffix as company's abbreviation separated by '-'"""
	import frappe

	company_abbr = frappe.get_cached_value("Company", company, "abbr")
	parts = [doc_title.strip(), company_abbr]
	if cstr(number_value).strip():
		parts.insert(0, cstr(number_value).strip())
	return " - ".join(parts)


def _get_fiscal_years(company: str | None = None) -> list[_dict]:
	import frappe

	rows = frappe.get_all(
		"Fiscal Year",
		fields=["name", "year_start_date", "year_end_date", "disabled"],
		filters={"disabled": 0},
		order_by="year_start_date desc",
	)
	return [_dict(r) for r in rows]


def get_fiscal_years(
	transaction_date: Any = None,
	fiscal_year: str | None = None,
	label: str = "Date",
	verbose: int = 1,
	company: str | None = None,
	as_dict: bool = False,
	boolean: bool | None = None,
	raise_on_missing: bool = True,
) -> Any:
	import frappe

	if transaction_date:
		transaction_date = getdate(transaction_date)
	if boolean is not None:
		raise_on_missing = not boolean
	all_fiscal_years = _get_fiscal_years(company=company)
	if not transaction_date and not fiscal_year:
		return all_fiscal_years
	for fy in all_fiscal_years:
		if (fiscal_year and fy.name == fiscal_year) or (
			transaction_date and getdate(fy.year_start_date) <= transaction_date <= getdate(fy.year_end_date)
		):
			if as_dict:
				return (fy,)
			return ((fy.name, fy.year_start_date, fy.year_end_date),)
	if raise_on_missing:
		error_msg = f"{label} {formatdate(transaction_date)} is not in any active Fiscal Year"
		if company:
			error_msg = f"{error_msg} for {frappe.bold(company)}"
		if verbose == 1:
			frappe.msgprint(error_msg)
		raise FiscalYearError(error_msg)
	return []


def get_fiscal_year(
	date: Any = None,
	fiscal_year: str | None = None,
	label: str = "Date",
	verbose: int = 1,
	company: str | None = None,
	as_dict: bool = False,
	boolean: bool | None = None,
	raise_on_missing: bool = True,
	truncate: bool = False,
) -> Any:
	fiscal_years = get_fiscal_years(
		date,
		fiscal_year,
		label,
		verbose,
		company,
		as_dict=as_dict,
		boolean=boolean,
		raise_on_missing=raise_on_missing,
	)
	if fiscal_years:
		return fiscal_years[0]
	return False


def _descendant_accounts(account: str) -> set[str]:
	import frappe

	rows = frappe.get_all("Account", fields=["name", "parent_account"])
	children: dict[str, list[str]] = {}
	for row in rows:
		children.setdefault(row.parent_account, []).append(row.name)
	out: set[str] = set()
	stack = [account]
	while stack:
		current = stack.pop()
		out.add(current)
		stack.extend(children.get(current, []))
	return out


def get_balance_on(
	account: str | None = None,
	date: Any = None,
	party_type: str | None = None,
	party: str | None = None,
	company: str | None = None,
	in_account_currency: bool = True,
	cost_center: str | None = None,
	ignore_account_permission: bool = False,
	account_type: str | None = None,
	start_date: Any = None,
	finance_book: str | None = None,
	include_default_fb_balances: bool = False,
) -> float | None:
	import frappe

	if not date:
		date = nowdate()
	date = getdate(date)
	if account:
		acc = frappe.get_doc("Account", account)
	try:
		get_fiscal_year(date, company=company, verbose=0)
	except FiscalYearError:
		if date > getdate(nowdate()):
			get_fiscal_year(nowdate(), verbose=1)
		else:
			return 0.0
	if not (account or (party_type and party) or account_type):
		return None
	if cost_center:
		raise NotImplementedError("frappe stub: get_balance_on(cost_center=...) is not implemented")
	if finance_book:
		raise NotImplementedError("frappe stub: get_balance_on(finance_book=...) is not implemented")

	accounts: set[str] | None = None
	if account:
		if acc.is_group:
			accounts = _descendant_accounts(account)
			if acc.account_currency == frappe.get_cached_value("Company", acc.company, "default_currency"):
				in_account_currency = False
		else:
			accounts = {account}
	debit_field = "debit_in_account_currency" if in_account_currency else "debit"
	credit_field = "credit_in_account_currency" if in_account_currency else "credit"
	total = 0.0
	for row in frappe.get_all("GL Entry", fields=["*"]):
		if row.is_cancelled:
			continue
		if accounts is not None and row.account not in accounts:
			continue
		if party_type and party and (row.party_type != party_type or row.party != party):
			continue
		if account_type and frappe.db.get_value("Account", row.account, "account_type") != account_type:
			continue
		if company and row.company != company:
			continue
		if row.posting_date is None or getdate(row.posting_date) > date:
			continue
		if start_date and getdate(row.posting_date) < getdate(start_date):
			continue
		total += flt(row.get(debit_field)) - flt(row.get(credit_field))
	return flt(total, 2)


def get_account_currency(account: str | None) -> Any:
	import frappe

	if not account:
		return None
	account_currency, company = frappe.get_cached_value("Account", account, ["account_currency", "company"])
	if not account_currency:
		account_currency = frappe.get_cached_value("Company", company, "default_currency")
	return account_currency


def get_company_default(company: str, fieldname: str, ignore_validation: bool = False) -> Any:
	import frappe

	value = frappe.get_cached_value("Company", company, fieldname)
	if not value and not ignore_validation:
		label = frappe.get_meta("Company").get_label(fieldname)
		raise ValidationError(f"Please set default {label} in Company {company}")
	return value
