"""Card actions after the proposal exists: change account, reject, account pickers, correction
proposals after a reversal, and the learned rule that two agreeing corrections create."""

from __future__ import annotations

import json

import frappe
import pytest

from nyabo_mn.agent import post
from nyabo_mn.i18n import mn
from tests.flows.conftest import ACCOUNTANT, OWNER


def test_change_account_rewrites_entry_and_records_correction(run_receipt):
	proposal = run_receipt("petrovis_fuel")
	updated = post.change_account(proposal.name, "6220", ACCOUNTANT, telegram_id="700002")
	assert updated.account_code == "6220" and updated.account == "6220 - Тээврийн зардал - TST"
	codes = {line["account_code"] for line in json.loads(updated.entry_json)["lines"]}
	assert codes == {"6220", "1810", "2110"}
	corrections = frappe.get_all(
		"Nyabo Correction",
		filters={"proposal": proposal.name},
		fields=["field", "proposed_value", "corrected_value", "corrected_by", "source", "supplier"],
	)
	assert len(corrections) == 1
	row = corrections[0]
	assert (row.field, row.proposed_value, row.corrected_value) == ("account_code", "6210", "6220")
	assert (row.corrected_by, row.source, row.supplier) == (ACCOUNTANT, "edit", "Петровис ХХК")
	# posting uses the corrected account
	result = post.post_proposal(proposal.name, ACCOUNTANT)
	pi = frappe.get_doc("Purchase Invoice", result["posted_name"])
	assert pi.items[0].expense_account == "6220 - Тээврийн зардал - TST"


def test_change_account_refuses_unknown_or_group_code(run_receipt):
	proposal = run_receipt("petrovis_fuel")
	with pytest.raises(post.ApprovalError) as info:
		post.change_account(proposal.name, "6000", ACCOUNTANT)  # a group
	assert info.value.message_mn == mn.MSG_ACCOUNT_CODE_INVALID.format(code="6000")
	with pytest.raises(post.ApprovalError):
		post.change_account(proposal.name, "9999", ACCOUNTANT)


def test_reject_records_reason_and_marks_document(run_receipt):
	proposal = run_receipt("petrovis_fuel")
	post.reject(proposal.name, "personal", OWNER, telegram_id="700001")
	proposal.reload()
	assert proposal.status == "rejected" and proposal.rejection_reason == mn.REJECT_PERSONAL
	assert frappe.db.get_value("Nyabo Document", proposal.document, "status") == "rejected"
	row = frappe.get_all(
		"Nyabo Correction",
		filters={"proposal": proposal.name},
		fields=["field", "source", "reason", "reason_text"],
	)[0]
	assert (row.field, row.source, row.reason, row.reason_text) == (
		"rejected",
		"rejection",
		"personal",
		mn.REJECT_PERSONAL,
	)
	assert frappe.db.exists("Nyabo Event", {"event_type": "proposal_rejected", "ref_name": proposal.name})


def test_two_agreeing_corrections_learn_a_pending_rule(run_receipt, books):
	first = run_receipt("petrovis_fuel")
	post.change_account(first.name, "6220", ACCOUNTANT)
	assert frappe.db.count("Nyabo Rule", {"source": "learned"}) == 0
	second = run_receipt("petrovis_fuel")
	post.change_account(second.name, "6220", ACCOUNTANT)
	rules = frappe.get_all(
		"Nyabo Rule",
		filters={"source": "learned"},
		fields=[
			"name",
			"match_type",
			"match_value",
			"target_account_code",
			"status",
			"created_from_corrections",
		],
	)
	assert len(rules) == 1
	rule = rules[0]
	assert (rule.match_type, rule.match_value, rule.target_account_code) == (
		"supplier_register_no",
		"2550385",
		"6220",
	)
	assert rule.status == "pending_confirmation"
	names = frappe.get_all(
		"Nyabo Correction", filters={"field": "account_code"}, pluck="name", order_by="creation asc"
	)
	assert rule.created_from_corrections == ", ".join(names)
	# a pending rule never fires; a third correction does not create a duplicate
	third = run_receipt("petrovis_fuel")
	assert third.rule_applied is None and third.account_code == "6210"
	post.change_account(third.name, "6220", ACCOUNTANT)
	assert frappe.db.count("Nyabo Rule", {"source": "learned"}) == 1
	# confirmation by the accountant activates it and the next receipt uses it
	with pytest.raises(post.ApprovalError):
		post.confirm_rule(rule.name, OWNER)
	post.confirm_rule(rule.name, ACCOUNTANT)
	assert frappe.db.get_value("Nyabo Rule", rule.name, "status") == "active"
	fourth = run_receipt("petrovis_fuel")
	assert fourth.rule_applied == rule.name and fourth.account_code == "6220"


