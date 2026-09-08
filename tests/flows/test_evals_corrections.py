"""The nightly corrections job on the stub: cases created once, event written, learner optional."""

from __future__ import annotations

import datetime as dt
import json
import sys
import types

import pytest

from nyabo_mn.evals import corrections_job


@pytest.fixture
def corrected(company):
	"""A proposal with three corrections today: account, VAT treatment, and an unsupported total.

	Provisioning already wrote the first regime row (simplified 1% from the fiscal-year
	start), so the company becomes a VAT payer through ``rules.regime.set_regime``, which
	closes that row the day before; the proposal's June posting date falls in the VAT period.
	"""
	import frappe

	from nyabo_mn.rules.regime import set_regime

	set_regime(company, "vat_payer", "2026-02-01")
	document = frappe.get_doc(
		{
			"doctype": "Nyabo Document",
			"company": company,
			"doc_type": "receipt",
			"file_hash": "abc",
			"file": "/private/files/receipt.jpg",
		}
	).insert()
	proposal = frappe.get_doc(
		{
			"doctype": "Nyabo Proposal",
			"company": company,
			"document": document.name,
			"kind": "receipt",
			"status": "posted",
			"posted_doctype": "Journal Entry",
			"posted_name": "ACC-JV-2026-00001",
			"posting_date": "2026-06-15",
			"account_code": "6210",
			"vat_treatment": "withheld",
			"supplier": None,
			"extracted_json": json.dumps(
				{"seller_name": "Петровис ХХК", "total": "85000.00"}, ensure_ascii=False
			),
		}
	).insert()
	rows = []
	for field, proposed, corrected_value in (
		("account_code", "6210", "6220"),
		("vat_treatment", "withheld", "in_expense"),
		("total", "85000", "58000"),
	):
		rows.append(
			frappe.get_doc(
				{
					"doctype": "Nyabo Correction",
					"company": company,
					"proposal": proposal.name,
					"field": field,
					"proposed_value": proposed,
					"corrected_value": corrected_value,
					"reason": "account",
					"reason_text": "Тээврийн зардал байсан",
				}
			).insert()
		)
	return proposal, rows


def test_nightly_creates_cases_once_and_writes_an_event(corrected, company):
	import frappe

	proposal, rows = corrected
	today = dt.date.today()
	first = corrections_job.run_nightly(today)
	assert first["corrections"] == 3 and first["created"] == 2 and first["unsupported"] == 1
	assert first["skipped"] == 0 and first["rules_proposed"] == 0 and first["errors"] == 0
	cases = frappe.get_all(
		"Nyabo Eval Case",
		filters={"source": "correction"},
		fields=[
			"name",
			"kind",
			"regime",
			"company",
			"on_date",
			"input_json",
			"expected_json",
			"notes",
			"input_document",
		],
	)
	assert {c.kind for c in cases} == {"classification", "vat"}
	by_kind = {c.kind: c for c in cases}
	assert json.loads(by_kind["classification"].expected_json) == {"account_code": "6220"}
	assert json.loads(by_kind["vat"].expected_json) == {"vat_treatment": "in_expense"}
	payload = json.loads(by_kind["classification"].input_json)
	assert payload["receipt"]["seller_name"] == "Петровис ХХК"
	assert payload["context"]["regime"] == "vat_payer" and payload["context"]["proposed_value"] == "6210"
	assert by_kind["classification"].regime == "vat_payer" and by_kind["classification"].company == company
	assert by_kind["classification"].input_document == proposal.document
	assert str(by_kind["classification"].on_date) == "2026-06-15"
	assert f"correction:{rows[0].name}" in by_kind["classification"].notes

	event = frappe.get_doc("Nyabo Event", first["event"])
	assert event.event_type == "evals_nightly"
	assert json.loads(event.payload_json)["created"] == 2 and "2026" not in event.reason or event.reason

	second = corrections_job.run_nightly(today)
	assert second["created"] == 0 and second["skipped"] == 3 - 1 and second["unsupported"] == 1
	assert frappe.db.count("Nyabo Eval Case", {"source": "correction"}) == 2
	assert frappe.db.count("Nyabo Event", {"event_type": "evals_nightly"}) == 2


