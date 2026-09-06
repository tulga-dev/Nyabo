from __future__ import annotations

import copy
from typing import Any

import pytest

from nyabo_mn.setup import chart as c

REQUIRED_LEAVES = [
	"1110",  # Касс
	"1120",  # Банк
	"1310",  # Дансны авлага
	"1810",  # Татан суутгах НӨАТ
	"1910",  # Түр нээлтийн данс
	"2110",  # Дансны өглөг
	"2210",  # Төлөх НӨАТ
	"4110",  # Борлуулалтын орлого
	"6210",  # Шатахуун
	"6810",  # Банкны хураамж
	"6910",  # Бусад зардал
	"6920",  # Round off
	"6930",  # Exchange gain/loss
	"6940",  # Write off
]


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
	return c.load_raw()


@pytest.fixture(scope="module")
def chart() -> c.NormalizedChart:
	return c.load_chart()


def _walk(node: dict[str, Any]):
	for key, value in node.items():
		yield key, value
		if key not in c.METADATA_KEYS and isinstance(value, dict):
			yield from _walk(value)


def test_draft_chart_is_valid(chart: c.NormalizedChart):
	assert c.validate(chart) == []
	assert chart.country_code == "mn"


def test_no_documentation_keys_reach_erpnext(chart: c.NormalizedChart):
	for root in chart.tree.values():
		for key, value in _walk(root):
			assert not key.startswith("_"), key
			# every non-metadata key is a child account (dict), never a string
			assert key in c.METADATA_KEYS or isinstance(value, dict), key


def test_range_numbers_are_dropped_with_a_warning(chart: c.NormalizedChart):
	assert any("1100-1800" in w for w in chart.warnings)
	assert any("5000-9000" in w for w in chart.warnings)
	for account in chart.accounts():
		assert account.number == "" or account.number.isdigit(), account


def test_required_leaf_codes_present(chart: c.NormalizedChart):
	leaves = chart.leaf_numbers()
	missing = [code for code in REQUIRED_LEAVES if code not in leaves]
	assert not missing, missing


def test_five_roots_with_root_types(chart: c.NormalizedChart):
	roots = [a for a in chart.accounts() if a.depth == 0]
	assert {r.root_type for r in roots} == set(c.ROOT_TYPES)
	assert all(r.is_group for r in roots)


def test_is_group_matches_children(chart: c.NormalizedChart):
	def check(node: dict[str, Any]):
		children = [k for k, v in node.items() if k not in c.METADATA_KEYS and isinstance(v, dict)]
		assert node["is_group"] == (1 if children else 0)
		for child in children:
			check(node[child])

	for root in chart.tree.values():
		check(root)


def test_every_account_has_currency(chart: c.NormalizedChart):
	for root in chart.tree.values():
		for key, value in _walk(root):
			if key not in c.METADATA_KEYS:
				assert value["account_currency"] == "MNT"


def test_tax_rate_overlay(chart: c.NormalizedChart):
	rates = {}
	for root in chart.tree.values():
		for key, value in _walk(root):
			if key not in c.METADATA_KEYS and value.get("account_number") in c.TAX_RATE_BY_CODE:
				rates[value["account_number"]] = value.get("tax_rate")
	assert rates == {"2210": 10.0, "1810": 10.0}


def test_account_category_overlay(chart: c.NormalizedChart):
	categories = {}
	for root in chart.tree.values():
		for key, value in _walk(root):
			if key not in c.METADATA_KEYS:
				categories[value.get("account_number")] = value.get("account_category")
	assert categories["1110"] == "Cash and Cash Equivalents"
	assert categories["6210"] == "Operating Expenses"
	assert categories["6810"] == "Finance Costs"
	assert categories["9110"] == "Tax Expense"
	assert categories["1910"] is None  # temporary opening account stays out of the statements
	assert categories[""] is None  # groups get no category


def test_vat_defaults_reference_existing_leaves(raw: dict[str, Any], chart: c.NormalizedChart):
	defaults = c.vat_defaults(raw)
	assert set(defaults) == {"output_vat_10", "input_vat_10", "exempt"}
	leaves = chart.leaf_numbers()
	for group, codes in defaults.items():
		unknown = [code for code in codes if code not in leaves]
		assert not unknown, (group, unknown)


def test_report_type_follows_root_type(chart: c.NormalizedChart):
	by_number = chart.by_number()
	assert by_number["1110"].report_type == "Balance Sheet"
	assert by_number["6210"].report_type == "Profit and Loss"


def test_duplicate_number_is_rejected(raw: dict[str, Any]):
	broken = copy.deepcopy(raw)
	broken["tree"]["Зардал"]["Үйл ажиллагааны зардал"]["Шатахуун"]["account_number"] = "6220"
	errors = c.validate(c.normalize(broken))
	assert any("duplicate account_number 6220" in e for e in errors)


def test_leaf_without_number_is_rejected(raw: dict[str, Any]):
	broken = copy.deepcopy(raw)
	del broken["tree"]["Зардал"]["Үйл ажиллагааны зардал"]["Шатахуун"]["account_number"]
	errors = c.validate(c.normalize(broken))
	assert any("has no account_number" in e for e in errors)


def test_root_without_root_type_is_rejected(raw: dict[str, Any]):
	broken = copy.deepcopy(raw)
	del broken["tree"]["Орлого"]["root_type"]
	with pytest.raises(c.ChartError):
		c.normalize(broken)


def test_unexpected_scalar_key_is_rejected(raw: dict[str, Any]):
	broken = copy.deepcopy(raw)
	broken["tree"]["Орлого"]["note"] = "not an account"
	with pytest.raises(c.ChartError):
		c.normalize(broken)


def test_load_chart_raises_on_invalid(tmp_path, raw: dict[str, Any]):
	broken = copy.deepcopy(raw)
	broken["tree"]["Зардал"]["Үйл ажиллагааны зардал"]["Шатахуун"]["account_number"] = "6220"
	path = tmp_path / "bad.json"
	path.write_text(__import__("json").dumps(broken, ensure_ascii=False), encoding="utf-8")
	with pytest.raises(c.ChartError):
		c.load_chart(path)
