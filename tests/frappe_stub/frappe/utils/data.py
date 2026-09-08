"""Pure-Python re-implementations of the frappe.utils.data helpers application code uses.

Semantics follow frappe/utils/data.py (version-16) where they matter to tests: getdate
accepts str/date/datetime/None, flt/cint never raise on garbage, add_months clips to the
month end, get_first_day/get_last_day return dates. Nothing here touches a database.
"""

from __future__ import annotations

import calendar
import datetime
import hashlib
import html
import math
import random
import re
import string
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Any

DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


# --- dates -------------------------------------------------------------------------------


def _parse_date_string(text: str) -> datetime.date:
	text = text.strip()
	for fmt in (
		"%Y-%m-%d",
		"%Y-%m-%d %H:%M:%S.%f",
		"%Y-%m-%d %H:%M:%S",
		"%Y-%m-%dT%H:%M:%S",
		"%d-%m-%Y",
		"%Y/%m/%d",
	):
		try:
			return datetime.datetime.strptime(text[:26], fmt).date()
		except ValueError:
			continue
	return datetime.datetime.fromisoformat(text).date()


def getdate(string_date: Any = None, parse_day_first: bool = False) -> datetime.date | None:
	"""``None``/'' -> today (like Frappe); dates pass through; datetimes lose their time."""
	if string_date is None or string_date == "":
		return nowdate_as_date()
	if isinstance(string_date, datetime.datetime):
		return string_date.date()
	if isinstance(string_date, datetime.date):
		return string_date
	if isinstance(string_date, str):
		if parse_day_first:
			try:
				return datetime.datetime.strptime(string_date.strip()[:10], "%d-%m-%Y").date()
			except ValueError:
				pass
		return _parse_date_string(string_date)
	raise TypeError(f"getdate() cannot convert {type(string_date).__name__}: {string_date!r}")


def get_datetime(datetime_str: Any = None) -> datetime.datetime | None:
	if datetime_str is None or datetime_str == "":
		return now_datetime()
	if isinstance(datetime_str, datetime.datetime):
		return datetime_str
	if isinstance(datetime_str, datetime.date):
		return datetime.datetime.combine(datetime_str, datetime.time())
	if isinstance(datetime_str, str):
		text = datetime_str.strip()
		for fmt in (
			"%Y-%m-%d %H:%M:%S.%f",
			"%Y-%m-%d %H:%M:%S",
			"%Y-%m-%dT%H:%M:%S",
			"%Y-%m-%d %H:%M",
			"%Y-%m-%d",
		):
			try:
				return datetime.datetime.strptime(text, fmt)
			except ValueError:
				continue
		return datetime.datetime.fromisoformat(text)
	raise TypeError(f"get_datetime() cannot convert {type(datetime_str).__name__}: {datetime_str!r}")


def get_datetime_str(value: Any) -> str:
	return get_datetime(value).strftime(DATETIME_FORMAT)


def get_date_str(value: Any) -> str:
	return getdate(value).strftime(DATE_FORMAT)


def get_time(value: Any) -> datetime.time:
	if isinstance(value, datetime.time):
		return value
	if isinstance(value, datetime.datetime):
		return value.time()
	if isinstance(value, datetime.timedelta):
		return (datetime.datetime.min + value).time()
	return datetime.time.fromisoformat(str(value))


def now_datetime() -> datetime.datetime:
	return datetime.datetime.now()


def nowdate_as_date() -> datetime.date:
	return datetime.date.today()


def now() -> str:
	return now_datetime().strftime(DATETIME_FORMAT)


def nowdate() -> str:
	return nowdate_as_date().strftime(DATE_FORMAT)


def today() -> str:
	return nowdate()


def nowtime() -> str:
	return now_datetime().strftime("%H:%M:%S.%f")


def get_system_timezone() -> str:
	return "Asia/Ulaanbaatar"


def convert_utc_to_system_timezone(value: datetime.datetime) -> datetime.datetime:
	return value


def add_to_date(
	date: Any,
	years: int = 0,
	months: int = 0,
	weeks: int = 0,
	days: int = 0,
	hours: int = 0,
	minutes: int = 0,
	seconds: int = 0,
	as_string: bool = False,
	as_datetime: bool = False,
) -> Any:
	"""Same rules as Frappe (which uses dateutil.relativedelta): months clip to the month end."""
	is_datetime = isinstance(date, datetime.datetime) or (isinstance(date, str) and " " in date.strip())
	value = (
		get_datetime(date) if (is_datetime or hours or minutes or seconds or as_datetime) else getdate(date)
	)
	if years or months:
		total = value.month - 1 + months + 12 * years
		year = value.year + total // 12
		month = total % 12 + 1
		day = min(value.day, calendar.monthrange(year, month)[1])
		value = value.replace(year=year, month=month, day=day)
	value = value + datetime.timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)
	if as_string:
		return (
			value.strftime(DATETIME_FORMAT)
			if isinstance(value, datetime.datetime)
			else value.strftime(DATE_FORMAT)
		)
	return value


def add_days(date: Any, days: int) -> Any:
	return add_to_date(date, days=days)


