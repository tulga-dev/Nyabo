from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from nyabo_mn.core import rules_engine as re_
from nyabo_mn.core.models import Citation, Regime, RegimeContext
from nyabo_mn.core.validate import validate_entry
from nyabo_mn.i18n import mn
from nyabo_mn.nyabo.seed import load_seed
from nyabo_mn.setup import chart as chart_mod
from nyabo_mn.setup.chart import DEFAULT_CHART_PATH


@pytest.fixture(scope="module")
def parameters() -> list[re_.ParameterRow]:
	return [re_.ParameterRow.from_dict(row) for row in load_seed("tax_parameters")["rows"]]


@pytest.fixture(scope="module")
def patterns() -> list[re_.PatternSpec]:
	return [re_.PatternSpec.from_dict(row) for row in load_seed("posting_patterns")["rows"]]


@pytest.fixture(scope="module")
def code_roles() -> dict:
	return load_seed("code_roles")


@pytest.fixture(scope="module")
def v1_leaves() -> set[str]:
	return chart_mod.load_chart(DEFAULT_CHART_PATH).leaf_numbers()


# --- tax parameters ------------------------------------------------------------------------------


def test_vat_registration_threshold_by_year(parameters):
	assert re_.parameter_decimal(parameters, "vat.registration_threshold", dt.date(2026, 6, 1)) == Decimal(
		50_000_000
	)
	assert re_.parameter_decimal(parameters, "vat.registration_threshold", dt.date(2027, 1, 1)) == Decimal(
		400_000_000
	)
	assert re_.parameter_decimal(parameters, "vat.registration_threshold", dt.date(2026, 12, 31)) == Decimal(
		50_000_000
	)
	row = re_.resolve_parameter(parameters, "vat.registration_threshold", dt.date(2027, 5, 1))
	assert row.value["comparator"] == "gte"
	# read from VAT Law art. 5.2 (docs/legal/vat_law.md): the note quotes the sentence
	assert row.verified is True and row.article and row.source_url and "«" in row.note


def test_vat_rate_is_ten_percent_both_years(parameters):
	for day in (dt.date(2026, 3, 1), dt.date(2027, 3, 1)):
		assert re_.parameter_decimal(parameters, "vat.rate", day) == Decimal("0.1")


def test_pending_parameter_raises_and_never_falls_back(parameters):
	# The 2026 simplified-regime threshold is active; the 2027 row is pending because the
	# 400M change exists only in a Government bill, not in the consolidated CIT Law (art. 29.1).
	assert (
		re_.resolve_parameter(parameters, "simplified.revenue_threshold", dt.date(2026, 7, 1)).status
		== "active"
	)
	with pytest.raises(re_.PendingRuleError) as exc:
		re_.resolve_parameter(parameters, "simplified.revenue_threshold", dt.date(2027, 3, 1))
	assert exc.value.message_mn == mn.MSG_RULE_PENDING.format(
		key="simplified.revenue_threshold", date="2027-03-01"
	)
	with pytest.raises(re_.PendingRuleError):
		re_.resolve_parameter(parameters, "emd.employee_rate", dt.date(2026, 3, 1))


def test_missing_parameter_raises(parameters):
	with pytest.raises(re_.MissingRuleError) as exc:
		re_.resolve_parameter(parameters, "vat.registration_threshold", dt.date(2025, 12, 31))
	assert "2025-12-31" in exc.value.message_mn
	with pytest.raises(re_.MissingRuleError):
		re_.resolve_parameter(parameters, "no.such.key", dt.date(2026, 1, 1))


def test_ambiguous_parameter_raises():
	rows = [
		re_.ParameterRow("k", 1, "years", dt.date(2026, 1, 1), None),
		re_.ParameterRow("k", 2, "years", dt.date(2026, 6, 1), None),
	]
	assert re_.resolve_parameter(rows, "k", dt.date(2026, 3, 1)).value == 1
	with pytest.raises(re_.AmbiguousRuleError):
		re_.resolve_parameter(rows, "k", dt.date(2026, 7, 1))


