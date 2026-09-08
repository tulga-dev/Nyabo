"""Nyabo Bank Layout rows <-> core LayoutSpec, plus learning a layout from the accountant.

Why a separate loader: the DocType stores JSON fields as text, the seed stores them as
objects, and the core parser wants one frozen ``LayoutSpec``. Everything that touches
Frappe for layouts is here so ``core.statements`` stays pure.

Learned layouts are created with ``verified = 0``. They are usable under the simulator
(``frappe.flags.nyabo_simulation``) and in tests; a real import refuses them until the
admin verifies the row against the sample file (ARCHITECTURE §1.2, §5.4).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from nyabo_mn.core.statements import COLUMN_ROLES, LayoutSpec, norm_header
from nyabo_mn.i18n import mn
from nyabo_mn.nyabo.seed import load_seed

DOCTYPE = "Nyabo Bank Layout"
LEARNED_PREFIX = "learned_"
LAYOUT_FIELDS = (
	"name",
	"layout_id",
	"bank",
	"verified",
	"amount_style",
	"header_row_hint",
	"currency_default",
	"keywords_json",
	"date_formats",
	"header_signature_json",
	"column_map_json",
	"notes",
)
BANK_SLUGS: Mapping[str, str] = {
	"Khan Bank": "khan_bank",
	"TDB": "tdb",
	"Golomt Bank": "golomt_bank",
	"Trans Bank": "trans_bank",
	"XacBank": "xacbank",
	"Other": "other",
}


def _json_field(value: Any, field: str) -> Any:
	"""JSON fieldtype values arrive as str from the desk and as objects from Python."""
	if value in (None, ""):
		return None
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError) as exc:
		raise ValueError(mn.MSG_LAYOUT_BAD_JSON.format(field=field)) from exc


def spec_from_row(row: Mapping[str, Any]) -> LayoutSpec:
	"""A DocType row (frappe.get_all dict or Document.as_dict) -> LayoutSpec."""
	data: dict[str, Any] = {
		"layout_id": row.get("layout_id") or row.get("name"),
		"bank": row.get("bank"),
		"verified": bool(row.get("verified")),
		"amount_style": row.get("amount_style"),
		"header_row_hint": row.get("header_row_hint"),
		"currency_default": row.get("currency_default"),
		"date_formats": row.get("date_formats"),
		"notes": row.get("notes"),
		"header_signature": _json_field(row.get("header_signature_json"), "header_signature_json") or [],
		"column_map": _json_field(row.get("column_map_json"), "column_map_json") or {},
	}
	keywords = _json_field(row.get("keywords_json"), "keywords_json")
	if keywords:
		data["keywords"] = keywords
	return LayoutSpec.from_dict(data)


def seed_specs() -> list[LayoutSpec]:
	"""The shipped bank_layouts.json (placeholders + generic_mn) as specs."""
	return [LayoutSpec.from_dict(row) for row in load_seed("bank_layouts")["rows"]]


def load_layouts(company: str | None = None) -> list[LayoutSpec]:
	"""Nyabo Bank Layout rows; the seed file when the table is empty (fresh site, tests).

	``company`` is accepted for a future per-company filter; layouts are global today
	because a bank's export does not depend on the customer.
	"""
	del company
	import frappe

	rows = frappe.get_all(DOCTYPE, fields=list(LAYOUT_FIELDS))
	specs = [spec_from_row(row) for row in rows]
	seen = {spec.layout_id for spec in specs}
	# The generic keyword layout must always exist for the preview guess, even when the
	# admin has not seeded the table.
	for spec in seed_specs():
		if spec.layout_id not in seen and (not specs or spec.is_generic):
			specs.append(spec)
			seen.add(spec.layout_id)
	return specs


def is_learned(spec: LayoutSpec) -> bool:
	return spec.layout_id.startswith(LEARNED_PREFIX)


def header_signature_of(header_row: Sequence[Any]) -> tuple[str, ...]:
	"""Non-empty header cell texts, whitespace-normalised; order kept for the desk view."""
	return tuple(norm_header(cell) for cell in header_row if norm_header(cell))


def normalise_column_map(column_map: Mapping[str, Any]) -> dict[str, int | str]:
	"""Accountant answers arrive as {role: column index} or {column index: role}; keep role -> index.

	An "ignore" role drops the column. Unknown roles raise so a typo in a button payload
	cannot silently map the balance column to the amount.
	"""
	out: dict[str, int | str] = {}
	for key, value in column_map.items():
		if isinstance(value, str) and value in COLUMN_ROLES and str(key).lstrip("-").isdigit():
			role, ref = value, int(key)
		elif isinstance(value, str) and value == "ignore":
			continue
		else:
			role, ref = str(key), value
		if role == "ignore":
			continue
		if role not in COLUMN_ROLES:
			raise ValueError(mn.MSG_LAYOUT_ROLE_UNKNOWN.format(role=role, roles=", ".join(COLUMN_ROLES)))
		if isinstance(ref, str) and ref.lstrip("-").isdigit():
			ref = int(ref)
		out[role] = ref
	if "date" not in out or "description" not in out:
		raise ValueError(mn.MSG_LAYOUT_NEEDS_DATE_DESCRIPTION)
	return out


def amount_style_for(column_map: Mapping[str, Any]) -> str:
	if "amount" in column_map and "debit" not in column_map and "credit" not in column_map:
		return "signed_amount"
	return "separate_debit_credit"


def learned_layout_id(bank: str, signature: Sequence[str]) -> str:
	digest = hashlib.sha256("|".join(signature).encode("utf-8")).hexdigest()[:8]
	return f"{LEARNED_PREFIX}{BANK_SLUGS.get(bank, 'other')}_{digest}"


def save_learned_layout(
	bank: str,
	header_row: Sequence[Any],
	column_map: Mapping[str, Any],
	company: str,
	sample_document: str | None = None,
	*,
	date_formats: Sequence[str] | None = None,
	currency_default: str = "MNT",
) -> Any:
	"""Persist the accountant's column mapping as an unverified Nyabo Bank Layout.

	Idempotent per (bank, header signature): answering the same question twice updates
	the row instead of creating a twin. Returns the Document.
	"""
	import frappe

	signature = header_signature_of(header_row)
	if not signature:
		raise ValueError(mn.MSG_LAYOUT_NEEDS_DATE_DESCRIPTION)
	columns = normalise_column_map(column_map)
	layout_id = learned_layout_id(bank, signature)
	values: dict[str, Any] = {
		"layout_id": layout_id,
		"bank": bank if bank in BANK_SLUGS else "Other",
		"verified": 0,
		"amount_style": amount_style_for(columns),
		"header_row_hint": None,
		"currency_default": currency_default or "MNT",
		"header_signature_json": json.dumps(list(signature), ensure_ascii=False),
		"column_map_json": json.dumps(columns, ensure_ascii=False),
		"notes": mn.MSG_LAYOUT_LEARNED_NOTE.format(company=company, document=sample_document or "-"),
	}
	if date_formats:
		values["date_formats"] = "\n".join(date_formats)
	sample_url = _sample_file_url(sample_document)
	if sample_url:
		values["sample_file"] = sample_url

	existing = frappe.db.exists(DOCTYPE, layout_id)
	if existing:
		doc = frappe.get_doc(DOCTYPE, existing)
		if doc.verified:
			# An admin already verified this signature; the accountant's re-answer must not
			# silently demote it. Keep the verified row untouched.
			return doc
		doc.update(values)
	else:
		doc = frappe.get_doc({"doctype": DOCTYPE, **values})
	doc.flags.ignore_permissions = True
	doc.save()
	_write_event(
		"bank_layout_learned",
		company=company,
		ref_name=doc.name,
		payload={"bank": bank, "column_map": columns, "sample_document": sample_document},
	)
	return doc


def _sample_file_url(sample_document: str | None) -> str | None:
	import frappe

	if not sample_document or not frappe.db.exists("Nyabo Document", sample_document):
		return None
	return frappe.db.get_value("Nyabo Document", sample_document, "file")


def _write_event(event_type: str, *, company: str, ref_name: str, payload: Mapping[str, Any]) -> None:
	import frappe

	frappe.get_doc(
		{
			"doctype": "Nyabo Event",
			"event_type": event_type,
			"company": company,
			"actor_user": frappe.session.user,
			"ref_doctype": DOCTYPE,
			"ref_name": ref_name,
			"payload_json": json.dumps(dict(payload), ensure_ascii=False, default=str),
		}
	).insert(ignore_permissions=True)


__all__ = [
	"DOCTYPE",
	"LEARNED_PREFIX",
	"amount_style_for",
	"header_signature_of",
	"is_learned",
	"learned_layout_id",
	"load_layouts",
	"normalise_column_map",
	"save_learned_layout",
	"seed_specs",
	"spec_from_row",
]
