from __future__ import annotations

import datetime as dt

import pytest

from nyabo_mn.core import dates
from nyabo_mn.i18n import mn


def test_weekday_short_mn_monday_to_sunday():
	monday = dt.date(2026, 9, 7)
	assert [dates.weekday_short_mn(monday + dt.timedelta(days=i)) for i in range(7)] == mn.WEEKDAYS_SHORT
	assert dates.weekday_short_mn(monday) == "Да"


def test_month_bounds_handles_leap_year_and_december():
	assert dates.month_bounds(2026, 8) == (dt.date(2026, 8, 1), dt.date(2026, 8, 31))
	assert dates.month_bounds(2028, 2) == (dt.date(2028, 2, 1), dt.date(2028, 2, 29))
	assert dates.month_bounds(2027, 2) == (dt.date(2027, 2, 1), dt.date(2027, 2, 28))
	assert dates.month_bounds(2026, 12) == (dt.date(2026, 12, 1), dt.date(2026, 12, 31))
	with pytest.raises(ValueError):
		dates.month_bounds(2026, 13)


@pytest.mark.parametrize(
	("day", "quarter"),
	[
		(dt.date(2026, 1, 1), 1),
		(dt.date(2026, 3, 31), 1),
		(dt.date(2026, 4, 1), 2),
		(dt.date(2026, 9, 8), 3),
		(dt.date(2026, 12, 31), 4),
	],
)
def test_quarter_of(day: dt.date, quarter: int):
	assert dates.quarter_of(day) == quarter


def test_quarter_bounds():
	assert dates.quarter_bounds(2026, 1) == (dt.date(2026, 1, 1), dt.date(2026, 3, 31))
	assert dates.quarter_bounds(2026, 3) == (dt.date(2026, 7, 1), dt.date(2026, 9, 30))
	assert dates.quarter_bounds(2026, 4) == (dt.date(2026, 10, 1), dt.date(2026, 12, 31))
	with pytest.raises(ValueError):
		dates.quarter_bounds(2026, 5)


def test_period_label_and_quarter_label():
	assert dates.period_label("2026-08") == "2026 оны 8-р сар"
	assert dates.period_label("2026-12") == "2026 оны 12-р сар"
	assert dates.quarter_label(2026, 3) == "2026 оны 3-р улирал"


@pytest.mark.parametrize(
	("text", "expected"),
	[("2026-08", (2026, 8)), (" 2026-8 ", (2026, 8)), ("2027-01", (2027, 1))],
)
def test_parse_period(text: str, expected: tuple[int, int]):
	assert dates.parse_period(text) == expected


@pytest.mark.parametrize("text", ["2026-13", "2026-00", "202608", "2026/08", "", "сар", "2026-08-01"])
def test_parse_period_rejects(text: str):
	with pytest.raises(ValueError):
		dates.parse_period(text)


def test_period_helpers_round_trip():
	day = dt.date(2026, 8, 15)
	assert dates.period_of(day) == "2026-08"
	assert dates.period_bounds("2026-08") == dates.month_bounds(2026, 8)
	assert dates.days_between(dt.date(2026, 8, 1), dt.date(2026, 8, 4)) == 3
	assert dates.days_between(dt.date(2026, 8, 4), dt.date(2026, 8, 1)) == 3
