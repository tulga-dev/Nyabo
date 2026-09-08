"""Period lock: refusal before month end, Accounting Period creation, reopen event, ERPNext refusal."""

from __future__ import annotations

import frappe
import pytest
from compliance_helpers import make_je

from nyabo_mn.compliance import period
from nyabo_mn.i18n import mn


def _pattern(pattern_id: str, verified: int):
	return frappe.get_doc(
		{
			"doctype": "Nyabo Posting Pattern",
			"pattern_id": pattern_id,
			"name_mn": "Тест загвар",
			"family": "purchase",
			"document_types": "Journal Entry",
			"verified": verified,
			"enabled": 1,
			"lines": [
				{"side": "debit", "account_class": "70", "amount_kind": "gross"},
				{"side": "credit", "account_class": "10", "amount_kind": "gross"},
			],
		}
	).insert()


def test_lock_refuses_before_month_end_then_creates_the_period(company):
	with pytest.raises(frappe.ValidationError) as exc:
		period.lock(company, "2099-01", "Administrator")
	assert mn.MSG_PERIOD_NOT_ENDED.split("{")[0] in str(exc.value)
	with pytest.raises(frappe.ValidationError) as exc:
		period.lock(company, "март", "Administrator")
	assert mn.MSG_CLOSE_USAGE in str(exc.value)

	name = period.lock(company, "2026-02", "Administrator", telegram_id=12345)
	assert name == "2026-02 - TST"
	doc = frappe.get_doc("Accounting Period", name)
	assert (str(doc.start_date), str(doc.end_date)) == ("2026-02-01", "2026-02-28")
	assert any(r.document_type == "Journal Entry" and r.closed for r in doc.closed_documents)
	assert period.is_locked(company, "2026-02-15") == (True, "2026-02")
	assert period.is_locked(company, "2026-03-01") == (False, None)
	events = frappe.get_all(
		"Nyabo Event", filters={"ref_name": name}, fields=["event_type", "actor_telegram_id", "actor_user"]
	)
	assert [e.event_type for e in events] == [mn.EVENT_PERIOD_LOCKED]
	assert events[0].actor_telegram_id == "12345" and events[0].actor_user == "Administrator"

	with pytest.raises(frappe.ValidationError) as exc:
		period.lock(company, "2026-02", "Administrator")
	assert name in str(exc.value)
	# ERPNext refuses a posting dated inside the closed month
	with pytest.raises(frappe.ValidationError, match="closed Accounting Period"):
		make_je(company, posting_date="2026-02-10", nyabo_primary_document_ref="x").insert()


def test_lock_needs_an_accountant_role(company, as_user):
	with as_user("owner@example.com", ["Nyabo Owner"]) as user:
		with pytest.raises(frappe.PermissionError):
			period.lock(company, "2026-02", user)
	with as_user("acc@example.com", ["Nyabo Accountant"]) as user:
		assert period.lock(company, "2026-02", user).startswith("2026-02")


def test_lock_refuses_when_a_posted_proposal_used_an_unverified_pattern(company):
	_pattern("test_unverified", 0)
	_pattern("test_verified", 1)
	# the proposal controller refuses "posted" without the document it posted (see nyabo_proposal.py)
	posted = make_je(company, posting_date="2026-02-12", nyabo_primary_document_ref="x").insert()
	frappe.get_doc(
		{
			"doctype": "Nyabo Proposal",
			"company": company,
			"kind": "receipt",
			"status": "posted",
			"posting_date": "2026-02-12",
			"posting_pattern": "test_unverified",
			"posted_doctype": "Journal Entry",
			"posted_name": posted.name,
		}
	).insert()
	with pytest.raises(frappe.ValidationError) as exc:
		period.lock(company, "2026-02", "Administrator")
	assert mn.MSG_PERIOD_UNVERIFIED_RULES in str(exc.value)
	assert not frappe.db.exists("Accounting Period", "2026-02 - TST")
	pattern = frappe.get_doc("Nyabo Posting Pattern", "test_unverified")
	pattern.verified = 1
	pattern.save()
	assert period.lock(company, "2026-02", "Administrator") == "2026-02 - TST"


