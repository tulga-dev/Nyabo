"""Turn codes, aliases and roles into the company's own chart codes and ERPNext accounts.

Resolution order (docs/ARCHITECTURE.md §4 Nyabo Account Alias, seed/README code_roles):

1. `role:<name>` -> `code_roles.json[scheme][name]`; a null role raises MissingRuleError
   so the proposal is marked needs_accountant instead of guessing an account;
2. Nyabo Account Alias rows of the company (`alias_code` in scheme v1 / accountant / mof
   -> `target_code` in the installed chart), followed for up to three hops so a V1 code
   reaches an accountant's chart through the v0.3 template;
3. identity: the code is already a chart code.

The company's chart scheme comes from Nyabo Company Settings; a company provisioned
before the settings existed is treated as V1, the only chart Phase 0 installed.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.core.rules_engine import MissingRuleError
from nyabo_mn.i18n import mn
from nyabo_mn.nyabo.seed import load_seed
from nyabo_mn.setup.chart_db import account_for_code

ALIAS_DOCTYPE = "Nyabo Account Alias"
SCHEME_V1 = "v1"
SCHEME_V03 = "v03"
SCHEME_ACCOUNTANT = "accountant"
CHART_SCHEMES: tuple[str, ...] = (SCHEME_V1, SCHEME_V03, SCHEME_ACCOUNTANT)
# Alias rows of a company on the accountant's chart map v0.3 template codes ("mof",
# the Ministry of Finance model chart) and V1 codes to the accountant's codes.
ALIAS_SCHEME_TEMPLATE = "mof"
ROLE_PREFIX = "role:"
MAX_HOPS = 3


def code_roles() -> dict[str, dict[str, str | None]]:
	return load_seed("code_roles")["schemes"]


def role_scheme(chart_scheme: str) -> str:
	"""The accountant's chart has no role table; its roles resolve through the v0.3 template + aliases."""
	return SCHEME_V03 if chart_scheme == SCHEME_ACCOUNTANT else chart_scheme


def chart_scheme(company: str) -> str:
	value = None
	if frappe.db.exists("DocType", "Nyabo Company Settings"):
		value = frappe.db.get_value("Nyabo Company Settings", {"company": company}, "chart_scheme")
	return str(value) if value in CHART_SCHEMES else SCHEME_V1


def role_code(role: str, scheme: str) -> str:
	"""The template code of a role in a chart scheme; null roles refuse (D-013)."""
	table = code_roles().get(role_scheme(scheme)) or {}
	code = table.get(role)
	if not code:
		raise MissingRuleError(
			f"role {role!r} has no account in scheme {scheme!r}",
			mn.MSG_ROLE_UNRESOLVED.format(role=role, scheme=scheme),
		)
	return str(code)


def in_chart(company: str, code: str) -> bool:
	"""True when the company's installed chart has an account with this number."""
	return bool(frappe.db.exists("Account", {"company": company, "account_number": str(code)}))


def alias_target(company: str, alias_code: str, scheme: str | None = None) -> str | None:
	"""target_code of an alias row for the company (any alias scheme unless one is given)."""
	filters: dict[str, Any] = {"company": company, "alias_code": str(alias_code)}
	if scheme:
		filters["scheme"] = scheme
	return frappe.db.get_value(ALIAS_DOCTYPE, filters, "target_code")


def resolve_code(company: str, code_or_alias: str, scheme: str | None = None) -> str:
	"""Chart code for a role selector, an aliased code or a plain code (see module docstring).

	`scheme` restricts the alias lookup to one alias scheme (v1 / accountant / mof); the
	role table always follows the company's chart scheme.
	"""
	value = str(code_or_alias).strip()
	company_scheme = chart_scheme(company)
	if value.startswith(ROLE_PREFIX):
		value = role_code(value[len(ROLE_PREFIX) :], company_scheme)
		if company_scheme != SCHEME_ACCOUNTANT:
			return value  # the role table already names a code of the installed chart
		scheme = scheme or ALIAS_SCHEME_TEMPLATE
	elif in_chart(company, value):
		# V1 and v0.3 share codes such as 6110 with different meanings: a code that exists in
		# the installed chart is that account, never an alias (D-017).
		return value
	seen = {value}
	for _ in range(MAX_HOPS):
		target = alias_target(company, value, scheme)
		if not target or target in seen:
			break
		seen.add(target)
		value = str(target)
		if in_chart(company, value):
			break  # an alias target that is a chart account is final; a further hop would re-read it as another scheme's code
	return value


def account_for(company: str, code_or_alias: str, scheme: str | None = None, *, leaf: bool = True) -> str:
	"""ERPNext account name for a code, alias or role (raises ChartError when the chart lacks it)."""
	return account_for_code(company, resolve_code(company, code_or_alias, scheme), leaf=leaf)


def resolver(company: str) -> Any:
	"""`resolve_code` bound to a company: the callable `core.rules_engine.instantiate` takes."""

	def _resolve(selector: str) -> str:
		return resolve_code(company, selector)

	return _resolve


def upsert_alias(
	company: str,
	scheme: str,
	alias_code: str,
	target_code: str,
	*,
	note: str = "",
	target_account: str | None = None,
) -> str:
	"""Create or update one alias row; returns its name."""
	name = f"{company}:{scheme}:{alias_code}"
	if frappe.db.exists(ALIAS_DOCTYPE, name):
		doc = frappe.get_doc(ALIAS_DOCTYPE, name)
		doc.target_code = target_code
	else:
		doc = frappe.get_doc(
			{
				"doctype": ALIAS_DOCTYPE,
				"company": company,
				"scheme": scheme,
				"alias_code": alias_code,
				"target_code": target_code,
			}
		)
	if note:
		doc.note = note
	if target_account:
		doc.target_account = target_account
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def seed_v1_aliases(company: str, *, to_codes: dict[str, str] | None = None) -> int:
	"""V1 -> v0.3 aliases for a company on the v0.3 chart (or, via `to_codes`, on the accountant's).

	`to_codes` maps v0.3 template codes to the installed chart's codes; a V1 code whose
	v0.3 target is not in the map gets no alias (reported by the caller).
	"""
	mapping = {
		k: v for k, v in load_seed("aliases_v1_to_v03").items() if not k.startswith("_") and k != "unmapped"
	}
	count = 0
	for v1_code, v03_code in mapping.items():
		target = str(v03_code) if to_codes is None else to_codes.get(str(v03_code))
		if not target:
			continue
		upsert_alias(company, SCHEME_V1, str(v1_code), target)
		count += 1
	return count
