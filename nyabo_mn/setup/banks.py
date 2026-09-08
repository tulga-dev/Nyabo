"""One GL sub-account and one ERPNext Bank Account per bank account the owner names (§5.2 step 3).

The sub-accounts sit under the group that holds the scheme's `bank` role account
(class 11 "Банкинд байгаа мөнгө" on v0.3, group 1100 on V1) so the Balance Sheet keeps
one bank line and the Trial Balance shows each account. The code is the next free
sub-code of that group; the name is "<Bank in Mongolian> <currency> <last 4 digits>".

ERPNext side (fields verified in tests/frappe_stub/erpnext_meta.json): `Bank`
(`bank_name`, named by it) and `Bank Account` (`account_name`, `bank`, `account`,
`is_company_account`, `company`, `bank_account_no`; named "<account_name> - <bank>").
Everything is idempotent on (company, GL account).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import frappe

from nyabo_mn.i18n import mn
from nyabo_mn.rules import aliases

BANKS: tuple[str, ...] = tuple(mn.BANK_NAMES_MN)
# Digits a sub-code appends to the group's prefix: v0.3 leaves are CC+SS, V1 leaves 111+D.
SUB_CODE_DIGITS: dict[str, int] = {"v1": 1, "v03": 2, "accountant": 2}


def account_name_for(bank: str, currency: str, account_number: str | None) -> str:
	bank_mn = mn.BANK_NAMES_MN.get(bank)
	if not bank_mn:
		frappe.throw(mn.MSG_BANK_UNKNOWN.format(bank=bank))
	digits = "".join(ch for ch in (account_number or "") if ch.isdigit())
	suffix = f" {digits[-4:]}" if digits else ""
	return f"{bank_mn} {currency}{suffix}"


def bank_group(company: str) -> tuple[str, str]:
	"""(parent group account name, code of the scheme's bank leaf) for the company."""
	leaf = aliases.account_for(company, "role:bank")
	parent = frappe.db.get_value("Account", leaf, "parent_account")
	code = frappe.db.get_value("Account", leaf, "account_number")
	return parent, str(code)


def next_sub_code(company: str, base_code: str, scheme: str) -> str:
	"""Next free code with the base's prefix: 1101 -> 1103 on v0.3 (1102 taken), 1120 -> 1121 on V1."""
	digits = SUB_CODE_DIGITS.get(scheme, 2)
	prefix = base_code[:-digits]
	taken = set(
		frappe.get_all(
			"Account",
			filters={"company": company, "account_number": ["like", f"{prefix}%"]},
			pluck="account_number",
		)
	)
	for n in range(1, 10**digits):
		candidate = f"{prefix}{n:0{digits}d}"
		if candidate not in taken:
			return candidate
	raise frappe.ValidationError(f"no free sub-code left under {prefix}")


def ensure_bank_accounts(company: str, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
	"""Create the GL sub-account, Bank and Bank Account for each row; returns what exists now."""
	scheme = aliases.chart_scheme(company)
	parent, base_code = bank_group(company)
	out: list[dict[str, Any]] = []
	for row in rows:
		bank = str(row.get("bank") or "").strip()
		currency = str(row.get("currency") or "MNT").strip().upper()
		account_number = str(row.get("account_number") or "").strip() or None
		name = account_name_for(bank, currency, account_number)
		gl_account = frappe.db.get_value("Account", {"company": company, "account_name": name}, "name")
		if not gl_account:
			doc = frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": name,
					"account_number": next_sub_code(company, base_code, scheme),
					"parent_account": parent,
					"company": company,
					"account_type": "Bank",
					"account_currency": currency,
					"is_group": 0,
				}
			)
			doc.flags.ignore_permissions = True
			doc.insert()
			gl_account = doc.name
		if not frappe.db.exists("Bank", bank):
			frappe.get_doc({"doctype": "Bank", "bank_name": bank}).insert(ignore_permissions=True)
		bank_account = frappe.db.get_value(
			"Bank Account", {"company": company, "account": gl_account}, "name"
		)
		if not bank_account:
			doc = frappe.get_doc(
				{
					"doctype": "Bank Account",
					"account_name": name,
					"bank": bank,
					"account": gl_account,
					"is_company_account": 1,
					"company": company,
					"bank_account_no": account_number,
				}
			)
			doc.flags.ignore_permissions = True
			doc.insert()
			bank_account = doc.name
		out.append(
			{
				"bank": bank,
				"currency": currency,
				"account_number": account_number,
				"gl_account": gl_account,
				"erpnext_bank_account": bank_account,
			}
		)
	return out
