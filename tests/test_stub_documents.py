"""Document lifecycle in the stub: meta validation, links, docstatus, versions, files, jobs."""

from __future__ import annotations

import json

import frappe
import pytest
from frappe.utils.file_manager import save_file


def test_unknown_field_is_a_validation_error(site):
	with pytest.raises(frappe.ValidationError, match="has no field 'event_typo'"):
		frappe.get_doc({"doctype": "Nyabo Event", "event_typo": "x"})
	doc = frappe.get_doc({"doctype": "Nyabo Event", "event_type": "ok"})
	with pytest.raises(frappe.ValidationError, match="reasn"):
		doc.reasn = "typo"
	with pytest.raises(AttributeError):
		_ = doc.reasn
	# standard and private attributes never trip the check
	doc._scratch = 1
	doc.idx = 3
	assert doc.reason is None


def test_custom_fields_are_merged_into_erpnext_metas(site):
	meta = frappe.get_meta("Purchase Invoice")
	assert meta.has_field("nyabo_explanation")
	assert meta.get_field("source_document").options == "Nyabo Document"
	assert frappe.get_meta("Supplier").has_field("register_no")
	pi = frappe.new_doc("Purchase Invoice")
	pi.nyabo_explanation = "Шатахууны зардал"
	assert pi.nyabo_explanation == "Шатахууны зардал"


def test_mandatory_and_select_checks(site):
	with pytest.raises(frappe.MandatoryError, match="purpose"):
		frappe.get_doc({"doctype": "Nyabo LLM Call"}).insert()
	with pytest.raises(frappe.ValidationError, match="cannot be"):
		frappe.get_doc({"doctype": "Nyabo LLM Call", "purpose": "not-an-option"}).insert()


def test_link_check_depends_on_target_rows_and_strict_flag(site, frappe_flags):
	# Company table is empty: the link is not checked ...
	frappe.get_doc({"doctype": "Nyabo LLM Call", "purpose": "extract", "company": "Байхгүй ХХК"}).insert()
	# ... but in strict mode every Link is checked, and a target without any meta is refused
	with frappe_flags(stub_strict_links=True):
		with pytest.raises(frappe.LinkValidationError):
			frappe.get_doc(
				{"doctype": "Nyabo LLM Call", "purpose": "extract", "company": "Байхгүй ХХК"}
			).insert()
		with pytest.raises(frappe.DoesNotExistError):
			frappe.get_doc({"doctype": "Supplier", "supplier_name": "X", "country": "Mongolia"}).insert()


def test_link_check_once_target_has_rows(site, company):
	with pytest.raises(frappe.LinkValidationError, match="Could not find"):
		frappe.get_doc({"doctype": "Nyabo LLM Call", "purpose": "extract", "company": "Байхгүй ХХК"}).insert()
	frappe.get_doc({"doctype": "Nyabo LLM Call", "purpose": "extract", "company": company}).insert()


def test_child_tables_append_and_dict_rows(site, company):
	settings = frappe.get_doc("Nyabo Company Settings", company)
	# provisioning already opened simplified_1pct from the fiscal-year start; continue the history
	settings.regimes[0].effective_to = "2026-12-31"
	settings.append("regimes", {"regime": "vat_payer", "effective_from": "2027-01-01"})
	settings.set("bank_accounts", [{"bank": "Khan Bank", "currency": "MNT", "account_number": "5000123456"}])
	settings.save()
	settings.reload()
	assert settings.regimes[0].regime == "simplified_1pct" and settings.regimes[1].regime == "vat_payer"
	assert settings.regimes[0].parent == company and settings.regimes[0].parentfield == "regimes"
	assert settings.bank_accounts[0].idx == 1
	assert frappe.db.count("Nyabo Bank Account Row", {"parent": company}) == 1
	settings.remove(settings.bank_accounts[0])
	settings.save()
	assert frappe.db.count("Nyabo Bank Account Row", {"parent": company}) == 0
	with pytest.raises(frappe.ValidationError):
		settings.append("no_such_table", {})