def add_months(date: Any, months: int) -> Any:
	return add_to_date(date, months=months)


def add_years(date: Any, years: int) -> Any:
	return add_to_date(date, years=years)


def date_diff(string_ed_date: Any, string_st_date: Any) -> int:
	return (getdate(string_ed_date) - getdate(string_st_date)).days


def month_diff(string_ed_date: Any, string_st_date: Any) -> int:
	ed, st = getdate(string_ed_date), getdate(string_st_date)
	return (ed.year - st.year) * 12 + ed.month - st.month + 1


def time_diff_in_seconds(string_ed_date: Any, string_st_date: Any) -> float:
	return (get_datetime(string_ed_date) - get_datetime(string_st_date)).total_seconds()


def get_first_day(dt: Any, d_years: int = 0, d_months: int = 0, as_str: bool = False) -> Any:
	value = getdate(dt)
	total = value.month - 1 + d_months + 12 * d_years
	first = datetime.date(value.year + total // 12, total % 12 + 1, 1)
	return first.strftime(DATE_FORMAT) if as_str else first


def get_last_day(dt: Any) -> datetime.date:
	value = getdate(dt)
	return datetime.date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def get_quarter_start(dt: Any, as_str: bool = False) -> Any:
	value = getdate(dt)
	start = datetime.date(value.year, 3 * ((value.month - 1) // 3) + 1, 1)
	return start.strftime(DATE_FORMAT) if as_str else start


def get_year_start(dt: Any, as_str: bool = False) -> Any:
	value = getdate(dt)
	start = datetime.date(value.year, 1, 1)
	return start.strftime(DATE_FORMAT) if as_str else start


def get_year_ending(dt: Any) -> datetime.date:
	return datetime.date(getdate(dt).year, 12, 31)


_JAVA_TO_STRFTIME = (
	("yyyy", "%Y"),
	("yy", "%y"),
	("MM", "%m"),
	("dd", "%d"),
	("HH", "%H"),
	("mm", "%M"),
	("ss", "%S"),
)


def formatdate(string_date: Any = "", format_string: str | None = None) -> str:
	"""Frappe formats with the site's date format (default dd-mm-yyyy) using Java-style patterns."""
	if string_date in (None, ""):
		return ""
	value = getdate(string_date)
	pattern = format_string or "dd-MM-yyyy"
	for java, py in _JAVA_TO_STRFTIME:
		pattern = pattern.replace(java, py)
	return value.strftime(pattern)


def format_datetime(datetime_string: Any, format_string: str | None = None) -> str:
	if datetime_string in (None, ""):
		return ""
	value = get_datetime(datetime_string)
	pattern = format_string or "dd-MM-yyyy HH:mm:ss"
	for java, py in _JAVA_TO_STRFTIME:
		pattern = pattern.replace(java, py)
	return value.strftime(pattern)


def format_date(*args: Any, **kwargs: Any) -> str:
	return formatdate(*args, **kwargs)


def pretty_date(iso_datetime: Any) -> str:
	return format_datetime(iso_datetime)


# --- numbers -------------------------------------------------------------------------------


def _rounded(value: float, precision: int | None, rounding_method: str | None) -> float:
	if precision is None:
		return value
	method = ROUND_HALF_EVEN if rounding_method == "Banker's Rounding" else ROUND_HALF_UP
	quantum = Decimal(1).scaleb(-int(precision))
	return float(Decimal(repr(value)).quantize(quantum, rounding=method))


def flt(s: Any, precision: int | None = None, rounding_method: str | None = None) -> float:
	"""Never raises: garbage -> 0.0, like Frappe."""
	if isinstance(s, str):
		s = s.replace(",", "").strip()
	try:
		num = float(s or 0)
	except (ValueError, TypeError):
		num = 0.0
	if math.isnan(num):
		num = 0.0
	return _rounded(num, precision, rounding_method)


def cint(s: Any, default: int = 0) -> int:
	if s is None:
		return default
	if isinstance(s, bool):
		return int(s)
	try:
		return int(float(str(s).strip() or 0))
	except (ValueError, TypeError):
		return default


def cstr(s: Any, encoding: str = "utf-8") -> str:
	if s is None:
		return ""
	if isinstance(s, bytes):
		return s.decode(encoding)
	return str(s)


def sbool(x: Any) -> Any:
	if isinstance(x, str):
		if x.lower() in ("true", "1"):
			return True
		if x.lower() in ("false", "0"):
			return False
	return x


def rounded(num: float, precision: int = 0, rounding_method: str | None = None) -> float:
	return _rounded(flt(num), precision, rounding_method)


def round_based_on_smallest_currency_fraction(value: float, currency: str, precision: int = 2) -> float:
	return rounded(value, precision)


def fmt_money(
	amount: Any, precision: int | None = None, currency: str | None = None, format: str | None = None
) -> str:  # noqa: A002
	"""``#,###.##`` with the currency symbol as a suffix when one is given (Frappe uses the Currency doc)."""
	if precision is None:
		precision = 2
	value = flt(amount, precision)
	text = f"{value:,.{precision}f}"
	if currency:
		text = f"{text} {currency}"
	return text


def money_in_words(
	number: Any, main_currency: str | None = None, fraction_currency: str | None = None
) -> str:
	raise NotImplementedError(
		"frappe stub: money_in_words is not implemented (Mongolian number words are not in Frappe)"
	)


def get_number_format_info(number_format: str) -> tuple[str, str, int]:
	return (",", ".", 2)


# --- strings -------------------------------------------------------------------------------


def random_string(length: int) -> str:
	return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def sha256_hash(*args: Any) -> str:
	hasher = hashlib.sha256()
	for arg in args:
		hasher.update(arg if isinstance(arg, bytes) else cstr(arg).encode("utf-8"))
	return hasher.hexdigest()


def md5_hash(*args: Any) -> str:
	hasher = hashlib.md5()
	for arg in args:
		hasher.update(arg if isinstance(arg, bytes) else cstr(arg).encode("utf-8"))
	return hasher.hexdigest()


def escape_html(text: Any) -> str:
	return html.escape(cstr(text), quote=True)


def strip_html(text: Any) -> str:
	return re.sub(r"<[^>]*>", "", cstr(text))


def strip(value: Any, chars: str | None = None) -> str:
	return cstr(value).strip(chars)


def cast(fieldtype: str, value: Any = None) -> Any:
	if fieldtype in ("Currency", "Float", "Percent"):
		return flt(value)
	if fieldtype in ("Int", "Check"):
		return cint(value)
	if fieldtype == "Date":
		return getdate(value) if value else None
	if fieldtype == "Datetime":
		return get_datetime(value) if value else None
	return cstr(value) if value is not None else None


def comma_and(some_list: Any, add_quotes: bool = True) -> str:
	return comma_sep(some_list, "and", add_quotes)


def comma_or(some_list: Any, add_quotes: bool = True) -> str:
	return comma_sep(some_list, "or", add_quotes)


def comma_sep(some_list: Any, pattern: str, add_quotes: bool = True) -> str:
	if isinstance(some_list, (list, tuple)):
		items = [f"'{x}'" if add_quotes else cstr(x) for x in some_list]
		if len(items) == 1:
			return items[0]
		if not items:
			return ""
		return ", ".join(items[:-1]) + f" {pattern} " + items[-1]
	return cstr(some_list)


def unique(seq: Any) -> list:
	seen: set = set()
	out = []
	for item in seq:
		if item not in seen:
			seen.add(item)
			out.append(item)
	return out


def get_url(uri: str | None = None, full_address: bool = False) -> str:
	base = "http://test.localhost"
	if uri:
		return base + ("" if uri.startswith("/") else "/") + uri
	return base


def get_link_to_form(doctype: str, name: Any, label: str | None = None) -> str:
	return f'<a href="/app/{doctype.lower().replace(" ", "-")}/{name}">{label or name}</a>'


def get_url_to_form(doctype: str, name: Any) -> str:
	return get_url(f"/app/{doctype.lower().replace(' ', '-')}/{name}")


def validate_email_address(email_str: Any, throw: bool = False) -> str:
	email = cstr(email_str).strip()
	if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
		return email
	if throw:
		from frappe.exceptions import InvalidEmailAddressError

		raise InvalidEmailAddressError(f"{email_str} is not a valid Email Address")
	return ""


def is_html(text: Any) -> bool:
	return bool(re.search(r"<[a-z][\s\S]*>", cstr(text), re.IGNORECASE))


def to_markdown(html_text: Any) -> str:
	return strip_html(html_text)


def md_to_html(markdown_text: Any) -> str:
	return cstr(markdown_text)


def get_fullname(user: str | None = None) -> str:
	return cstr(user)


def encode(obj: Any, encoding: str = "utf-8") -> Any:
	return obj


def is_number(text: Any) -> bool:
	return bool(_NUMBER.match(cstr(text).strip()))


def get_timespan_date_range(timespan: str) -> tuple[datetime.date, datetime.date]:
	raise NotImplementedError("frappe stub: get_timespan_date_range is not implemented")


def json_default(obj: Any) -> Any:
	"""``json.dumps(default=...)`` used by frappe.as_json: dates, Decimals and documents."""
	if isinstance(obj, (datetime.date, datetime.datetime, datetime.time, datetime.timedelta)):
		return str(obj)
	if isinstance(obj, Decimal):
		return float(obj)
	if isinstance(obj, (set, frozenset)):
		return list(obj)
	if hasattr(obj, "as_dict"):
		return obj.as_dict()
	if isinstance(obj, bytes):
		return obj.decode("utf-8", errors="replace")
	raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def get_traceback(with_context: bool = False) -> str:
	import traceback

	return traceback.format_exc()


def get_timedelta(time: Any = None) -> datetime.timedelta | None:
	if time is None:
		return None
	if isinstance(time, datetime.timedelta):
		return time
	parsed = time if isinstance(time, datetime.time) else get_time(time)
	return datetime.timedelta(
		hours=parsed.hour, minutes=parsed.minute, seconds=parsed.second, microseconds=parsed.microsecond
	)
