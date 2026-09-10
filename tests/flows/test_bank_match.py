"""match.run / reconcile / proposals: exact match, fee, transfer, false-match guard, manual tap."""

from __future__ import annotations

import json

import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.matching import bank_import, cards, match, rules
from nyabo_mn.nyabo.seed import load_seed
from tests.fixtures.statements import make_fixtures as fixtures
from tests.flows import bank_helpers as helpers


@pytest.fixture
def books(company, frappe_hooks):
	with frappe_hooks(without_apps=("nyabo_mn",)):
		yield company


@pytest.fixture
def banks(books):
	helpers.register_layouts()
	return helpers.setup_banks(books)


def _import(company: str, builder) -> dict:
	filename, data = builder()
	return bank_import.import_statement(helpers.statement_document(company, filename, data))


def _bt(**filters):
	import frappe

	name = frappe.db.get_value("Bank Transaction", filters, "name")
	assert name, filters
	return frappe.get_doc("Bank Transaction", name)


def test_exact_match_reconciles_a_paid_purchase_invoice(books, banks):
	import frappe

	pi = helpers.paid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01", banks["khan_gl"])
	assert frappe.db.get_value("Purchase Invoice", pi.name, "status") == "Paid"
	candidates = match.candidates_for(books, banks["khan_gl"], direction=-1)
	assert [(c.doctype, c.name, str(c.amount), c.party_name) for c in candidates] == [
		("Purchase Invoice", pi.name, "-93500.00", "Петровис ХХК")
	]

	summary = _import(books, fixtures.khan_xlsx)
	assert summary["matched"] == 1
	assert summary["match"]["fee_proposals"] == 1 and summary["match"]["unmatched"] == 3
	bt = _bt(withdrawal=93500.0)
	assert bt.status == "Reconciled" and bt.unallocated_amount == 0 and bt.allocated_amount == 93500.0
	assert [(p.payment_document, p.payment_entry, p.allocated_amount) for p in bt.payment_entries] == [
		("Purchase Invoice", pi.name, 93500.0)
	]
	assert str(frappe.db.get_value("Purchase Invoice", pi.name, "clearance_date")) == "2026-09-02"
	event = frappe.get_all(
		"Nyabo Event",
		filters={"event_type": "bank_line_matched", "ref_name": bt.name},
		fields=["payload_json"],
	)
	assert len(event) == 1 and json.loads(event[0].payload_json)["manual"] is False
	text, proposal = cards.render_bank_line(bt.name)
	assert proposal is None and mn.CARD_BANK_MATCHED.split(":")[0] in text and pi.name in text
	# The invoice is spent: it is no longer a candidate.
	assert match.candidates_for(books, banks["khan_gl"], direction=-1) == []


def test_fee_line_yields_a_bank_fee_proposal_that_is_not_posted(books, banks):
	import frappe

	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=1500.0)
	proposal_name = rules.existing_proposal(bt.name)
	assert proposal_name
	proposal = frappe.get_doc("Nyabo Proposal", proposal_name)
	fee_code = load_seed("code_roles")["schemes"]["v1"]["bank_fee"]
	assert proposal.kind == "bank_line" and proposal.status == "proposed"
	assert proposal.account_code == fee_code and proposal.account.startswith(fee_code)
	assert proposal.needs_accountant == 0  # the pattern citation is verified (Заавар 116, 1.4; 12.2.2 А)
	assert proposal.bank_transaction == bt.name and proposal.vat_treatment == "none"
	entry = json.loads(proposal.entry_json)
	assert entry["pattern_id"] == "bank_fee_expense" and entry["document_kind"] == "journal_entry"
	assert [(line["account_code"], line["debit"], line["credit"]) for line in entry["lines"]] == [
		(fee_code, "1500.00", "0.00"),
		("1120", "0.00", "1500.00"),
	]
	assert mn.WARN_UNVERIFIED_RULE not in json.loads(proposal.warnings_json)
	assert proposal.explanation.endswith("1.4; 12.2.2 А")
	assert proposal.document == frappe.db.get_value("Nyabo Document", {"doc_type": "bank_statement"}, "name")
	assert frappe.db.count("Journal Entry") == 0
	assert bt.status == "Unreconciled"
	text, found = cards.render_bank_line(bt.name)
	assert found == proposal_name and fee_code in text
	# A second run neither re-proposes nor re-cards the line.
	stats = match.run(books, banks["khan"], send_cards=False)
	assert stats["skipped_proposed"] == 1 and rules.existing_proposal(bt.name) == proposal_name
	assert frappe.db.count("Nyabo Proposal") == 1


