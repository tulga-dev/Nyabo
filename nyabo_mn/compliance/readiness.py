"""Nyabo's own certification readiness checklist (docs/mn-rules-reference.md §6.1).

``checks()`` inspects the site — files shipped by the app, hooks installed, rows in the
audit tables, per-company settings — and returns one row per ``mn.READINESS_ITEMS`` key.
Nothing is assumed: an item passes only when the artefact is really there. E-signature is
reported as failed on purpose until the MoF publishes the technical requirement.

The list is Nyabo's, not an instrument's. The certification procedure «Нягтлан бодох
бүртгэлийн программ хангамжид хяналт тавих журам» has not been obtained, so the report
claims no requirement numbers and says so in Mongolian (``mn.READINESS_SOURCE_PENDING``);
when the procedure text is fetched into ``docs/legal/`` the rows are mapped to it, with the
verbatim quotes ``docs/legal/README.md`` requires of any citation.

    bench --site <site> execute nyabo_mn.compliance.readiness.run
"""

from __future__ import annotations

import os
from typing import Any

import frappe
from frappe.utils import formatdate, nowdate

from nyabo_mn.i18n import mn

APP = "nyabo_mn"
REPORTS: dict[str, str] = {
	"general_journal": "nyabo_general_journal",
	"cash_journal": "nyabo_cash_journal",
}
ERPNEXT_REPORTS: dict[str, str] = {"general_ledger": "General Ledger", "trial_balance": "Trial Balance"}
PRINT_FORMATS: tuple[str, ...] = (
	"nyabo_cash_receipt_voucher",
	"nyabo_cash_payment_voucher",
	"nyabo_invoice",
	"nyabo_payment_order_list",
)
STATEMENT_TEMPLATES: dict[str, str] = {
	"balance_sheet": "nyabo_sme_balance_sheet_(mn)",
	"income_statement": "nyabo_sme_income_statement_(mn)",
	"equity_statement": "nyabo_sme_equity_statement",
	"cash_flow": "nyabo_sme_cash_flow",
}
TEMPLATES: tuple[str, ...] = ("report.html", "policy_document.html", "readiness.html")
HOOKS_REQUIRED: dict[str, tuple[tuple[str, str, str], ...]] = {
	"retention": (
		("File", "on_trash", "nyabo_mn.compliance.hooks.block_retained_file_delete"),
		("Nyabo Document", "before_insert", "nyabo_mn.compliance.hooks.stamp_retention"),
	),
	"primary_document_required": (
		("Purchase Invoice", "before_submit", "nyabo_mn.compliance.hooks.require_primary_document"),
		("Journal Entry", "before_submit", "nyabo_mn.compliance.hooks.require_primary_document"),
	),
	"corrections": (
		(
			"Purchase Invoice",
			"before_update_after_submit",
			"nyabo_mn.compliance.hooks.guard_no_edit_after_submit",
		),
		(
			"Journal Entry",
			"before_update_after_submit",
			"nyabo_mn.compliance.hooks.guard_no_edit_after_submit",
		),
	),
	"audit_trail": (
		("Nyabo Event", "before_save", "nyabo_mn.compliance.events.enforce_append_only"),
		("Nyabo Event", "on_trash", "nyabo_mn.compliance.events.block_delete"),
	),
	"period_lock": (("Accounting Period", "on_trash", "nyabo_mn.compliance.period.log_period_delete"),),
}


def _app_path(*parts: str) -> str:
	return frappe.get_app_path(APP, *parts)


def _module_file(*parts: str) -> bool:
	return os.path.isfile(_app_path("nyabo", *parts))


def _hooks_installed(entries: tuple[tuple[str, str, str], ...]) -> tuple[bool, str]:
	doc_hooks = frappe.get_doc_hooks()
	missing = [
		handler
		for doctype, event, handler in entries
		if handler not in (doc_hooks.get(doctype, {}).get(event) or [])
	]
	if missing:
		return False, mn.READINESS_DETAIL_MISSING.format(what=", ".join(missing))
	return True, mn.READINESS_DETAIL_HOOK.format(handler=entries[0][2])


def _count(doctype: str, filters: dict[str, Any] | None = None) -> int:
	if not frappe.db.exists("DocType", doctype):
		return 0
	return frappe.db.count(doctype, filters or {})


