"""process_receipt end to end against the stub: extraction -> seller -> supplier -> rules/classification
-> pattern -> validation -> Nyabo Proposal, under both regimes, with the four fixture receipts."""

from __future__ import annotations

import json
from decimal import Decimal

import frappe
import pytest

from nyabo_mn.agent import pipeline
from nyabo_mn.agent.llm_client import LlmProviderError
from nyabo_mn.i18n import mn


def _entry(proposal):
	return json.loads(proposal.entry_json)


def _lines(proposal):
	return {
		(line["account_code"], Decimal(line["debit"]), Decimal(line["credit"]))
		for line in _entry(proposal)["lines"]
	}


def test_vat_payer_receipt_proposes_purchase_invoice_with_input_vat(run_receipt):
	proposal = run_receipt("petrovis_fuel")
	assert proposal.status == "proposed" and proposal.kind == "receipt"
	assert proposal.vat_treatment == "withheld"
	assert proposal.account_code == "6210" and proposal.account == "6210 - Шатахуун - TST"
	entry = _entry(proposal)
	assert entry["document_kind"] == "purchase_invoice"
	assert entry["pattern_id"] == "purchase_expense_vat_payer"
	assert _lines(proposal) == {
		("6210", Decimal("77272.73"), Decimal("0.00")),
		("1810", Decimal("7727.27"), Decimal("0.00")),
		("2110", Decimal("0.00"), Decimal("85000.00")),
	}
	assert proposal.total == 85000.0 and proposal.vat_amount == 7727.27
	assert proposal.explanation.endswith(f", {mn.CITATION_SECTION_PENDING}")
	assert "Заавар 116" in proposal.citation
	assert proposal.supplier == "Петровис ХХК" and proposal.supplier_is_new == 1
	assert frappe.db.get_value("Supplier", "Петровис ХХК", "nyabo_pending_confirmation") == 1
	assert frappe.db.get_value("Supplier", "Петровис ХХК", "tin") == "37200019261"
	assert mn.WARN_NEW_SUPPLIER in json.loads(proposal.warnings_json)
	assert proposal.needs_accountant == 1  # new supplier -> accountant only
	assert frappe.db.get_value("Nyabo Document", proposal.document, "status") == "proposed"
	verification = json.loads(proposal.verification_json)
	assert verification["seller"]["found"] is True and verification["seller"]["vat_payer"] is True
	assert verification["receipt"]["status"] == "unsupported"
	assert proposal.prompt_version.startswith("receipt_extract.v1+classify.v1")
	calls = frappe.get_all("Nyabo LLM Call", filters={"proposal": proposal.name}, fields=["purpose"])
	assert sorted(c.purpose for c in calls) == ["classify", "extract"]
	assert frappe.db.exists("Nyabo Event", {"event_type": "proposal_created", "ref_name": proposal.name})


def test_vat_payer_receipt_paid_in_cash_credits_cash_not_the_payable(run_receipt):
	"""A receipt paid over the counter credits cash even when the input VAT makes it an invoice:
	no bank statement line will ever settle a payable that was already paid (D-019)."""
	proposal = run_receipt("petrovis_fuel", payment_method="cash")
	assert proposal.vat_treatment == "withheld"
	entry = _entry(proposal)
	assert entry["document_kind"] == "purchase_invoice"
	assert _lines(proposal) == {
		("6210", Decimal("77272.73"), Decimal("0.00")),
		("1810", Decimal("7727.27"), Decimal("0.00")),
		("1110", Decimal("0.00"), Decimal("85000.00")),
	}


def test_same_receipt_under_simplified_regime_proposes_gross_journal_entry(run_receipt):
	proposal = run_receipt("petrovis_fuel", date="2027-01-15")
	assert proposal.vat_treatment == "in_expense"
	entry = _entry(proposal)
	assert entry["document_kind"] == "journal_entry"
	assert entry["pattern_id"] == "purchase_expense_non_vat"
	assert _lines(proposal) == {
		("6210", Decimal("85000.00"), Decimal("0.00")),
		("2110", Decimal("0.00"), Decimal("85000.00")),
	}
	assert proposal.vat_amount == 0.0
	assert "1810" not in {code for code, _d, _c in _lines(proposal)}
	assert mn.EXPL_NO_VAT_NON_PAYER in proposal.explanation


