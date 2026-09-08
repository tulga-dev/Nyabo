"""Posting patterns from Nyabo Posting Pattern rows.

The DocType is the admin's copy of `seed/posting_patterns.json` (verified flag, notes);
this module turns it back into `core.rules_engine.PatternSpec` objects and delegates the
selection to the core engine, so the Frappe side adds nothing but the database read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import frappe

from nyabo_mn.core.models import RegimeContext
from nyabo_mn.core.rules_engine import NoPatternError, PatternSpec, select_pattern
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.nyabo.seed import load_seed

DOCTYPE = "Nyabo Posting Pattern"
LINE_DOCTYPE = "Nyabo Posting Pattern Line"
_CACHE_ATTR = "nyabo_posting_patterns"


def spec_from_doc(doc: Any) -> PatternSpec:
	"""A Nyabo Posting Pattern document (with its lines) as the core dataclass."""
	data = dict(doc.as_dict()) if callable(getattr(doc, "as_dict", None)) else dict(doc)
	data["lines"] = [
		dict(line.as_dict()) if callable(getattr(line, "as_dict", None)) else dict(line)
		for line in data.get("lines") or []
	]
	return PatternSpec.from_dict(data)


def load_all(*, refresh: bool = False) -> list[PatternSpec]:
	"""Every pattern in seed order (idx of insertion), cached on frappe.local for the request.

	Falls back to the seed file, with a log line, on a site whose rows were never synced.
	"""
	cached = getattr(frappe.local, _CACHE_ATTR, None)
	if cached is not None and not refresh:
		return cached
	specs: list[PatternSpec] = []
	if frappe.db.exists("DocType", DOCTYPE):
		names = frappe.get_all(DOCTYPE, pluck="name", order_by="creation asc")
		specs = [spec_from_doc(frappe.get_doc(DOCTYPE, name)) for name in names]
	if not specs:
		log_event("rules.patterns.seed_fallback", level="warning", doctype=DOCTYPE)
		specs = [PatternSpec.from_dict(r) for r in load_seed("posting_patterns")["rows"]]
	setattr(frappe.local, _CACHE_ATTR, specs)
	return specs


def clear_cache() -> None:
	if hasattr(frappe.local, _CACHE_ATTR):
		delattr(frappe.local, _CACHE_ATTR)


def load(pattern_id: str) -> PatternSpec:
	"""One pattern by id; raises NoPatternError with a Mongolian message when unknown."""
	for spec in load_all():
		if spec.pattern_id == pattern_id:
			return spec
	raise NoPatternError(
		f"no posting pattern {pattern_id!r}", mn.MSG_PATTERN_NOT_FOUND.format(document=pattern_id)
	)


def select(document_kind: str, ctx: RegimeContext, hints: Mapping[str, Any] | None = None) -> PatternSpec:
	"""`core.rules_engine.select_pattern` over the DocType rows (family / pattern_id hints)."""
	return select_pattern(load_all(), document_kind, ctx, hints)
