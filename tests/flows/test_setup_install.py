"""after_install / after_migrate: custom fields, seed, report templates, FX provider off; idempotent."""

from __future__ import annotations

import frappe

from nyabo_mn.nyabo.seed import load_seed
from nyabo_mn.setup.install import after_install, after_migrate


def test_install_and_migrate_are_idempotent(site):
	after_install()
	assert frappe.db.exists("Custom Field", "Journal Entry-nyabo_primary_document_ref")
	assert frappe.db.count("Nyabo Tax Parameter") == len(load_seed("tax_parameters")["rows"])
	assert frappe.db.count("Nyabo Posting Pattern") == len(load_seed("posting_patterns")["rows"])
	assert frappe.db.count("Nyabo Bank Layout") == len(load_seed("bank_layouts")["rows"])
	assert len(frappe._stub.calls("sync_financial_report_templates")) == 1

	frappe.db.set_value("Nyabo Bank Layout", "khan_bank_xlsx", "verified", 1)
	after_migrate()
	assert frappe.db.count("Nyabo Tax Parameter") == len(load_seed("tax_parameters")["rows"])
	assert frappe.db.get_value("Nyabo Bank Layout", "khan_bank_xlsx", "verified") == 1
	assert len(frappe._stub.calls("sync_financial_report_templates")) == 2
	assert frappe.db.count("Custom Field", {"dt": "Supplier"}) == 5
