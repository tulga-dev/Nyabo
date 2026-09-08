from __future__ import annotations

import datetime as dt
from decimal import Decimal

from nyabo_mn.core.models import Citation, ProposedEntry, ProposedLine
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.core.validate import validate_entry
from nyabo_mn.i18n import mn

LEAVES = {"6210", "1810", "2110", "1110", "6910"}
GROUPS = {"6000", "1000"}
CITATION = Citation("Заавар 116 (2000)", None, False)
VAT_RATE = Decimal("0.10")


def _entry(lines: tuple[ProposedLine, ...], vat_treatment: str = "none", total="0", vat="0") -> ProposedEntry:
	return ProposedEntry(
		company="Тест ХХК",
		posting_date=dt.date(2026, 9, 5),
		lines=lines,
		pattern_id="purchase_expense_vat_payer",
		citation=CITATION,
		explanation="",
		document_kind="journal_entry",
		vat_treatment=vat_treatment,  # type: ignore[arg-type]
		total=Decimal(total),
		vat_amount=Decimal(vat),
	)


def _line(code: str, debit="0", credit="0") -> ProposedLine:
	return ProposedLine(code, Decimal(debit), Decimal(credit))


def test_valid_vat_entry_has_no_problems():
	entry = _entry(
		(_line("6210", "77272.73"), _line("1810", "7727.27"), _line("2110", credit="85000")),
		vat_treatment="withheld",
		total="85000",
		vat="7727.27",
	)
	assert validate_entry(entry, LEAVES, VAT_RATE) == []


def test_valid_gross_entry_for_non_vat_company():
	entry = _entry((_line("6210", "85000"), _line("2110", credit="85000")), "in_expense", "85000", "0")
	assert validate_entry(entry, LEAVES, VAT_RATE) == []


def test_unbalanced_entry():
	entry = _entry((_line("6210", "85000"), _line("2110", credit="80000")))
	problems = validate_entry(entry, LEAVES, VAT_RATE)
	assert problems == [mn.MSG_ENTRY_UNBALANCED.format(debit=fmt_mnt(85000), credit=fmt_mnt(80000))]


def test_too_few_lines():
	entry = _entry((_line("6210", "85000"),))
	problems = validate_entry(entry, LEAVES, VAT_RATE)
	assert mn.MSG_ENTRY_TOO_FEW_LINES in problems
	assert any(p.startswith("Бичилт тэнцэхгүй") for p in problems)


def test_unknown_and_group_accounts():
	entry = _entry((_line("6000", "100"), _line("9999", credit="100")))
	problems = validate_entry(entry, LEAVES, VAT_RATE, group_codes=GROUPS)
	assert mn.MSG_ACCOUNT_IS_GROUP.format(account="6000") in problems
	assert mn.MSG_ACCOUNT_UNKNOWN.format(account="9999") in problems
	# Without a group list every non-leaf is reported as a group (the safe reading of "not a leaf").
	problems = validate_entry(entry, LEAVES, VAT_RATE)
	assert mn.MSG_ACCOUNT_IS_GROUP.format(account="9999") in problems


def test_zero_negative_and_two_sided_lines():
	entry = _entry(
		(
			_line("6210", "0"),
			_line("1810", "-5"),
			_line("2110", "10", "10"),
			_line("1110", credit="-5"),
		)
	)
	problems = validate_entry(entry, LEAVES, VAT_RATE)
	assert mn.MSG_ENTRY_ZERO_LINE.format(account="6210") in problems
	assert mn.MSG_ENTRY_NEGATIVE_AMOUNT.format(account="1810") in problems
	assert mn.MSG_ENTRY_LINE_BOTH_SIDES.format(account="2110") in problems
	assert mn.MSG_ENTRY_NEGATIVE_AMOUNT.format(account="1110") in problems


def test_vat_math_checked_only_when_withheld():
	lines = (_line("6210", "77272.73"), _line("1810", "9000"), _line("2110", credit="86272.73"))
	withheld = _entry(lines, "withheld", "86272.73", "9000")
	problems = validate_entry(withheld, LEAVES, VAT_RATE)
	assert problems == [mn.MSG_VAT_MATH_INCONSISTENT.format(vat=fmt_mnt(9000), rate="10")]
	not_withheld = _entry(lines, "in_expense", "86272.73", "9000")
	assert validate_entry(not_withheld, LEAVES, VAT_RATE) == []


def test_vat_math_tolerance_is_one_togrog_by_default():
	lines = (_line("6210", "77273"), _line("1810", "7727"), _line("2110", credit="85000"))
	entry = _entry(lines, "withheld", "85000", "7727")
	assert validate_entry(entry, LEAVES, VAT_RATE) == []
	off = _entry(lines, "withheld", "85000", "7725")
	assert validate_entry(off, LEAVES, VAT_RATE) != []
	assert validate_entry(off, LEAVES, VAT_RATE, vat_tolerance=Decimal("5")) == []


def test_withheld_with_zero_total_is_inconsistent():
	entry = _entry((_line("6210", "1"), _line("2110", credit="1")), "withheld", "0", "0")
	problems = validate_entry(entry, LEAVES, VAT_RATE)
	assert any(p.startswith("НӨАТ-ын дүн") for p in problems)


def test_rate_formatting_in_message():
	entry = _entry((_line("6210", "100"), _line("2110", credit="100")), "withheld", "100", "50")
	problems = validate_entry(entry, LEAVES, Decimal("0.115"))
	assert problems == [mn.MSG_VAT_MATH_INCONSISTENT.format(vat="50", rate="11.5")]
