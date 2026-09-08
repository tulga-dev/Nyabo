"""Install and migrate hooks (see hooks.py). Everything here must be idempotent.

Both hooks run the same steps, in this order, because a migrate is how a redeploy
reaches an existing site: custom fields (update=True), roles (fixtures, applied by
bench before this hook), the rules seed (never overwriting verified rows), ERPNext's
financial report templates (skipped with a log line when this ERPNext has none) plus
Nyabo's own re-sync of the templates it ships, the external exchange-rate provider
switched off (Nyabo records Монголбанк rates itself, ARCHITECTURE §2), and a warning per
missing site-config key.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import frappe

from nyabo_mn.config import get_settings
from nyabo_mn.log import log_error, log_event
from nyabo_mn.setup.custom_fields import (
	TEMPLATE_CHECKSUM_FIELD,
	TEMPLATE_DOCTYPE,
	ensure_custom_fields,
)

CURRENCY_EXCHANGE_SETTINGS = "Currency Exchange Settings"
TEMPLATE_DIR = ("nyabo", "financial_report_template")
# What Nyabo ships on a template row, and therefore owns. Anything else on the document
# (ERPNext's own columns, the site's) is never written or compared.
TEMPLATE_FIELDS: tuple[str, ...] = ("template_name", "report_type", "module", "disabled")


def after_install() -> None:
	_setup("install")


def after_migrate() -> None:
	_setup("migrate")


def _setup(stage: str) -> dict[str, Any]:
	report: dict[str, Any] = {}
	report["custom_fields"] = ensure_custom_fields()
	log_event(f"{stage}.custom_fields", doctypes=report["custom_fields"])
	report["seed"] = _sync_seed(stage)
	report["financial_report_templates"] = _sync_financial_report_templates(stage)
	report["shipped_templates"] = _update_shipped_templates(stage)
	report["currency_exchange_disabled"] = _disable_exchange_provider(stage)
	_warn_missing_settings()
	return report


def _sync_seed(stage: str) -> dict[str, Any]:
	from nyabo_mn.rules import seed

	counts = seed.sync()
	log_event(f"{stage}.seed", **{k.replace(" ", "_"): v for k, v in counts.items()})
	return counts


def _sync_financial_report_templates(stage: str) -> bool:
	try:
		from erpnext.accounts.doctype.financial_report_template.financial_report_template import (
			sync_financial_report_templates,
		)
	except ImportError as exc:
		log_event(f"{stage}.financial_report_templates.skipped", level="warning", error=repr(exc))
		return False
	try:
		sync_financial_report_templates()
	except Exception as exc:  # a template error must not block the whole migrate
		log_error(f"{stage}.financial_report_templates", exc)
		return False
	return True


def _update_shipped_templates(stage: str) -> dict[str, str]:
	"""``update_shipped_templates`` with the migrate's rule: a template error is logged, not raised."""
	try:
		return update_shipped_templates(stage)
	except Exception as exc:  # noqa: BLE001 - a template must not block the whole migrate
		log_error(f"{stage}.financial_report_templates.update", exc)
		return {}


# --- Nyabo's own financial report templates (F9) ------------------------------------------


def shipped_template_files() -> list[str]:
	"""Every ``nyabo_mn/nyabo/financial_report_template/<name>/<name>.json`` on disk."""
	root = frappe.get_app_path("nyabo_mn", *TEMPLATE_DIR)
	if not os.path.isdir(root):
		return []
	paths = []
	for folder in sorted(os.listdir(root)):
		path = os.path.join(root, folder, f"{folder}.json")
		if os.path.isfile(path):
			paths.append(path)
	return paths


def _clean(row: Any) -> dict[str, Any]:
	"""A child row as content only: Frappe's own columns and unset/zero fields dropped.

	Dropping falsy values makes "the JSON omits it" and "the row stores the field default"
	the same thing - every check on Financial Report Row defaults to 0 - so a document Nyabo
	wrote and the file it wrote it from hash alike.
	"""
	data = dict(row.as_dict()) if hasattr(row, "as_dict") else dict(row)
	skip = {
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"parent",
		"parentfield",
		"parenttype",
		"doctype",
		"idx",
		"docstatus",
	}
	return {k: v for k, v in sorted(data.items()) if k not in skip and v not in (None, "", 0, False)}