def test_corrections_that_disagree_do_not_learn(run_receipt):
	post.change_account(run_receipt("petrovis_fuel").name, "6220", ACCOUNTANT)
	post.change_account(run_receipt("petrovis_fuel").name, "6910", ACCOUNTANT)
	assert frappe.db.count("Nyabo Rule", {"source": "learned"}) == 0


def test_top_accounts_prefers_usage_then_chart_defaults(run_receipt, books):
	assert [code for code, _n in post.top_accounts(books)][:1] == ["6910"]  # settings default first
	assert len(post.top_accounts(books, n=6)) == 6
	proposal = run_receipt("petrovis_fuel")
	post.post_proposal(proposal.name, ACCOUNTANT)
	top = post.top_accounts(books, n=3)
	assert top[0] == ("6210", "Шатахуун") and top[1][0] == "6910"
	assert all(code != "6000" for code, _n in top)


def test_search_accounts_by_code_prefix_or_name(books):
	assert post.search_accounts(books, "62") == [("6210", "Шатахуун"), ("6220", "Тээврийн зардал")]
	assert post.search_accounts(books, "түрээс") == [("6310", "Түрээс")]
	assert post.search_accounts(books, "") == []


def test_make_correction_proposal_prefills_from_posted_document(run_receipt):
	proposal = run_receipt("petrovis_fuel")
	posted = post.post_proposal(proposal.name, ACCOUNTANT)
	name = post.make_correction_proposal(
		posted["posted_doctype"], posted["posted_name"], "account", ACCOUNTANT
	)
	correction = frappe.get_doc("Nyabo Proposal", name)
	assert (
		correction.kind == "correction"
		and correction.status == "proposed"
		and correction.needs_accountant == 1
	)
	assert correction.document == proposal.document and correction.supplier == proposal.supplier
	assert correction.explanation.startswith(
		mn.EXPL_CORRECTION_PREFIX.format(reason=mn.CORRECT_WRONG_ACCOUNT)
	)
	entry = json.loads(correction.entry_json)
	assert entry["pattern_id"] == "purchase_expense_vat_payer" and entry["total"] == "85000.00"
	assert frappe.db.exists("Nyabo Event", {"event_type": "correction_proposal_created", "ref_name": name})
	# the corrected proposal posts like any other after the accountant changes the account
	post.change_account(name, "6220", ACCOUNTANT)
	result = post.post_proposal(name, ACCOUNTANT)
	assert frappe.db.get_value("Purchase Invoice", result["posted_name"], "nyabo_proposal") == name


def test_make_correction_proposal_refuses_manual_documents(books):
	frappe.get_doc({"doctype": "Supplier", "supplier_name": "Гар ХХК"}).insert(ignore_permissions=True)
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": books,
			"posting_date": "2026-03-05",
			"accounts": [
				{"account": "6210 - Шатахуун - TST", "debit_in_account_currency": 100},
				{"account": "1110 - Касс - TST", "credit_in_account_currency": 100},
			],
		}
	).insert(ignore_permissions=True)
	with pytest.raises(post.ApprovalError) as info:
		post.make_correction_proposal("Journal Entry", je.name, "amount", ACCOUNTANT)
	assert info.value.message_mn == mn.MSG_CORRECTION_ORIGINAL_NOT_NYABO.format(name=je.name)
