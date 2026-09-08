"""Hook dispatch: controller methods, doc_events from hooks.py, and missing handlers."""

from __future__ import annotations

import frappe
import pytest


def record(doc, method=None):
	"""Dummy doc_events handler; records into the stub's call log so module identity does not matter."""
	frappe._stub.record_call("dummy_hook", doctype=doc.doctype, name=doc.name, method=method)


def test_real_hooks_are_loaded_from_nyabo_hooks_py(site):
	hooks = frappe.get_hooks()
	assert hooks.after_install == ["nyabo_mn.setup.install.after_install"]
	assert "Purchase Invoice" in frappe.get_hooks("period_closing_doctypes")
	doc_hooks = frappe.get_doc_hooks()
	assert (
		"nyabo_mn.compliance.hooks.validate_accounting_document" in doc_hooks["Purchase Invoice"]["validate"]
	)
	assert doc_hooks["Journal Entry"]["validate"][0].startswith("erpnext.accounts.doctype.accounting_period")


def test_temporary_hooks_dispatch_to_dummy_handler(site, frappe_hooks):
	path = f"{record.__module__}.record"
	with frappe_hooks(
		doc_events={"Nyabo LLM Call": {"before_insert": path, "after_insert": path, "on_update": path}}
	):
		doc = frappe.get_doc({"doctype": "Nyabo LLM Call", "purpose": "extract"}).insert()
	calls = frappe._stub.calls("dummy_hook")
	assert [c.method for c in calls] == ["before_insert", "after_insert", "on_update"]
	assert calls[0].name is None and calls[1].name == doc.name
	# outside the block the hook is gone
	frappe.get_doc({"doctype": "Nyabo LLM Call", "purpose": "extract"}).insert()
	assert len(frappe._stub.calls("dummy_hook")) == 3


def test_missing_handler_module_raises_import_error_naming_the_path(site, frappe_hooks):
	# a hook pointing at a module that does not exist must surface, never be swallowed
	missing = {"Nyabo Event": {"before_save": "nyabo_mn.no_such_module.handler"}}
	with frappe_hooks(replace=True, doc_events=missing):
		with pytest.raises(ImportError, match="nyabo_mn.no_such_module.handler"):
			frappe.get_doc({"doctype": "Nyabo Event", "event_type": "x"}).save()


def test_controller_methods_run_with_hooks(site, frappe_hooks):
	from nyabo_mn.nyabo.doctype.nyabo_event.nyabo_event import NyaboEvent

	with frappe_hooks(without_apps=("nyabo_mn",)):
		doc = frappe.get_doc({"doctype": "Nyabo Event", "event_type": "x"}).insert()
	assert isinstance(doc, NyaboEvent)
	assert doc.run_method("no_such_method") is None
