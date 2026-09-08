"""``frappe.utils``: the data helpers plus the site-path / files helpers the app calls.

Everything in ``frappe.utils.data`` is re-exported (``from frappe.utils import getdate``
works). The site paths point at the per-reset temporary directory so File contents can be
written and read back like on a bench.
"""

from __future__ import annotations

import os
from typing import Any

from frappe.utils.data import *  # noqa: F401,F403 - re-export like frappe/utils/__init__.py
from frappe.utils.data import get_datetime, get_traceback  # noqa: F401  (explicit for type checkers)


def get_site_path(*joins: str) -> str:
	import frappe

	return os.path.join(frappe.local.site_path, *joins)


def get_site_base_path() -> str:
	import frappe

	return frappe.local.site_path


def get_bench_path() -> str:
	import frappe

	return frappe.local.sites_path


def get_files_path(*path: str, is_private: bool = False) -> str:
	return get_site_path("private" if is_private else "public", "files", *path)


def get_request_site_address(full_address: bool = False) -> str:
	from frappe.utils.data import get_url

	return get_url(full_address=full_address)


def get_hook_method(hook_name: str, fallback: Any = None) -> Any:
	import frappe

	methods = frappe.get_hooks(hook_name)
	if methods:
		return frappe.get_attr(methods[0])
	return fallback


def call_hook_method(hook: str, *args: Any, **kwargs: Any) -> Any:
	import frappe

	out = None
	for method in frappe.get_hooks(hook):
		out = frappe.get_attr(method)(*args, **kwargs) or out
	return out


def update_progress_bar(txt: str, i: int, l: int, absolute: bool = False) -> None:  # noqa: E741 - Frappe signature
	return None


def get_request_session(max_retries: int = 5) -> Any:
	raise NotImplementedError("frappe stub: no HTTP sessions in tests; inject a client instead")


def validate_url(txt: Any, throw: bool = False, valid_schemes: Any = None) -> bool:  # noqa: A002 - Frappe signature
	import re

	ok = bool(re.match(r"^https?://[^\s]+$", str(txt or "")))
	if not ok and throw:
		from frappe.exceptions import ValidationError

		raise ValidationError(f"{txt} is not a valid URL")
	return ok


def cast_fieldtype(fieldtype: str, value: Any) -> Any:
	from frappe.utils.data import cast

	return cast(fieldtype, value)