def test_parameter_row_from_doctype_shape_and_pending_without_status():
	row = re_.ParameterRow.from_dict(
		{"key": "x", "value_json": None, "unit": "rule", "effective_from": "2027-01-01", "status": "active"}
	)
	assert row.is_pending  # null value is pending even when status says active
	with pytest.raises(ValueError):
		re_.ParameterRow.from_dict({"key": "x", "value": 1, "unit": "years"})
	with pytest.raises(TypeError):
		re_.ParameterRow("x", {"period": "monthly"}, "deadline", dt.date(2026, 1, 1)).as_decimal()


# --- regimes -------------------------------------------------------------------------------------


HISTORY = [
	("vat_payer", "2026-01-01", "2026-12-31"),
	(Regime.SIMPLIFIED_1PCT, dt.date(2027, 1, 1), None),
]


def test_regime_on_switches_at_year_end():
	ctx_2026 = re_.regime_on(HISTORY, dt.date(2026, 9, 5))
	assert ctx_2026.regime is Regime.VAT_PAYER
	assert ctx_2026.is_vat_payer and ctx_2026.input_vat_recoverable
	assert ctx_2026.summary_kind == re_.SUMMARY_VAT_MONTHLY
	assert ctx_2026.effective_from == dt.date(2026, 1, 1)
	ctx_2027 = re_.regime_on(HISTORY, dt.date(2027, 2, 1))
	assert ctx_2027.regime is Regime.SIMPLIFIED_1PCT
	assert not ctx_2027.is_vat_payer and not ctx_2027.input_vat_recoverable
	assert ctx_2027.summary_kind == re_.SUMMARY_SIMPLIFIED_QUARTERLY


def test_regime_missing_raises_mongolian():
	with pytest.raises(re_.MissingRuleError) as exc:
		re_.regime_on(HISTORY, dt.date(2025, 6, 1))
	assert exc.value.message_mn == mn.MSG_REGIME_MISSING.format(date="2025-06-01")
	with pytest.raises(re_.MissingRuleError):
		re_.regime_on([], dt.date(2026, 6, 1))


def test_regime_overlap_latest_start_wins():
	history = [("vat_payer", "2026-01-01", None), ("simplified_1pct", "2026-07-01", None)]
	assert re_.regime_on(history, dt.date(2026, 8, 1)).regime is Regime.SIMPLIFIED_1PCT
	assert re_.regime_on(history, dt.date(2026, 3, 1)).regime is Regime.VAT_PAYER


# --- patterns ------------------------------------------------------------------------------------


def _resolver(code_roles: dict, scheme: str, expense_code: str):
	roles = code_roles["schemes"][scheme]

	def resolve(selector: str) -> str:
		if selector.startswith("role:"):
			code = roles[selector[5:]]
			assert code is not None, selector
			return code
		if selector.startswith("class:"):
			assert selector in ("class:70", "class:71"), selector
			return expense_code
		return selector

	return resolve


RECEIPT_AMOUNTS = {"net": Decimal("100000"), "vat": Decimal("10000"), "gross": Decimal("110000")}


def _lines(entry) -> list[tuple[str, Decimal, Decimal]]:
	return [(line.account_code, line.debit, line.credit) for line in entry.lines]


def test_same_receipt_vat_payer_2026_splits_input_vat(patterns, code_roles, v1_leaves):
	ctx = re_.regime_on(HISTORY, dt.date(2026, 9, 5))
	pattern = re_.select_pattern(patterns, "purchase_invoice", ctx, {"family": "purchase_expense"})
	assert pattern.pattern_id == "purchase_expense_vat_payer"
	entry = re_.instantiate(
		pattern,
		RECEIPT_AMOUNTS,
		_resolver(code_roles, "v1", "6210"),
		company="Тест ХХК",
		posting_date=dt.date(2026, 9, 5),
		explanation="Шатахуун авав",
		vat_treatment="withheld",
		supplier="Петровис ХХК",
	)
	assert _lines(entry) == [
		("6210", Decimal("100000.00"), Decimal("0.00")),
		("1810", Decimal("10000.00"), Decimal("0.00")),
		("2110", Decimal("0.00"), Decimal("110000.00")),
	]
	assert entry.total == Decimal("110000.00") and entry.vat_amount == Decimal("10000.00")
	assert entry.document_kind == "purchase_invoice"
	assert entry.explanation == "Шатахуун авав" + re_.citation_suffix(pattern.citation)
	assert entry.explanation.endswith(
		mn.EXPL_SUFFIX_CITATION.format(instrument="Заавар 116 (2000)", section=mn.CITATION_SECTION_PENDING)
	)
	assert mn.WARN_UNVERIFIED_RULE in entry.warnings
	assert validate_entry(entry, v1_leaves, Decimal("0.10")) == []


