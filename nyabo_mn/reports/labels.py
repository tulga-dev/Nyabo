"""Mongolian labels for Jinja print formats.

Print-format templates cannot import Python, and hard-coding Cyrillic in them would
break the one-place rule for user-facing text. The Jinja environment Frappe gives print
formats exposes ``frappe.call`` (frappe/utils/safe_exec.py ``get_safe_globals``:
``call_whitelisted_function``), so a template starts with
``{% set L = frappe.call("nyabo_mn.reports.labels.print_labels") %}`` and reads
``L.FORM_LBL_DATE``. Every ``FORM_*``, ``LBL_*``, ``COL_*`` and ``JOURNAL_*`` name is exported.
"""

from __future__ import annotations

import frappe

from nyabo_mn.i18n import mn

PREFIXES: tuple[str, ...] = ("FORM_", "LBL_", "COL_", "JOURNAL_", "REPORT_", "DEBIT_", "CREDIT_")


@frappe.whitelist()
def print_labels() -> dict[str, str]:
	"""Label name -> Mongolian text (strings only; dict/list constants are left out)."""
	return {
		name: value
		for name, value in vars(mn).items()
		if name.startswith(PREFIXES) and isinstance(value, str)
	}
