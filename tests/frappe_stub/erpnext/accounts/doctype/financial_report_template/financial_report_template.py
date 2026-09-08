"""``sync_financial_report_templates(chart_of_accounts=None, existing_company=None)``.

The version-16 function imports every installed app's ``financial_report_template``
folder (JSON per template plus ``account_categories.json``). The stub records the call
(``frappe._stub.calls("sync_financial_report_templates")``) and, for the Nyabo module
only, inserts any template JSON found under ``nyabo_mn/nyabo/financial_report_template``
that is not yet in the table, so tests can assert both the call and the rows.
"""

from __future__ import annotations

import json
import os
from typing import Any


def sync_financial_report_templates(chart_of_accounts: str | None = None, existing_company: str | None = None) -> None:
	import frappe

	frappe._stub.record_call(
		"sync_financial_report_templates", chart_of_accounts=chart_of_accounts, existing_company=existing_company
	)
	if existing_company:
		return
	_sync_templates_for("nyabo_mn")


def _sync_templates_for(app_name: str) -> None:
	import frappe

	templates: list[str] = []
	for module_name in frappe.local.app_modules.get(app_name) or []:
		template_path = os.path.join(frappe.get_module_path(module_name), "financial_report_template")
		if not os.path.isdir(template_path):
			continue
		import_account_categories(template_path)
		for template_dir in sorted(os.listdir(template_path)):
			json_file = os.path.join(template_path, template_dir, f"{template_dir}.json")
			if os.path.isfile(json_file):
				templates.append(json_file)
	for template_path in templates:
		with open(template_path, encoding="utf-8") as f:
			template_data: dict[str, Any] = json.load(f)
		template_name = template_data.get("name")
		if template_name and not frappe.db.exists("Financial Report Template", template_name):
			doc = frappe.get_doc(template_data)
			doc.flags.ignore_mandatory = True
			doc.flags.ignore_permissions = True
			doc.flags.ignore_validate = True
			doc.insert()


def import_account_categories(template_path: str) -> None:
	import frappe

	path = os.path.join(template_path, "account_categories.json")
	if not os.path.isfile(path):
		return
	with open(path, encoding="utf-8") as f:
		rows = json.load(f)
	for row in rows:
		name = row.get("account_category_name") or row.get("name")
		if name and not frappe.db.exists("Account Category", name):
			frappe.get_doc({"doctype": "Account Category", **{k: v for k, v in row.items() if k != "doctype"}}).insert(
				ignore_permissions=True
			)
