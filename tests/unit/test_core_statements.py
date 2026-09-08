from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from nyabo_mn.core import statements as st
from nyabo_mn.nyabo.seed import load_seed

# A separate debit/credit export with a title block above the header, Mongolian headers,
# mixed amount spellings and a closing-balance row.
SEPARATE_ROWS: list[list[object]] = [
	["Хаан банк", None, None, None, None, None],
	["Дансны хуулга 2026.09.01 - 2026.09.30", None, None, None, None, None],
	[],
	["Огноо", "Гүйлгээний утга", "Зарлага", "Орлого", "Үлдэгдэл", "Лавлах"],
	["2026.09.01", "Эхний үлдэгдэл", "", "", "1 000 000", ""],
	["2026.09.02", "Петровис ХХК шатахуун", "85 000₮", "", "915 000", "TX1"],
	["03.09.2026", "Номин ХХК төлбөр", "", "1,250,000.00", "2 165 000", "TX2"],
	[dt.datetime(2026, 9, 4, 10, 15), "Банкны хураамж", "(1 500)", "-", "2 163 500", ""],
	["2026.09.05", "Өөрийн данс 5012345678 руу", 200000, None, "1 963 500", "TX4"],
	["", "", "", "", "", ""],
	["2026.09.30", "Эцсийн үлдэгдэл", "", "", "1 963 500", ""],
	["Нийт", "", "286 500", "1 250 000", "", ""],
]

SEPARATE_LAYOUT = st.LayoutSpec(
	layout_id="test_separate",
	bank="Khan Bank",
	header_signature=("Огноо", "Гүйлгээний утга", "Зарлага", "Орлого"),
	column_map={"date": 0, "description": 1, "debit": 2, "credit": 3, "balance": 4, "reference": 5},
	amount_style="separate_debit_credit",
	date_formats=("%Y.%m.%d", "%d.%m.%Y"),
	verified=True,
)

SIGNED_ROWS: list[list[object]] = [
	["Date", "Description", "Amount", "Currency"],
	["2026-09-02", "PETROVIS LLC fuel", "-85,000.00", "MNT"],
	["2026-09-03 14:20:00", "NOMIN LLC payment", "1 250 000", "MNT"],
	["2026-09-04", "USD transfer", "100.50", "USD"],
	["2026-09-05", "No amount row", "", "MNT"],
]

SIGNED_LAYOUT = st.LayoutSpec(
	layout_id="test_signed",
	bank="Other",
	header_signature=("Date", "Description", "Amount"),
	column_map={"date": "Date", "description": "Description", "amount": "Amount", "currency": "Currency"},
	amount_style="signed_amount",
	date_formats=("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"),
)


def test_parse_rows_separate_debit_credit_all_amount_spellings():
	lines = st.parse_rows(SEPARATE_ROWS, SEPARATE_LAYOUT)
	assert [line.date for line in lines] == [
		dt.date(2026, 9, 2),
		dt.date(2026, 9, 3),
		dt.date(2026, 9, 4),
		dt.date(2026, 9, 5),
	]
	fuel, nomin, fee, transfer = lines
	assert (fuel.debit, fuel.credit, fuel.amount) == (
		Decimal("85000.00"),
		Decimal("0.00"),
		Decimal("-85000.00"),
	)
	assert (nomin.debit, nomin.credit, nomin.amount) == (
		Decimal("0.00"),
		Decimal("1250000.00"),
		Decimal("1250000.00"),
	)
	assert (fee.debit, fee.amount) == (
		Decimal("1500.00"),
		Decimal("-1500.00"),
	)  # parentheses, abs on the debit side
	assert transfer.amount == Decimal("-200000.00")  # numeric cell
	assert fuel.balance == Decimal("915000.00")
	assert fuel.reference == "TX1" and fee.reference == ""
	assert fuel.currency == "MNT"
	assert fuel.row_index == 5 and transfer.row_index == 8
	assert all(isinstance(line.amount, Decimal) for line in lines)