def _row(key: str, passed: bool, detail: str) -> dict[str, Any]:
	return {
		"key": key,
		"label_mn": mn.READINESS_ITEMS[key],
		"passed": bool(passed),
		"status_mn": mn.READINESS_PASS if passed else mn.READINESS_FAIL,
		"detail": detail,
	}


def _check_report(key: str) -> dict[str, Any]:
	scrub = REPORTS[key]
	present = _module_file("report", scrub, f"{scrub}.json") and _module_file("report", scrub, f"{scrub}.py")
	return _row(
		key, present, mn.READINESS_DETAIL_OK if present else mn.READINESS_DETAIL_MISSING.format(what=scrub)
	)


def _check_erpnext_report(key: str) -> dict[str, Any]:
	report = ERPNEXT_REPORTS[key]
	on_site = frappe.db.exists("Report", report) if frappe.db.exists("DocType", "Report") else None
	present = bool(on_site) or "erpnext" in frappe.get_installed_apps()
	return _row(key, present, mn.READINESS_DETAIL_ERPNEXT_REPORT.format(report=report))


def _check_statements() -> dict[str, Any]:
	present = [
		name
		for name, scrub in STATEMENT_TEMPLATES.items()
		if _module_file("financial_report_template", scrub, f"{scrub}.json")
	]
	missing = [name for name in STATEMENT_TEMPLATES if name not in present] + ["notes"]
	return _row(
		"statements",
		not missing,
		mn.READINESS_DETAIL_STATEMENTS.format(present=", ".join(present) or "-", missing=", ".join(missing)),
	)


def _check_primary_forms() -> dict[str, Any]:
	missing = [
		scrub
		for scrub in PRINT_FORMATS
		if not (
			_module_file("print_format", scrub, f"{scrub}.json")
			and _module_file("print_format", scrub, f"{scrub}.html")
		)
	]
	return _row(
		"primary_forms",
		not missing,
		mn.READINESS_DETAIL_OK
		if not missing
		else mn.READINESS_DETAIL_MISSING.format(what=", ".join(missing)),
	)


def _check_audit_trail() -> dict[str, Any]:
	ok, detail = _hooks_installed(HOOKS_REQUIRED["audit_trail"])
	tracked = all(
		bool(frappe.get_meta(dt).get("track_changes")) for dt in ("Purchase Invoice", "Journal Entry")
	)
	events = _count("Nyabo Event")
	detail = f"{detail}; {mn.READINESS_DETAIL_COUNT.format(count=events)}"
	return _row("audit_trail", ok and tracked, detail)


def _check_hooks(key: str) -> dict[str, Any]:
	ok, detail = _hooks_installed(HOOKS_REQUIRED[key])
	return _row(key, ok, detail)


def _check_corrections() -> dict[str, Any]:
	ok, detail = _hooks_installed(HOOKS_REQUIRED["corrections"])
	has_doctype = bool(frappe.db.exists("DocType", "Nyabo Correction"))
	return _row("corrections", ok and has_doctype, detail)


def _check_period_lock() -> dict[str, Any]:
	ok, detail = _hooks_installed(HOOKS_REQUIRED["period_lock"])
	has_doctype = bool(frappe.db.exists("DocType", "Accounting Period"))
	return _row("period_lock", ok and has_doctype, detail)


def _check_accountant_of_record() -> dict[str, Any]:
	rows = (
		frappe.get_all("Nyabo Company Settings", fields=["company", "accountant_of_record_name"])
		if frappe.db.exists("DocType", "Nyabo Company Settings")
		else []
	)
	ok_rows = [r for r in rows if (r.accountant_of_record_name or "").strip()]
	return _row(
		"accountant_of_record",
		bool(rows) and len(ok_rows) == len(rows),
		mn.READINESS_DETAIL_COMPANIES.format(ok=len(ok_rows), total=len(rows)),
	)


def _check_policy_document() -> dict[str, Any]:
	template = os.path.isfile(_app_path("templates", "policy_document.html"))
	attached = _count("File", {"attached_to_doctype": "Nyabo Company Settings"})
	detail = (
		mn.READINESS_DETAIL_OK
		if template
		else mn.READINESS_DETAIL_MISSING.format(what="policy_document.html")
	)
	return _row("policy_document", template, f"{detail}; {mn.READINESS_DETAIL_COUNT.format(count=attached)}")


