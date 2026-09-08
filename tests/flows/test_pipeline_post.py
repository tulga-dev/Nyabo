"""post_proposal: Purchase Invoice under the VAT regime, Journal Entry under the simplified regime,
the guards (unverified pattern, owner vs accountant, closed period, idempotency) and the audit fields."""

from __future__ import annotations

import frappe
import pytest
from erpnext.accounts.utils import get_balance_on

from nyabo_mn.agent import pipeline, post
from nyabo_mn.i18n import mn
from tests.flows.conftest import ACCOUNTANT, NOBODY, OWNER

EXPENSE = "6210 - Шатахуун - TST"
INPUT_VAT = "1810 - Татан суутгах НӨАТ - TST"
PAYABLE = "2110 - Дансны өглөг - TST"
CASH = "1110 - Касс - TST"


def _gl(name):
	return {
		(r.account, r.debit, r.credit)
		for r in frappe.get_all(
			"GL Entry", filters={"voucher_no": name, "is_cancelled": 0}, fields=["account", "debit", "credit"]
		)
	}


def test_vat_payer_2026_posts_purchase_invoice_with_input_vat(run_receipt):
	proposal = run_receipt("petrovis_fuel")
	result = post.post_proposal(proposal.name, ACCOUNTANT, approver_telegram_id="700002")
	assert result["posted_doctype"] == "Purchase Invoice"
	pi = frappe.get_doc("Purchase Invoice", result["posted_name"])
	assert pi.docstatus == 1 and pi.supplier == "Петровис ХХК"
	assert str(pi.posting_date) == "2026-09-05" and pi.set_posting_time == 1
	assert (pi.net_total, pi.total_taxes_and_charges, pi.grand_total) == (77272.73, 7727.27, 85000.0)
	assert pi.items[0].expense_account == EXPENSE and pi.items[0].item_name == "АИ-92 бензин"
	assert pi.taxes[0].account_head == INPUT_VAT and pi.taxes[0].charge_type == "Actual"
	assert pi.taxes_and_charges == "Татан суутгах НӨАТ 10% - TST"
	assert _gl(pi.name) == {(EXPENSE, 77272.73, 0.0), (INPUT_VAT, 7727.27, 0.0), (PAYABLE, 0.0, 85000.0)}
	# every posted document carries why and where from (ARCHITECTURE §1.4)
	assert pi.source_document == proposal.document and pi.nyabo_proposal == proposal.name
	assert pi.nyabo_explanation == proposal.explanation and pi.remarks == proposal.explanation
	assert pi.nyabo_approved_by == ACCOUNTANT and pi.nyabo_prompt_version == proposal.prompt_version
	assert pi.ebarimt_receipt_id == "00012345678901234567890123" and pi.ebarimt_lottery_no == "AB12345678"
	assert pi.ebarimt_verified == 1 and pi.bill_no == "00012345678901234567890123"
	proposal.reload()
	assert (proposal.status, proposal.approved_by, proposal.approved_telegram_id) == (
		"posted",
		ACCOUNTANT,
		"700002",
	)
	assert (proposal.posted_doctype, proposal.posted_name) == ("Purchase Invoice", pi.name)
	document = frappe.get_doc("Nyabo Document", proposal.document)
	assert (document.status, document.posted_doctype, document.posted_name) == (
		"posted",
		"Purchase Invoice",
		pi.name,
	)
	assert frappe.db.exists("Nyabo Event", {"event_type": "proposal_posted", "ref_name": pi.name})
	assert get_balance_on(INPUT_VAT, "2026-09-30") == 7727.27


def test_simplified_2027_posts_gross_journal_entry_without_vat_accounts(run_receipt):
	proposal = run_receipt("petrovis_fuel", date="2027-01-15")
	result = post.post_proposal(proposal.name, ACCOUNTANT)
	assert result["posted_doctype"] == "Journal Entry"
	je = frappe.get_doc("Journal Entry", result["posted_name"])
	assert je.docstatus == 1 and je.voucher_type == "Journal Entry" and str(je.posting_date) == "2027-01-15"
	assert je.user_remark == proposal.explanation
	assert _gl(je.name) == {(EXPENSE, 85000.0, 0.0), (PAYABLE, 0.0, 85000.0)}
	payable_row = next(r for r in je.accounts if r.account == PAYABLE)
	assert (payable_row.party_type, payable_row.party) == ("Supplier", "Петровис ХХК")
	assert je.source_document == proposal.document and je.nyabo_proposal == proposal.name
	assert je.nyabo_explanation == proposal.explanation and je.nyabo_approved_by == ACCOUNTANT
	assert get_balance_on(INPUT_VAT, "2027-01-31") == 0.0
	assert get_balance_on(EXPENSE, "2027-01-31") == 85000.0


def test_cash_receipt_journal_entry_credits_cash(run_receipt):
	proposal = run_receipt("non_vat_seller")
	result = post.post_proposal(proposal.name, ACCOUNTANT)
	assert _gl(result["posted_name"]) == {("6210 - Шатахуун - TST", 42000.0, 0.0), (CASH, 0.0, 42000.0)}