def test_own_transfer_is_paired_into_one_journal_proposal(books, banks):
	import frappe

	_import(books, fixtures.khan_xlsx)
	summary = _import(books, fixtures.tdb_xlsx)
	assert summary["match"]["transfers"] == 1
	out_bt = _bt(withdrawal=200000.0)
	in_bt = _bt(deposit=200000.0)
	proposal_name = rules.existing_proposal(out_bt.name)
	assert proposal_name and rules.existing_proposal(in_bt.name) is None
	proposal = frappe.get_doc("Nyabo Proposal", proposal_name)
	entry = json.loads(proposal.entry_json)
	assert entry["transfer"] == {"withdrawal": out_bt.name, "deposit": in_bt.name}
	assert [(line["account_code"], line["debit"], line["credit"]) for line in entry["lines"]] == [
		("1121", "200000.00", "0.00"),
		("1120", "0.00", "200000.00"),
	]
	text, _ = cards.render_bank_line(out_bt.name)
	assert mn.CARD_BANK_TRANSFER.split(":")[0] in text
	assert frappe.db.count("Journal Entry") == 0


def test_the_transfer_card_stops_warning_once_this_company_accepts_the_uncited_rule(books, banks):
	"""MAJOR 1 on the bank side: ``bank_transfer_internal`` ships uncited, and the card said so.

	An own-account transfer is ordinary work and the seed has no printed entry for it, so this
	card carried ⚠️ on every transfer for ever — including for the accountant who had already
	answered for it. The warning asks the acceptance too now, and only for these books.
	"""
	import frappe

	from nyabo_mn.rules import verify
	from tests.flows.conftest import seed_patterns

	assert not rules.pattern_citation(rules.TRANSFER_PATTERN_ID).verified
	# The row an acceptance points at; this module's fixtures do not sync the whole seed.
	seed_patterns(verified=False, only=(rules.TRANSFER_PATTERN_ID,))
	_import(books, fixtures.khan_xlsx)
	_import(books, fixtures.tdb_xlsx)
	before = frappe.get_doc("Nyabo Proposal", rules.existing_proposal(_bt(withdrawal=200000.0).name))
	assert mn.WARN_UNVERIFIED_RULE in json.loads(before.warnings_json)

	verify.accept(verify.KIND_PATTERN, rules.TRANSFER_PATTERN_ID, books, "Administrator")

	assert rules.pattern_cleared(
		rules.TRANSFER_PATTERN_ID, books, rules.pattern_citation(rules.TRANSFER_PATTERN_ID)
	)
	assert not rules.pattern_cleared(
		rules.TRANSFER_PATTERN_ID, "Гурав ХХК", rules.pattern_citation(rules.TRANSFER_PATTERN_ID)
	), "an acceptance speaks for one company's books and no other"


def test_false_match_guard_leaves_a_far_dissimilar_voucher_alone(books, banks):
	import frappe

	pi = helpers.paid_purchase_invoice(books, "Хос ХХК", 50000, "2026-08-20", banks["khan_gl"])
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=50000.0)  # "Тэнгэр ХХК төлбөр" on 2026-09-06
	assert bt.status == "Unreconciled" and not bt.payment_entries
	assert frappe.db.get_value("Purchase Invoice", pi.name, "clearance_date") is None
	text, proposal = cards.render_bank_line(bt.name)
	assert proposal is None and mn.CARD_BANK_UNMATCHED in text


