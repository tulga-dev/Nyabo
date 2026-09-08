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

import frappe

from nyabo_mn.i18n import mn

LINK_DOCTYPE = "Nyabo User Link"
LINK_COMPANY_DOCTYPE = "Nyabo User Company"


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


__all__ = ["link_companies", "may_use_company", "require_company"]
