"""Role -> ERPNext Account for reports (input_vat, output_vat, cash, bank, ...).

The report code never names an account: it asks for a *role*; ``nyabo_mn.rules.aliases``
maps the role to a code (``seed/code_roles.json`` for the company's chart scheme, Nyabo
Account Alias rows for the ``accountant`` scheme) and this module finds the Account row by
``account_number``. What stays here is the chart probe (COMP-05): the configured scheme is
trusted only when its cash-role code exists in the installed chart.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.core.rules_engine import MissingRuleError
from nyabo_mn.i18n import mn
from nyabo_mn.rules import aliases

DEFAULT_SCHEME = aliases.SCHEME_V1
CASH_BANK_TYPES: tuple[str, ...] = ("Cash", "Bank")


def _scheme_matches_chart(company: str, scheme: str) -> bool:
	"""A scheme fits the installed chart when its cash-role code is an account of the company."""
	code = aliases.code_roles().get(aliases.role_scheme(scheme), {}).get("cash")
	return bool(code) and account_by_number(company, code) is not None


def chart_scheme(company: str) -> str:
	"""The scheme in Nyabo Company Settings, checked against the chart that is really installed.

	The settings row carries a default (v0.3) before provisioning has chosen a chart, and
	Phase-0 companies run the V1 chart; trusting the field blindly would resolve input VAT
	to a code the chart does not have. The check is on the cash role, which every scheme has.
	"""
	configured = None
	if frappe.db.exists("DocType", "Nyabo Company Settings"):
		configured = frappe.db.get_value("Nyabo Company Settings", {"company": company}, "chart_scheme")
	if configured and _scheme_matches_chart(company, configured):
		return configured
	for scheme in (DEFAULT_SCHEME, aliases.SCHEME_V03):
		if _scheme_matches_chart(company, scheme):
			return scheme
	return configured or DEFAULT_SCHEME


def role_code(company: str, role: str) -> str | None:
	"""Account code for the role in the company's (probed) scheme, or None when the scheme has none.

	``rules.aliases`` owns the role table and the alias hops; a null role (CORE-13) is
	reported as None here so the caller can refuse with the Mongolian message.
	"""
	scheme = chart_scheme(company)
	try:
		code = aliases.role_code(role, scheme)
	except MissingRuleError:
		return None
	if scheme != aliases.SCHEME_ACCOUNTANT:
		return code
	return aliases.alias_target(company, code, aliases.ALIAS_SCHEME_TEMPLATE) or code


def account_by_number(company: str, code: str) -> str | None:
	return frappe.db.get_value("Account", {"company": company, "account_number": str(code)}, "name")


def role_account(company: str, role: str) -> str:
	"""ERPNext Account name for the role; refuses (Mongolian) when the chart has no such account."""
	code = role_code(company, role)
	account = account_by_number(company, code) if code else None
	if not account:
		frappe.throw(mn.MSG_ACCOUNT_UNKNOWN.format(account=f"{role} ({code or '-'})"))
	return account


def role_account_or_none(company: str, role: str) -> str | None:
	code = role_code(company, role)
	return account_by_number(company, code) if code else None


def cash_bank_accounts(company: str) -> list[str]:
	"""Ledger accounts of type Cash/Bank plus the cash/bank role accounts (MoF МГ-1/МГ-2 scope)."""
	names = frappe.get_all(
		"Account",
		filters={"company": company, "account_type": ["in", list(CASH_BANK_TYPES)], "is_group": 0},
		pluck="name",
	)
	for role in ("cash", "bank", "petty_cash"):
		account = role_account_or_none(company, role)
		if account and account not in names:
			names.append(account)
	return names


def account_numbers(company: str) -> dict[str, str]:
	"""{account name: account_number} for the company (empty string when unnumbered)."""
	rows = frappe.get_all("Account", filters={"company": company}, fields=["name", "account_number"])
	return {r.name: r.account_number or "" for r in rows}


def accounts_by_root_type(company: str, root_types: tuple[str, ...]) -> list[str]:
	return frappe.get_all(
		"Account",
		filters={"company": company, "root_type": ["in", list(root_types)], "is_group": 0},
		pluck="name",
	)


def account_currency(account: str) -> Any:
	return frappe.db.get_value("Account", account, "account_currency")