def test_cash_paid_vat_payer_invoice_is_posted_as_paid_and_credits_cash(run_receipt):
	"""The VAT makes it a Purchase Invoice, the cash payment makes it ERPNext's paid invoice:
	the payable nets to zero and the cash account carries the credit (PIPE-03)."""
	proposal = run_receipt("petrovis_fuel", payment_method="cash")
	result = post.post_proposal(proposal.name, ACCOUNTANT)
	assert result["posted_doctype"] == "Purchase Invoice"
	pi = frappe.get_doc("Purchase Invoice", result["posted_name"])
	assert pi.is_paid == 1 and pi.cash_bank_account == CASH and pi.paid_amount == 85000.0
	assert pi.outstanding_amount == 0.0 and pi.status == "Paid"
	assert _gl(pi.name) == {
		(EXPENSE, 77272.73, 0.0),
		(INPUT_VAT, 7727.27, 0.0),
		(PAYABLE, 0.0, 85000.0),
		(PAYABLE, 85000.0, 0.0),
		(CASH, 0.0, 85000.0),
	}
	assert get_balance_on(PAYABLE, "2026-09-30") == 0.0
	assert get_balance_on(CASH, "2026-09-30") == -85000.0


def test_unverified_pattern_is_refused_with_mongolian_message(run_receipt):
	proposal = run_receipt("petrovis_fuel")
	frappe.db.set_value("Nyabo Posting Pattern", "purchase_expense_vat_payer", "verified", 0)
	with pytest.raises(pipeline.UnverifiedRuleError) as info:
		post.post_proposal(proposal.name, ACCOUNTANT)
	assert info.value.message_mn == mn.MSG_UNVERIFIED_RULE_BLOCKED.format(rule="purchase_expense_vat_payer")
	assert frappe.db.count("Purchase Invoice") == 0 and frappe.db.count("Journal Entry") == 0
	assert frappe.db.get_value("Nyabo Proposal", proposal.name, "status") == "proposed"


def test_owner_cannot_approve_when_needs_accountant(run_receipt):
	proposal = run_receipt("petrovis_fuel")  # new supplier -> needs_accountant
	with pytest.raises(post.ApprovalError) as info:
		post.post_proposal(proposal.name, OWNER)
	assert info.value.message_mn == mn.MSG_ACCOUNTANT_ONLY
	assert frappe.db.count("Purchase Invoice") == 0
	# a plain proposal is fine for the owner
	proposal.db_set({"needs_accountant": 0})
	result = post.post_proposal(proposal.name, OWNER)
	assert frappe.db.get_value("Purchase Invoice", result["posted_name"], "nyabo_approved_by") == OWNER


def test_unlinked_user_cannot_approve(run_receipt):
	proposal = run_receipt("petrovis_fuel")
	with pytest.raises(post.ApprovalError) as info:
		post.post_proposal(proposal.name, NOBODY)
	assert info.value.message_mn == mn.MSG_NO_PERMISSION


def test_duplicate_post_is_idempotent(run_receipt):
	proposal = run_receipt("petrovis_fuel")
	first = post.post_proposal(proposal.name, ACCOUNTANT)
	second = post.post_proposal(proposal.name, ACCOUNTANT)
	assert first == second
	assert frappe.db.count("Purchase Invoice") == 1
	assert frappe.db.count("Nyabo Event", {"event_type": "proposal_posted"}) == 1


def test_rejected_proposal_cannot_be_posted(run_receipt):
	proposal = run_receipt("petrovis_fuel")
	post.reject(proposal.name, "dup", ACCOUNTANT)
	with pytest.raises(post.ApprovalError) as info:
		post.post_proposal(proposal.name, ACCOUNTANT)
	assert info.value.message_mn == mn.MSG_PROPOSAL_ALREADY_DECIDED.format(status="rejected")


def test_posting_into_closed_period_is_refused(run_receipt, books):
	frappe.get_doc(
		{
			"doctype": "Accounting Period",
			"period_name": "2026-08",
			"company": books,
			"start_date": "2026-08-01",
			"end_date": "2026-08-31",
		}
	).insert(ignore_permissions=True)
	proposal = run_receipt("petrovis_fuel", date="2026-08-20")
	with pytest.raises(post.ClosedPeriodError) as info:
		post.post_proposal(proposal.name, ACCOUNTANT)
	assert info.value.message_mn == mn.MSG_POSTING_IN_CLOSED_PERIOD.format(
		date="2026-08-20", period=mn.PERIOD_LABEL.format(year=2026, month=mn.MONTHS[7])
	)
	assert frappe.db.count("Purchase Invoice") == 0
	assert frappe.db.get_value("Nyabo Proposal", proposal.name, "status") == "proposed"


def test_missing_regime_on_posting_date_is_refused(run_receipt, books):
	proposal = run_receipt("petrovis_fuel")
	settings = frappe.get_doc("Nyabo Company Settings", books)
	settings.regimes = []
	settings.flags.ignore_permissions = True
	settings.save()
	from nyabo_mn.core.rules_engine import MissingRuleError

	with pytest.raises(MissingRuleError):
		post.post_proposal(proposal.name, ACCOUNTANT)
	assert frappe.db.count("Purchase Invoice") == 0
