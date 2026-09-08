"""Refuse unverified rules for real postings (docs/ARCHITECTURE.md §1.2).

A Tax Parameter, Posting Pattern or Bank Layout with `verified = 0` may drive tests and
the simulator, but nothing built on it may reach `insert()` on an accounting document.
`require_verified` is called by the pipeline right before it posts; the only bypass is
`frappe.flags.nyabo_simulation`, which the simulator and tests set deliberately.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import frappe

from nyabo_mn.i18n import mn

# Order matters: a bare name is looked up in these DocTypes in turn.
GUARDED_DOCTYPES: tuple[str, ...] = ("Nyabo Posting Pattern", "Nyabo Bank Layout", "Nyabo Tax Parameter")


class UnverifiedRuleError(frappe.ValidationError):
	"""Raised with a Mongolian message naming the rule (pattern id, layout id or parameter name)."""

	def __init__(self, rule: str):
		self.rule = rule
		# `message_mn` is the attribute every Nyabo refusal exposes; the pipeline's failure
		# handler and the Telegram reply read it without knowing which module raised.
		self.message_mn = mn.MSG_UNVERIFIED_RULE_BLOCKED.format(rule=rule)
		super().__init__(self.message_mn)


def is_simulation() -> bool:
	"""True while the simulator or a test runs with `frappe.flags.nyabo_simulation` set."""
	return bool(frappe.flags.get("nyabo_simulation"))


def require_verified(*rules: Any) -> None:
	"""Raise UnverifiedRuleError unless every rule is verified (or the simulation flag is set).

	Accepts Frappe documents of the guarded DocTypes, core objects with a `verified`
	attribute (ParameterRow, PatternSpec, LayoutSpec), `(doctype, name)` tuples, bare
	names, or lists of those. An unknown name counts as unverified: refusing is the safe
	default.
	"""
	if is_simulation():
		return
	for rule in _flatten(rules):
		label, verified = _inspect(rule)
		if not verified:
			raise UnverifiedRuleError(label)


def is_verified(rule: Any) -> bool:
	"""The plain check for cards (`needs_accountant`), without raising or the bypass."""
	return _inspect(rule)[1]


def _flatten(rules: Iterable[Any]) -> Iterable[Any]:
	for rule in rules:
		if isinstance(rule, (list, set, frozenset)) or (isinstance(rule, tuple) and not _is_ref(rule)):
			yield from _flatten(rule)
		else:
			yield rule


def _is_ref(value: tuple) -> bool:
	return len(value) == 2 and all(isinstance(v, str) for v in value) and value[0] in GUARDED_DOCTYPES


def _inspect(rule: Any) -> tuple[str, bool]:
	"""(label for the message, verified?) for any accepted rule shape."""
	if rule is None:
		return "?", False
	if isinstance(rule, tuple) and _is_ref(rule):
		return _lookup(rule[0], rule[1])
	if isinstance(rule, str):
		for doctype in GUARDED_DOCTYPES:
			if frappe.db.exists(doctype, rule):
				return _lookup(doctype, rule)
		return rule, False
	label = (
		getattr(rule, "pattern_id", None)
		or getattr(rule, "layout_id", None)
		or getattr(rule, "name", None)
		or getattr(rule, "key", None)
		or str(rule)
	)
	verified = getattr(rule, "verified", None)
	if verified is None and hasattr(rule, "get"):
		verified = rule.get("verified")
	return str(label), bool(verified)


def _lookup(doctype: str, name: str) -> tuple[str, bool]:
	verified = frappe.db.get_value(doctype, name, "verified")
	if verified is None:
		return name, False
	return name, bool(int(verified))
