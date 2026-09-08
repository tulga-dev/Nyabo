"""Reversal flow: JE reversal pair, PI debit note, reason + approver, second reversal refused."""

from __future__ import annotations

import frappe
import pytest
from compliance_helpers import CASH, EXPENSE, make_je, make_nyabo_document, make_pi
from erpnext.accounts.utils import get_balance_on

from nyabo_mn.compliance import period, reversal
from nyabo_mn.i18n import mn

INPUT_VAT = "1810 - Татан суутгах НӨАТ - TST"
PAYABLE = "2110 - Дансны өглөг - TST"


@pytest.fixture
def supplier(company):
	return frappe.get_doc(
		{"doctype": "Supplier", "supplier_name": "Петровис ХХК", "tin": "12345678"}
	).insert()


def _posted_je(company):
	nyd = make_nyabo_document(company)
	proposal = frappe.get_doc(
		{"doctype": "Nyabo Proposal", "company": company, "kind": "receipt", "document": nyd.name}
	).insert()
	je = make_je(company, source_document=nyd.name, nyabo_proposal=proposal.name).insert()
	je.submit()
	return je


def test_reverse_journal_entry_in_the_original_period(company, as_user):
	je = _posted_je(company)
	frappe.get_doc({"doctype": "Role", "role_name": "Accounts User", "desk_access": 1}).insert()
	with as_user("acc@example.com", ["Nyabo Accountant", "Accounts User"]) as user:
		result = reversal.reverse("Journal Entry", je.name, "account", "6210 биш 6310 байх ёстой", user, 777)
	assert result["reversal_doctype"] == "Journal Entry" and result["dated_in_original_period"] is True
	rev = frappe.get_doc("Journal Entry", result["reversal_name"])
	assert rev.docstatus == 1 and rev.reversal_of == je.name and str(rev.posting_date) == "2026-03-05"
	assert rev.nyabo_corrects == je.name and rev.nyabo_approved_by == "acc@example.com"
	assert rev.nyabo_correction_reason == f"{mn.CORRECT_WRONG_ACCOUNT}: 6210 биш 6310 байх ёстой"
	assert rev.user_remark == rev.nyabo_correction_reason
	assert rev.source_document == je.source_document and rev.nyabo_proposal == je.nyabo_proposal
	assert "15.1" in rev.nyabo_explanation and je.name in rev.nyabo_explanation
	assert [(r.account, r.debit, r.credit) for r in rev.accounts] == [
		(EXPENSE, 0.0, 85000.0),
		(CASH, 85000.0, 0.0),
	]
	assert get_balance_on(EXPENSE, "2026-03-31") == 0.0
	# the original is untouched (no cancel, no edit)
	assert frappe.db.get_value("Journal Entry", je.name, "docstatus") == 1

	corrections = frappe.get_all(
		"Nyabo Correction",
		filters={"posted_name": je.name},
		fields=["field", "source", "corrected_by", "corrected_telegram_id", "reason", "reversal_name"],
	)
	assert len(corrections) == 1
	c = corrections[0]
	assert (c.field, c.source, c.corrected_by, c.corrected_telegram_id) == (
		"reversed",
		"reversal",
		"acc@example.com",
		"777",
	)
	assert c.reason == mn.CORRECT_WRONG_ACCOUNT and c.reversal_name == rev.name
	events = frappe.get_all(
		"Nyabo Event", filters={"ref_name": je.name}, fields=["event_type", "payload_json"]
	)
	assert [e.event_type for e in events] == [mn.EVENT_ENTRY_REVERSED]
	assert rev.name in events[0].payload_json
	assert frappe.db.exists("Comment", {"reference_name": je.name})

	with pytest.raises(frappe.ValidationError) as exc:
		reversal.reverse("Journal Entry", je.name, "dup", "", "Administrator")
	assert mn.MSG_CORRECTION_ALREADY_REVERSED in str(exc.value)
	with pytest.raises(frappe.ValidationError) as exc:
		reversal.reverse("Journal Entry", je.name, "nonsense", "", "Administrator")
	assert "nonsense" in str(exc.value)


def test_reverse_after_period_lock_is_dated_today(company):
	je = make_je(company, posting_date="2026-02-10", nyabo_primary_document_ref="x").insert()
	je.submit()
	period.lock(company, "2026-02", "Administrator")
	result = reversal.reverse("Journal Entry", je.name, "amount", "", "Administrator")
	assert result["dated_in_original_period"] is False
	rev = frappe.get_doc("Journal Entry", result["reversal_name"])
	assert str(rev.posting_date) == frappe.utils.nowdate()
	assert rev.user_remark == mn.CORRECT_WRONG_AMOUNT


def test_reverse_purchase_invoice_creates_a_debit_note(company, supplier):
	pi = make_pi(
		company,
		supplier,
		nyabo_primary_document_ref="AB-1",
		taxes=[
			{"account_head": INPUT_VAT, "charge_type": "On Net Total", "rate": 10, "description": "НӨАТ 10%"}
		],
	).insert()
	pi.submit()
	result = reversal.reverse("Purchase Invoice", pi.name, "dup", "давхар илгээсэн", "Administrator")
	note = frappe.get_doc("Purchase Invoice", result["reversal_name"])
	assert note.is_return == 1 and note.return_against == pi.name and note.docstatus == 1
	assert note.grand_total == -93500.0 and str(note.posting_date) == "2026-03-10"
	assert note.remarks == f"{mn.CORRECT_DUPLICATE}: давхар илгээсэн"
	assert note.nyabo_corrects == pi.name and note.nyabo_approved_by == "Administrator"
	assert frappe.db.get_value("Purchase Invoice", pi.name, "status") == "Debit Note Issued"
	assert get_balance_on(PAYABLE, "2026-03-31") == 0.0
	with pytest.raises(frappe.ValidationError) as exc:
		reversal.reverse("Purchase Invoice", pi.name, "dup", "", "Administrator")
	assert mn.MSG_CORRECTION_ALREADY_REVERSED in str(exc.value)
	with pytest.raises(frappe.ValidationError):
		reversal.reverse("Sales Invoice", pi.name, "dup", "", "Administrator")


