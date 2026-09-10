"""Refuse unverified rules for real postings (docs/ARCHITECTURE.md §1.2).

A Tax Parameter, Posting Pattern or Bank Layout with `verified = 0` may drive tests and
the simulator, but nothing built on it may reach `insert()` on an accounting document.
`require_verified` is called by the pipeline right before it posts; the only bypass is
`frappe.flags.nyabo_simulation`, which the simulator and tests set deliberately.

Two things clear a rule, and the guard asks about both (DECISIONS ACC-01):

* ``verified = 1`` on the row itself — the seed's citation, or a site admin's tap. It holds for
  every company on the site.
* a ``Nyabo Rule Acceptance`` for the company being posted for — the accountant who keeps those
  books saying the rule applies to them. It holds for that company and no other.

So the guard takes the company it is posting for. Without one it behaves exactly as it always
did: only the global flag counts. Nothing here is weakened — a rule that neither evidence nor a
named person has accepted still refuses, and the refusal still names the rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import frappe

from nyabo_mn.i18n import mn

# Order matters: a bare name is looked up in these DocTypes in turn.
GUARDED_DOCTYPES: tuple[str, ...] = ("Nyabo Posting Pattern", "Nyabo Bank Layout", "Nyabo Tax Parameter")


class UnverifiedRuleError(frappe.ValidationError):
	"""Raised with a Mongolian message naming the rule (pattern id, layout id or parameter name).

	``company`` rides along so the Telegram layer can offer the accountant the acceptance that
	would clear it — for those books, which is the only company this refusal is about.
	"""

	def __init__(self, rule: str, company: str | None = None):
		self.rule = rule
		self.company = company or None
		# `message_mn` is the attribute every Nyabo refusal exposes; the pipeline's failure
		# handler and the Telegram reply read it without knowing which module raised.
		self.message_mn = mn.MSG_UNVERIFIED_RULE_BLOCKED.format(rule=rule)
		super().__init__(self.message_mn)


def is_simulation() -> bool:
	"""True while the simulator or a test runs with `frappe.flags.nyabo_simulation` set."""
	return bool(frappe.flags.get("nyabo_simulation"))


def require_verified(*rules: Any, company: str | None = None) -> None:
	"""Raise UnverifiedRuleError unless every rule is cleared (or the simulation flag is set).

	Accepts Frappe documents of the guarded DocTypes, core objects with a `verified`
	attribute (ParameterRow, PatternSpec, LayoutSpec), `(doctype, name)` tuples, bare
	names, or lists of those. An unknown name counts as unverified: refusing is the safe
	default.

	`company` is the company the posting belongs to. A rule that company's accountant has
	accepted passes; the same rule for any other company still raises.
	"""
	if is_simulation():
		return
	for rule in _flatten(rules):
		if not _cleared(rule, company):
			raise UnverifiedRuleError(_label(rule), company=company)


def is_verified(rule: Any, company: str | None = None) -> bool:
	"""The plain check for cards (`needs_accountant`), without raising or the bypass."""
	return _cleared(rule, company)


def accepted_for(rule: Any, company: str | None) -> bool:
	"""True when this company's accountant accepted this rule (and nobody verified the row).

	Kept separate from `is_verified` so a card can say *which* of the two cleared the rule: an
	accountant's acceptance and a legal citation are not the same claim (DECISIONS VER-07).
	"""
	doctype, name = _ref(rule)
	if not name or not company:
		return False
	from nyabo_mn.rules import verify

	return verify.acceptance(company, name, doctype) is not None


def _cleared(rule: Any, company: str | None) -> bool:
	if _inspect(rule)[1]:
		return True
	return accepted_for(rule, company)


def _label(rule: Any) -> str:
	return _inspect(rule)[0]


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


def _ref(rule: Any) -> tuple[str | None, str | None]:
	"""``(doctype or None, row name or None)`` — what an acceptance row would be keyed on.

	WHY this is not simply `_inspect`'s label: a core ``ParameterRow`` carries `key` and
	`effective_from` separately, while the DocType row it came from is named
	``key:effective_from``. Looking an acceptance up by the label alone would ask about
	``si.employer_rate`` and never find the acceptance recorded for
	``si.employer_rate:2027-01-01`` — the guard would keep refusing a rule the accountant had
	just accepted, which is the one failure this whole flow exists to remove.
	"""
	if rule is None:
		return None, None
	if isinstance(rule, tuple) and _is_ref(rule):
		return rule[0], rule[1]
	if isinstance(rule, str):
		for doctype in GUARDED_DOCTYPES:
			if frappe.db.exists(doctype, rule):
				return doctype, rule
		return None, rule
	doctype = getattr(rule, "doctype", None)
	name = getattr(rule, "name", None)
	if isinstance(doctype, str) and doctype in GUARDED_DOCTYPES and isinstance(name, str):
		return doctype, name
	pattern_id = getattr(rule, "pattern_id", None)
	if pattern_id:
		return "Nyabo Posting Pattern", str(pattern_id)
	layout_id = getattr(rule, "layout_id", None)
	if layout_id:
		return "Nyabo Bank Layout", str(layout_id)
	key = getattr(rule, "key", None)
	if key:
		effective_from = getattr(rule, "effective_from", None)
		return "Nyabo Tax Parameter", f"{key}:{effective_from}" if effective_from else str(key)
	return None, None


def _lookup(doctype: str, name: str) -> tuple[str, bool]:
	verified = frappe.db.get_value(doctype, name, "verified")
	if verified is None:
		return name, False
	return name, bool(int(verified))
