"""process_receipt end to end against the stub: extraction -> seller -> supplier -> rules/classification
-> pattern -> validation -> Nyabo Proposal, under both regimes, with the four fixture receipts."""

from __future__ import annotations

import datetime as dt
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
	no bank statement line will ever settle a payable that was already paid (PIPE-03)."""
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


# --- the QR arm (ARCHITECTURE §5.3 step 1, §7) -----------------------------------------------------

QR_DATA = "0009900000000000000000000000000000000000000000000000000000000000000"


def _decoder(monkeypatch, value):
	"""Stand in for ebarimt.qr.decode; the real one needs pyzbar/zxing and a photo of a QR."""
	seen: list[bytes] = []

	def _decode(image_bytes: bytes) -> str | None:
		seen.append(image_bytes)
		return value

	from nyabo_mn.ebarimt import qr

	monkeypatch.setattr(qr, "decode", _decode)
	return seen


def test_a_decoded_qr_reaches_the_proposal_the_card_and_the_posted_document(run_receipt, monkeypatch):
	from nyabo_mn.agent import post
	from nyabo_mn.telegram.handlers.receipt import card_for
	from tests.flows.conftest import ACCOUNTANT

	seen = _decoder(monkeypatch, QR_DATA)
	proposal = run_receipt("petrovis_fuel")
	assert seen and isinstance(seen[0], bytes) and seen[0]  # the photo bytes, before extraction
	verification = json.loads(proposal.verification_json)
	assert verification["qr_data"] == QR_DATA
	# The provider is asked to verify with the payload we read (no endpoint exists yet, §7).
	assert verification["receipt"]["status"] == "unsupported"

	text, _markup = card_for(proposal)
	# UX-10 moved the three verification facts off the money line onto their own line so the
	# money line stays readable on a phone; the QR fact sits next to the unchecked-receipt one.
	expected = (
		f"{mn.VERIFICATION_SELLER_OK} · {mn.VERIFICATION_RECEIPT_UNCHECKED} · {mn.VERIFICATION_QR_FOUND}"
	)
	assert any(line.endswith(expected) for line in text.split("\n")), text

	result = post.post_proposal(proposal.name, ACCOUNTANT, approver_telegram_id="700002")
	posted = frappe.get_doc(result["posted_doctype"], result["posted_name"])
	assert posted.ebarimt_qr_data == QR_DATA and posted.ebarimt_verified == 1


def test_without_a_decodable_qr_the_card_says_so_and_nothing_is_stored(run_receipt, monkeypatch):
	from nyabo_mn.agent import post
	from nyabo_mn.telegram.handlers.receipt import card_for
	from tests.flows.conftest import ACCOUNTANT

	_decoder(monkeypatch, None)
	proposal = run_receipt("petrovis_fuel")
	assert json.loads(proposal.verification_json)["qr_data"] is None
	assert mn.VERIFICATION_QR_MISSING in card_for(proposal)[0]
	result = post.post_proposal(proposal.name, ACCOUNTANT, approver_telegram_id="700002")
	assert not frappe.get_doc(result["posted_doctype"], result["posted_name"]).ebarimt_qr_data


def test_a_qr_never_contradicts_the_vision_answer(run_receipt, monkeypatch):
	"""Recorded deviation from §5.3 step 7: the payload is opaque, so no mismatch is asserted.

	The receipt below is read as 85 000₮ while the QR string spells 12 345; if the payload
	format is ever published, this test is the one that must start expecting the warning.
	"""
	_decoder(monkeypatch, "12345")
	proposal = run_receipt("petrovis_fuel")
	assert proposal.total == 85000.0
	assert mn.WARN_QR_VISION_MISMATCH not in json.loads(proposal.warnings_json)
	read = pipeline.Receipt(
		seller_name="Петровис ХХК",
		seller_tin=None,
		seller_register_no=None,
		date=None,
		total=Decimal("85000"),
		vat_amount=None,
	)
	assert pipeline._qr_vision_mismatch("12345", read) is False
	assert pipeline._qr_vision_mismatch(None, read) is False


def test_missing_date_uses_today_and_warns(run_receipt):
	proposal = run_receipt("petrovis_fuel", date=None)
	assert mn.MSG_DATE_DEFAULTED_TODAY in json.loads(proposal.warnings_json)
	assert proposal.needs_accountant == 1
	assert str(proposal.posting_date) == str(frappe.utils.today())


def test_the_defaulted_date_is_the_sites_day_not_utcs(run_receipt, monkeypatch):
	"""Улаанбаатар is UTC+8: from 08:00 UTC to midnight the UTC day is already yesterday there.

	Dating a receipt by the UTC day would book eight hours of every day one day back — and on
	the 1st of a month into the previous, possibly closed, period.
	"""
	import frappe

	monkeypatch.setattr(frappe.utils, "today", lambda: "2026-03-15")
	proposal = run_receipt("petrovis_fuel", date=None)
	assert str(proposal.posting_date) == "2026-03-15"
	assert mn.MSG_DATE_DEFAULTED_TODAY in json.loads(proposal.warnings_json)


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


def test_posting_date_defaults_to_the_site_date_not_utc(monkeypatch):
	"""A receipt with no readable date is posted on the site's business day.

	Ulaanbaatar is UTC+8, so for eight hours of every UTC day the UTC date is yesterday's:
	taking it would post a night-time receipt into the previous day, and on the 1st into a
	period the accountant may already have closed.
	"""
	monkeypatch.setattr(frappe.utils, "today", lambda: "2026-07-04")
	assert pipeline._today(None) == dt.date(2026, 7, 4)
	# an explicit timestamp (the caller's, a replay) still decides
	given = dt.datetime(2026, 1, 2, 3, 4, tzinfo=dt.timezone.utc)
	assert pipeline._today(given) == dt.date(2026, 1, 2)


def _vat_rate_row(verified: int):
	"""An explicit ``vat.rate`` Nyabo Tax Parameter row (the shipped seed row is verified)."""
	return frappe.get_doc(
		{
			"doctype": "Nyabo Tax Parameter",
			"key": "vat.rate",
			"effective_from": "2026-01-01",
			"value_json": "0.1",
			"unit": "fraction",
			"status": "active",
			"verified": verified,
			"source_text": "НӨАТ-ын тухай хууль",
		}
	).insert()


def test_unverified_vat_rate_is_refused_and_only_the_simulation_flag_bypasses_it(
	run_receipt, books, frappe_flags
):
	"""F-09: the rate that sizes a proposal goes through rules.params + rules.guard, not a raw resolve."""
	row = _vat_rate_row(verified=0)
	with pytest.raises(pipeline.UnverifiedRuleError) as exc:
		pipeline.vat_rate(dt.date(2026, 6, 15))
	assert "vat.rate" in str(exc.value) and getattr(exc.value, "message_mn", None)

	with pytest.raises(pipeline.UnverifiedRuleError):
		run_receipt("petrovis_fuel")
	assert frappe.get_all("Nyabo Document", filters={"status": "failed"}, pluck="name")
	assert frappe.db.exists("Nyabo Event", {"event_type": "pipeline_failed"})

	# the provisioning path only builds templates, so it may read the same unverified row
	from nyabo_mn.setup import taxes

	assert taxes.vat_rate_percent("2026-06-15") == 10.0
	assert pipeline.vat_rate(dt.date(2026, 6, 15), allow_unverified=True) == Decimal("0.1")

	# the simulator and the tests bypass the guard with the flag, nothing else
	with frappe_flags(nyabo_simulation=True):
		assert pipeline.vat_rate(dt.date(2026, 6, 15)) == Decimal("0.1")

	row.verified = 1  # the admin read the primary text
	row.save()
	assert pipeline.vat_rate(dt.date(2026, 6, 15)) == Decimal("0.1")
	assert run_receipt("petrovis_fuel").vat_amount == 7727.27


def test_the_receipt_card_drops_the_unverified_warning_once_this_company_accepts_the_rule(run_receipt, books):
	"""MAJOR 1, on the one screen the founder looks at: the receipt card.

	``instantiate`` used to decide the warning from ``pattern.verified`` alone, so an accountant
	who had already accepted the rule for these books went on reading «⚠️ Дүрэм баталгаажаагүй»
	on every receipt that used it. The warning now asks the same two questions the guard asks,
	and the pipeline is what threads the company into them.
	"""
	from nyabo_mn.rules import patterns, verify

	frappe.db.set_value("Nyabo Posting Pattern", "purchase_expense_vat_payer", "verified", 0)
	patterns.clear_cache()

	before = run_receipt("petrovis_fuel")
	assert json.loads(before.entry_json)["pattern_id"] == "purchase_expense_vat_payer"
	assert mn.WARN_UNVERIFIED_RULE in json.loads(before.warnings_json)

	verify.accept(verify.KIND_PATTERN, "purchase_expense_vat_payer", books, "Administrator")
	after = run_receipt("petrovis_fuel")

	assert mn.WARN_UNVERIFIED_RULE not in json.loads(after.warnings_json)
	# The global row is untouched: the acceptance speaks for these books and no others.
	assert frappe.db.get_value("Nyabo Posting Pattern", "purchase_expense_vat_payer", "verified") == 0
