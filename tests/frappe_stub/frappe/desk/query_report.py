"""``frappe.desk.query_report.run`` for Script Reports shipped by this app.

Mirrors frappe/desk/query_report.py (version-16): ``run`` resolves the Report, checks the
Report's roles, calls the report module's ``execute(filters)`` and returns the same dict
(``result, columns, message, chart, report_summary, skip_total_row, status,
execution_time``). Reports are found in the stub's Report table first (inserted by a test
or by fixtures) and otherwise by their JSON under ``nyabo_mn/nyabo/report/<scrub>/``.
ERPNext's own reports (Trial Balance, Balance Sheet, ...) are not shipped: running one
raises ``NotImplementedError`` naming it.
"""

from __future__ import annotations

import importlib
import json
import os
from typing import Any

from frappe._stub.dictlike import _dict
from frappe.exceptions import DoesNotExistError, PermissionError

NYABO_REPORT_ROOT = "nyabo_mn.nyabo.report"


def _scrub(name: str) -> str:
	import frappe

	return frappe.scrub(name)


def get_report_doc(report_name: str) -> _dict:
	import frappe

	if frappe.db.exists("Report", report_name):
		doc = frappe.get_doc("Report", report_name)
		return _dict(doc.as_dict())
	path = frappe.get_app_path("nyabo_mn", "nyabo", "report", _scrub(report_name), f"{_scrub(report_name)}.json")
	if os.path.exists(path):
		with open(path, encoding="utf-8") as f:
			raw = json.load(f)
		raw.setdefault("report_name", report_name)
		raw.setdefault("report_type", "Script Report")
		raw.setdefault("module", "Nyabo")
		return _dict(raw)
	raise DoesNotExistError(
		f"frappe stub: Report {report_name!r} is neither in the Report table nor under nyabo_mn/nyabo/report; "
		"ERPNext's standard reports are not available in the stub"
	)


def _report_module(report: _dict) -> Any:
	if (report.get("module") or "Nyabo") != "Nyabo":
		raise NotImplementedError(
			f"frappe stub: report {report.report_name!r} belongs to module {report.module!r}; only Nyabo reports run here"
		)
	scrubbed = _scrub(report.report_name)
	return importlib.import_module(f"{NYABO_REPORT_ROOT}.{scrubbed}.{scrubbed}")


def _check_roles(report: _dict) -> None:
	import frappe

	roles = [r.get("role") for r in (report.get("roles") or []) if r.get("role")]
	if not roles or frappe.session.user == "Administrator":
		return
	if not set(roles).intersection(frappe.get_roles()):
		raise PermissionError(f"Not permitted to run report {report.report_name}")


def generate_report_result(
	report: _dict,
	filters: Any = None,
	user: str | None = None,
	custom_columns: Any = None,
	is_tree: bool = False,
	parent_field: str | None = None,
) -> dict[str, Any]:
	if report.get("report_type") != "Script Report":
		raise NotImplementedError(
			f"frappe stub: only Script Reports run; {report.report_name!r} is a {report.get('report_type')!r}"
		)
	module = _report_module(report)
	res = module.execute(_dict(filters or {}))
	columns, result = res[0], res[1]
	message = res[2] if len(res) > 2 else None
	chart = res[3] if len(res) > 3 else None
	report_summary = res[4] if len(res) > 4 else None
	skip_total_row = res[5] if len(res) > 5 else 0
	return {
		"result": result,
		"columns": columns,
		"message": message,
		"chart": chart,
		"report_summary": report_summary,
		"skip_total_row": skip_total_row or 0,
		"status": None,
		"execution_time": 0,
	}


def run(
	report_name: str,
	filters: Any = None,
	user: str | None = None,
	ignore_prepared_report: bool = False,
	custom_columns: Any = None,
	is_tree: bool = False,
	parent_field: str | None = None,
	are_default_filters: bool = True,
	js_filters: Any = None,
) -> dict[str, Any]:
	if isinstance(filters, str):
		filters = json.loads(filters)
	report = get_report_doc(report_name)
	_check_roles(report)
	return generate_report_result(report, filters, user, custom_columns, is_tree, parent_field)


def get_script(report_name: str) -> dict[str, Any]:
	raise NotImplementedError("frappe stub: client scripts of reports are not served")