def test_reverse_cash_paid_purchase_invoice_gives_the_cash_back(company, supplier):
	"""A cash receipt is posted as ERPNext's paid invoice (PIPE-03), so its debit note has to put
	the money back in the till, not leave a negative payable behind."""
	pi = make_pi(
		company,
		supplier,
		nyabo_primary_document_ref="AB-2",
		is_paid=1,
		cash_bank_account=CASH,
		paid_amount=85000,
	).insert()
	pi.submit()
	assert pi.status == "Paid" and get_balance_on(CASH, "2026-03-31") == -85000.0
	result = reversal.reverse("Purchase Invoice", pi.name, "dup", "давхар илгээсэн", "Administrator")
	note = frappe.get_doc("Purchase Invoice", result["reversal_name"])
	assert note.is_return == 1 and note.paid_amount == -85000.0
	assert get_balance_on(CASH, "2026-03-31") == 0.0
	assert get_balance_on(PAYABLE, "2026-03-31") == 0.0


def test_a_reversal_cannot_itself_be_reversed(company, supplier):
	"""F-06: the correction chain stays one level deep (art. 15.1), refused in Mongolian.

	Without the check the refusal came from ERPNext in English, reached the accountant as the
	generic «алдаа гарлаа» and woke the admins with a handler failure.
	"""
	je = _posted_je(company)
	rev = reversal.reverse("Journal Entry", je.name, "account", "", "Administrator")
	reversal_je = frappe.get_doc("Journal Entry", rev["reversal_name"])
	assert reversal.is_reversal("Journal Entry", reversal_je) is True
	with pytest.raises(frappe.ValidationError) as exc:
		reversal.reverse("Journal Entry", reversal_je.name, "other", "", "Administrator")
	assert mn.MSG_CORRECTION_IS_REVERSAL in str(exc.value)

	pi = make_pi(company, supplier, nyabo_primary_document_ref="AB-1").insert()
	pi.submit()
	note_name = reversal.reverse("Purchase Invoice", pi.name, "dup", "", "Administrator")["reversal_name"]
	note = frappe.get_doc("Purchase Invoice", note_name)
	assert reversal.is_reversal("Purchase Invoice", note) is True
	with pytest.raises(frappe.ValidationError) as exc:
		reversal.reverse("Purchase Invoice", note_name, "dup", "", "Administrator")
	assert mn.MSG_CORRECTION_IS_REVERSAL in str(exc.value)


def test_draft_cannot_be_reversed(company):
	je = make_je(company).insert()
	with pytest.raises(frappe.ValidationError) as exc:
		reversal.reverse("Journal Entry", je.name, "other", "x", "Administrator")
	assert je.name in str(exc.value)


def test_a_linked_accountant_has_the_erpnext_access_a_correction_needs(company):
	"""The bot runs as the linked user, so the link must grant real ERPNext access (F2).

	Only ``ensure_frappe_user`` decides what a Telegram accountant may do on a real site;
	the Nyabo roles ship with no DocPerms, so with them alone ERPNext refuses
	``make_reverse_journal_entry`` and every Nyabo report.
	"""
	from nyabo_mn.reports import export
	from nyabo_mn.telegram import state as chat_state

	for role_name in ("Accounts User", "Accounts Manager"):
		frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert()
	je = _posted_je(company)
	code = chat_state.issue_link_code("Accountant", company, issued_by="Administrator")
	link = chat_state.consume_link_code(code.code, {"id": 4242, "first_name": "Сараа"})
	assert set(frappe.get_roles(link.user)) >= {"Nyabo Accountant", "Accounts User"}

	previous = frappe.session.user
	frappe.set_user(link.user)
	try:
		result = reversal.reverse("Journal Entry", je.name, "account", "буруу данс", link.user, 4242)
		columns, _rows = export.run_report(
			"Nyabo General Journal",
			{"company": company, "from_date": "2026-03-01", "to_date": "2026-03-31"},
		)
	finally:
		frappe.set_user(previous)
	assert frappe.db.get_value("Journal Entry", result["reversal_name"], "docstatus") == 1
	assert columns


def test_an_owner_link_grants_no_ledger_access(company):
	"""An owner only taps cards; they must not get ERPNext ledger roles."""
	from nyabo_mn.telegram import state as chat_state

	frappe.get_doc({"doctype": "Role", "role_name": "Accounts User", "desk_access": 1}).insert()
	code = chat_state.issue_link_code("Owner", company, issued_by="Administrator")
	link = chat_state.consume_link_code(code.code, {"id": 4243, "first_name": "Бат"})
	roles = set(frappe.get_roles(link.user))
	assert "Nyabo Owner" in roles
	assert not roles & {"Accounts User", "Accounts Manager"}