def test_summary_and_blank_rows_are_skipped():
	descriptions = [line.description for line in st.parse_rows(SEPARATE_ROWS, SEPARATE_LAYOUT)]
	assert "Эхний үлдэгдэл" not in descriptions
	assert "Эцсийн үлдэгдэл" not in descriptions
	assert "Нийт" not in descriptions


def test_parse_rows_signed_amount_with_header_text_mapping():
	lines = st.parse_rows(SIGNED_ROWS, SIGNED_LAYOUT)
	assert len(lines) == 3  # the empty-amount row is dropped
	fuel, nomin, usd = lines
	assert (fuel.debit, fuel.credit, fuel.amount) == (
		Decimal("85000.00"),
		Decimal("0.00"),
		Decimal("-85000.00"),
	)
	assert (nomin.debit, nomin.credit, nomin.amount) == (
		Decimal("0.00"),
		Decimal("1250000.00"),
		Decimal("1250000.00"),
	)
	assert nomin.date == dt.date(2026, 9, 3)  # datetime string parsed by the listed format
	assert usd.currency == "USD" and usd.amount == Decimal("100.50")
	assert usd.balance is None


def test_date_formats_are_the_listed_ones_only():
	strict = st.LayoutSpec(
		"strict", "Other", column_map={"date": 0, "description": 1, "debit": 2}, date_formats=("%Y-%m-%d",)
	)
	rows = [
		["Огноо", "Утга", "Зарлага"],
		["2026-09-02", "a", "10"],
		["02.09.2026", "b", "10"],
		["2026/09/02", "c", "10"],
	]
	lines = st.parse_rows(rows, strict)
	assert [line.description for line in lines] == ["a"]
	assert st.parse_cell_date("2026.09.02", ("%Y.%m.%d",)) == dt.date(2026, 9, 2)
	assert st.parse_cell_date("02.09.2026 10:15", ("%d.%m.%Y",)) == dt.date(2026, 9, 2)
	assert st.parse_cell_date("nonsense", ("%Y-%m-%d",)) is None
	assert st.parse_cell_date(dt.date(2026, 1, 2)) == dt.date(2026, 1, 2)


def test_parse_cell_amount_edge_cases():
	assert st.parse_cell_amount("") is None
	assert st.parse_cell_amount("-") is None
	assert st.parse_cell_amount(True) is None
	assert st.parse_cell_amount("abc") is None
	assert st.parse_cell_amount(1500.5) == Decimal("1500.50")
	assert st.parse_cell_amount("1 500₮") == Decimal("1500.00")


def test_row_hash_is_stable_and_row_sensitive():
	a = st.row_hash(dt.date(2026, 9, 2), Decimal("-85000"), "Петровис ХХК", "TX1", 5)
	b = st.row_hash(dt.date(2026, 9, 2), Decimal("-85000.00"), " Петровис ХХК ", "TX1 ", 5)
	c = st.row_hash(dt.date(2026, 9, 2), Decimal("-85000"), "Петровис ХХК", "TX1", 6)
	assert a == b and a != c and len(a) == 64
	lines = st.parse_rows(SEPARATE_ROWS, SEPARATE_LAYOUT)
	assert lines[0].row_hash == st.row_hash(
		lines[0].date, lines[0].amount, lines[0].description, lines[0].reference, 5
	)
	assert len({line.row_hash for line in lines}) == len(lines)


def test_detect_layout_by_signature_and_placeholders_never_match():
	seed = [st.LayoutSpec.from_dict(row) for row in load_seed("bank_layouts")["rows"]]
	placeholders = [layout for layout in seed if not layout.is_generic]
	assert len(placeholders) == 5 and all(layout.header_signature == () for layout in placeholders)
	assert all(layout.verified is False for layout in seed)
	assert st.detect_layout(SEPARATE_ROWS, placeholders) is None
	found = st.detect_layout(SEPARATE_ROWS, [*placeholders, SEPARATE_LAYOUT, SIGNED_LAYOUT])
	assert found is SEPARATE_LAYOUT
	assert st.detect_layout(SIGNED_ROWS, [SEPARATE_LAYOUT, SIGNED_LAYOUT]) is SIGNED_LAYOUT


