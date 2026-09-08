"""The golden set loads, matches the Nyabo Eval Case DocType and round-trips through it."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from nyabo_mn.evals import loader
from nyabo_mn.evals.golden import _generate

EXPECTED_COUNTS = {
	"extraction": 10,
	"classification": 20,
	"rules": 10,
	"injection": 8,
	"correction": 5,
	"document_required": 5,
	"period_lock": 5,
	"fx": 3,
	"matching": 20,
}


def test_golden_set_loads_with_the_documented_counts():
	cases = loader.load_golden()
	assert Counter(c.kind for c in cases) == EXPECTED_COUNTS
	assert len({c.case_id for c in cases}) == len(cases)
	assert all(c.source == "synthetic" for c in cases)
	for c in cases:
		assert c.expected_json and isinstance(c.input_json, dict)
		if c.kind != "matching":
			assert c.on_date is not None
		if c.kind in ("classification", "correction", "rules", "injection"):
			assert c.regime in ("vat_payer", "simplified_1pct")


def test_classification_cases_cover_both_regimes_for_every_receipt():
	cases = loader.load_golden(["classification"])
	pairs = Counter((c.input_json["receipt"]["seller_name"], c.regime) for c in cases)
	assert all(n == 1 for n in pairs.values())
	assert {r for _s, r in pairs} == {"vat_payer", "simplified_1pct"}
	dates = {c.regime: c.on_date.isoformat() for c in cases}
	assert dates == {"vat_payer": "2026-06-15", "simplified_1pct": "2027-02-15"}


def _chart_leaves(scheme: str) -> dict[str, str]:
	"""``code -> name`` for the shipped chart of a scheme: v1 = the draft, v03 = the seed."""
	from nyabo_mn.nyabo.seed import seed_path
	from nyabo_mn.setup import chart as chart_mod

	path = chart_mod.DEFAULT_CHART_PATH if scheme == "v1" else seed_path("chart_v03")
	chart = chart_mod.load_chart(path)
	return {a.number: a.name for a in chart.accounts() if a.number and not a.is_group}


def _expected_account_codes(case) -> list[tuple[str, str]]:
	"""``(code, where)`` for every account a case expects the app to post to."""
	expected = dict(case.expected_json)
	found: list[tuple[str, str]] = []
	if expected.get("account_code"):
		found.append((str(expected["account_code"]), "account_code"))
	for key in ("lines", "reversal_lines", "new_entry_lines", "fx_lines"):
		for index, line in enumerate(expected.get(key) or []):
			if line.get("account_code"):
				found.append((str(line["account_code"]), f"{key}[{index}]"))
	for index, row in enumerate(expected.get("correction_rows") or []):
		if row.get("field") != "account_code":
			continue
		for side in ("proposed_value", "corrected_value"):
			if row.get(side):
				found.append((str(row[side]), f"correction_rows[{index}].{side}"))
	return found


def test_every_expected_account_code_is_a_leaf_of_the_shipped_chart():
	"""An expectation naming an account the chart does not have would pass the eval and then
	fail on a real site (ERPNext refuses a GL entry on a group account or an unknown one)."""
	checked = 0
	for case in loader.load_golden():
		scheme = str(case.input_json.get("scheme") or "v1")
		leaves = _chart_leaves(scheme)
		assert leaves, scheme
		for code, where in _expected_account_codes(case):
			assert code in leaves, f"{case.case_id}: {where} = {code} is not a leaf of the {scheme} chart"
			checked += 1
	assert checked >= 60, checked  # the 20 classification cases alone carry three lines each


def test_every_expected_account_code_also_resolves_on_the_v03_chart():
	"""The golden set is spelled in V1 codes; a v0.3 site reaches them through the alias table.

	So every code the set expects must have an alias whose target is a v0.3 leaf — otherwise
	the same approved receipt is postable on one shipped chart and not on the other.
	"""
	from nyabo_mn.nyabo.seed import load_seed

	aliases = {
		k: str(v)
		for k, v in load_seed("aliases_v1_to_v03").items()
		if not k.startswith("_") and k != "unmapped"
	}
	v03_leaves = _chart_leaves("v03")
	for case in loader.load_golden():
		if str(case.input_json.get("scheme") or "v1") != "v1":
			continue
		for code, where in _expected_account_codes(case):
			assert code in aliases, f"{case.case_id}: {where} = {code} has no v0.3 alias"
			target = aliases[code]
			assert target in v03_leaves, (
				f"{case.case_id}: {where} = {code} maps to {target}, which is not a v0.3 leaf"
			)


def test_every_referenced_fixture_exists():
	from nyabo_mn.agent.mock_client import DEFAULT_FIXTURES_DIR

	for c in loader.load_golden():
		for key in ("llm_fixture", "classify_fixture"):
			if c.input_json.get(key):
				assert (DEFAULT_FIXTURES_DIR / f"{c.input_json[key]}.json").is_file(), (c.case_id, key)


def test_golden_files_are_up_to_date_with_the_generator():
	files, _fixtures = _generate.build()
	for name, cases in files.items():
		with (loader.GOLDEN_DIR / f"{name}.json").open(encoding="utf-8") as fh:
			on_disk = json.load(fh)["cases"]
		assert on_disk == cases, (
			f"{name}.json differs from _generate.py; run python -m nyabo_mn.evals.golden._generate"
		)


def test_select_options_come_from_the_doctype_json():
	options = loader.field_options()
	assert "injection" in options["kind"] and "correction" in options["source"]
	assert set(loader.ALL_KINDS) <= set(options["kind"])


@pytest.mark.parametrize(
	"bad, message",
	[
		({"case_id": "x", "kind": "nope", "expected_json": {"a": 1}, "on_date": "2026-01-01"}, "kind='nope'"),
		(
			{"case_id": "x", "kind": "fx", "expected_json": {"a": 1}, "on_date": "2026-13-01"},
			"not YYYY-MM-DD",
		),
		(
			{"case_id": "x", "kind": "fx", "expected_json": {}, "on_date": "2026-01-01"},
			"expected_json is empty",
		),
		(
			{"case_id": "x", "kind": "classification", "expected_json": {"a": 1}, "on_date": "2026-01-01"},
			"needs a regime",
		),
		(
			{"case_id": "x", "kind": "fx", "expected_json": {"a": 1}, "on_date": "2026-01-01", "bogus": 1},
			"unknown fields",
		),
		(
			{"case_id": "x", "kind": "fx", "expected_json": "[1]", "on_date": "2026-01-01"},
			"must be a JSON object",
		),
	],
)
def test_invalid_cases_are_refused_with_the_field_named(bad, message):
	with pytest.raises(loader.GoldenCaseError, match=message):
		loader.validate_case(bad)


def test_case_round_trips_through_the_doctype(site):
	import frappe

	case = next(c for c in loader.load_golden(["fx"]))
	doc = frappe.get_doc(case.to_doc())
	doc.insert()
	stored = frappe.get_doc("Nyabo Eval Case", doc.name)
	assert stored.kind == "fx" and stored.source == "synthetic"
	assert json.loads(stored.expected_json) == dict(case.expected_json)
	back = loader.EvalCase.from_doc(stored)
	assert back.case_id == case.case_id and back.expected_json == case.expected_json
	assert back.on_date == case.on_date and back.name == doc.name


def test_doctype_controller_refuses_bad_json_and_missing_regime(site):
	import frappe

	with pytest.raises(frappe.ValidationError, match="JSON"):
		frappe.get_doc(
			{
				"doctype": "Nyabo Eval Case",
				"kind": "fx",
				"on_date": "2026-01-01",
				"expected_json": "{not json",
			}
		).insert()
	with pytest.raises(frappe.ValidationError, match="горим"):
		frappe.get_doc(
			{
				"doctype": "Nyabo Eval Case",
				"kind": "classification",
				"expected_json": {"account_code": "6210"},
			}
		).insert()
	ok = frappe.get_doc(
		{
			"doctype": "Nyabo Eval Case",
			"kind": "classification",
			"regime": "vat_payer",
			"expected_json": {"account_code": "6210"},
		}
	).insert()
	assert json.loads(ok.expected_json) == {"account_code": "6210"}
