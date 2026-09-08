"""Load the JSON seed into the rules DocTypes (docs/ARCHITECTURE.md §9, docs/seed/README.md).

`sync()` runs on install and after every migrate. It upserts by name so a redeploy
brings new rows and corrected values, and it never touches a row an admin has marked
`verified = 1`: that flag records a human comparison with the primary legal text, and
a code push must not silently undo it. `force=True` is the explicit way to reseed.

Company-scoped seed (`rules_default.json`, `aliases_v1_to_v03.json`) is applied at
provisioning by `seed_default_rules` / `rules.aliases.seed_v1_aliases`, because those
DocTypes need a company. The charts and `code_roles.json` are read from the files.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import frappe

from nyabo_mn.log import log_event
from nyabo_mn.nyabo.seed import load_seed

TAX_PARAMETER = "Nyabo Tax Parameter"
POSTING_PATTERN = "Nyabo Posting Pattern"
BANK_LAYOUT = "Nyabo Bank Layout"
RULE = "Nyabo Rule"

PATTERN_LINE_FIELDS = (
	"side",
	"account_class",
	"class_name_mn",
	"sub_account_mn",
	"amount_kind",
	"role",
	"optional",
	"v1_code_hint",
	"v1_code_range",
	"class_assumed",
)


# --- row shaping: seed dict -> DocType values ------------------------------------------------------


def tax_parameter_values(row: Mapping[str, Any]) -> dict[str, Any]:
	return {
		"key": row["key"],
		"effective_from": row["effective_from"],
		"effective_to": row.get("effective_to"),
		"status": row.get("status") or "active",
		"verified": 1 if row.get("verified") else 0,
		"value_json": None if row.get("value") is None else json.dumps(row["value"], ensure_ascii=False),
		"unit": row.get("unit") or "fraction",
		"source_text": row.get("source_text") or "",
		"source_url": row.get("source_url") or "",
		"article": row.get("article") or "",
		"note": row.get("note") or "",
	}


def tax_parameter_name(row: Mapping[str, Any]) -> str:
	return f"{row['key']}:{row['effective_from']}"


def posting_pattern_values(row: Mapping[str, Any]) -> dict[str, Any]:
	citation = row.get("citation") or {}
	doc_types = row.get("document_types") or []
	lines = []
	for line in row.get("lines") or []:
		values = {field: line.get(field) for field in PATTERN_LINE_FIELDS}
		code_range = line.get("v1_code_range")
		if isinstance(code_range, (list, tuple)):  # Data column: "6210-6910" range as "6210, 6910"
			values["v1_code_range"] = ", ".join(str(c) for c in code_range)
		values["optional"] = 1 if line.get("optional") else 0
		values["class_assumed"] = 1 if line.get("class_assumed") else 0
		values["alternatives_json"] = json.dumps(line.get("alternatives") or [], ensure_ascii=False)
		lines.append(values)
	return {
		"pattern_id": row["pattern_id"],
		"name_mn": row["name_mn"],
		"family": row.get("family") or "",
		"reference_bullet": row.get("reference_bullet") or "",
		"document_types": ", ".join(doc_types) if isinstance(doc_types, list) else str(doc_types),
		"applies_to_vat": row.get("applies_to_vat") or "any",
		"applies_to_cit": row.get("applies_to_cit") or "any",
		"conditions": row.get("conditions") or "",
		"verified": 1 if row.get("verified") else 0,
		"enabled": 0 if row.get("enabled") is False else 1,
		"lines": lines,
		"primary_document_mn": row.get("primary_document_mn") or "",
		"citation_instrument": citation.get("instrument") or "",
		"citation_instrument_full": citation.get("instrument_full") or "",
		"citation_section": citation.get("section") or "",
		"citation_quote": citation.get("quote") or "",
		"citation_url": citation.get("url") or "",
		"notes": row.get("notes") or "",
	}


def bank_layout_values(row: Mapping[str, Any]) -> dict[str, Any]:
	formats = row.get("date_formats") or []
	return {
		"layout_id": row["layout_id"],
		"bank": row.get("bank") or "Other",
		"verified": 1 if row.get("verified") else 0,
		"amount_style": row.get("amount_style") or "separate_debit_credit",
		"header_row_hint": row.get("header_row_hint"),
		"currency_default": row.get("currency_default") or "MNT",
		"keywords_json": json.dumps(row.get("keywords") or {}, ensure_ascii=False),
		"date_formats": "\n".join(formats) if isinstance(formats, list) else str(formats),
		"header_signature_json": json.dumps(row.get("header_signature") or [], ensure_ascii=False),
		"column_map_json": json.dumps(row.get("column_map") or {}, ensure_ascii=False),
		"notes": row.get("notes") or "",
	}


# --- upsert -------------------------------------------------------------------------------------


def _same(doc: Any, values: Mapping[str, Any], child_field: str | None = None) -> bool:
	"""True when saving `values` on `doc` would change nothing (JSON compared parsed)."""
	for key, value in values.items():
		if key == child_field:
			continue
		if not _equal(doc.get(key), value, doc.meta.get_field(key)):
			return False
	if child_field:
		rows = doc.get(child_field) or []
		wanted = values.get(child_field) or []
		if len(rows) != len(wanted):
			return False
		child_meta = frappe.get_meta(doc.meta.get_field(child_field).options)
		for row, want in zip(rows, wanted, strict=True):
			for key, value in want.items():
				if not _equal(row.get(key), value, child_meta.get_field(key)):
					return False
	return True


def _equal(current: Any, wanted: Any, df: Any) -> bool:
	fieldtype = df.fieldtype if df is not None else "Data"
	if fieldtype == "JSON":
		return _json_value(current) == _json_value(wanted)
	if fieldtype in ("Check", "Int"):
		return int(current or 0) == int(wanted or 0)
	if fieldtype == "Date":
		return str(current or "") == str(wanted or "")
	return (current if current is not None else "") == (wanted if wanted is not None else "")


def _json_value(value: Any) -> Any:
	if value in (None, ""):
		return None
	if isinstance(value, str):
		try:
			return json.loads(value)
		except ValueError:
			return value
	return value


def upsert(
	doctype: str, name: str, values: Mapping[str, Any], *, force: bool, child_field: str | None = None
) -> str:
	"""Insert or update one row; returns inserted / updated / unchanged / skipped_verified."""
	if not frappe.db.exists(doctype, name):
		doc = frappe.get_doc({"doctype": doctype, **values})
		doc.flags.ignore_permissions = True
		doc.insert()
		return "inserted"
	doc = frappe.get_doc(doctype, name)
	if int(doc.get("verified") or 0) and not force:
		return "skipped_verified"
	if _same(doc, values, child_field):
		return "unchanged"
	doc.update(dict(values))
	doc.flags.ignore_permissions = True
	doc.save()
	return "updated"


def sync(force: bool = False) -> dict[str, dict[str, int]]:
	"""Upsert every seed file into its DocType; returns {doctype: {outcome: count}}."""
	counts: dict[str, dict[str, int]] = {}
	plan: list[tuple[str, str, dict[str, Any], str | None]] = []
	for row in load_seed("tax_parameters")["rows"]:
		plan.append((TAX_PARAMETER, tax_parameter_name(row), tax_parameter_values(row), None))
	for row in load_seed("posting_patterns")["rows"]:
		plan.append((POSTING_PATTERN, row["pattern_id"], posting_pattern_values(row), "lines"))
	for row in load_seed("bank_layouts")["rows"]:
		plan.append((BANK_LAYOUT, row["layout_id"], bank_layout_values(row), None))
	for doctype, name, values, child_field in plan:
		if not frappe.db.exists("DocType", doctype):
			counts.setdefault(doctype, {})["missing_doctype"] = 1
			continue
		outcome = upsert(doctype, name, values, force=force, child_field=child_field)
		bucket = counts.setdefault(doctype, {})
		bucket[outcome] = bucket.get(outcome, 0) + 1
	_clear_caches()
	log_event("rules.seed.sync", force=force, **{k.replace(" ", "_"): v for k, v in counts.items()})
	return counts


def _clear_caches() -> None:
	from nyabo_mn.rules import params, patterns

	params.clear_cache()
	patterns.clear_cache()


def seed_default_rules(company: str, scheme: str) -> int:
	"""Company-independent Nyabo Rule rows of `rules_default.json` for one company and chart scheme.

	Keyed by `seed_rule_id` so provisioning twice does not duplicate them. Returns the
	number of rows created.
	"""
	if not frappe.db.exists("DocType", RULE):
		return 0
	created = 0
	for row in load_seed("rules_default")["rows"]:
		if row.get("scheme") != scheme:
			continue
		if frappe.db.exists(RULE, {"company": company, "seed_rule_id": row["rule_id"]}):
			continue
		doc = frappe.get_doc(
			{
				"doctype": RULE,
				"company": company,
				"match_type": row["match_type"],
				"match_value": row.get("match_value") or "",
				"target_account_code": row["target_account_code"],
				"vat_treatment": row.get("vat_treatment") or "none",
				"posting_pattern": row.get("posting_pattern")
				if frappe.db.exists(POSTING_PATTERN, row.get("posting_pattern") or "")
				else None,
				"source": row.get("source") or "seed",
				"status": row.get("status") or "active",
				"seed_rule_id": row["rule_id"],
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		created += 1
	return created
