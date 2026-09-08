"""Deterministic checks on a ProposedEntry before it becomes a card.

The model proposes an account and an explanation; this module is the part that does
not trust it. Every problem is a Mongolian sentence the card can show, so the
accountant sees why a proposal is held back rather than a stack trace.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from nyabo_mn.core.models import ProposedEntry
from nyabo_mn.core.money import ZERO, fmt_mnt, to_decimal, vat_consistent
from nyabo_mn.i18n import mn


def validate_entry(
	entry: ProposedEntry,
	leaf_codes: Iterable[str],
	vat_rate: Decimal | float | str,
	*,
	group_codes: Iterable[str] | None = None,
	vat_tolerance: Decimal = Decimal("1"),
) -> list[str]:
	"""Return the list of problems (empty when the entry may be posted).

	Checks: at least two lines, no zero or negative or two-sided lines, every account
	is a leaf of the chart, debits equal credits, and when the VAT is withheld the
	printed VAT agrees with the rate within `vat_tolerance` tögrög.
	"""
	problems: list[str] = []
	leaves = set(leaf_codes)
	groups = set(group_codes) if group_codes is not None else None

	if len(entry.lines) < 2:
		problems.append(mn.MSG_ENTRY_TOO_FEW_LINES)

	for line in entry.lines:
		if line.debit < 0 or line.credit < 0:
			problems.append(mn.MSG_ENTRY_NEGATIVE_AMOUNT.format(account=line.account_code))
		elif line.debit == 0 and line.credit == 0:
			problems.append(mn.MSG_ENTRY_ZERO_LINE.format(account=line.account_code))
		elif line.debit != 0 and line.credit != 0:
			problems.append(mn.MSG_ENTRY_LINE_BOTH_SIDES.format(account=line.account_code))
		if line.account_code not in leaves:
			if groups is not None and line.account_code not in groups:
				problems.append(mn.MSG_ACCOUNT_UNKNOWN.format(account=line.account_code))
			else:
				problems.append(mn.MSG_ACCOUNT_IS_GROUP.format(account=line.account_code))

	debit, credit = entry.total_debit, entry.total_credit
	if debit != credit:
		problems.append(mn.MSG_ENTRY_UNBALANCED.format(debit=fmt_mnt(debit), credit=fmt_mnt(credit)))

	if entry.vat_treatment == "withheld":
		rate = to_decimal(vat_rate)
		if entry.total <= ZERO or not vat_consistent(entry.total, entry.vat_amount, rate, vat_tolerance):
			problems.append(
				mn.MSG_VAT_MATH_INCONSISTENT.format(vat=fmt_mnt(entry.vat_amount), rate=_percent(rate))
			)
	return problems


def _percent(rate: Decimal) -> str:
	"""0.10 -> '10', 0.115 -> '11.5' (rates are fractions in the seed)."""
	value = (rate * 100).normalize()
	text = format(value, "f")
	return text.rstrip("0").rstrip(".") if "." in text else text
