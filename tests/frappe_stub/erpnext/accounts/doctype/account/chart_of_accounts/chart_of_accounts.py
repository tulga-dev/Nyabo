"""``create_charts`` (erpnext/accounts/doctype/account/chart_of_accounts/chart_of_accounts.py).

The loop is the version-16 one: metadata keys are skipped, ``is_group`` is taken from
the node or inferred from having children, ``report_type`` follows ``root_type``, a
duplicate ``<number> - <name>`` gets a numeric suffix, and every Account is inserted with
``ignore_permissions`` (roots also ``ignore_mandatory``). Only ``custom_chart`` is
supported: the Standard / country templates are not shipped with the stub.
"""

from __future__ import annotations

from typing import Any

from frappe.utils.data import cstr


def get_chart_metadata_fields() -> list[str]:
	return [
		"account_name",
		"account_number",
		"account_type",
		"account_category",
		"root_type",
		"is_group",
		"tax_rate",
		"account_currency",
	]


def identify_is_group(child: dict[str, Any]) -> int:
	if child.get("is_group"):
		return child.get("is_group")
	if len(set(child.keys()) - set(get_chart_metadata_fields())):
		return 1
	return 0


def add_suffix_if_duplicate(account_name: str, account_number: str, accounts: list[str]) -> tuple[str, str]:
	if account_number:
		account_name_in_db = " - ".join([account_number, account_name.strip().lower()])
	else:
		account_name_in_db = account_name.strip().lower()
	if account_name_in_db in accounts:
		count = accounts.count(account_name_in_db)
		account_name = account_name + " " + cstr(count)
	return account_name, account_name_in_db


def get_chart(chart_template: str | None, existing_company: str | None = None) -> Any:
	raise NotImplementedError(
		f"frappe stub: chart template {chart_template!r} is not shipped; pass custom_chart=... to create_charts"
	)


def create_charts(
	company: str,
	chart_template: str | None = None,
	existing_company: str | None = None,
	custom_chart: dict[str, Any] | None = None,
	from_coa_importer: bool | None = None,
) -> None:
	import frappe

	chart = custom_chart or get_chart(chart_template, existing_company)
	if not chart:
		return
	accounts: list[str] = []

	def _import_accounts(
		children: dict[str, Any], parent: str | None, root_type: str | None, root_account: bool = False
	) -> None:
		for account_name, child in children.items():
			if root_account:
				root_type = child.get("root_type")
			if account_name in get_chart_metadata_fields():
				continue
			account_number = cstr(child.get("account_number")).strip()
			account_name, account_name_in_db = add_suffix_if_duplicate(account_name, account_number, accounts)
			is_group = identify_is_group(child)
			report_type = (
				"Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
			)
			account = frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": child.get("account_name") if from_coa_importer else account_name,
					"company": company,
					"parent_account": parent,
					"is_group": is_group,
					"root_type": root_type,
					"report_type": report_type,
					"account_number": account_number,
					"account_type": child.get("account_type"),
					"account_category": child.get("account_category"),
					"account_currency": child.get("account_currency")
					if custom_chart
					else frappe.get_cached_value("Company", company, "default_currency"),
					"tax_rate": child.get("tax_rate"),
				}
			)
			if root_account or frappe.local.flags.allow_unverified_charts:
				account.flags.ignore_mandatory = True
			account.flags.ignore_permissions = True
			account.insert()
			accounts.append(account_name_in_db)
			_import_accounts(child, account.name, root_type)

	frappe.local.flags.ignore_update_nsm = True
	_import_accounts(chart, None, None, root_account=True)
	frappe.local.flags.ignore_update_nsm = False