def test_non_vat_seller_paid_in_cash_credits_cash_without_vat(run_receipt):
	proposal = run_receipt(
		"non_vat_seller",
		classify={
			"account_code": "6510",
			"vat_treatment": "withheld",
			"reason_mn": "Принтерийн хор бичиг хэргийн зардал.",
			"confidence": 0.8,
		},
	)
	assert proposal.vat_treatment == "none"  # nothing printed to withhold, whatever the model said
	assert proposal.account_code == "6510"
	assert _entry(proposal)["document_kind"] == "journal_entry"
	assert _lines(proposal) == {
		("6510", Decimal("42000.00"), Decimal("0.00")),
		("1110", Decimal("0.00"), Decimal("42000.00")),
	}


def test_vat_payer_company_but_non_vat_seller_keeps_vat_in_expense(run_receipt):
	proposal = run_receipt(
		"petrovis_fuel", seller_tin="12345678901", seller_register_no="9988776", seller_name="Ганбат"
	)
	assert proposal.vat_treatment == "in_expense"
	assert mn.WARN_SELLER_NOT_VAT_PAYER in json.loads(proposal.warnings_json)
	assert _entry(proposal)["document_kind"] == "journal_entry"
	assert ("6210", Decimal("85000.00"), Decimal("0.00")) in _lines(proposal)


def test_low_confidence_marks_needs_accountant_with_field_warnings(run_receipt):
	proposal = run_receipt("low_confidence")
	warnings = json.loads(proposal.warnings_json)
	assert proposal.needs_accountant == 1
	assert mn.WARN_LOW_CONFIDENCE.format(field=mn.FIELD_LABELS["total"], confidence=60) in warnings
	assert mn.WARN_LOW_CONFIDENCE.format(field=mn.FIELD_LABELS["date"], confidence=55) in warnings
	assert mn.WARN_LOW_CONFIDENCE.format(field=mn.FIELD_LABELS["vat_amount"], confidence=40) in warnings


def test_injection_text_sets_warning_and_event(run_receipt):
	proposal = run_receipt("injection")
	assert mn.WARN_INJECTION_SUSPECTED in json.loads(proposal.warnings_json)
	assert proposal.needs_accountant == 1
	events = frappe.get_all(
		"Nyabo Event",
		filters={"event_type": "injection_suspected", "ref_name": proposal.document},
		fields=["reason", "payload_json"],
	)
	assert len(events) == 1 and "ignore all previous instructions" in events[0].reason.lower()
	# The instruction was not acted on: the proposal still needs a human tap.
	assert proposal.status == "proposed"


def test_missing_date_uses_today_and_warns(run_receipt):
	proposal = run_receipt("petrovis_fuel", date=None)
	assert mn.MSG_DATE_DEFAULTED_TODAY in json.loads(proposal.warnings_json)
	assert proposal.needs_accountant == 1
	assert str(proposal.posting_date) == str(frappe.utils.today())


def test_existing_supplier_is_matched_by_tin_then_name(run_receipt, books):
	frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": "Петровис ХХК",
			"tin": "37200019261",
			"supplier_type": "Company",
		}
	).insert(ignore_permissions=True)
	proposal = run_receipt("petrovis_fuel")
	assert proposal.supplier == "Петровис ХХК" and proposal.supplier_is_new == 0
	assert mn.WARN_NEW_SUPPLIER not in json.loads(proposal.warnings_json)
	# name-only match (no identifiers on the receipt)
	frappe.get_doc(
		{"doctype": "Supplier", "supplier_name": "Номин Юнайтед ХХК", "supplier_type": "Company"}
	).insert(ignore_permissions=True)
	second = run_receipt(
		"low_confidence", seller_tin=None, seller_register_no=None, seller_name="Номин Юнайтед"
	)
	assert second.supplier == "Номин Юнайтед ХХК" and second.supplier_is_new == 0


def test_active_rule_wins_over_classification_and_counts_hits(run_receipt, books):
	rule = frappe.get_doc(
		{
			"doctype": "Nyabo Rule",
			"company": books,
			"match_type": "supplier_name_pattern",
			"match_value": "петровис",
			"target_account_code": "6220",
			"vat_treatment": "withheld",
			"source": "accountant",
			"status": "active",
		}
	).insert(ignore_permissions=True)
	proposal = run_receipt("petrovis_fuel")
	assert proposal.rule_applied == rule.name and proposal.account_code == "6220"
	assert frappe.db.get_value("Nyabo Rule", rule.name, "hit_count") == 1
	assert frappe.db.get_value("Nyabo Rule", rule.name, "last_hit") is not None
	assert rule.name in proposal.explanation
	# Only one model call (extraction): the rule replaced classification.
	purposes = [
		c.purpose
		for c in frappe.get_all("Nyabo LLM Call", filters={"proposal": proposal.name}, fields=["purpose"])
	]
	assert purposes == ["extract"]


