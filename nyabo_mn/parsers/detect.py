"""Which layout applies to these rows (ARCHITECTURE §5.4).

Order: verified layouts by header signature; learned (unverified) layouts only under
``frappe.flags.nyabo_simulation``; never a seed placeholder. The generic keyword guess
is always computed and returned separately so the bot can show the accountant a
pre-filled column question even when nothing matched.
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


def usable_layouts(specs: Iterable[LayoutSpec], *, simulation: bool | None = None) -> list[LayoutSpec]:
	"""Layouts a real import may trust: verified ones, plus learned ones under simulation."""
	if simulation is None:
		simulation = simulation_mode()
	out: list[LayoutSpec] = []
	for spec in specs:
		if spec.is_generic:
			continue
		if spec.verified or (simulation and layouts_mod.is_learned(spec)):
			out.append(spec)
	return out


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
	trusted = detect_layout(rows, usable_layouts(specs, simulation=simulation))
	template = generic_template(specs)
	guess = guess_layout(rows, template=template) if template is not None else guess_layout(rows)
	return trusted, guess


def unverified_match(rows: Sequence[Sequence[Any]], company: str | None = None) -> LayoutSpec | None:
	"""A stored layout whose signature matches these rows but which nobody has verified.

	Never trusted for an import (``detect`` already refused it); it only tells the bot that
	the mapping question has been answered once and the admin, not the accountant, is next.
	"""
	specs = layouts_mod.load_layouts(company)
	candidates = [s for s in specs if not s.is_generic and not s.verified and s.header_signature]
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
	"detect",
	"find_account_number",
	"generic_template",
	"simulation_mode",
	"unverified_match",
	"usable_layouts",
]
