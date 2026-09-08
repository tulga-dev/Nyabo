"""Role -> ERPNext Account for reports (input_vat, output_vat, cash, bank, ...).

The report code never names an account: it asks for a *role* and this module maps the
role to a code through ``seed/code_roles.json`` for the company's chart scheme, then to
the Account row by ``account_number``. The ``accountant`` scheme goes through Nyabo
Account Alias rows (the accountant's own codes mapped to v0.3 codes).

INTEGRATION: when ``nyabo_mn.rules.aliases`` (core+rules stage) lands, ``role_account``
should delegate to it; the public signatures here stay.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.i18n import mn
from nyabo_mn.nyabo.seed import load_seed

DEFAULT_SCHEME = "v1"
CASH_BANK_TYPES: tuple[str, ...] = ("Cash", "Bank")


def _schemes() -> dict[str, dict[str, str | None]]:
	return load_seed("code_roles")["schemes"]


def _scheme_matches_chart(company: str, scheme: str) -> bool:
	"""A scheme fits the installed chart when its cash-role code is an account of the company."""
	code = _schemes().get("v03" if scheme == "accountant" else scheme, {}).get("cash")
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
	for scheme in (DEFAULT_SCHEME, "v03"):
		if _scheme_matches_chart(company, scheme):
			return scheme
	return configured or DEFAULT_SCHEME


def role_code(company: str, role: str) -> str | None:
	"""Account code for the role in the company's scheme, or None when the scheme has none."""
	scheme = chart_scheme(company)
	lookup_scheme = "v03" if scheme == "accountant" else scheme
	code = _schemes().get(lookup_scheme, {}).get(role)
	if code is None or scheme != "accountant":
		return code
	target = frappe.db.get_value(
		"Nyabo Account Alias", {"company": company, "scheme": "accountant", "alias_code": code}, "target_code"
	)
	return target or code


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