def test_manual_find_and_reconcile(books, banks, as_user):
	import frappe

	pi = helpers.paid_purchase_invoice(books, "Хос ХХК", 50000, "2026-08-20", banks["khan_gl"])
	helpers.paid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01", banks["khan_gl"])
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=50000.0)
	found = match.find_candidates(bt.name, "Хос")
	assert found and found[0]["doctype"] == "Purchase Invoice" and found[0]["name"] == pi.name
	assert found[0]["amount_diff"] == "0.00"
	assert set(found[0]) >= {"doctype", "name", "date", "amount", "party_name", "score"}
	assert pi.name in cards.render_candidates(found)
	assert cards.render_candidates([]) == mn.MSG_BANK_FIND_NONE
	# A paid invoice moved the bank already: it is reconciled, not settled (BANK-08).
	assert found[0]["needs_settlement"] is False
	assert match.settlement_needed("Purchase Invoice", pi.name) is False
	assert match.settlement_candidate(bt.name) is None

	with as_user("acc@example.com", ["Nyabo Accountant"]) as user:
		result = match.reconcile(bt.name, "Purchase Invoice", pi.name, user, telegram_id="2002")
	assert result["status"] == "Reconciled" and result["allocated_amount"] == 50000.0
	assert str(frappe.db.get_value("Purchase Invoice", pi.name, "clearance_date")) == "2026-09-06"
	event = frappe.get_all(
		"Nyabo Event",
		filters={"event_type": "bank_line_matched", "ref_name": bt.name},
		fields=["actor_user", "actor_telegram_id", "payload_json"],
	)
	assert event[0].actor_user == "acc@example.com" and event[0].actor_telegram_id == "2002"
	assert json.loads(event[0].payload_json)["manual"] is True
	with pytest.raises(match.MatchError) as info:
		match.reconcile(bt.name, "Purchase Invoice", pi.name, "acc@example.com")
	assert info.value.message_mn == mn.MSG_BANK_LINE_ALREADY_RECONCILED
	with pytest.raises(match.MatchError):
		match.reconcile(_bt(deposit=1250000.0).name, "Stock Entry", "X", "acc@example.com")
	with pytest.raises(match.MatchError):
		match.reconcile(_bt(deposit=1250000.0).name, "Sales Invoice", "missing", "acc@example.com")


def test_unmatched_expense_line_is_classified_by_the_mock_under_simulation(
	books, banks, frappe_flags, monkeypatch
):
	import frappe

	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=50000.0)
	with frappe_flags(nyabo_simulation=True):
		proposal_name = rules.propose_for_line(bt.name)
	proposal = frappe.get_doc("Nyabo Proposal", proposal_name)
	assert proposal.account_code == "6210" and proposal.model == "mock-model"
	assert proposal.kind == "bank_line" and proposal.rule_applied is None
	assert json.loads(proposal.confidence_json)["account_code"] == 0.9
	assert frappe.db.count("Nyabo LLM Call", {"purpose": "classify"}) == 1
	assert rules.propose_for_line(bt.name) == proposal_name

	# Without a usable model the default expense account is proposed and flagged.
	from nyabo_mn.config import MissingSettingError

	monkeypatch.setattr(
		rules, "_llm_client", lambda company: (_ for _ in ()).throw(MissingSettingError("no key"))
	)
	other = frappe.get_doc("Nyabo Proposal", rules.propose_for_line(_bt(withdrawal=200000.0).name))
	assert other.account_code == "6910" and "llm_unavailable" in json.loads(other.warnings_json)
	assert other.needs_accountant == 1

	# An inflow goes to the receivable role for the accountant.
	income = frappe.get_doc("Nyabo Proposal", rules.propose_for_line(_bt(deposit=1250000.0).name))
	assert income.account_code == load_seed("code_roles")["schemes"]["v1"]["receivable"]
	entry = json.loads(income.entry_json)
	assert entry["lines"][0]["account_code"] == "1120" and entry["lines"][0]["debit"] == "1250000.00"


def test_unmatched_lines_are_carded_into_the_statement_chat(books, banks):
	"""Every unmatched line reaches the accountant as a card (ARCHITECTURE §5.4)."""
	import frappe

	from nyabo_mn.telegram import api
	from tests.fixtures.telegram.fake_bot import FakeBotApi

	filename, data = fixtures.khan_xlsx()
	document = helpers.statement_document(books, filename, data)
	frappe.db.set_value("Nyabo Document", document, "telegram_chat_id", "3101")
	bot = FakeBotApi()
	with api.use_bot(bot):
		summary = bank_import.import_statement(document)
	assert summary["match"]["unmatched"] == 4 and summary["match"]["cards_sent"] == 4
	sent = bot.sent("send_message")
	assert len(sent) == 4 and {call["chat_id"] for call in sent} == {"3101"}
	assert mn.CARD_BANK_UNMATCHED in sent[0]["text"]
	buttons = [b["callback_data"] for row in sent[0]["reply_markup"]["inline_keyboard"] for b in row]
	assert any(data.endswith(":find") for data in buttons)
	# Nothing to settle here: the settlement button only appears with an open invoice (BANK-08).
	assert not any(":st:" in data for data in buttons)

	# No chat to send to: the line is still counted, the import is not rolled back.
	second = helpers.statement_document(books, *fixtures.tdb_xlsx())
	bot.clear()
	with api.use_bot(bot):
		other = bank_import.import_statement(second)
	assert other["match"]["cards_sent"] == 0 and bot.calls == []


