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
	"""A cash receipt is posted as ERPNext's paid invoice (D-019), so its debit note has to put
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


def test_draft_cannot_be_reversed(company):
	je = make_je(company).insert()
	with pytest.raises(frappe.ValidationError) as exc:
		reversal.reverse("Journal Entry", je.name, "other", "x", "Administrator")
	assert je.name in str(exc.value)