def test_nightly_with_no_corrections_still_writes_the_event(site):
	import frappe

	counts = corrections_job.run_nightly("2026-01-01")
	assert counts["corrections"] == 0 and counts["created"] == 0
	assert frappe.db.exists("Nyabo Event", counts["event"])


def test_learned_rules_go_through_the_pipeline_when_it_exists(corrected, monkeypatch):
	seen = []
	fake = types.ModuleType("nyabo_mn.agent.pipeline")
	fake.propose_learned_rules = lambda corrections: seen.extend(corrections) or ["NYR-00001"]  # type: ignore[attr-defined]
	monkeypatch.setitem(sys.modules, "nyabo_mn.agent.pipeline", fake)
	counts = corrections_job.run_nightly(dt.date.today())
	assert counts["rules_proposed"] == 1 and len(seen) == 3
	assert {row["field"] for row in seen} == {"account_code", "vat_treatment", "total"}


def test_two_agreeing_corrections_learn_a_rule_through_the_nightly_job(company):
	"""Without ``pipeline.propose_learned_rules`` the job calls ``agent.post.learn_from_correction`` (PIPE-06)."""
	import frappe

	from nyabo_mn.rules.regime import set_regime

	set_regime(company, "vat_payer", "2026-02-01")
	for n in (1, 2):
		document = frappe.get_doc(
			{
				"doctype": "Nyabo Document",
				"company": company,
				"doc_type": "receipt",
				"file_hash": f"hash-{n}",
				"file": "/private/files/receipt.jpg",
			}
		).insert()
		proposal = frappe.get_doc(
			{
				"doctype": "Nyabo Proposal",
				"company": company,
				"document": document.name,
				"kind": "receipt",
				"status": "posted",
				"posted_doctype": "Journal Entry",
				"posted_name": f"ACC-JV-2026-0000{n}",
				"posting_date": "2026-06-15",
				"account_code": "6910",
				"vat_treatment": "in_expense",
				"extracted_json": json.dumps(
					{"seller_name": "Ганбат", "total": "50000.00", "lines": [{"description": "Дизель"}]},
					ensure_ascii=False,
				),
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Nyabo Correction",
				"company": company,
				"proposal": proposal.name,
				"field": "account_code",
				"proposed_value": "6910",
				"corrected_value": "6210",
				"reason": "account",
			}
		).insert()
	counts = corrections_job.run_nightly(dt.date.today())
	assert counts["created"] == 2 and counts["rules_proposed"] == 1 and counts["errors"] == 0
	rules = frappe.get_all(
		"Nyabo Rule",
		filters={"company": company, "source": "learned"},
		fields=["match_type", "match_value", "target_account_code", "status"],
	)
	assert [dict(r) for r in rules] == [
		{
			"match_type": "description_pattern",
			"match_value": "дизель",
			"target_account_code": "6210",
			"status": "pending_confirmation",
		}
	]
	again = corrections_job.run_nightly(dt.date.today())
	assert again["rules_proposed"] == 0 and again["skipped"] == 2  # an existing rule blocks a duplicate


def test_regime_lookup_reads_the_regime_history(corrected, company):
	assert corrections_job.regime_for(company, dt.date(2026, 6, 15)) == "vat_payer"
	assert corrections_job.regime_for(company, dt.date(2026, 1, 15)) == "simplified_1pct"  # provisioned
	assert corrections_job.regime_for(company, dt.date(2025, 6, 15)) == ""  # before onboarding
	assert corrections_job.regime_for("Байхгүй ХХК", dt.date(2026, 6, 15)) == ""