def _journal_entry(company, amount=85000, posting_date="2026-03-05"):
	return frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": company,
			"posting_date": posting_date,
			"user_remark": "Шатахуун",
			"accounts": [
				{"account": "6210 - Шатахуун - TST", "debit_in_account_currency": amount},
				{"account": "1110 - Касс - TST", "credit_in_account_currency": amount},
			],
		}
	)


def test_docstatus_transitions_and_update_after_submit(site, company, frappe_hooks):
	with frappe_hooks(without_apps=("nyabo_mn",)):
		je = _journal_entry(company).insert()
		assert je.docstatus == 0 and je.is_new() is False
		je.submit()
		assert je.docstatus == 1 and je.docstatus.is_submitted()
		# only allow_on_submit fields may change
		je.title = "Шинэ гарчиг"
		je.save()
		je.reload()
		assert je.title == "Шинэ гарчиг"
		je.user_remark = "өөрчилсөн"
		with pytest.raises(frappe.UpdateAfterSubmitError):
			je.save()
		je.reload()
		je.docstatus = 0
		with pytest.raises(frappe.DocstatusTransitionError):
			je.save()
		je.reload()
		je.cancel()
		assert je.docstatus == 2
		je.title = "x"
		with pytest.raises(frappe.ValidationError, match="cancelled"):
			je.save()
		draft = _journal_entry(company)
		draft.docstatus = 2
		with pytest.raises(frappe.DocstatusTransitionError):
			draft.insert()


def test_version_rows_and_comments(site, company):
	settings = frappe.get_doc("Nyabo Company Settings", company)
	before = frappe.db.count("Version", {"ref_doctype": "Nyabo Company Settings", "docname": company})
	settings.default_expense_code = "6220"
	settings.save()
	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": "Nyabo Company Settings", "docname": company},
		fields=["data"],
		order_by="creation asc",
	)
	assert len(versions) == before + 1
	changed = json.loads(versions[-1].data)["changed"]
	assert [c for c in changed if c[0] == "default_expense_code"][0][2] == "6220"
	comment = settings.add_comment("Comment", "Данс солив")
	assert comment.reference_name == company
	assert (
		frappe.db.count("Comment", {"reference_doctype": "Nyabo Company Settings", "reference_name": company})
		== 1
	)


def test_db_set_get_doc_before_save_and_has_value_changed(site, company):
	settings = frappe.get_doc("Nyabo Company Settings", company)
	settings.db_set("onboarding_state", "banks")
	assert frappe.db.get_value("Nyabo Company Settings", company, "onboarding_state") == "banks"
	settings.onboarding_state = "done"
	settings.save()
	assert settings.get_doc_before_save().onboarding_state == "banks"
	assert settings.has_value_changed("onboarding_state")
	assert not settings.has_value_changed("company")
	assert settings.as_dict()["doctype"] == "Nyabo Company Settings"


def test_delete_leaves_a_deleted_document_and_removes_attached_files(site, frappe_hooks):
	with frappe_hooks(without_apps=("nyabo_mn",)):  # File.on_trash is guarded by the compliance module
		_delete_supplier_with_file()


def _delete_supplier_with_file():
	supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": "Устгах ХХК"}).insert()
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": "contract.pdf",
			"content": b"%PDF-1.4 test",
			"is_private": 1,
			"attached_to_doctype": "Supplier",
			"attached_to_name": supplier.name,
		}
	).insert()
	path = file.get_full_path()
	assert frappe.get_doc("File", file.name).get_content() == b"%PDF-1.4 test"
	frappe.delete_doc("Supplier", supplier.name)
	assert not frappe.db.exists("Supplier", supplier.name)
	assert not frappe.db.exists("File", file.name)
	import os

	assert not os.path.exists(path)
	deleted = frappe.get_all(
		"Deleted Document", filters={"deleted_doctype": "Supplier"}, fields=["deleted_name", "data"]
	)
	assert deleted[0].deleted_name == supplier.name
	assert json.loads(deleted[0].data)["supplier_name"] == "Устгах ХХК"


