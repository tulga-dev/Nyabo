"""after_install / after_migrate: custom fields, seed, report templates, FX provider off; idempotent."""

from __future__ import annotations

import frappe

from nyabo_mn.nyabo.seed import load_seed
from nyabo_mn.setup.install import (
	CURRENCY_EXCHANGE_SETTINGS,
	_setup,
	after_install,
	after_migrate,
)


def test_install_and_migrate_are_idempotent(site):
	after_install()
	assert frappe.db.exists("Custom Field", "Journal Entry-nyabo_primary_document_ref")
	assert frappe.db.count("Nyabo Tax Parameter") == len(load_seed("tax_parameters")["rows"])
	assert frappe.db.count("Nyabo Posting Pattern") == len(load_seed("posting_patterns")["rows"])
	assert frappe.db.count("Nyabo Bank Layout") == len(load_seed("bank_layouts")["rows"])
	assert len(frappe._stub.calls("sync_financial_report_templates")) == 1
	# ARCHITECTURE §2: Nyabo records Монголбанк rates itself, so ERPNext's external provider
	# must be off after an install — the Single is in the stub meta, so this is a real check.
	assert frappe.db.get_single_value(CURRENCY_EXCHANGE_SETTINGS, "disabled") == 1

	frappe.db.set_value("Nyabo Bank Layout", "khan_bank_xlsx", "verified", 1)
	after_migrate()
	assert frappe.db.count("Nyabo Tax Parameter") == len(load_seed("tax_parameters")["rows"])
	assert frappe.db.get_value("Nyabo Bank Layout", "khan_bank_xlsx", "verified") == 1
	assert len(frappe._stub.calls("sync_financial_report_templates")) == 2
	assert frappe.db.count("Custom Field", {"dt": "Supplier"}) == 5
	assert frappe.db.get_single_value(CURRENCY_EXCHANGE_SETTINGS, "disabled") == 1


def test_install_reports_the_exchange_provider_it_switched_off(site):
	"""The step is reported, not silently skipped: a site without the Single must say so."""
	assert _setup("install")["currency_exchange_disabled"] is True
	assert frappe.db.get_single_value(CURRENCY_EXCHANGE_SETTINGS, "disabled") == 1
	# Re-enabling it by hand (or an ERPNext update) is undone by the next migrate.
	frappe.db.set_single_value(CURRENCY_EXCHANGE_SETTINGS, "disabled", 0)
	after_migrate()
	assert frappe.db.get_single_value(CURRENCY_EXCHANGE_SETTINGS, "disabled") == 1
