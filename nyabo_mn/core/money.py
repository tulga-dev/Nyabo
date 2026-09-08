"""Money as Decimal, never float.

Tögrög amounts are stored and compared as Decimal quantised to 0.01 so that a receipt
total, a VAT split and a bank line add up exactly. Floats would drift by a tögrög on
sums of many lines, and a one-tögrög difference is exactly what the reconciliation
matcher treats as a mismatch.

Rates are fractions (0.10 = 10%) to match the unit used by the tax-parameter seed;
ERPNext's own templates want percent, and the conversion happens at that boundary,
never here.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from nyabo_mn.i18n import mn

Money = Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

_CURRENCY_MARKS = re.compile(r"[₮₮]|MNT|mnt|төг(?:рөг)?\.?", re.UNICODE)
_SPACES = re.compile(r"[\s   ']")
_NUMBER = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


class MoneyParseError(ValueError):
	"""Raised when a string cannot be read as a tögrög amount.

	Carries a Mongolian message so a Telegram handler can show it as is.
	"""

	def __init__(self, text: str):
		super().__init__(f"cannot parse money: {text!r}")
		self.text = text
		self.message_mn = mn.MSG_MONEY_UNPARSEABLE.format(text=text)


def quantize(value: Decimal | int | str) -> Decimal:
	"""Round to 0.01 with ROUND_HALF_UP (the rounding accountants expect, not banker's)."""
	return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_decimal(value: Decimal | int | float | str) -> Decimal:
	"""Coerce a rate or amount to Decimal without going through float precision loss.

	Floats are converted via str() so 0.1 becomes Decimal("0.1"), not the binary expansion.
	"""
	if isinstance(value, Decimal):
		return value
	if isinstance(value, float):
		return Decimal(str(value))
	return Decimal(value)


def parse_mnt(text: str | int | float | Decimal) -> Decimal:
	"""Read amounts as receipts and statements print them: "85 000₮", "85,000.00", "(1 500)".

	Rules: currency marks and thin/no-break spaces are dropped; parentheses or a leading
	minus mean negative; when both "," and "." occur the last one is the decimal separator;
	a lone comma is a thousands separator only when every group after it has three digits,
	otherwise it is the decimal separator (Mongolian exports use both conventions).
	"""
	if isinstance(text, (int, Decimal)):
		return quantize(text)
	if isinstance(text, float):
		return quantize(to_decimal(text))
	raw = str(text)
	s = _CURRENCY_MARKS.sub("", raw)
	s = _SPACES.sub("", s).strip()
	negative = False
	if s.startswith("(") and s.endswith(")"):
		negative = True
		s = s[1:-1]
	if s.startswith("-") or s.startswith("−"):
		negative = True
		s = s[1:]
	elif s.startswith("+"):
		s = s[1:]
	s = s.rstrip("-")  # trailing minus, seen in some bank exports
	if not s:
		raise MoneyParseError(raw)

	if "," in s and "." in s:
		if s.rfind(",") > s.rfind("."):
			s = s.replace(".", "").replace(",", ".")
		else:
			s = s.replace(",", "")
	elif "," in s:
		head, *groups = s.split(",")
		if groups and all(len(g) == 3 and g.isdigit() for g in groups) and head.isdigit():
			s = head + "".join(groups)
		elif len(groups) == 1:
			s = head + "." + groups[0]
		else:
			raise MoneyParseError(raw)

	if not _NUMBER.match(s):
		raise MoneyParseError(raw)
	try:
		value = Decimal(s)
	except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
		raise MoneyParseError(raw) from exc
	if negative:
		value = -value
	return quantize(value)


def fmt_mnt(value: Decimal | int | str) -> str:
	"""Format for cards: "85 000", "85 000.50", "-1 500". No currency sign (the card adds ₮)."""
	amount = quantize(to_decimal(value)) if not isinstance(value, Decimal) else quantize(value)
	sign = "-" if amount < 0 else ""
	amount = abs(amount)
	whole = int(amount)
	fraction = amount - whole
	whole_text = f"{whole:,}".replace(",", " ")
	if fraction == 0:
		return f"{sign}{whole_text}"
	return f"{sign}{whole_text}.{str(fraction)[2:]}"


def vat_from_gross(gross: Decimal | int | str, rate: Decimal | float | str) -> Decimal:
	"""VAT contained in a VAT-inclusive amount: gross * r / (1 + r), ROUND_HALF_UP to 0.01.

	Ebarimt receipts print the gross and the VAT; this is what the receipt should show
	when the seller is a VAT payer at the given rate.
	"""
	g = to_decimal(gross)
	r = to_decimal(rate)
	return quantize(g * r / (Decimal(1) + r))


def vat_from_net(net: Decimal | int | str, rate: Decimal | float | str) -> Decimal:
	"""VAT on a VAT-exclusive amount: net * r, ROUND_HALF_UP to 0.01."""
	return quantize(to_decimal(net) * to_decimal(rate))


def net_from_gross(gross: Decimal | int | str, rate: Decimal | float | str) -> Decimal:
	"""Gross minus the VAT it contains; the two parts always sum back to gross."""
	g = quantize(to_decimal(gross))
	return g - vat_from_gross(g, rate)


def vat_consistent(
	gross: Decimal | int | str,
	vat: Decimal | int | str,
	rate: Decimal | float | str,
	tolerance: Decimal = Decimal("1"),
) -> bool:
	"""True when the printed VAT is within `tolerance` tögrög of gross * r / (1 + r).

	Receipts round per line, so a one-tögrög difference on the total is normal; more than
	that means the seller is not a VAT payer, the rate differs, or the extraction is wrong.
	"""
	expected = vat_from_gross(gross, rate)
	return abs(quantize(to_decimal(vat)) - expected) <= to_decimal(tolerance)
