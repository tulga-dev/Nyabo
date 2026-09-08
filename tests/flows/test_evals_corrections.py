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
	"""A proposal with three corrections today: account, VAT treatment, and an unsupported total."""
	import frappe

	settings = frappe.get_doc("Nyabo Company Settings", company)
	settings.append("regimes", {"regime": "vat_payer", "effective_from": "2026-01-01"})
	settings.flags.ignore_permissions = True
	settings.save()
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


def test_regime_lookup_falls_back_to_company_settings(corrected, company):
	assert corrections_job.regime_for(company, dt.date(2026, 6, 15)) == "vat_payer"
	assert corrections_job.regime_for(company, dt.date(2025, 6, 15)) == ""  # before onboarding
	assert corrections_job.regime_for("Байхгүй ХХК", dt.date(2026, 6, 15)) == ""
