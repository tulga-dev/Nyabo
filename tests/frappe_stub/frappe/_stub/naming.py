"""Document naming, mirrored from frappe/model/naming.py (version-16).

Order in ``set_new_name``: amended name -> single -> controller ``autoname()`` -> the
DocType's ``autoname`` option (``field:``, ``naming_series:``, ``format:``, ``.####``
series, ``hash``) -> hash. Series counters are per prefix and zero-padded to the number
of ``#`` characters, exactly like ``tabSeries``.
"""

from __future__ import annotations

import datetime
import random
import re
import string
import time
from typing import TYPE_CHECKING, Any

from frappe.exceptions import ValidationError
from frappe.utils.data import cstr, now_datetime

if TYPE_CHECKING:
	from frappe.model.document import Document

BRACED_PARAMS_PATTERN = re.compile(r"(\{[\w | #]+\})")
NAMING_SERIES_PART_TYPES = (int, str, datetime.datetime, datetime.date, datetime.time, datetime.timedelta)


def _series_store() -> dict[str, int]:
	import frappe

	return frappe.db.series


def getseries(key: str, digits: int) -> str:
	store = _series_store()
	store[key] = store.get(key, 0) + 1
	return ("%0" + str(digits) + "d") % store[key]


def get_series_current(key: str) -> int:
	return _series_store().get(key, 0)


def revert_series_if_last(key: str, name: str, doc: Any = None) -> None:
	"""Frappe decrements the counter when the deleted document was the last one of its series."""
	prefix = key.split(".#")[0].replace(".", "")
	store = _series_store()
	current = store.get(prefix)
	if current and name.endswith(str(current).zfill(len(name) - len(prefix))):
		store[prefix] = current - 1


def _generate_random_string(length: int) -> str:
	return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _get_timestamp_prefix() -> str:
	return format(int(time.time() * 10) % (36**3), "x")[-3:].lower()


def make_autoname(key: str = "", doctype: str = "", doc: Any = "", *, ignore_validate: bool = False) -> str:
	if key == "hash":
		return (_get_timestamp_prefix() + _generate_random_string(7))[:10]
	return parse_naming_series(key, doctype=doctype, doc=doc)


def parse_naming_series(
	parts: list[str] | str, doctype: str | None = None, doc: Any = None, number_generator: Any = None
) -> str:
	name = ""
	sentinel = object()
	if isinstance(parts, str):
		parts = parts.split(".")
	if not number_generator:
		number_generator = getseries
	series_set = False
	today = now_datetime()
	for e in parts:
		if not e:
			continue
		part: Any = ""
		if e.startswith("#"):
			if not series_set:
				part = number_generator(name, len(e))
				series_set = True
		elif e == "YY":
			part = today.strftime("%y")
		elif e == "MM":
			part = today.strftime("%m")
		elif e == "DD":
			part = today.strftime("%d")
		elif e == "YYYY":
			part = today.strftime("%Y")
		elif e == "JJJ":
			part = today.strftime("%j")
		elif e == "WW":
			part = today.strftime("%V")
		elif e == "timestamp":
			part = str(today)
		elif doc is not None and doc != "" and (e.startswith("{") or doc.get(e, sentinel) is not sentinel):
			e = e.replace("{", "").replace("}", "")
			part = doc.get(e)
		else:
			part = e
		if isinstance(part, str):
			name += part
		elif isinstance(part, NAMING_SERIES_PART_TYPES):
			name += cstr(part).strip()
	return name


def get_default_naming_series(doctype: str) -> str | None:
	"""First non-empty line of the naming_series field's options."""
	import frappe

	meta = frappe.get_meta(doctype)
	df = meta.get_field("naming_series")
	if df is None:
		return None
	for line in (df.options or "").split("\n"):
		if line.strip():
			return line.strip()
	return df.default or None


def set_name_by_naming_series(doc: Document) -> None:
	if not doc.get("naming_series"):
		doc.naming_series = get_default_naming_series(doc.doctype)
	if not doc.naming_series:
		raise ValidationError("Naming Series mandatory")
	doc.name = make_autoname(doc.naming_series + ".#####", "", doc)


def _field_autoname(autoname: str, doc: Document) -> str:
	fieldname = autoname[6:]
	return (cstr(doc.get(fieldname)) or "").strip()


def _format_autoname(autoname: str, doc: Document) -> str:
	autoname_value = autoname[autoname.find(":") + 1 :]

	def replace(match: re.Match) -> str:
		param = match.group()
		return parse_naming_series([param[1:-1]], doc=doc)

	return BRACED_PARAMS_PATTERN.sub(replace, autoname_value)


def set_name_from_naming_options(autoname: str, doc: Document) -> None:
	lowered = autoname.lower()
	if lowered.startswith("field:"):
		doc.name = _field_autoname(autoname, doc)
		if not doc.name:
			raise ValidationError(f"{doc.meta.get_label(autoname[6:])} is required")
	elif lowered.startswith("naming_series:"):
		set_name_by_naming_series(doc)
	elif lowered.startswith("prompt"):
		if not doc.name:
			raise ValidationError("Name is required (autoname: Prompt)")
	elif lowered.startswith("format:"):
		doc.name = _format_autoname(autoname, doc)
	elif "#" in autoname:
		doc.name = make_autoname(autoname, doc=doc)


def _set_amended_name(doc: Document) -> None:
	import frappe

	base = str(doc.amended_from).split("-")
	if base[-1].isdigit():
		base = base[:-1]
	prefix = "-".join(base)
	count = frappe.db.count(doc.doctype, {"amended_from": doc.amended_from}) + 1
	doc.name = f"{prefix}-{count}"


def set_new_name(doc: Document, set_name: str | None = None) -> None:
	doc.run_method("before_naming")
	meta = doc.meta
	autoname = meta.autoname or ""
	if set_name:
		doc.name = set_name
	elif autoname.lower() not in ("prompt", "uuid"):
		doc.name = None

	if doc.get("amended_from"):
		_set_amended_name(doc)
		if doc.name:
			return
	elif meta.issingle:
		doc.name = doc.doctype

	if not doc.name:
		doc.run_method("autoname")
	if not doc.name and autoname:
		set_name_from_naming_options(autoname, doc)
	if not doc.name:
		doc.name = make_autoname("hash", doc.doctype)
	doc.name = validate_name(doc.doctype, doc.name)


def validate_name(doctype: str, name: Any) -> str:
	if name is None or name == "":
		raise ValidationError(f"No Name Specified for {doctype}")
	name = cstr(name).strip()
	if name.startswith("New " + doctype):
		raise ValidationError(
			f"There were some errors setting the name, please contact the administrator ({name})"
		)
	return name