def test_bank_line_patterns_exist_and_stop_at_the_unverified_gate(books, banks):
	"""Both bank pattern ids resolve to a row an admin can verify (ARCHITECTURE §1.2)."""
	import frappe

	from nyabo_mn.agent import pipeline, post
	from tests.flows.conftest import seed_patterns

	inserted = seed_patterns(verified=False, only=(rules.EXPENSE_PATTERN_ID, rules.TRANSFER_PATTERN_ID))
	assert sorted(inserted) == sorted([rules.EXPENSE_PATTERN_ID, rules.TRANSFER_PATTERN_ID])
	for pattern_id in (rules.EXPENSE_PATTERN_ID, rules.TRANSFER_PATTERN_ID):
		assert pipeline.pattern_by_id(pattern_id).verified is False

	_import(books, fixtures.khan_xlsx)
	_import(books, fixtures.tdb_xlsx)
	expense = match.propose_expense(_bt(withdrawal=50000.0).name, "6910")
	transfer = rules.existing_proposal(_bt(withdrawal=200000.0).name)
	assert frappe.db.get_value("Nyabo Proposal", expense, "posting_pattern") == rules.EXPENSE_PATTERN_ID
	assert frappe.db.get_value("Nyabo Proposal", transfer, "posting_pattern") == rules.TRANSFER_PATTERN_ID
	for proposal_name, pattern_id in (
		(expense, rules.EXPENSE_PATTERN_ID),
		(transfer, rules.TRANSFER_PATTERN_ID),
	):
		with pytest.raises(pipeline.UnverifiedRuleError) as info:
			post.post_proposal(proposal_name, "Administrator")
		assert info.value.message_mn == mn.MSG_UNVERIFIED_RULE_BLOCKED.format(rule=pattern_id)
	assert frappe.db.count("Journal Entry") == 0

	# The admin verifies the row in the desk and the same tap posts.
	frappe.db.set_value("Nyabo Posting Pattern", rules.EXPENSE_PATTERN_ID, "verified", 1)
	assert post.post_proposal(expense, "Administrator")["posted_doctype"] == "Journal Entry"


def test_the_bank_fee_rule_is_decided_even_when_two_rules_share_a_timestamp(books):
	"""The flake behind test_bank_fee_rule_prefers_the_company_rule_row, pinned as a rule.

	Provisioning writes a `bank_fee` rule from `rules_default.json`, so the accountant's own
	rule is the second row on the company and `order_by="modified desc"` is what prefers it.
	Two writes inside one clock tick — ordinary on the Windows test clock, possible anywhere
	after a bulk update — left that comparison undecided, and which rule won then depended on
	the order rows had been inserted in. In the books that is one statement line booked to a
	different account than the next.
	"""
	import frappe

	seeded = frappe.get_all(
		"Nyabo Rule", filters={"company": books, "match_type": "bank_fee"}, fields=["name"]
	)
	assert len(seeded) == 1, "provisioning seeds one bank_fee rule; the test's own makes two"
	rule = frappe.get_doc(
		{
			"doctype": "Nyabo Rule",
			"company": books,
			"match_type": "bank_fee",
			"match_value": "хураамж|шимтгэл",
			"target_account_code": "6810",
			"vat_treatment": "none",
			"source": "accountant",
			"status": "active",
		}
	).insert()
	stamp = frappe.db.get_value("Nyabo Rule", rule.name, "modified")
	frappe.db.set_value("Nyabo Rule", seeded[0]["name"], "match_value", "шимтгэл", modified=stamp)

	assert rules.bank_fee_rule(books)["name"] == rule.name


def test_bank_fee_rule_prefers_the_company_rule_row(books, banks):
	import frappe

	rule = frappe.get_doc(
		{
			"doctype": "Nyabo Rule",
			"company": books,
			"match_type": "bank_fee",
			"match_value": "хураамж|шимтгэл",
			"target_account_code": "6810",
			"vat_treatment": "none",
			"source": "seed",
			"status": "active",
		}
	).insert()
	_import(books, fixtures.khan_xlsx)
	proposal = frappe.get_doc("Nyabo Proposal", rules.existing_proposal(_bt(withdrawal=1500.0).name))
	assert proposal.rule_applied == rule.name
	assert frappe.db.get_value("Nyabo Rule", rule.name, "hit_count") == 1
	assert rules.is_fee_line("Гүйлгээний шимтгэл", {"match_value": "хураамж|шимтгэл"})
	assert not rules.is_fee_line("Петровис ХХК", {"match_value": "хураамж|шимтгэл"})
