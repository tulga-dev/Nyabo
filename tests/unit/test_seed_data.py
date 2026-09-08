"""Content assertions on the shipped seed (what the reference and the reviewers require)."""

from __future__ import annotations

import datetime as dt

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
	# Only rows compared with a primary text (Law on Accounting, legalinfo URL + article) are verified.
	assert verified and all(r["source_url"] and r["article"] for r in verified)
	assert all(r["key"].startswith(("retention.", "statements.")) for r in verified)
	assert all(
		not r["verified"] for r in rows if r["key"].startswith(("vat.", "cit.", "pit.", "si.", "simplified."))
	)
	pending = {r["key"] for r in rows if r["status"] == "pending"}
	assert {"cit.brackets", "pit.brackets", "si.employer_rate", "si.accident_tiers"} <= pending
	assert all(r["value"] is None for r in rows if r["status"] == "pending")
	keys = {r["key"] for r in rows}
	assert {
		"vat.rate",
		"vat.registration_threshold",
		"simplified.revenue_threshold",
		"simplified.rate",
		"cit.credit_90pct_threshold",
		"si.employee_rate",
		"retention.years",
		"sme.classification",
		"filing.vat",
	} <= keys
	# No guessed in-force date on the tax-debt rule (reviewer): a single pending row.
	debt = [r for r in rows if r["key"] == "tax_debt.enforcement_split"]
	assert len(debt) == 1 and debt[0]["status"] == "pending"


def test_tax_parameter_shapes():
	rows = [rules_engine.ParameterRow.from_dict(r) for r in load_seed("tax_parameters")["rows"]]
	assert rules_engine.parameter_decimal(rows, "retention.years", dt.date(2026, 1, 1)) == 10
	assert (
		rules_engine.parameter_decimal(rows, "simplified.revenue_threshold", dt.date(2027, 1, 1))
		== 400_000_000
	)
	assert (
		rules_engine.parameter_decimal(rows, "cit.credit_90pct_threshold", dt.date(2027, 1, 1))
		== 2_500_000_000
	)
	deadline = rules_engine.resolve_parameter(rows, "statements.annual_deadline", dt.date(2026, 1, 1)).value
	assert deadline == {
		"period": "annual",
		"due_months_after_period_end": 2,
		"due_day": 10,
		"applies_to": "all",
	}


def test_posting_patterns_cover_the_reference_and_are_unverified():
	rows = load_seed("posting_patterns")["rows"]
	ids = {r["pattern_id"] for r in rows}
	assert REQUIRED_PATTERNS <= ids
	for row in rows:
		assert row["verified"] is False, row["pattern_id"]
		assert row["citation"]["section"] is None, row["pattern_id"]
		assert row["citation"]["verified"] is False
		assert row["citation"]["instrument"]
		assert row["primary_document_mn"]
		assert row["applies_to_vat"] in ("any", "vat_payer", "non_vat")
		assert row["applies_to_cit"] in ("any", "regular", "simplified_1pct")
	by_id = {r["pattern_id"]: r for r in rows}
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
