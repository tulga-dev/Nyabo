"""Period helpers and Mongolian date labels.

Every accounting lookup in Nyabo is keyed by the transaction date, and the month-end
flow talks in "2026-08" periods. These helpers are the only place that knows how a
period string, a quarter and a Mongolian month label relate, so the Telegram handlers
and the reports agree.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re

from nyabo_mn.i18n import mn

_PERIOD = re.compile(r"^(\d{4})-(\d{1,2})$")


def weekday_short_mn(day: dt.date) -> str:
	"""Two-letter Mongolian weekday (Monday = Да), used in receipt card titles."""
	return mn.WEEKDAYS_SHORT[day.weekday()]


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
	"""First and last day of the month (inclusive)."""
	if not 1 <= month <= 12:
		raise ValueError(f"month out of range: {month}")
	last = calendar.monthrange(year, month)[1]
	return dt.date(year, month, 1), dt.date(year, month, last)


def quarter_of(day: dt.date) -> int:
	"""Calendar quarter 1..4 (fiscal year = calendar year, Law on Accounting art. 9)."""
	return (day.month - 1) // 3 + 1


def quarter_bounds(year: int, quarter: int) -> tuple[dt.date, dt.date]:
	"""First and last day of the quarter (inclusive)."""
	if not 1 <= quarter <= 4:
		raise ValueError(f"quarter out of range: {quarter}")
	first_month = (quarter - 1) * 3 + 1
	start = dt.date(year, first_month, 1)
	end = month_bounds(year, first_month + 2)[1]
	return start, end


def parse_period(text: str) -> tuple[int, int]:
	"""'2026-08' -> (2026, 8). Raises ValueError on anything else (the handler shows usage)."""
	match = _PERIOD.match((text or "").strip())
	if not match:
		raise ValueError(f"not a YYYY-MM period: {text!r}")
	year, month = int(match.group(1)), int(match.group(2))
	if not 1 <= month <= 12:
		raise ValueError(f"month out of range in period: {text!r}")
	return year, month


def period_of(day: dt.date) -> str:
	"""The 'YYYY-MM' period a date belongs to."""
	return f"{day.year:04d}-{day.month:02d}"


def period_bounds(text: str) -> tuple[dt.date, dt.date]:
	"""Month bounds of a 'YYYY-MM' period."""
	year, month = parse_period(text)
	return month_bounds(year, month)


def period_label(text: str) -> str:
	"""'2026-08' -> '2026 оны 8-р сар'."""
	year, month = parse_period(text)
	return mn.PERIOD_LABEL.format(year=year, month=mn.MONTHS[month - 1])


def quarter_label(year: int, quarter: int) -> str:
	"""(2026, 3) -> '2026 оны 3-р улирал'."""
	if not 1 <= quarter <= 4:
		raise ValueError(f"quarter out of range: {quarter}")
	return mn.QUARTER_LABEL.format(year=year, quarter=quarter)


def days_between(a: dt.date, b: dt.date) -> int:
	"""Absolute number of days between two dates."""
	return abs((a - b).days)