def test_generic_fallback_guesses_columns_and_is_unverified():
	seed = [st.LayoutSpec.from_dict(row) for row in load_seed("bank_layouts")["rows"]]
	guessed = st.detect_layout(SEPARATE_ROWS, seed)
	assert guessed is not None
	assert guessed.layout_id == "generic_mn"
	assert guessed.verified is False
	assert guessed.header_row_hint == 3
	assert guessed.column_map == {
		"date": 0,
		"description": 1,
		"debit": 2,
		"credit": 3,
		"balance": 4,
		"reference": 5,
	}
	assert guessed.amount_style == "separate_debit_credit"
	lines = st.parse_rows(SEPARATE_ROWS, guessed)
	assert [line.amount for line in lines] == [
		Decimal("-85000.00"),
		Decimal("1250000.00"),
		Decimal("-1500.00"),
		Decimal("-200000.00"),
	]


def test_generic_fallback_english_signed_export():
	seed = [st.LayoutSpec.from_dict(row) for row in load_seed("bank_layouts")["rows"]]
	guessed = st.detect_layout(SIGNED_ROWS, seed)
	assert guessed is not None and guessed.verified is False
	assert guessed.amount_style == "signed_amount"
	assert guessed.column_map["amount"] == 2 and guessed.column_map["currency"] == 3
	assert len(st.parse_rows(SIGNED_ROWS, guessed)) == 3


def test_generic_fallback_gives_up_without_date_or_amount():
	rows = [["Нэр", "Тайлбар", "Хаяг"], ["a", "b", "c"]]
	assert st.guess_layout(rows) is None
	assert st.detect_layout(rows, [st.LayoutSpec.from_dict(load_seed("bank_layouts")["rows"][-1])]) is None


def test_layout_errors_for_unusable_layouts():
	with pytest.raises(st.LayoutError):
		st.parse_rows(SEPARATE_ROWS, st.LayoutSpec("x", "Other", column_map={"date": 0, "debit": 2}))
	with pytest.raises(st.LayoutError):
		st.parse_rows(SEPARATE_ROWS, st.LayoutSpec("x", "Other", column_map={"date": 0, "description": 1}))
	with pytest.raises(st.LayoutError):
		st.parse_rows(
			SEPARATE_ROWS,
			st.LayoutSpec(
				"x",
				"Other",
				column_map={"date": 0, "description": 1, "amount": "Дүн"},
				amount_style="signed_amount",
			),
		)
	with pytest.raises(st.LayoutError):
		st.parse_rows(
			SIGNED_ROWS,
			st.LayoutSpec(
				"x",
				"Other",
				column_map={"date": "Date", "description": "Nope", "amount": "Amount"},
				amount_style="signed_amount",
			),
		)


def test_layout_spec_from_doctype_shape():
	spec = st.LayoutSpec.from_dict(
		{
			"layout_id": "khan_bank_xlsx",
			"bank": "Khan Bank",
			"header_signature_json": ["Огноо", "Утга"],
			"column_map_json": {"date": "0", "description": 1, "debit": "Зарлага"},
			"date_formats": "%Y-%m-%d\n%d.%m.%Y\n",
			"header_row_hint": "",
			"verified": 1,
		}
	)
	assert spec.header_signature == ("Огноо", "Утга")
	assert spec.date_formats == ("%Y-%m-%d", "%d.%m.%Y")
	assert spec.header_row_hint is None and spec.verified is True and not spec.is_generic
	rows = [["Огноо", "Утга", "Зарлага"], ["2026-09-02", "a", "10"]]
	assert st.resolve_columns(rows, spec) == (0, {"date": 0, "description": 1, "debit": 2})
