"""after_install / after_migrate: custom fields, seed, report templates, FX provider off; idempotent."""

from __future__ import annotations

import frappe

from nyabo_mn.nyabo.seed import load_seed
from nyabo_mn.setup import install
from nyabo_mn.setup.custom_fields import TEMPLATE_CHECKSUM_FIELD, TEMPLATE_DOCTYPE
from nyabo_mn.setup.install import after_install, after_migrate

BALANCE_SHEET = "Nyabo SME Balance Sheet (MN)"


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


def _shipped() -> dict:
	"""The balance-sheet template as this app ships it on disk."""
	import json

	path = frappe.get_app_path(
		"nyabo_mn",
		"nyabo",
		"financial_report_template",
		"nyabo_sme_balance_sheet_(mn)",
		"nyabo_sme_balance_sheet_(mn).json",
	)
	with open(path, encoding="utf-8") as fh:
		return json.load(fh)


def test_a_corrected_shipped_template_reaches_an_existing_site(site):
	"""F9: ERPNext's sync only inserts, so Nyabo re-applies the templates it owns on migrate."""
	after_install()
	assert frappe.db.get_value(TEMPLATE_DOCTYPE, BALANCE_SHEET, TEMPLATE_CHECKSUM_FIELD) == (
		install.template_checksum(_shipped())
	)  # install stamps what it shipped

	# the site now holds what an older release shipped: stamped by that release, untouched since
	doc = frappe.get_doc(TEMPLATE_DOCTYPE, BALANCE_SHEET)
	doc.rows[1].display_name = "Хуучин нэр"
	doc.rows[1].calculation_formula = '["account_category", "=", "Wrong Category"]'
	doc.set(TEMPLATE_CHECKSUM_FIELD, install.template_checksum(doc))
	doc.flags.ignore_permissions = True
	doc.save()

	after_migrate()
	shipped = _shipped()
	fixed = frappe.get_doc(TEMPLATE_DOCTYPE, BALANCE_SHEET)
	assert fixed.rows[1].display_name == shipped["rows"][1]["display_name"]
	assert fixed.rows[1].calculation_formula == shipped["rows"][1].get("calculation_formula")
	assert len(fixed.rows) == len(shipped["rows"])
	assert fixed.get(TEMPLATE_CHECKSUM_FIELD) == install.template_checksum(shipped)
	# and the next migrate finds nothing to do
	assert install.update_shipped_templates("migrate")[BALANCE_SHEET] == "unchanged"


def test_a_template_the_accountant_edited_is_never_overwritten(site, as_user):
	"""The other half of F9: Nyabo corrects its own template, never the accountant's work."""
	after_install()
	with as_user("acc@example.com", ["Nyabo Accountant", "System Manager"]):
		doc = frappe.get_doc(TEMPLATE_DOCTYPE, BALANCE_SHEET)
		doc.rows[1].display_name = "Нягтлангийн өөрчлөлт"
		doc.flags.ignore_permissions = True
		doc.save()

	assert install.update_shipped_templates("migrate")[BALANCE_SHEET] == "kept"
	assert frappe.get_doc(TEMPLATE_DOCTYPE, BALANCE_SHEET).rows[1].display_name == "Нягтлангийн өөрчлөлт"

	# an unstamped row a named user has saved is the accountant's too (a site that installed
	# before the stamp existed, and where somebody has since edited the template on the desk)
	frappe.db.set_value(
		TEMPLATE_DOCTYPE,
		BALANCE_SHEET,
		{TEMPLATE_CHECKSUM_FIELD: None, "modified_by": "acc@example.com"},
		update_modified=False,
	)
	assert install.update_shipped_templates("migrate")[BALANCE_SHEET] == "kept"
	assert frappe.get_doc(TEMPLATE_DOCTYPE, BALANCE_SHEET).rows[1].display_name == "Нягтлангийн өөрчлөлт"
