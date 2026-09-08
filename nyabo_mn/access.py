"""Who may act on which company.

A Telegram user is a ``Nyabo User Link`` with a flat ``companies`` child table; every
handler re-checks the document's company against that list, because callback data is
attacker-chosen and ERPNext document names are a global sequence, not per company.

The check lives here too - not only in the handlers - so the invariant survives a new
caller: ``compliance.period.lock`` already guards itself, and reversal and bank
reconciliation now do the same. Desk users with no Telegram link are left to ERPNext's
own permission layer.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.i18n import mn

LINK_DOCTYPE = "Nyabo User Link"
LINK_COMPANY_DOCTYPE = "Nyabo User Company"


def user_link(user: str) -> Any | None:
	"""The user's active ``Nyabo User Link``, or None."""
	if not user:
		return None
	name = frappe.db.get_value(LINK_DOCTYPE, {"user": user, "status": "active"}, "name")
	return frappe.get_doc(LINK_DOCTYPE, name) if name else None


def role_for(link: Any, company: str | None = None) -> str | None:
	"""The link's role *on this company*.

	A person is often the owner of their own company and the bookkeeper of another, so the
	role lives on the ``Nyabo User Company`` row. The link-level role is the fallback: it is
	what a link with no companies carries, and what rows written before the per-company role
	existed fall back to.
	"""
	if link is None:
		return None
	if company:
		for row in link.get("companies") or []:
			if row.company == company:
				return row.get("role") or link.role
	return link.role


def link_companies(user: str) -> list[str] | None:
	"""Companies the user's active link covers; ``None`` when the user has no link at all."""
	if not user:
		return None
	link = frappe.db.get_value(LINK_DOCTYPE, {"user": user, "status": "active"}, "name")
	if not link:
		return None
	return frappe.get_all(LINK_COMPANY_DOCTYPE, filters={"parent": link}, pluck="company")


def may_use_company(user: str | None, company: str) -> bool:
	"""``Administrator``, background jobs (``user`` is None) and unlinked desk users pass."""
	if not user or user == "Administrator":
		return True
	companies = link_companies(user)
	if not companies:  # no link, or a link with no company yet -> nothing to narrow
		return True
	return company in companies


def require_company(user: str | None, company: str) -> None:
	if not may_use_company(user, company):
		frappe.throw(mn.MSG_NO_PERMISSION, frappe.PermissionError)


__all__ = ["link_companies", "may_use_company", "require_company", "role_for", "user_link"]
