"""ERPNext stub package: the version-16 helpers Nyabo calls, on top of the frappe stub."""

from __future__ import annotations

from typing import Any

__version__ = "16.34.0"


def get_default_company(user: str | None = None) -> Any:
	import frappe

	return frappe.defaults.get_user_default("Company", user)


def get_default_currency() -> Any:
	import frappe

	company = get_default_company()
	if company:
		return frappe.get_cached_value("Company", company, "default_currency")
	return None


def get_company_currency(company: str) -> Any:
	import frappe

	return frappe.get_cached_value("Company", company, "default_currency")


def is_perpetual_inventory_enabled(company: str) -> int:
	import frappe
	from frappe.utils.data import cint

	return cint(frappe.get_cached_value("Company", company, "enable_perpetual_inventory"))


def encode_company_abbr(name: str, company: str | None = None, abbr: str | None = None) -> str:
	"""Suffix ``name`` with the company abbreviation if it is not already there."""
	import frappe

	company_abbr = abbr or frappe.get_cached_value("Company", company, "abbr")
	parts = name.rsplit(" - ", 1)
	if parts[-1].lower() != company_abbr.lower():
		parts.append(company_abbr)
	return " - ".join(parts)
