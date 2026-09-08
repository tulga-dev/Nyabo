"""rules.seed.sync: every seed row lands in its DocType, twice is a no-op, verified rows are kept."""

from __future__ import annotations

import json

import frappe
import pytest

from nyabo_mn.nyabo.seed import load_seed
from nyabo_mn.rules import seed


def test_sync_inserts_every_row_and_is_idempotent(site):
	first = seed.sync()
	assert first["Nyabo Tax Parameter"] == {"inserted": len(load_seed("tax_parameters")["rows"])}
	assert first["Nyabo Posting Pattern"] == {"inserted": len(load_seed("posting_patterns")["rows"])}
	assert first["Nyabo Bank Layout"] == {"inserted": len(load_seed("bank_layouts")["rows"])}
	assert frappe.db.exists("Nyabo Tax Parameter", "vat.registration_threshold:2027-01-01")
	pattern = frappe.get_doc("Nyabo Posting Pattern", "purchase_expense_vat_payer")
	assert pattern.document_types == "Purchase Invoice"
	assert {row.side for row in pattern.lines} == {"debit", "credit"}
	assert isinstance(json.loads(pattern.lines[0].alternatives_json), list)
	fee = frappe.get_doc("Nyabo Posting Pattern", "bank_fee_expense")
	assert fee.document_types == "Journal Entry, Bank Transaction" and fee.lines[0].role == "bank_fee"
	layout = frappe.get_doc("Nyabo Bank Layout", "generic_mn")
	assert json.loads(layout.keywords_json)["debit"][0] == "дебит"
	assert layout.date_formats.splitlines()[0] == "%Y-%m-%d"

	second = seed.sync()
	verified = len([r for r in load_seed("tax_parameters")["rows"] if r["verified"]])
	assert second["Nyabo Tax Parameter"] == {
		"unchanged": len(load_seed("tax_parameters")["rows"]) - verified,
		"skipped_verified": verified,
	}
	assert "inserted" not in second["Nyabo Posting Pattern"]
	assert frappe.db.count("Nyabo Posting Pattern Line") == sum(
		len(r["lines"]) for r in load_seed("posting_patterns")["rows"]
	)


def test_sync_never_overwrites_a_verified_row_unless_forced(site):
	seed.sync()
	doc = frappe.get_doc("Nyabo Posting Pattern", "bank_fee_expense")
	doc.verified = 1
	doc.citation_section = "5.3"
	doc.notes = "checked against the instrument"
	doc.save()
	counts = seed.sync()
	assert counts["Nyabo Posting Pattern"]["skipped_verified"] == 1
	kept = frappe.get_doc("Nyabo Posting Pattern", "bank_fee_expense")
	assert kept.verified == 1 and kept.citation_section == "5.3"

	# a drifted unverified row is brought back to the seed value
	other = frappe.get_doc("Nyabo Posting Pattern", "vat_settle")
	other.notes = "edited by hand"
	other.save()
	assert seed.sync()["Nyabo Posting Pattern"].get("updated") == 1
	assert frappe.get_doc("Nyabo Posting Pattern", "vat_settle").notes != "edited by hand"

	forced = seed.sync(force=True)
	assert "skipped_verified" not in forced["Nyabo Posting Pattern"]
	reset = frappe.get_doc("Nyabo Posting Pattern", "bank_fee_expense")
	assert reset.verified == 0 and not reset.citation_section


def test_seed_default_rules_per_company_and_scheme(company_v03):
	assert frappe.db.count("Nyabo Rule", {"company": company_v03, "seed_rule_id": "bank_fee_v03"}) == 1
	rule = frappe.get_doc("Nyabo Rule", {"company": company_v03, "seed_rule_id": "bank_fee_v03"})
	assert rule.target_account_code == "7012" and rule.posting_pattern == "bank_fee_expense"
	assert seed.seed_default_rules(company_v03, "v03") == 0  # idempotent


def test_tax_parameter_controller_refuses_bad_rows(site):
	seed.sync()
	with pytest.raises(frappe.ValidationError, match="эхлэх огноо"):
		frappe.get_doc(
			{
				"doctype": "Nyabo Tax Parameter",
				"key": "x.rate",
				"value_json": "0.1",
				"effective_from": "2026-06-01",
				"effective_to": "2026-01-01",
			}
		).insert()
	with pytest.raises(frappe.ValidationError, match="давхцаж"):
		frappe.get_doc(
			{
				"doctype": "Nyabo Tax Parameter",
				"key": "vat.rate",
				"value_json": "0.1",
				"effective_from": "2027-01-01",
			}
		).insert()
	with pytest.raises(frappe.ValidationError, match="JSON"):
		frappe.get_doc(
			{
				"doctype": "Nyabo Tax Parameter",
				"key": "x.rate",
				"value_json": "{oops",
				"effective_from": "2026-01-01",
			}
		).insert()
	with pytest.raises(frappe.ValidationError, match="pending"):
		frappe.get_doc(
			{"doctype": "Nyabo Tax Parameter", "key": "x.rate", "effective_from": "2026-01-01"}
		).insert()
	pending = frappe.get_doc(
		{
			"doctype": "Nyabo Tax Parameter",
			"key": "x.rate",
			"effective_from": "2026-01-01",
			"status": "pending",
		}
	).insert()
	assert pending.value_json in (None, "")


def test_posting_pattern_controller_needs_both_sides_and_document_types(site):
	base = {
		"doctype": "Nyabo Posting Pattern",
		"pattern_id": "probe",
		"name_mn": "Туршилт",
		"family": "probe",
		"document_types": "Journal Entry",
		"lines": [{"side": "debit", "account_class": "70", "amount_kind": "gross"}],
	}
	with pytest.raises(frappe.ValidationError, match="кредит"):
		frappe.get_doc(base).insert()
	both = dict(base)
	both["lines"] = base["lines"] + [{"side": "credit", "account_class": "10", "amount_kind": "gross"}]
	both["document_types"] = " , "
	with pytest.raises(frappe.ValidationError, match="баримтын төрл"):
		frappe.get_doc(both).insert()
	both["document_types"] = "Journal Entry\nPurchase Invoice"
	doc = frappe.get_doc(both).insert()
	assert doc.document_types == "Journal Entry, Purchase Invoice"
