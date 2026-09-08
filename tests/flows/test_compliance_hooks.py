"""Document constraints: primary document required, no edit after submit, retention, events."""

from __future__ import annotations

import frappe
import pytest
from compliance_helpers import CASH, make_je, make_nyabo_document, make_pi, make_supplier
from frappe.utils import add_years, getdate

from nyabo_mn.compliance import hooks as compliance_hooks
from nyabo_mn.i18n import mn


@pytest.fixture
def supplier(company):
	return make_supplier()


def test_journal_entry_without_primary_document_is_refused(company):
	je = make_je(company).insert()
	with pytest.raises(frappe.ValidationError) as exc:
		je.submit()
	assert mn.MSG_PRIMARY_DOCUMENT_REQUIRED in str(exc.value)
	assert frappe.db.count("GL Entry", {"voucher_no": je.name}) == 0


def test_journal_entry_with_source_document_posts_and_is_retained(company):
	nyd = make_nyabo_document(company)
	assert str(nyd.retain_until) == str(getdate(add_years("2026-03-05", 10)))
	je = make_je(company, source_document=nyd.name).insert()
	je.submit()
	assert je.docstatus == 1
	assert str(je.nyabo_retain_until) == str(getdate(add_years("2026-03-05", 10)))
	assert frappe.db.count("GL Entry", {"voucher_no": je.name}) == 2


def test_written_reference_or_attachment_satisfies_the_document_rule(company):
	je = make_je(company, nyabo_primary_document_ref="Гэрээ №12, 2026-03-01").insert()
	je.submit()
	assert je.docstatus == 1
	other = make_je(company).insert()
	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": "receipt.jpg",
			"content": b"\xff\xd8 test",
			"is_private": 1,
			"attached_to_doctype": "Journal Entry",
			"attached_to_name": other.name,
		}
	).insert()
	other.submit()
	assert other.docstatus == 1


def test_explanation_length_and_proposal_link_are_validated(company):
	je = make_je(company, nyabo_explanation="х" * 301)
	with pytest.raises(frappe.ValidationError) as exc:
		je.insert()
	assert "301" in str(exc.value)
	frappe.get_doc(
		{"doctype": "Company", "company_name": "Өөр ХХК", "abbr": "OOR", "default_currency": "MNT"}
	)
	proposal = frappe.get_doc({"doctype": "Nyabo Proposal", "company": company, "kind": "receipt"}).insert()
	je = make_je(company, nyabo_proposal=proposal.name, nyabo_primary_document_ref="x").insert()
	assert je.nyabo_proposal == proposal.name
	with pytest.raises(frappe.ValidationError) as exc:
		make_je(company, nyabo_proposal="NYP-99999").insert()
	assert "NYP-99999" in str(exc.value)


def test_submitted_invoice_cannot_change_its_accounts_but_may_change_audit_fields(company, supplier):
	pi = make_pi(company, supplier, nyabo_primary_document_ref="AB-1").insert()
	pi.submit()
	pi.reload()
	pi.items[0].expense_account = CASH
	with pytest.raises(frappe.ValidationError) as exc:
		pi.save()
	assert mn.MSG_NO_EDIT_AFTER_SUBMIT in str(exc.value)
	# the guard itself lets an audit-field-only change through (Frappe still needs allow_on_submit)
	pi = frappe.get_doc("Purchase Invoice", pi.name)
	pi.load_doc_before_save()
	pi.nyabo_explanation = "Шатахууны зардал — Заавар 116, §3"
	pi.remarks = "тайлбар"
	assert compliance_hooks.changed_fields_after_submit(pi) == []
	compliance_hooks.guard_no_edit_after_submit(pi)
	pi.supplier = "Хэн нэгэн"
	assert compliance_hooks.changed_fields_after_submit(pi) == ["supplier"]


def test_posted_document_from_a_proposal_cannot_be_deleted(company):
	proposal = frappe.get_doc({"doctype": "Nyabo Proposal", "company": company, "kind": "receipt"}).insert()
	je = make_je(company, nyabo_proposal=proposal.name, nyabo_primary_document_ref="x").insert()
	je.submit()
	je.flags.ignore_links = True
	frappe.flags.nyabo_allow_submit_edit = True
	try:
		je.cancel()
	finally:
		frappe.flags.pop("nyabo_allow_submit_edit", None)
	with pytest.raises(frappe.ValidationError) as exc:
		frappe.delete_doc("Journal Entry", je.name)
	assert mn.MSG_POSTED_DELETE_BLOCKED in str(exc.value)
	draft = make_je(company).insert()
	frappe.delete_doc("Journal Entry", draft.name)
	assert not frappe.db.exists("Journal Entry", draft.name)