def test_rule_order_register_no_before_name_pattern(run_receipt, books):
	frappe.get_doc(
		{
			"doctype": "Nyabo Rule",
			"company": books,
			"match_type": "supplier_name_pattern",
			"match_value": "петровис",
			"target_account_code": "6220",
			"status": "active",
		}
	).insert(ignore_permissions=True)
	by_register = frappe.get_doc(
		{
			"doctype": "Nyabo Rule",
			"company": books,
			"match_type": "supplier_register_no",
			"match_value": "2550385",
			"target_account_code": "6910",
			"status": "active",
		}
	).insert(ignore_permissions=True)
	proposal = run_receipt("petrovis_fuel")
	assert proposal.rule_applied == by_register.name and proposal.account_code == "6910"


def test_extraction_failure_marks_document_failed_and_reraises(store_receipt, mock_provider):
	class Broken:
		provider = "mock"
		model = "broken"

		def structured(self, **kwargs):
			raise LlmProviderError("boom", status_code=500)

		def with_tools(self, **kwargs):
			raise LlmProviderError("boom", status_code=500)

	document = store_receipt()
	with pytest.raises(LlmProviderError):
		pipeline.process_receipt(document, client=Broken(), provider=mock_provider, send=None)
	doc = frappe.get_doc("Nyabo Document", document)
	assert doc.status == "failed" and "LlmProviderError" in doc.error
	assert frappe.db.exists("Nyabo Event", {"event_type": "pipeline_failed", "ref_name": document})
	assert frappe.db.count("Nyabo Proposal") == 0


def test_missing_total_fails_with_mongolian_message(store_receipt, mock_llm, mock_provider):
	document = store_receipt()
	with pytest.raises(pipeline.PipelineError) as info:
		pipeline.process_receipt(
			document, client=mock_llm("petrovis_fuel", total=None), provider=mock_provider, send=None
		)
	assert info.value.message_mn == mn.MSG_RECEIPT_AMOUNT_MISSING
	assert frappe.db.get_value("Nyabo Document", document, "error") == mn.MSG_RECEIPT_AMOUNT_MISSING


def test_card_sender_is_called_with_the_proposal(store_receipt, mock_llm, mock_provider):
	sent = []
	document = store_receipt()
	name = pipeline.process_receipt(document, client=mock_llm(), provider=mock_provider, send=sent.append)
	assert sent == [name]


def test_default_send_card_survives_missing_telegram_handler(store_receipt, mock_llm, mock_provider):
	document = store_receipt()
	name = pipeline.process_receipt(document, client=mock_llm(), provider=mock_provider)
	assert frappe.db.get_value("Nyabo Proposal", name, "status") == "proposed"


def test_few_shot_examples_come_from_approved_proposals(run_receipt, books):
	from nyabo_mn.agent import few_shot

	proposal = run_receipt("petrovis_fuel")
	assert few_shot.build(books) == []
	proposal.db_set({"status": "approved"})
	few_shot.invalidate(books)
	bundle = few_shot.bundle(books)
	assert bundle == [
		{
			"seller": "Петровис ХХК",
			"description": "АИ-92 бензин",
			"account_code": "6210",
			"vat_treatment": "withheld",
		}
	]
	assert few_shot.refresh_all() == {books: 1}
	assert frappe.db.get_value("Nyabo Company Settings", books, "few_shot_refreshed_at") is not None


def test_chart_scheme_falls_back_to_the_chart_that_is_installed(books):
	settings = pipeline.company_settings(books)
	settings.chart_scheme = "v03"
	leaves = [code for code, _n in pipeline.chart_leaves(books)]
	assert pipeline.chart_scheme(books, settings, leaves) == "v1"
	assert pipeline.role_code(books, "v1", "payable") == "2110"
	assert pipeline.role_code(books, "v1", "si_payable") is None
	assert pipeline.family_for_code(books, "1410") == pipeline.FAMILY_INVENTORY
	assert pipeline.family_for_code(books, "1510") == pipeline.FAMILY_FIXED_ASSET
	assert pipeline.family_for_code(books, "6210") == pipeline.FAMILY_EXPENSE
