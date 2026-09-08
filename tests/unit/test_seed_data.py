"""Content assertions on the shipped seed (what the reference and the reviewers require)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from nyabo_mn.core import rules_engine, statements
from nyabo_mn.nyabo.seed import SEED_FILES, load_seed, seed_path
from nyabo_mn.setup import chart as chart_mod

REQUIRED_ROLES = [
	"cash",
	"bank",
	"receivable",
	"payable",
	"input_vat",
	"output_vat",
	"default_expense",
	"bank_fee",
	"round_off",
	"write_off",
	"fx_gain_loss",
	"temporary_opening",
	"inventory_goods",
	"inventory_materials",
	"srbnb",
	"stock_adjustment",
	"valuation_expense",
	"accumulated_depreciation",
	"depreciation_expense",
	"cwip",
	"fixed_asset",
	"salary_expense",
	"salary_payable",
	"si_expense",
	"si_payable",
	"pit_payable",
	"cit_expense",
	"cit_payable",
	"prepaid_expense",
	"customer_advance",
	"revenue_sales",
	"revenue_services",
	"cogs",
	"closing",
]

REQUIRED_PATTERNS = {
	"purchase_expense_vat_payer",
	"purchase_expense_non_vat",
	"purchase_inventory_vat_payer",
	"purchase_inventory_non_vat",
	"sale_cash_vat_payer",
	"sale_credit_vat_payer",
	"sale_cash_non_vat",
	"sale_credit_non_vat",
	"receivable_collect",
	"payable_pay",
	"vat_settle",
	"payroll_withhold_employee_si",
	"payroll_withhold_pit",
	"payroll_employer_si",
	"fixed_asset_acquire_vat_payer",
	"fixed_asset_acquire_non_vat",
	"fixed_asset_dispose_gain",
	"fixed_asset_dispose_loss",
	"fixed_asset_scrap",
	"bank_fee_expense",
	"income_tax_accrue",
	"simplified_tax_accrue",
}


def test_every_seed_file_loads():
	for name in SEED_FILES:
		assert seed_path(name).exists(), name
		assert load_seed(name)


def test_tax_parameters_metadata_and_verification_policy():
	data = load_seed("tax_parameters")
	assert data["schema_version"] == 1
	assert data["horizon_start"] == "2026-01-01"
	assert "verified_means" in data
	rows = data["rows"]
	verified = [r for r in rows if r["verified"]]
	# A verified row was compared with a primary text: article, URL and the quoted sentence in the note.
	assert verified and all(r["source_url"] and r["article"] and r["note"].startswith("«") for r in verified)
	# Derived numbers and draft-law values never ship verified (docs/legal/*.md).
	unverified_keys = {r["key"] for r in rows if not r["verified"]}
	assert {
		"si.employee_rate",
		"si.employer_rate",
		"vat.voluntary_registration_threshold",
		"sme.classification",
	} <= unverified_keys
	pending = {r["key"] for r in rows if r["status"] == "pending"}
	assert {
		"simplified.revenue_threshold",
		"simplified.filing_period",
		"property_tax.rate",
		"emd.employee_rate",
		"emd.employer_rate",
	} <= pending
	assert all(r["value"] is None for r in rows if r["status"] == "pending")
	keys = {r["key"] for r in rows}
	assert {
		"vat.rate",
		"vat.registration_threshold",
		"vat.input_deduction_categories",
		"simplified.revenue_threshold",
		"simplified.rate",
		"cit.brackets",
		"cit.credit_90pct_threshold",
		"depreciation.tax_life",
		"pit.brackets",
		"si.employee.pension",
		"si.employer.pension",
		"si.accident_tiers",
		"retention.years",
		"sme.classification",
		"filing.vat",
		"filing.cit_half_year",
		"filing.si",
	} <= keys
	# The tax-debt cap starts on the package's adoption date, quoted from GTL 63.2 (no guessed day).
	debt = [r for r in rows if r["key"] == "tax_debt.enforcement_split"]
	assert len(debt) == 1 and debt[0]["status"] == "active" and debt[0]["effective_from"] == "2026-06-26"


def test_tax_parameter_shapes():
	rows = [rules_engine.ParameterRow.from_dict(r) for r in load_seed("tax_parameters")["rows"]]
	assert rules_engine.parameter_decimal(rows, "retention.years", dt.date(2026, 1, 1)) == 10
	assert (
		rules_engine.parameter_decimal(rows, "simplified.revenue_threshold", dt.date(2026, 6, 1))
		== 50_000_000
	)
	assert (
		rules_engine.parameter_decimal(rows, "cit.credit_90pct_threshold", dt.date(2027, 1, 1))
		== 2_500_000_000
	)
	# CIT Law art. 20.1 as amended 26 Jun 2026: 10% to 6bn, 15% to 10bn, 25% above
	brackets = rules_engine.resolve_parameter(rows, "cit.brackets", dt.date(2027, 1, 1)).value["brackets"]
	assert [(b["up_to"], b["rate"]) for b in brackets] == [
		(6_000_000_000, 0.1),
		(10_000_000_000, 0.15),
		(None, 0.25),
	]
	# CIT Law art. 17.1: computers and software are 2 years, servers 3 years from 2027
	lives_2026 = rules_engine.resolve_parameter(rows, "depreciation.tax_life", dt.date(2026, 6, 1)).value
	lives_2027 = rules_engine.resolve_parameter(rows, "depreciation.tax_life", dt.date(2027, 6, 1)).value
	assert lives_2026["computers_software"] == 2 and "servers_data_processing_gpu" not in lives_2026
	assert lives_2027["servers_data_processing_gpu"] == 3 and lives_2027["buildings"] == 40
	# PIT 21.1 (2022 amendment): progressive since 2023, annual basis
	pit = rules_engine.resolve_parameter(rows, "pit.brackets", dt.date(2026, 6, 1)).value
	assert [b["rate"] for b in pit["brackets"]] == [0.1, 0.15, 0.2]
	# social insurance is per fund (art. 18.1); the totals are derived and unverified
	assert rules_engine.parameter_decimal(rows, "si.employee.pension", dt.date(2026, 1, 1)) == Decimal(
		"0.085"
	)
	assert rules_engine.parameter_decimal(rows, "si.employer.unemployment", dt.date(2027, 1, 1)) == Decimal(
		"0.006"
	)
	tiers = rules_engine.resolve_parameter(rows, "si.accident_tiers", dt.date(2027, 1, 1)).value["tiers"]
	assert [t["rate"] for t in tiers] == [0.003, 0.012, 0.022]
	deadline = rules_engine.resolve_parameter(rows, "statements.annual_deadline", dt.date(2026, 1, 1)).value
	assert deadline == {
		"period": "annual",
		"due_months_after_period_end": 2,
		"due_day": 10,
		"applies_to": "all",
	}
	half_year = rules_engine.resolve_parameter(rows, "filing.cit_half_year", dt.date(2027, 1, 1)).value
	assert (half_year["due_months_after_period_end"], half_year["due_day"]) == (2, 5)


def test_posting_patterns_cover_the_reference_and_carry_citations():
	rows = load_seed("posting_patterns")["rows"]
	ids = {r["pattern_id"] for r in rows}
	assert REQUIRED_PATTERNS <= ids
	for row in rows:
		assert row["citation"]["verified"] is row["verified"], row["pattern_id"]
		assert row["citation"]["instrument"]
		assert row["primary_document_mn"]
		assert row["applies_to_vat"] in ("any", "vat_payer", "non_vat")
		assert row["applies_to_cit"] in ("any", "regular", "simplified_1pct")
	by_id = {r["pattern_id"]: r for r in rows}
	# patterns the instrument does not prescribe stay unverified without a section
	for pid in ("customer_prepayment_recognize_vat_payer", "customer_prepayment_recognize_non_vat"):
		assert by_id[pid]["verified"] is False and by_id[pid]["citation"]["section"] is None
	# composites rated only "probable" by the readers stay unverified
	assert by_id["purchase_expense_vat_payer"]["verified"] is False
	assert by_id["purchase_expense_vat_payer"]["applies_to_vat"] == "vat_payer"
	assert by_id["purchase_expense_non_vat"]["applies_to_vat"] == "non_vat"
	assert by_id["income_tax_accrue"]["applies_to_cit"] == "regular"
	assert by_id["simplified_tax_accrue"]["applies_to_cit"] == "simplified_1pct"
	# settlement legs are separate patterns; the invoice patterns do not claim Payment Entry
	assert by_id["sale_cash_vat_payer"]["document_types"] == ["Sales Invoice"]
	assert "Bank Transaction" in by_id["receivable_collect"]["document_types"]
	# goods for resale sit in class 15, raw materials in 14
	assert by_id["purchase_inventory_vat_payer"]["lines"][0]["account_class"] == "15"
	assert by_id["cogs_on_sale"]["lines"][1]["account_class"] == "15"
	# the employee SI withholding exists and moves salary payable to SI payable
	si = by_id["payroll_withhold_employee_si"]["lines"]
	assert [(line["side"], line["role"]) for line in si] == [
		("debit", "salary_payable"),
		("credit", "si_payable"),
	]
	# alternatives carry a stated condition, and sub-account names carry no parentheses guidance
	for row in rows:
		for line in row["lines"]:
			assert "бол" not in line["sub_account_mn"], (row["pattern_id"], line["sub_account_mn"])
			for alt in line.get("alternatives", []):
				assert alt["when"] and alt["when_mn"]


def test_charts_and_aliases():
	v1 = chart_mod.load_chart(chart_mod.DEFAULT_CHART_PATH)
	v03 = chart_mod.load_chart(seed_path("chart_v03"))
	assert len(v1.leaf_numbers()) == 40
	assert v03.warnings == []
	aliases = load_seed("aliases_v1_to_v03")
	mapping = {k: v for k, v in aliases.items() if not k.startswith("_") and k != "unmapped"}
	assert set(mapping) == v1.leaf_numbers()
	assert set(mapping.values()) <= v03.leaf_numbers()
	assert aliases["unmapped"] == []
	assert mapping["1810"] == "1210" and mapping["2210"] == "3110" and mapping["6810"] == "7012"


def test_code_roles_resolve_in_both_schemes():
	data = load_seed("code_roles")
	assert set(REQUIRED_ROLES) <= set(data["required_roles"])
	v1 = chart_mod.load_chart(chart_mod.DEFAULT_CHART_PATH).leaf_numbers()
	v03 = chart_mod.load_chart(seed_path("chart_v03")).leaf_numbers()
	for role in REQUIRED_ROLES:
		assert data["schemes"]["v03"][role] in v03, role
		code = data["schemes"]["v1"][role]
		assert code in v1 or (code is None and role in data["null_allowed"]["v1"]), role
	assert data["schemes"]["v1"]["input_vat"] == "1810" and data["schemes"]["v03"]["input_vat"] == "1210"
	assert data["schemes"]["v1"]["bank_fee"] == "6810" and data["schemes"]["v03"]["bank_fee"] == "7012"


def test_bank_layouts_are_placeholders_plus_generic():
	rows = load_seed("bank_layouts")["rows"]
	banks = {r["bank"] for r in rows}
	assert {"Khan Bank", "TDB", "Golomt Bank", "Trans Bank", "XacBank", "Other"} == banks
	for row in rows:
		assert row["verified"] is False
		assert row["header_signature"] == [] and row["column_map"] == {}
	generic = next(r for r in rows if r["layout_id"] == "generic_mn")
	assert set(generic["keywords"]) <= set(statements.COLUMN_ROLES)
	assert statements.LayoutSpec.from_dict(generic).is_generic


@pytest.mark.parametrize("scheme", ["v1", "v03"])
def test_rules_default_bank_fee_per_scheme(scheme: str):
	rows = load_seed("rules_default")["rows"]
	rule = next(r for r in rows if r["scheme"] == scheme)
	assert rule["match_type"] == "bank_fee" and rule["posting_pattern"] == "bank_fee_expense"
	assert rule["target_account_code"] == load_seed("code_roles")["schemes"][scheme]["bank_fee"]
