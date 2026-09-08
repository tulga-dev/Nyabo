"""Stub-only helpers: ``reset()`` builds a fresh site; the rest is introspection for tests.

Nothing here exists in real Frappe; application code must never import ``frappe._stub``.
"""

from __future__ import annotations

import json
from typing import Any

from frappe._stub.dictlike import _dict
from frappe._stub.state import DEFAULT_SITE, STUB_DIR, Local

ACCOUNT_CATEGORIES_PATH = STUB_DIR / "account_categories.json"


def reset(site: str = DEFAULT_SITE, custom_fields: bool = True) -> Local:
	"""A new empty site: metas re-read from disk, empty tables, Administrator session.

	``custom_fields=True`` merges ``nyabo_mn.setup.custom_fields.get_custom_fields()`` into
	the ERPNext metas so ``doc.nyabo_explanation = ...`` validates like on a migrated site.
	"""
	import frappe
	from frappe._stub.controllers import clear_controller_cache
	from frappe._stub.db import Database
	from frappe._stub.meta import MetaRegistry

	old = getattr(frappe, "local", None)
	if isinstance(old, Local):
		old.destroy()
	local = Local(site)
	frappe.local = local
	registry = MetaRegistry()
	registry.load()
	local.registry = registry
	local.db = Database(registry)
	clear_controller_cache()
	_seed_account_categories(local.db)
	if custom_fields:
		merge_custom_fields()
	return local


def registry() -> Any:
	import frappe

	return frappe.local.registry


def merge_custom_fields() -> dict[str, list[dict]]:
	"""Apply the app's custom fields to the metas without creating Custom Field rows."""
	from nyabo_mn.setup.custom_fields import get_custom_fields

	fields = get_custom_fields()
	reg = registry()
	for doctype, dfs in fields.items():
		meta = reg.get(doctype)
		if meta is None:
			continue
		for df in dfs:
			meta.add_custom_field(dict(df))
	return fields


def _seed_account_categories(db: Any) -> None:
	"""ERPNext ships 29 Account Categories with the Financial Report Templates; a site has them."""
	from frappe.utils.data import now_datetime

	with open(ACCOUNT_CATEGORIES_PATH, encoding="utf-8") as f:
		rows = json.load(f)
	now = now_datetime()
	for row in rows:
		name = row.get("name") or row.get("account_category_name")
		db.insert_row(
			"Account Category",
			{
				"name": name,
				"account_category_name": row.get("account_category_name") or name,
				"description": row.get("description"),
				"root_type": row.get("root_type"),
				"owner": "Administrator",
				"modified_by": "Administrator",
				"creation": now,
				"modified": now,
				"docstatus": 0,
			},
		)


def find_links_to(doctype: str, name: str) -> list[tuple[str, str, str]]:
	"""(doctype, fieldname, docname) of every row whose Link / Dynamic Link points at doctype/name."""
	import frappe

	out: list[tuple[str, str, str]] = []
	for meta in registry().metas.values():
		if meta.name == "DocType" or not frappe.db.tables.get(meta.name):
			continue
		links = [df for df in meta.get_link_fields() if df.options == doctype]
		dynamic = meta.get_dynamic_link_fields()
		if not links and not dynamic:
			continue
		for row in frappe.db.rows(meta.name):
			for df in links:
				if row.get(df.fieldname) == name:
					out.append((meta.name, df.fieldname, row["name"]))
			for df in dynamic:
				if row.get(df.options) == doctype and row.get(df.fieldname) == name:
					out.append((meta.name, df.fieldname, row["name"]))
	return out


def record_call(call: str, **kwargs: Any) -> None:
	"""Remember that ``call`` happened with ``kwargs`` (stubbed side effects: PDF, mail, sync, ...)."""
	import frappe

	frappe.local.recorded_calls.setdefault(call, []).append(_dict(kwargs))


def calls(call: str) -> list[_dict]:
	import frappe

	return list(frappe.local.recorded_calls.get(call, []))


def messages() -> list[_dict]:
	import frappe

	return list(frappe.local.message_log)
