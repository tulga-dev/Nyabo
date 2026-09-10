"""Which layout applies to these rows (ARCHITECTURE §5.4).

Order: verified layouts by header signature; layouts this company's accountant has confirmed
(DECISIONS ACC-02); learned (unverified) layouts only under ``frappe.flags.nyabo_simulation``;
never a seed placeholder. The generic keyword guess is always computed and returned separately so
the bot can show the accountant a pre-filled column question even when nothing matched.

WHY a company's confirmation counts here: the accountant who read the statement and mapped its
columns is the person who knows whether the mapping is right, and the evidence is their own file
rather than a legal text. It stays per company all the same — one client's Khan Bank export is not
proof about another client's — so the row's site-wide ``verified`` flag is still a site admin's.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from nyabo_mn.core.statements import HEADER_SCAN_ROWS, LayoutSpec, detect_layout, guess_layout
from nyabo_mn.parsers import layouts as layouts_mod

_DIGITS = re.compile(r"\d{6,}")


def simulation_mode() -> bool:
	import frappe

	return bool(frappe.flags.get("nyabo_simulation"))


def usable_layouts(
	specs: Iterable[LayoutSpec], *, simulation: bool | None = None, company: str | None = None
) -> list[LayoutSpec]:
	"""Layouts a real import may trust for this company (ACC-02), plus learned ones under simulation."""
	if simulation is None:
		simulation = simulation_mode()
	out: list[LayoutSpec] = []
	for spec in specs:
		if spec.is_generic:
			continue
		if spec.verified or accepted(spec, company) or (simulation and layouts_mod.is_learned(spec)):
			out.append(spec)
	return out


def accepted(spec: LayoutSpec, company: str | None) -> bool:
	"""True when this company's accountant confirmed this layout for their own books.

	Read through ``rules.verify`` so the layout, the posting pattern and the tax parameter all
	answer the same question in the same words and leave the same audit row.
	"""
	if not company or not getattr(spec, "layout_id", None):
		return False
	try:
		from nyabo_mn.rules import verify
	except ImportError:  # pragma: no cover - the rules package is always present on a site
		return False
	return verify.acceptance(company, spec.layout_id, verify.LAYOUT) is not None


def generic_template(specs: Iterable[LayoutSpec]) -> LayoutSpec | None:
	for spec in specs:
		if spec.is_generic:
			return spec
	for spec in layouts_mod.seed_specs():
		if spec.is_generic:
			return spec
	return None


def detect(
	rows: Sequence[Sequence[Any]],
	company: str | None = None,
	*,
	simulation: bool | None = None,
) -> tuple[LayoutSpec | None, LayoutSpec | None]:
	"""(trusted layout or None, generic guess or None)."""
	specs = layouts_mod.load_layouts(company)
	trusted = detect_layout(rows, usable_layouts(specs, simulation=simulation, company=company))
	template = generic_template(specs)
	guess = guess_layout(rows, template=template) if template is not None else guess_layout(rows)
	return trusted, guess


def unverified_match(rows: Sequence[Sequence[Any]], company: str | None = None) -> LayoutSpec | None:
	"""A stored layout whose signature matches these rows but which nobody has verified.

	Never trusted for an import (``detect`` already refused it); it only tells the bot that the
	mapping question has been answered once, so what is owed is the confirmation card and not the
	column questions again. Who answers that card is the accountant who read the file (ACC-02) —
	which is why ``accepted(s, company)`` is part of the filter below.
	"""
	specs = layouts_mod.load_layouts(company)
	candidates = [
		s
		for s in specs
		if not s.is_generic and not s.verified and not accepted(s, company) and s.header_signature
	]
	return detect_layout(rows, candidates)


def find_account_number(rows: Sequence[Sequence[Any]], numbers: Iterable[str]) -> str | None:
	"""The configured account number that appears in the title block (first rows), if any.

	Only contiguous digit groups are compared, as in ``core.matching.is_own_transfer``.
	"""
	wanted = {"".join(ch for ch in str(n) if ch.isdigit()): str(n) for n in numbers if n}
	wanted = {digits: original for digits, original in wanted.items() if len(digits) >= 6}
	if not wanted:
		return None
	for row in list(rows)[:HEADER_SCAN_ROWS]:
		for cell in row:
			if cell in (None, ""):
				continue
			text = str(cell)
			if isinstance(cell, float) and cell.is_integer():
				text = str(int(cell))
			for group in _DIGITS.findall(text):
				for digits, original in wanted.items():
					if digits in group:
						return original
	return None


__all__ = [
	"accepted",
	"detect",
	"find_account_number",
	"generic_template",
	"simulation_mode",
	"unverified_match",
	"usable_layouts",
]