def test_file_content_roundtrip_via_save_file(site):
	doc = save_file("statement.csv", "огноо,дүн\n2026-03-01,85000\n", "Role", "System Manager", is_private=1)
	assert doc.file_url.startswith("/private/files/")
	assert doc.get_content().decode("utf-8").startswith("огноо")
	again = save_file(
		"statement.csv", "огноо,дүн\n2026-03-01,85000\n", "Role", "System Manager", is_private=1
	)
	assert again.file_url == doc.file_url  # same hash -> same file on disk


def test_enqueue_runs_inline_and_records(site):
	calls = []

	def job(x, y=1):
		calls.append((x, y))
		return x + y

	result = frappe.enqueue(job, queue="short", enqueue_after_commit=True, x=2, y=3)
	assert calls == [(2, 3)] and result.result == 5
	frappe.enqueue("frappe.utils.data.cint", s="7")
	assert [e.method for e in frappe.enqueued][-1] == "frappe.utils.data.cint"
	assert frappe.enqueued[-1].result == 7
	assert frappe.enqueued[0].enqueue_after_commit is True
	with pytest.raises(ImportError, match="nyabo_mn.no_such_module.run"):
		frappe.enqueue("nyabo_mn.no_such_module.run")


def test_permissions_follow_doctype_roles(site, as_user):
	with as_user("owner@example.com", ["Nyabo Owner"]):
		assert frappe.has_permission("Nyabo Proposal", "read")
		assert not frappe.has_permission("Nyabo Proposal", "create")
		with pytest.raises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Nyabo Rule", "company": "X"}).insert()
		with pytest.raises(frappe.PermissionError):
			frappe.only_for("Nyabo Admin")
		frappe.only_for(["Nyabo Owner", "Nyabo Admin"])
	assert frappe.session.user == "Administrator"
	with as_user("acc@example.com", ["Nyabo Accountant"]):
		assert set(frappe.get_roles()) >= {"Nyabo Accountant", "All", "Guest"}
		assert frappe.has_permission("Nyabo Proposal", "write")


def test_request_response_and_misc_api(site):
	frappe.local.request = frappe.Request(
		data=json.dumps({"update_id": 1}),
		headers={"X-Telegram-Bot-Api-Secret-Token": "s", "Content-Type": "application/json"},
	)
	assert frappe.request.headers.get("x-telegram-bot-api-secret-token") == "s"
	assert frappe.get_request_header("X-Telegram-Bot-Api-Secret-Token") == "s"
	assert frappe.request.get_json()["update_id"] == 1
	assert frappe.request.get_data(as_text=True).startswith("{")
	frappe.response["http_status_code"] = 403
	assert frappe.local.response.http_status_code == 403
	assert frappe.render_template("Сайн байна уу, {{ name }}", {"name": "Болд"}) == "Сайн байна уу, Болд"
	assert frappe.scrub("Nyabo LLM Call") == "nyabo_llm_call"
	assert frappe.parse_json('{"a": 1}').a == 1
	frappe.cache().set_value("k", "v")
	assert frappe.cache().get_value("k") == "v"
	frappe.cache().delete_value("k")
	assert frappe.cache().get_value("k") is None
	with pytest.raises(frappe.ValidationError, match="Алдаа"):
		frappe.throw("Алдаа гарлаа")
	assert frappe.get_message_log()[-1].message == "Алдаа гарлаа"
	frappe.log_error(title="nyabo: test", message="boom")
	assert frappe.db.count("Error Log") == 1
	assert frappe.conf.telegram_bot_token == "test-bot-token"
	assert frappe.utils.pdf.get_pdf("<h1>Тайлан</h1>") == "<h1>Тайлан</h1>".encode()
	assert (
		frappe.utils.xlsxutils.make_xlsx([["Данс", "Дүн"], ["1110", 85000]], "Тайлан").getvalue()[:2] == b"PK"
	)