def _check_rules_verified() -> dict[str, Any]:
	"""How many posting patterns may post, and on whose authority — all three of them, apart.

	A bare count would let a certification reader take 35 verified rows for 35 human decisions,
	while the flag on most of them came from the seed (DECISIONS VER-07). A rule one company's
	accountant accepted for their own books is a third thing again (ACC-01): it is a named
	person, but it speaks for one company and no citation stands behind it. Three claims, three
	numbers, never added together.

	The accepted number counts what is in force. An acceptance a deploy has outrun clears
	nothing — the guard refuses on it — so counting it reported more rules cleared than are, on
	the one page whose whole job is to be accurate about that. The outrun ones are shown as their
	own number when there are any: they are the queue of rules an accountant has to look at
	again, and a page that dropped them would hide work rather than report it.
	"""
	from nyabo_mn.rules import verify

	counts = verify.verified_counts("Nyabo Posting Pattern")
	accepted = verify.accepted_counts("Nyabo Posting Pattern")
	detail = mn.READINESS_DETAIL_RULES_VERIFIED.format(
		count=counts["verified"],
		by_seed=counts["by_seed"],
		by_person=counts["by_person"],
		accepted=accepted["rules"],
		companies=accepted["companies"],
	)
	if accepted["stale"]:
		detail += mn.READINESS_DETAIL_RULES_ACCEPTANCE_STALE.format(stale=accepted["stale"])
	return _row("rules_verified", counts["verified"] > 0, detail)


def checks(site: str | None = None) -> list[dict[str, Any]]:
	"""One row per READINESS_ITEMS key: {key, label_mn, passed, status_mn, detail}."""
	rows = [
		_check_report("general_journal"),
		_check_report("cash_journal"),
		_check_erpnext_report("general_ledger"),
		_check_erpnext_report("trial_balance"),
		_check_statements(),
		_check_primary_forms(),
		_check_audit_trail(),
		_check_hooks("retention"),
		_check_corrections(),
		_check_period_lock(),
		_check_hooks("primary_document_required"),
		_row("e_signature", False, mn.READINESS_E_SIGNATURE_PENDING),
		_check_accountant_of_record(),
		_check_policy_document(),
		_check_rules_verified(),
	]
	missing_templates = [t for t in TEMPLATES if not os.path.isfile(_app_path("templates", t))]
	if missing_templates:
		rows[13]["passed"] = False
		rows[13]["status_mn"] = mn.READINESS_FAIL
		rows[13]["detail"] = mn.READINESS_DETAIL_MISSING.format(what=", ".join(missing_templates))
	assert [r["key"] for r in rows] == list(mn.READINESS_ITEMS), "readiness rows must cover every item"
	return rows


def run(site: str | None = None) -> list[dict[str, Any]]:
	"""bench execute entry point: prints the table and returns the rows."""
	rows = checks(site)
	site_name = site or getattr(frappe.local, "site", "") or ""
	print(mn.READINESS_TITLE)
	print(mn.READINESS_SITE_LINE.format(site=site_name))
	width = max(len(r["label_mn"]) for r in rows)
	for row in rows:
		print(f"{row['status_mn']:>8}  {row['label_mn']:<{width}}  {row['detail']}")
	print(mn.READINESS_SOURCE_PENDING)
	return rows


def readiness_report_pdf(site: str | None = None) -> bytes:
	from frappe.utils.pdf import get_pdf

	rows = checks(site)
	html = frappe.render_template(
		"nyabo_mn/templates/readiness.html",
		{
			"title": mn.READINESS_TITLE,
			"site_line": mn.READINESS_SITE_LINE.format(site=site or getattr(frappe.local, "site", "") or ""),
			"prepared_on": formatdate(nowdate()),
			"rows": rows,
			"L": {
				"item": mn.READINESS_COL_ITEM,
				"status": mn.READINESS_COL_STATUS,
				"detail": mn.READINESS_COL_DETAIL,
			},
			"note": mn.READINESS_SOURCE_PENDING,
			"footer": mn.REPORT_PDF_FOOTER.format(source=mn.FORM_SOURCE_INTERNAL),
		},
	)
	return get_pdf(html, options={"page-size": "A4"})
