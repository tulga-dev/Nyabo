"""``frappe.get_hooks`` / ``frappe.get_doc_hooks`` from the installed apps' ``hooks.py``.

Frappe folds every app's hooks module into one ``_dict``: scalars become one-element
lists, lists are concatenated and dicts are merged recursively (frappe/__init__.py
``_load_app_hooks`` / ``append_hook``). ERPNext's period-lock ``doc_events`` therefore
sit next to Nyabo's own handlers, keyed by a tuple of doctypes that ``get_doc_hooks``
expands. ``temporary_hooks`` lets a test layer extra hooks on top for a ``with`` block.
"""

from __future__ import annotations

import importlib
import types
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from frappe._stub.dictlike import _dict

# Order matters: later apps' doc_events run after earlier ones, as `installed_apps` order does.
INSTALLED_APPS = ("frappe", "erpnext", "nyabo_mn")
HOOK_MODULES = {"erpnext": "erpnext.hooks", "nyabo_mn": "nyabo_mn.hooks"}


def _read_hooks_module(module: types.ModuleType) -> dict[str, Any]:
	out: dict[str, Any] = {}
	for key in dir(module):
		if key.startswith("_"):
			continue
		value = getattr(module, key)
		if isinstance(value, (types.ModuleType, types.FunctionType, type)):
			continue
		out[key] = value
	return out


def append_hook(target: dict, key: Any, value: Any) -> None:
	"""Mirror of frappe.append_hook: dicts merge, everything else accumulates in a list."""
	if isinstance(value, dict):
		target.setdefault(key, {})
		for inner_key, inner_value in value.items():
			append_hook(target[key], inner_key, inner_value)
	else:
		target.setdefault(key, [])
		if isinstance(value, (list, tuple)):
			target[key].extend(value)
		else:
			target[key].append(value)


def load_hooks(extra: list[dict] | None = None) -> _dict:
	hooks: dict[str, Any] = {}
	for app in INSTALLED_APPS:
		module_name = HOOK_MODULES.get(app)
		if not module_name:
			continue
		module = importlib.import_module(module_name)
		for key, value in _read_hooks_module(module).items():
			append_hook(hooks, key, value)
	for override in extra or []:
		for key, value in override.items():
			append_hook(hooks, key, value)
	return _dict(hooks)


def expand_doc_events(doc_events: dict[Any, Any]) -> dict[str, dict[str, list[str]]]:
	"""Tuple keys (ERPNext's ``tuple(period_closing_doctypes)``) become one entry per doctype."""
	out: dict[str, dict[str, list[str]]] = {}
	for key, value in doc_events.items():
		doctypes = key if isinstance(key, tuple) else (key,)
		for doctype in doctypes:
			append_hook(out, doctype, value)
	return out


def get_hooks(hook: str | None = None, default: Any = "_KEEP_DEFAULT_LIST", app_name: str | None = None) -> Any:
	import frappe

	local = frappe.local
	if app_name:
		module_name = HOOK_MODULES.get(app_name)
		if not module_name:
			hooks = _dict()
		else:
			hooks = _dict()
			for key, value in _read_hooks_module(importlib.import_module(module_name)).items():
				append_hook(hooks, key, value)
	else:
		if local.hooks_cache is None:
			local.hooks_cache = load_hooks(local.hooks_overrides)
		hooks = local.hooks_cache
	if hook is None:
		return hooks
	if default == "_KEEP_DEFAULT_LIST":
		default = []
	return hooks.get(hook, default)


def get_doc_hooks() -> dict[str, dict[str, list[str]]]:
	import frappe

	local = frappe.local
	if local.doc_events_hooks is None:
		local.doc_events_hooks = expand_doc_events(get_hooks("doc_events", {}))
	return local.doc_events_hooks


def clear_hooks_cache() -> None:
	import frappe

	frappe.local.hooks_cache = None
	frappe.local.doc_events_hooks = None


@contextmanager
def temporary_hooks(replace: bool = False, **hooks: Any) -> Iterator[None]:
	"""Add (or, with ``replace=True``, substitute) hooks for the duration of the block.

	``replace=True`` drops every app's hooks and uses only the given ones: the way to test
	a document flow while the real handlers of another module are not written yet.
	"""
	import frappe

	local = frappe.local
	saved = list(local.hooks_overrides)
	saved_modules = dict(HOOK_MODULES)
	try:
		if replace:
			HOOK_MODULES.clear()
		local.hooks_overrides.append(hooks)
		clear_hooks_cache()
		yield
	finally:
		HOOK_MODULES.clear()
		HOOK_MODULES.update(saved_modules)
		local.hooks_overrides = saved
		clear_hooks_cache()
