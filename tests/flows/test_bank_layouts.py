"""Readers, detection and layout learning against the synthetic fixtures."""

from __future__ import annotations

import json

import pytest

from nyabo_mn.core.statements import parse_rows
from nyabo_mn.parsers import detect as detect_mod
from nyabo_mn.parsers import excel, layouts
from tests.fixtures.statements import make_fixtures as fixtures
from tests.flows import bank_helpers as helpers

EXPECTED_COUNTS = {
	"khan_xlsx": 5,
	"tdb_xlsx": 3,
	"golomt_xlsx": 3,
	"transbank_xlsx": 2,
	"xacbank_xlsx": 3,
	"khan_csv_cp1251": 5,
}


@pytest.mark.parametrize("builder", list(EXPECTED_COUNTS))
def test_read_rows_returns_header_and_lines(builder):
	filename, data = helpers.fixture_bytes(builder)
	rows = excel.read_rows(data, filename)
	assert len(rows) >= EXPECTED_COUNTS[builder] + 1
	assert any(
		any(str(c or "").lower() in ("огноо", "date", "гүйлгээний огноо") for c in row) for row in rows[:5]
	)


def test_xls_is_refused_with_a_clear_message():
	with pytest.raises(excel.StatementFileError) as info:
		excel.read_rows(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, "old.xls")
	assert info.value.kind == "xls"
	with pytest.raises(excel.StatementFileError):
		excel.read_rows(b"", "empty.xlsx")


def test_csv_cp1251_is_decoded_and_delimited():
	filename, data = fixtures.khan_csv_cp1251()
	text, encoding = excel.decode_csv(data)
	assert encoding == "cp1251" and "Петровис" in text
	rows = excel.read_rows(data, filename)
	assert rows[2][:2] == ["Огноо", "Гуйлгээний утга"]
	assert rows[3][2] == "93 500"


def test_detect_without_layouts_gives_only_a_generic_guess(site):
	filename, data = fixtures.khan_xlsx()
	rows = excel.read_rows(data, filename)
	trusted, guess = detect_mod.detect(rows, "Тест ХХК")
	assert trusted is None
	assert guess is not None and guess.verified is False
	assert {"date", "description", "debit", "credit", "balance"} <= set(guess.column_map)
	assert guess.header_row_hint == 3


@pytest.mark.parametrize(
	("builder", "layout_id"),
	[
		("khan_xlsx", "test_khan_synthetic"),
		("tdb_xlsx", "test_tdb_synthetic"),
		("golomt_xlsx", "test_golomt_synthetic"),
		("transbank_xlsx", "test_transbank_synthetic"),
		("xacbank_xlsx", "test_xacbank_synthetic"),
		("khan_csv_cp1251", "test_khan_synthetic_cp1251"),
	],
)
def test_detect_picks_the_verified_layout_and_parses_every_line(site, builder, layout_id):
	helpers.register_layouts()
	filename, data = helpers.fixture_bytes(builder)
	rows = excel.read_rows(data, filename)
	trusted, guess = detect_mod.detect(rows, "Тест ХХК")
	assert trusted is not None and trusted.layout_id == layout_id and trusted.verified
	assert guess is not None
	lines = parse_rows(rows, trusted)
	assert len(lines) == EXPECTED_COUNTS[builder]
	assert all(line.amount != 0 for line in lines)


def test_learned_layout_is_unverified_and_only_usable_under_simulation(site, frappe_flags):
	filename, data = fixtures.transbank_xlsx()
	rows = excel.read_rows(data, filename)
	doc = layouts.save_learned_layout(
		"Trans Bank",
		rows[0],
		{"0": "date", "1": "credit", "2": "debit", "3": "description", "4": "reference"},
		"Тест ХХК",
		None,
		date_formats=["%Y-%m-%d"],
	)
	assert doc.verified == 0 and doc.layout_id.startswith("learned_trans_bank_")
	assert json.loads(doc.column_map_json) == {
		"date": 0,
		"credit": 1,
		"debit": 2,
		"description": 3,
		"reference": 4,
	}
	assert doc.amount_style == "separate_debit_credit"
	trusted, _guess = detect_mod.detect(rows, "Тест ХХК")
	assert trusted is None
	with frappe_flags(nyabo_simulation=True):
		trusted, _guess = detect_mod.detect(rows, "Тест ХХК")
	assert trusted is not None and trusted.layout_id == doc.layout_id
	assert len(parse_rows(rows, trusted)) == 2
	# Saving the same signature again updates instead of duplicating.
	again = layouts.save_learned_layout(
		"Trans Bank", rows[0], {"date": 0, "description": 3, "debit": 2}, "Тест ХХК"
	)
	assert again.name == doc.name


def test_learned_layout_rejects_bad_answers(site):
	with pytest.raises(ValueError):
		layouts.save_learned_layout("Khan Bank", ["Огноо", "Утга"], {"0": "date", "1": "colour"}, "Тест ХХК")
	with pytest.raises(ValueError):
		layouts.save_learned_layout("Khan Bank", ["Огноо", "Утга"], {"0": "date"}, "Тест ХХК")


def test_bank_layout_doctype_validation(site):
	import frappe

	def make(**values):
		base = {
			"doctype": "Nyabo Bank Layout",
			"layout_id": values.pop("layout_id", "t_validate"),
			"bank": "Other",
			"amount_style": "separate_debit_credit",
			"header_signature_json": json.dumps(["огноо", "утга", "дүн"]),
			"column_map_json": json.dumps({"date": 0, "description": 1, "debit": 2}),
		}
		base.update(values)
		return frappe.get_doc(base)

	with pytest.raises(frappe.ValidationError):
		make(column_map_json=json.dumps({"date": 0, "description": 1, "colour": 2})).insert()
	with pytest.raises(frappe.ValidationError):
		make(column_map_json=json.dumps({"description": 1, "debit": 2})).insert()
	with pytest.raises(frappe.ValidationError):
		make(amount_style="signed_amount").insert()
	with pytest.raises(frappe.ValidationError):
		make(date_formats="%Q-%%").insert()
	with pytest.raises(frappe.ValidationError):
		make(layout_id="t_placeholder", verified=1, header_signature_json="[]", column_map_json="{}").insert()
	ok = make(verified=1).insert()
	assert ok.name == "t_validate" and json.loads(ok.column_map_json)["debit"] == 2
