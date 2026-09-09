"""Policy document rendering/attachment and the certification readiness checklist."""

from __future__ import annotations

import frappe

from nyabo_mn.compliance import policy_doc, readiness
from nyabo_mn.i18n import mn
from nyabo_mn.rules import regime


def _settings(company, **values):
	name = frappe.db.get_value("Nyabo Company Settings", {"company": company}, "name")
	doc = (
		frappe.get_doc("Nyabo Company Settings", name)
		if name
		else frappe.get_doc({"doctype": "Nyabo Company Settings", "company": company})
	)
	doc.update(values)
	doc.save()
	return doc


def test_policy_pdf_renders_from_settings_with_placeholders(company):
	# provisioning already records the first regime (simplified 1% for a non-VAT company)
	ctx = policy_doc.context(company)
	assert ctx["values"]["regime"] == policy_doc.POLICY_REGIME_LABELS[regime.REGIME_SIMPLIFIED]
	# a company whose onboarding has not reached the regime step renders the placeholder
	_settings(company, regimes=[])
	ctx = policy_doc.context(company)
	assert ctx["title"] == mn.POLICY_TITLE and ctx["watermark"] == mn.POLICY_DRAFT_WATERMARK
	assert [s["key"] for s in ctx["sections"]] == [s["key"] for s in mn.POLICY_SECTIONS]
	assert "accountant" in ctx["missing"] and "regime" in ctx["missing"]
	pdf = policy_doc.generate_pdf(company)
	html = pdf.decode("utf-8")
	assert html.lstrip().startswith("<!DOCTYPE html>")
	assert mn.POLICY_TITLE in html and mn.POLICY_DRAFT_WATERMARK in html and company in html
	assert "13.7" in html and "11.1" in html and "15.1" in html and "18.2" in html
	assert mn.POLICY_UNKNOWN in html and "DejaVu Sans" in html

	_settings(
		company,
		accountant_of_record_name="Б. Батаа",
		accountant_micpa_permit="MICPA-123",
		inventory_method="FIFO",
		depreciation_method="Straight Line",
		fx_policy="Монголбанкны албан ханш",
		regimes=[{"regime": "simplified_1pct", "effective_from": "2026-01-01"}],
	)
	ctx = policy_doc.context(company)
	assert "accountant" not in ctx["missing"] and "regime" not in ctx["missing"]
	html = policy_doc.generate_pdf(company).decode("utf-8")
	assert "Б. Батаа" in html and "MICPA-123" in html and "FIFO" in html
	assert policy_doc.POLICY_REGIME_LABELS[regime.REGIME_SIMPLIFIED] in html
	assert mn.POLICY_DEPRECIATION_LABELS["Straight Line"] in html


def test_policy_pdf_is_attached_as_a_private_file(company):
	settings = _settings(company, accountant_of_record_name="Б. Батаа")
	url = policy_doc.attach_to_settings(company)
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Nyabo Company Settings"},
		fields=["file_url", "is_private", "file_name"],
	)
	assert len(files) == 1 and files[0].file_url == url and files[0].is_private == 1
	assert files[0].attached_to_name if "attached_to_name" in files[0] else settings.name
	assert frappe.db.exists("Nyabo Event", {"event_type": mn.EVENT_POLICY_GENERATED, "company": company})


def test_readiness_returns_every_item_with_honest_results(company, capsys):
	rows = readiness.checks("nyabo.s.frappe.cloud")
	assert [r["key"] for r in rows] == list(mn.READINESS_ITEMS)
	by_key = {r["key"]: r for r in rows}
	for key in (
		"general_journal",
		"cash_journal",
		"primary_forms",
		"retention",
		"primary_document_required",
		"corrections",
		"period_lock",
		"audit_trail",
		"policy_document",
	):
		assert by_key[key]["passed"] is True, (key, by_key[key]["detail"])
	assert by_key["e_signature"]["passed"] is False and "MoF" not in by_key["e_signature"]["detail"]
	assert by_key["e_signature"]["detail"] == mn.READINESS_E_SIGNATURE_PENDING
	assert by_key["statements"]["passed"] is False and "equity_statement" in by_key["statements"]["detail"]
	assert by_key["rules_verified"]["passed"] is False
	# F-08: no row claims an item number of MoF Order 47/2018 — an instrument the project has
	# never fetched (docs/mn-rules-reference.md §6.1); the table says so instead.
	assert all("requirement" not in r for r in rows)
	assert all(r["status_mn"] in (mn.READINESS_PASS, mn.READINESS_FAIL) for r in rows)

	frappe.get_doc(
		{
			"doctype": "Nyabo Posting Pattern",
			"pattern_id": "p1",
			"name_mn": "x",
			"family": "purchase",
			"document_types": "Journal Entry",
			"verified": 1,
			"lines": [
				{"side": "debit", "account_class": "70", "amount_kind": "gross"},
				{"side": "credit", "account_class": "10", "amount_kind": "gross"},
			],
		}
	).insert()
	_settings(company, accountant_of_record_name="Б. Батаа")
	by_key = {r["key"]: r for r in readiness.checks()}
	assert by_key["rules_verified"]["passed"] is True and by_key["accountant_of_record"]["passed"] is True
	# The certification reader must not take a seeded flag for somebody's signature: the row
	# ships verified with verified_by empty, so the detail says one row, none of it human.
	assert by_key["rules_verified"]["detail"] == mn.READINESS_DETAIL_RULES_VERIFIED.format(
		count=1, by_seed=1, by_person=0
	)
	frappe.db.set_value("Nyabo Posting Pattern", "p1", "verified_by", "Administrator")
	detail = {r["key"]: r for r in readiness.checks()}["rules_verified"]["detail"]
	assert detail == mn.READINESS_DETAIL_RULES_VERIFIED.format(count=1, by_seed=0, by_person=1)

	printed = readiness.run("nyabo.s.frappe.cloud")
	out = capsys.readouterr().out
	assert mn.READINESS_TITLE in out and mn.READINESS_PASS in out and mn.READINESS_FAIL in out
	assert mn.READINESS_SOURCE_PENDING in out
	assert len(printed) == len(mn.READINESS_ITEMS)
	html = readiness.readiness_report_pdf().decode("utf-8")
	assert mn.READINESS_TITLE in html and mn.READINESS_ITEMS["e_signature"] in html
	assert mn.READINESS_SOURCE_PENDING in html and mn.FORM_SOURCE_INTERNAL in html
	assert "47/2018" not in html and "47 дугаар тушаал" not in html