def template_content(data: Any) -> dict[str, Any]:
	"""The comparable content of a template, from the shipped JSON or from the live document."""
	get = data.get if hasattr(data, "get") else lambda key: getattr(data, key, None)
	return {
		"fields": {field: get(field) for field in TEMPLATE_FIELDS},
		"rows": [_clean(row) for row in (get("rows") or [])],
	}


def template_checksum(data: Any) -> str:
	payload = json.dumps(template_content(data), ensure_ascii=False, sort_keys=True, default=str)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _nyabo_owns(doc: Any, live: str) -> bool:
	"""Is this row still Nyabo's to overwrite, or has an accountant edited it?

	1. A stamp that still matches the live content: Nyabo wrote this row and nobody has
	changed it since - ours.
	2. No stamp at all and the row has never been saved by a person (``modified_by`` is
	Administrator, which is who a bench migrate runs as): a site that installed before this
	code, so adopt it and stamp it.
	3. Anything else - a stamp that no longer matches, or an unstamped row a named user has
	saved - is an accountant's work and is never touched.
	"""
	stamp = doc.get(TEMPLATE_CHECKSUM_FIELD)
	if stamp:
		return str(stamp) == live
	return (doc.get("modified_by") or "Administrator") == "Administrator"


def update_shipped_templates(stage: str) -> dict[str, str]:
	"""Re-apply the Financial Report Templates Nyabo ships; returns {template: what happened}.

	WHY this exists (F9): ERPNext's ``sync_financial_report_templates`` only inserts, so a
	correction to a shipped template - a wrong account category, a formula that double-counts
	- reached new sites and no existing one. Nyabo therefore re-writes its own templates on
	every migrate, and only its own: ownership is decided by ``_nyabo_owns`` above, and a
	template an accountant has edited is left exactly as it is (logged as ``kept``). An
	accountant who wants their own version should save it under a different name; that name
	is not one Nyabo ships, so it is never considered here at all.
	"""
	results: dict[str, str] = {}
	if not frappe.db.exists("DocType", TEMPLATE_DOCTYPE):
		return results
	for path in shipped_template_files():
		with open(path, encoding="utf-8") as fh:
			shipped = json.load(fh)
		name = shipped.get("name") or shipped.get("template_name")
		if not name:
			continue
		checksum = template_checksum(shipped)
		if not frappe.db.exists(TEMPLATE_DOCTYPE, name):
			results[name] = "missing"  # ERPNext's sync inserts; nothing to correct yet
			continue
		doc = frappe.get_doc(TEMPLATE_DOCTYPE, name)
		live = template_checksum(doc)
		if not _nyabo_owns(doc, live):
			results[name] = "kept"
			continue
		if live == checksum and doc.get(TEMPLATE_CHECKSUM_FIELD) == checksum:
			results[name] = "unchanged"
			continue
		for field in TEMPLATE_FIELDS:
			if field in shipped:
				doc.set(field, shipped[field])
		doc.set("rows", [])
		for row in shipped.get("rows") or []:
			doc.append("rows", dict(row))
		doc.set(TEMPLATE_CHECKSUM_FIELD, checksum)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_validate = True
		doc.save()
		results[name] = "updated" if live != checksum else "stamped"
	log_event(f"{stage}.financial_report_templates.updated", templates=results)
	return results


def _disable_exchange_provider(stage: str) -> bool:
	"""`Currency Exchange Settings.disabled = 1` (ARCHITECTURE §2); skipped when the Single is absent."""
	if not frappe.db.exists("DocType", CURRENCY_EXCHANGE_SETTINGS):
		log_event(f"{stage}.currency_exchange_settings.absent", level="warning")
		return False
	try:
		frappe.db.set_single_value(CURRENCY_EXCHANGE_SETTINGS, "disabled", 1)
	except Exception as exc:
		log_error(f"{stage}.currency_exchange_settings", exc)
		return False
	return True


def _warn_missing_settings() -> None:
	"""Missing secrets must not block a deploy; features check again and fail loudly when used."""
	missing = {feature: keys for feature, keys in get_settings().report().items() if keys}
	if missing:
		log_event("config.missing", level="warning", **missing)
		for feature, keys in missing.items():
			print(f"nyabo_mn: site config is missing {', '.join(keys)} (needed for {feature})")
