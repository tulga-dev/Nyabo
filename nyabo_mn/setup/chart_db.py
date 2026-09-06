"""Database side of the chart of accounts: install the tree, look accounts up by code."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from nyabo_mn.setup.chart import METADATA_KEYS, ChartError, NormalizedChart


def install_chart(company: str, chart: NormalizedChart) -> int:
	"""Create the chart's accounts for a company that has none yet. Returns the account count."""
	from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import create_charts

	if frappe.db.exists("Account", {"company": company}):
		raise ChartError(
			_("Company {0} already has accounts; the chart can only be installed on a fresh company").format(
				company
			)
		)

	tree = _drop_unknown_categories(chart.tree, chart.warnings)
	# Same flag ERPNext's Company.create_default_accounts sets before calling create_charts.
	frappe.local.flags.ignore_root_company_validation = True
	create_charts(company, custom_chart=tree)
	return frappe.db.count("Account", {"company": company})


def _drop_unknown_categories(tree: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
	"""Remove account_category values that do not exist on this site (older ERPNext, or renamed)."""
	known: set[str] = set()
	if frappe.db.exists("DocType", "Account Category"):
		known = set(frappe.get_all("Account Category", pluck="name"))

	def walk(node: dict[str, Any]) -> dict[str, Any]:
		out: dict[str, Any] = {}
		for key, value in node.items():
			if key == "account_category":
				if value and value not in known:
					warnings.append(f"account_category {value!r} does not exist on this site; skipped")
					continue
				out[key] = value
			elif key not in METADATA_KEYS and isinstance(value, dict):
				out[key] = walk(value)
			else:
				out[key] = value
		return out

	return {name: walk(node) for name, node in tree.items()}


def code_map(company: str) -> dict[str, str]:
	"""{account_number: account name} for every numbered account of the company."""
	rows = frappe.get_all(
		"Account",
		filters={"company": company, "account_number": ["!=", ""]},
		fields=["account_number", "name"],
	)
	return {r.account_number: r.name for r in rows}


def account_for_code(company: str, code: str, *, leaf: bool = True) -> str:
	"""Resolve a V1 code (e.g. "6210") to the ERPNext account name for the company."""
	row = frappe.db.get_value(
		"Account",
		{"company": company, "account_number": str(code)},
		["name", "is_group", "disabled"],
		as_dict=True,
	)
	if not row:
		raise ChartError(_("Account with code {0} does not exist for company {1}").format(code, company))
	if leaf and row.is_group:
		raise ChartError(_("Account {0} is a group account; a ledger account is required").format(row.name))
	if row.disabled:
		raise ChartError(_("Account {0} is disabled").format(row.name))
	return row.name