def test_lock_reads_the_pattern_from_the_entry_when_the_link_is_empty(company):
	"""F-05: ``posting_pattern`` is a Link, so a seed-only or renamed pattern leaves it empty.

	The month may still not lock over books built on a rule the admin never checked, so the
	id is read back from ``entry_json`` and asked the same question the posting guard asked.
	"""
	posted = make_je(company, posting_date="2026-02-12", nyabo_primary_document_ref="x").insert()
	posted.submit()

	def _proposal(pattern_id):
		return frappe.get_doc(
			{
				"doctype": "Nyabo Proposal",
				"company": company,
				"kind": "receipt",
				"status": "posted",
				"posting_date": "2026-02-12",
				"entry_json": frappe.as_json({"pattern_id": pattern_id, "lines": []}),
				"posted_doctype": "Journal Entry",
				"posted_name": posted.name,
			}
		).insert()

	unlinked = _proposal("seed_only_pattern")  # no Nyabo Posting Pattern row and no seed row
	assert period.unverified_proposals(company, *period.period_bounds("2026-02")) == [unlinked.name]
	with pytest.raises(frappe.ValidationError) as exc:
		period.lock(company, "2026-02", "Administrator")
	assert mn.MSG_PERIOD_UNVERIFIED_RULES in str(exc.value)

	# the admin checks the primary text and marks the pattern verified: the month locks
	unlinked.db_set("entry_json", frappe.as_json({"pattern_id": "test_verified", "lines": []}))
	_pattern("test_verified", 1)
	assert period.proposal_pattern_id(frappe.get_doc("Nyabo Proposal", unlinked.name)) == "test_verified"
	assert period.unverified_proposals(company, *period.period_bounds("2026-02")) == []
	assert period.lock(company, "2026-02", "Administrator") == "2026-02 - TST"


def test_reopen_disables_the_period_and_writes_an_event(company, as_user):
	name = period.lock(company, "2026-02", "Administrator")
	with as_user("acc@example.com", ["Nyabo Accountant"]) as user:
		with pytest.raises(frappe.PermissionError):
			period.reopen(company, "2026-02", user, "буруу хаасан")
	with as_user("admin2@example.com", ["Nyabo Admin"]) as user:
		assert period.reopen(company, "2026-02", user, "буруу хаасан") == name
	assert frappe.db.get_value("Accounting Period", name, "disabled") == 1
	assert period.is_locked(company, "2026-02-15") == (False, None)
	events = frappe.get_all(
		"Nyabo Event",
		filters={"ref_name": name},
		fields=["event_type", "reason", "actor_user"],
		order_by="name asc",
	)
	assert [e.event_type for e in events] == [mn.EVENT_PERIOD_LOCKED, mn.EVENT_PERIOD_REOPENED]
	assert events[1].reason == "буруу хаасан" and events[1].actor_user == "admin2@example.com"
	make_je(company, posting_date="2026-02-10", nyabo_primary_document_ref="x").insert()


def test_manual_desk_changes_and_deletes_leave_events(company):
	doc = frappe.get_doc(
		{
			"doctype": "Accounting Period",
			"period_name": "2026-01",
			"company": company,
			"start_date": "2026-01-01",
			"end_date": "2026-01-31",
		}
	).insert()
	doc.disabled = 1
	doc.save()
	frappe.delete_doc("Accounting Period", doc.name)
	rows = [
		r
		for r in frappe.get_all(
			"Nyabo Event", fields=["event_type", "payload_json", "ref_name"], order_by="name asc"
		)
		if doc.name in r.payload_json
	]
	assert [r.event_type for r in rows] == [
		mn.EVENT_PERIOD_CHANGED,
		mn.EVENT_PERIOD_CHANGED,
		mn.EVENT_PERIOD_DELETED,
	]
	assert '"created"' in rows[0].payload_json and '"disabled"' in rows[1].payload_json
	assert all(r.ref_name is None for r in rows)
	# a period locked through Nyabo cannot be deleted from the desk at all
	name = period.lock(company, "2026-02", "Administrator")
	with pytest.raises(frappe.ValidationError) as exc:
		frappe.delete_doc("Accounting Period", name)
	assert name in str(exc.value)
	assert frappe.db.exists("Accounting Period", name)