def test_same_receipt_simplified_2027_puts_vat_in_expense(patterns, code_roles, v1_leaves):
	ctx = re_.regime_on(HISTORY, dt.date(2027, 2, 3))
	pattern = re_.select_pattern(patterns, "purchase_invoice", ctx, {"family": "purchase_expense"})
	assert pattern.pattern_id == "purchase_expense_non_vat"
	entry = re_.instantiate(
		pattern,
		RECEIPT_AMOUNTS,
		_resolver(code_roles, "v1", "6210"),
		company="Тест ХХК",
		posting_date=dt.date(2027, 2, 3),
		vat_treatment="in_expense",
	)
	assert _lines(entry) == [
		("6210", Decimal("110000.00"), Decimal("0.00")),
		("2110", Decimal("0.00"), Decimal("110000.00")),
	]
	assert entry.document_kind == "journal_entry"
	assert entry.total == Decimal("110000.00")
	assert validate_entry(entry, v1_leaves, Decimal("0.10")) == []


def test_same_receipt_on_v03_scheme(patterns, code_roles):
	ctx = re_.regime_on(HISTORY, dt.date(2026, 9, 5))
	pattern = re_.select_pattern(patterns, "Purchase Invoice", ctx, {"family": "purchase_expense"})
	entry = re_.instantiate(
		pattern, RECEIPT_AMOUNTS, _resolver(code_roles, "v03", "7003"), vat_treatment="withheld"
	)
	assert [line.account_code for line in entry.lines] == ["7003", "1210", "3101"]
	v03_leaves = chart_mod.load_chart("nyabo_mn/nyabo/seed/chart_v03.json").leaf_numbers()
	assert validate_entry(entry, v03_leaves, "0.10") == []


def test_optional_vat_line_dropped_when_zero(patterns, code_roles):
	ctx = re_.regime_on(HISTORY, dt.date(2026, 9, 5))
	pattern = re_.select_pattern(patterns, "purchase_invoice", ctx, {"family": "purchase_expense"})
	# A non-VAT seller under a VAT-payer company: the VAT line is optional and empty.
	entry = re_.instantiate(
		pattern,
		{"net": "50000", "vat": "0", "gross": "50000"},
		_resolver(code_roles, "v1", "6910"),
		vat_treatment="none",
	)
	assert [line.account_code for line in entry.lines] == ["6910", "2110"]
	entry = re_.instantiate(pattern, {"net": "50000", "gross": "50000"}, _resolver(code_roles, "v1", "6910"))
	assert len(entry.lines) == 2


def test_missing_mandatory_amount_raises(patterns, code_roles):
	ctx = re_.regime_on(HISTORY, dt.date(2026, 9, 5))
	pattern = re_.select_pattern(patterns, "purchase_invoice", ctx, {"family": "purchase_expense"})
	with pytest.raises(re_.MissingAmountError) as exc:
		re_.instantiate(pattern, {"vat": "10"}, _resolver(code_roles, "v1", "6910"))
	assert exc.value.message_mn == mn.MSG_PATTERN_AMOUNT_MISSING.format(
		pattern=pattern.name_mn, amount_kind="net"
	)


