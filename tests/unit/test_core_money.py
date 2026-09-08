from __future__ import annotations

from decimal import Decimal

import pytest

from nyabo_mn.core import money
from nyabo_mn.i18n import mn


@pytest.mark.parametrize(
	("text", "expected"),
	[
		("85 000₮", Decimal("85000.00")),
		("85,000.00", Decimal("85000.00")),
		("85000", Decimal("85000.00")),
		("85 000.50", Decimal("85000.50")),
		("1,234,567", Decimal("1234567.00")),
		("1.234.567,89", Decimal("1234567.89")),
		("1,5", Decimal("1.50")),
		("(1 500)", Decimal("-1500.00")),
		("-1 500", Decimal("-1500.00")),
		("−2 000₮", Decimal("-2000.00")),
		("1 500-", Decimal("-1500.00")),
		("+300", Decimal("300.00")),
		("12 500 MNT", Decimal("12500.00")),
		("12500 төг", Decimal("12500.00")),
		("0", Decimal("0.00")),
		("85 000", Decimal("85000.00")),
	],
)
def test_parse_mnt_strings(text: str, expected: Decimal):
	assert money.parse_mnt(text) == expected


def test_parse_mnt_numbers_are_quantised():
	assert money.parse_mnt(85000) == Decimal("85000.00")
	assert money.parse_mnt(Decimal("1.005")) == Decimal("1.01")  # half-up, not banker's
	assert money.parse_mnt(0.1) == Decimal("0.10")  # float goes through str(), no binary noise


@pytest.mark.parametrize("text", ["", "abc", "12.34.56.78", "1,23,4", "--5", "₮"])
def test_parse_mnt_rejects_garbage_with_mongolian_message(text: str):
	with pytest.raises(money.MoneyParseError) as exc:
		money.parse_mnt(text)
	assert exc.value.message_mn == mn.MSG_MONEY_UNPARSEABLE.format(text=text)


@pytest.mark.parametrize(
	("value", "expected"),
	[
		(Decimal("85000"), "85 000"),
		(Decimal("85000.00"), "85 000"),
		(Decimal("85000.50"), "85 000.50"),
		(Decimal("-1500"), "-1 500"),
		(Decimal("999"), "999"),
		(Decimal("0"), "0"),
		(1234567, "1 234 567"),
		("77272.73", "77 272.73"),
	],
)
def test_fmt_mnt(value, expected: str):
	assert money.fmt_mnt(value) == expected


def test_fmt_parse_round_trip():
	for text in ("85 000", "1 234 567.89", "-1 500"):
		assert money.fmt_mnt(money.parse_mnt(text)) == text


def test_vat_from_gross_uses_half_up():
	assert money.vat_from_gross(Decimal("85000"), Decimal("0.10")) == Decimal("7727.27")
	assert money.vat_from_gross(Decimal("110000"), "0.1") == Decimal("10000.00")
	# 11 * 0.1 / 1.1 = 1.000 exactly; 12.5 * 0.1 / 1.1 = 1.13636.. -> 1.14
	assert money.vat_from_gross("12.5", 0.1) == Decimal("1.14")


def test_vat_from_net_and_net_from_gross_sum_back():
	gross = Decimal("85000")
	vat = money.vat_from_gross(gross, "0.10")
	net = money.net_from_gross(gross, "0.10")
	assert net + vat == gross
	assert money.vat_from_net(Decimal("100000"), "0.10") == Decimal("10000.00")
	assert money.vat_from_net(Decimal("100000.005"), "0.10") == Decimal("10000.00")
	assert money.vat_from_net(Decimal("100005"), "0.10") == Decimal("10000.50")


def test_vat_from_net_half_up_rounding():
	# 33.335 * 0.10 = 3.3335 -> 3.33; 33.35 * 0.10 = 3.335 -> 3.34 (ROUND_HALF_UP)
	assert money.vat_from_net("33.35", "0.10") == Decimal("3.34")


def test_vat_consistent_default_tolerance_is_one_togrog():
	assert money.vat_consistent("85000", "7727.27", "0.10")
	assert money.vat_consistent("85000", "7727", "0.10")
	assert money.vat_consistent("85000", "7728", "0.10")
	assert not money.vat_consistent("85000", "7730", "0.10")
	assert not money.vat_consistent("85000", "0", "0.10")


def test_vat_consistent_custom_tolerance():
	assert money.vat_consistent("85000", "7730", "0.10", tolerance=Decimal("5"))
	assert money.vat_consistent("85000", "7727.27", "0.10", tolerance=Decimal("0"))
	assert not money.vat_consistent("85000", "7727", "0.10", tolerance=Decimal("0"))


def test_money_alias_and_quantize():
	assert money.Money is Decimal
	assert money.quantize("1.005") == Decimal("1.01")
	assert money.quantize(Decimal("2.5")) == Decimal("2.50")
	assert money.to_decimal(0.1) == Decimal("0.1")
	assert money.to_decimal("0.10") == Decimal("0.10")