def test_retained_file_and_document_cannot_be_deleted(company):
	nyd = make_nyabo_document(company)
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": "receipt.jpg",
			"content": b"\xff\xd8 test",
			"is_private": 1,
			"attached_to_doctype": "Nyabo Document",
			"attached_to_name": nyd.name,
		}
	).insert()
	with pytest.raises(frappe.ValidationError) as exc:
		frappe.delete_doc("File", file.name)
	assert "11.1" in str(exc.value)
	assert frappe.db.exists("File", file.name)
	with pytest.raises(frappe.ValidationError) as exc:
		frappe.delete_doc("Nyabo Document", nyd.name)
	assert mn.MSG_RETAINED_DOCUMENT_DELETE_BLOCKED.split("{")[0] in str(exc.value)
	frappe.flags.nyabo_allow_file_delete = True
	try:
		frappe.delete_doc("File", file.name)
	finally:
		frappe.flags.pop("nyabo_allow_file_delete", None)
	assert not frappe.db.exists("File", file.name)


def test_nyabo_event_is_append_only(company):
	from nyabo_mn.compliance import events

	name = events.log("test_event", company=company, reason="шалгалт", payload={"x": 1})
	doc = frappe.get_doc("Nyabo Event", name)
	assert doc.actor_user == "Administrator" and '"x": 1' in doc.payload_json
	doc.reason = "өөрчлөв"
	with pytest.raises(frappe.ValidationError) as exc:
		doc.save()
	assert mn.MSG_EVENT_APPEND_ONLY in str(exc.value)
	with pytest.raises(frappe.ValidationError):
		frappe.delete_doc("Nyabo Event", name)
	assert frappe.db.exists("Nyabo Event", name)


def test_an_event_records_a_document_without_making_it_undeletable(company):
	"""F11: the audit trail keeps the event, it does not veto a deletion Nyabo allows."""
	from nyabo_mn.compliance import events

	draft = make_je(company).insert()
	event = events.log("proposal_created", company=company, ref_doctype="Journal Entry", ref_name=draft.name)

	frappe.delete_doc("Journal Entry", draft.name)
	assert not frappe.db.exists("Journal Entry", draft.name)
	# the event survives the document and still says what it was about
	row = frappe.db.get_value("Nyabo Event", event, ["ref_doctype", "ref_name"], as_dict=True)
	assert (row.ref_doctype, row.ref_name) == ("Journal Entry", draft.name)
	with pytest.raises(frappe.ValidationError):
		frappe.delete_doc("Nyabo Event", event)

	# and the guards that must refuse still refuse, event or no event
	nyd = make_nyabo_document(company)
	events.log("document_received", company=company, ref_doctype="Nyabo Document", ref_name=nyd.name)
	with pytest.raises(frappe.ValidationError) as exc:
		frappe.delete_doc("Nyabo Document", nyd.name)
	assert mn.MSG_RETAINED_DOCUMENT_DELETE_BLOCKED.split("{")[0] in str(exc.value)
	assert frappe.db.exists("Nyabo Document", nyd.name)


def test_retention_years_come_from_the_tax_parameter_data(site):
	assert compliance_hooks.retention_years("2026-03-05") == 10
	frappe.get_doc(
		{
			"doctype": "Nyabo Tax Parameter",
			"key": "retention.years",
			"effective_from": "2016-01-01",
			"value_json": "12",
			"unit": "years",
			"status": "active",
			"verified": 1,
		}
	).insert()
	assert compliance_hooks.retention_years("2026-03-05") == 12


def test_system_generated_journal_entries_post_and_carry_their_source(company):
	"""F3: ERPNext's own entries (depreciation, revaluation, gain/loss) have no receipt to attach.

	Refusing them would break the ERPNext feature — the depreciation posting runs as a daily
	scheduler job — so the handler stamps what generated the entry instead of throwing.
	"""
	depreciation = make_je(company, voucher_type="Depreciation Entry").insert()
	depreciation.submit()
	assert depreciation.docstatus == 1
	assert depreciation.nyabo_primary_document_ref == mn.MSG_PRIMARY_DOCUMENT_SYSTEM_GENERATED.format(
		source="Depreciation Entry"
	)
	assert frappe.db.count("GL Entry", {"voucher_no": depreciation.name}) == 2

	fx = make_je(company, voucher_type="Exchange Gain Or Loss", is_system_generated=1).insert()
	fx.submit()
	assert fx.docstatus == 1

	# a hand-made entry of a plain voucher type is still refused
	manual = make_je(company).insert()
	with pytest.raises(frappe.ValidationError) as exc:
		manual.submit()
	assert mn.MSG_PRIMARY_DOCUMENT_REQUIRED in str(exc.value)
	assert compliance_hooks.system_generated_source(manual) is None
