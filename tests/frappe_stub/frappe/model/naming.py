"""Public module path for the naming helpers (implementation lives in frappe._stub.naming)."""

from __future__ import annotations

from frappe._stub.naming import (
	get_default_naming_series,
	get_series_current,
	getseries,
	make_autoname,
	parse_naming_series,
	revert_series_if_last,
	set_name_by_naming_series,
	set_name_from_naming_options,
	set_new_name,
	validate_name,
)

__all__ = [
	"get_default_naming_series",
	"get_series_current",
	"getseries",
	"make_autoname",
	"parse_naming_series",
	"revert_series_if_last",
	"set_name_by_naming_series",
	"set_name_from_naming_options",
	"set_new_name",
	"validate_name",
]