def test_select_pattern_specificity_and_no_match(patterns):
	ctx = re_.regime_on(HISTORY, dt.date(2027, 2, 3))
	# CIT-regime keyed family: simplified companies get the 1% accrual, regular ones the CIT one.
	assert (
		re_.select_pattern(patterns, "Journal Entry", ctx, {"family": "income_tax"}).pattern_id
		== "simplified_tax_accrue"
	)
	vat_ctx = re_.regime_on(HISTORY, dt.date(2026, 2, 3))
	assert (
		re_.select_pattern(patterns, "Journal Entry", vat_ctx, {"family": "income_tax"}).pattern_id
		== "income_tax_accrue"
	)
	# vat_settle only exists for VAT payers.
	assert (
		re_.select_pattern(patterns, "Journal Entry", vat_ctx, {"family": "vat_settle"}).pattern_id
		== "vat_settle"
	)
	with pytest.raises(re_.NoPatternError) as exc:
		re_.select_pattern(patterns, "Journal Entry", ctx, {"family": "vat_settle"})
	assert exc.value.message_mn == mn.MSG_PATTERN_NOT_FOUND.format(document="Journal Entry")
	# pattern_id hint is still regime-checked
	with pytest.raises(re_.NoPatternError):
		re_.select_pattern(patterns, "Purchase Invoice", ctx, {"pattern_id": "purchase_expense_vat_payer"})


def test_select_pattern_prefers_specific_over_wildcard():
	generic = re_.PatternSpec("g", "g", "f", ("Journal Entry",))
	specific = re_.PatternSpec("s", "s", "f", ("Journal Entry",), applies_to_vat="vat_payer")
	ctx = RegimeContext(Regime.VAT_PAYER, True, True, "vat_monthly")
	assert re_.select_pattern([generic, specific], "Journal Entry", ctx, {"family": "f"}).pattern_id == "s"
	disabled = re_.PatternSpec("d", "d", "f", ("Journal Entry",), applies_to_vat="vat_payer", enabled=False)
	assert re_.select_pattern([generic, disabled], "Journal Entry", ctx, {"family": "f"}).pattern_id == "g"


def test_pattern_spec_from_doctype_shape():
	spec = re_.PatternSpec.from_dict(
		{
			"pattern_id": "x",
			"name_mn": "X",
			"document_types": "Journal Entry, Purchase Invoice",
			"applies_to_vat": "non_vat",
			"citation_instrument": "Заавар 116 (2000)",
			"citation_section": "3.2",
			"verified": 1,
			"lines": [
				{
					"side": "debit",
					"account_class": "70",
					"amount_kind": "gross",
					"alternatives_json": '[{"account_class": "71"}]',
				},
				{"side": "credit", "account_class": "31", "amount_kind": "gross", "alternatives_json": ""},
			],
		}
	)
	assert spec.document_types == ("Journal Entry", "Purchase Invoice")
	assert spec.citation == Citation("Заавар 116 (2000)", "3.2", True, None, None)
	assert spec.lines[0].alternatives[0].account_class == "71"
	assert spec.lines[0].selector == "class:70"
	assert re_.PatternLine("debit", "12", "", "", "vat", role="input_vat").selector == "role:input_vat"
	assert re_.PatternLine("debit", "12", "", "", "vat", code="1810").selector == "1810"


def test_citation_suffix_uses_section_when_present():
	assert re_.citation_suffix(Citation("Заавар 116 (2000)", "3.4", True)) == " — Заавар 116 (2000), 3.4"
	assert re_.citation_suffix(Citation("Заавар 116 (2000)", None, False)).endswith(
		mn.CITATION_SECTION_PENDING
	)


def test_verified_pattern_adds_no_warning(code_roles):
	spec = re_.PatternSpec(
		"v",
		"V",
		"f",
		("Journal Entry",),
		lines=(
			re_.PatternLine("debit", "70", "", "", "gross", role="default_expense"),
			re_.PatternLine("credit", "11", "", "", "gross", role="bank"),
		),
		citation=Citation("Заавар 116 (2000)", "3.1", True),
		verified=True,
	)
	entry = re_.instantiate(spec, {"gross": 1000}, _resolver(code_roles, "v1", "6910"), warnings=["x"])
	assert entry.warnings == ("x",)
	assert entry.total == Decimal("1000.00")
	assert entry.pattern_id == "v"
