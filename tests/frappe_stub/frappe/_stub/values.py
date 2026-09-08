"""Value casting that mimics what MariaDB does to a Frappe column.

Documents keep whatever Python value was assigned; the table stores the typed value the
real site would hand back after ``reload()`` (dates as ``datetime.date``, numbers as
int/float, JSON columns as text, numeric NULLs as 0).
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from frappe.utils.data import cint, cstr, flt, get_datetime, getdate

TEXT_FIELDTYPES = frozenset(
	{
		"Data",
		"Link",
		"Dynamic Link",
		"Select",
		"Small Text",
		"Text",
		"Long Text",
		"Code",
		"HTML Editor",
		"Text Editor",
		"Markdown Editor",
		"Attach",
		"Attach Image",
		"Color",
		"Password",
		"Read Only",
		"Autocomplete",
		"Barcode",
		"Geolocation",
		"Icon",
		"Phone",
		"Signature",
		"JSON",
		"Time",
	}
)
FLOAT_FIELDTYPES = frozenset({"Currency", "Float", "Percent", "Duration", "Rating"})
INT_FIELDTYPES = frozenset({"Int", "Long Int", "Check"})
DATE_MIN = datetime.date(1, 1, 1)
DATETIME_MIN = datetime.datetime(1, 1, 1)


def cast_for_storage(fieldtype: str | None, value: Any) -> Any:
	"""What the column holds after an insert/update. ``None`` fieldtype = default field (kept as is)."""
	if fieldtype is None:
		return value
	if fieldtype in INT_FIELDTYPES:
		return cint(value)
	if fieldtype in FLOAT_FIELDTYPES:
		return flt(value)
	if fieldtype == "Date":
		return getdate(value) if value not in (None, "") else None
	if fieldtype == "Datetime":
		return get_datetime(value) if value not in (None, "") else None
	if fieldtype == "JSON":
		if value is None:
			return None
		if isinstance(value, (dict, list)):
			return json.dumps(value, ensure_ascii=False)
		return cstr(value)
	if fieldtype in TEXT_FIELDTYPES:
		return None if value is None else cstr(value)
	return value


def cast_for_compare(fieldtype: str | None, value: Any) -> Any:
	"""Filter values get the column's type so ``"2026-01-01" <= date(2026, 1, 2)`` works."""
	if value is None:
		return None
	if isinstance(value, (list, tuple, set)):
		return [cast_for_compare(fieldtype, v) for v in value]
	if fieldtype is None:
		return value
	if fieldtype in INT_FIELDTYPES:
		return cint(value) if not isinstance(value, str) or value.strip() else 0
	if fieldtype in FLOAT_FIELDTYPES:
		return flt(value)
	if fieldtype == "Date":
		return getdate(value) if value != "" else DATE_MIN
	if fieldtype == "Datetime":
		return get_datetime(value) if value != "" else DATETIME_MIN
	if fieldtype in TEXT_FIELDTYPES:
		return cstr(value)
	return value


def null_fallback(fieldtype: str | None) -> Any:
	"""Frappe wraps nullable columns in ``ifnull(col, fallback)`` (frappe/model/db_query.py)."""
	if fieldtype in INT_FIELDTYPES or fieldtype in FLOAT_FIELDTYPES:
		return 0
	if fieldtype == "Date":
		return DATE_MIN
	if fieldtype == "Datetime":
		return DATETIME_MIN
	return ""


def is_empty(value: Any) -> bool:
	"""Frappe's notion of "not set" for mandatory checks: None, '' or an empty list."""
	return value is None or value == "" or (isinstance(value, list) and not value)
