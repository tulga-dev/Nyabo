"""Month-end period lock on top of ERPNext's Accounting Period (ARCHITECTURE §2, §5.5).

One Accounting Period per company per month; ERPNext refuses postings into it at document
validate and at GL level. What ERPNext does not give us: a refusal before month end, a
refusal while unverified rules are still in the books, and an audit trail of who locked or
reopened a month and why. All three live here, and every change writes a Nyabo Event.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import frappe
from frappe.utils import formatdate, getdate, nowdate

from nyabo_mn.compliance import events
from nyabo_mn.core.dates import period_bounds
from nyabo_mn.i18n import mn

LOCK_ROLES: tuple[str, ...] = ("Nyabo Accountant", "Nyabo Admin", "System Manager")
REOPEN_ROLES: tuple[str, ...] = ("Nyabo Admin", "System Manager")


def _require_role(user: str, roles: tuple[str, ...]) -> None:
	if user == "Administrator":
		return
	if not set(roles).intersection(frappe.get_roles(user)):
		frappe.throw(mn.MSG_NO_PERMISSION, frappe.PermissionError)


def _period_dates(period: str) -> tuple[dt.date, dt.date]:
	try:
		return period_bounds(period)
	except ValueError:
		frappe.throw(mn.MSG_CLOSE_USAGE)
		raise  # unreachable


def existing_period(company: str, period: str) -> str | None:
	"""Name of an enabled Accounting Period with this period_name, if any."""
	return frappe.db.get_value(
		"Accounting Period", {"company": company, "period_name": period, "disabled": 0}, "name"
	)


def unverified_proposals(company: str, start: dt.date, end: dt.date) -> list[str]:
	"""Posted proposals in the range whose posting pattern is not verified (must be empty to lock)."""
	proposals = frappe.get_all(
		"Nyabo Proposal",
		filters={
			"company": company,
			"status": "posted",
			"posting_date": ["between", [start.isoformat(), end.isoformat()]],
			"posting_pattern": ["!=", ""],
		},
		fields=["name", "posting_pattern"],
	)
	if not proposals:
		return []
	patterns = {p.posting_pattern for p in proposals if p.posting_pattern}
	verified = set(
		frappe.get_all(
			"Nyabo Posting Pattern",
			filters={"name": ["in", list(patterns)], "verified": 1},
			pluck="name",
		)
	)
	return [p.name for p in proposals if p.posting_pattern and p.posting_pattern not in verified]


def lock(company: str, period: str, user: str, telegram_id: str | int | None = None) -> str:
	"""Create the Accounting Period for ``period`` ("YYYY-MM") and log it. Returns its name.

	Refuses before the last day of the month (ERPNext would too, with an English message),
	when the month is already locked, and when a posted proposal in the month used an
	unverified pattern: locking would freeze books built on a rule nobody checked.
	"""
	_require_role(user, LOCK_ROLES)
	start, end = _period_dates(period)
	today = getdate(nowdate())
	if today < end:
		frappe.throw(mn.MSG_PERIOD_NOT_ENDED.format(end_date=formatdate(end)))
	already = existing_period(company, period)
	if already:
		frappe.throw(mn.MSG_PERIOD_ALREADY_CLOSED.format(name=already))
	pending = unverified_proposals(company, start, end)
	if pending:
		frappe.throw(mn.MSG_PERIOD_UNVERIFIED_RULES)
	doc = frappe.get_doc(
		{
			"doctype": "Accounting Period",
			"period_name": period,
			"company": company,
			"start_date": start,
			"end_date": end,
		}
	)
	doc.flags.ignore_permissions = True
	frappe.flags.nyabo_period_action = mn.EVENT_PERIOD_LOCKED
	try:
		doc.insert()
	finally:
		frappe.flags.pop("nyabo_period_action", None)
	events.log(
		mn.EVENT_PERIOD_LOCKED,
		company=company,
		ref_doctype="Accounting Period",
		ref_name=doc.name,
		payload={"period": period, "start_date": start.isoformat(), "end_date": end.isoformat(), "user": user},
		actor_telegram_id=telegram_id,
	)
	return doc.name


def is_locked(company: str, date: dt.date | str) -> tuple[bool, str | None]:
	"""(True, period_name) when an enabled Accounting Period of the company covers the date."""
	on = getdate(date)
	for row in frappe.get_all(
		"Accounting Period",
		filters={"company": company, "disabled": 0},
		fields=["name", "period_name", "start_date", "end_date"],
	):
		if getdate(row.start_date) <= on <= getdate(row.end_date):
			return True, row.period_name or row.name
	return False, None


def reopen(company: str, period: str, user: str, reason: str) -> str:
	"""Disable the Accounting Period (ERPNext's way of reopening) and log who and why."""
	_require_role(user, REOPEN_ROLES)
	name = existing_period(company, period)
	if not name:
		frappe.throw(mn.MSG_PERIOD_NOT_ENDED.format(end_date=period))
	doc = frappe.get_doc("Accounting Period", name)
	doc.disabled = 1
	doc.flags.ignore_permissions = True
	frappe.flags.nyabo_period_action = mn.EVENT_PERIOD_REOPENED
	try:
		doc.save()
	finally:
		frappe.flags.pop("nyabo_period_action", None)
	events.log(
		mn.EVENT_PERIOD_REOPENED,
		company=company,
		ref_doctype="Accounting Period",
		ref_name=name,
		reason=reason,
		payload={"period": period, "user": user},
	)
	return name


# --- desk hooks: any manual change to an Accounting Period leaves a trace ------------------


def _changed(doc: Any) -> dict[str, Any]:
	before = doc.get_doc_before_save()
	if before is None:
		return {"action": "created"}
	out: dict[str, Any] = {"action": "updated"}
	for field in ("period_name", "start_date", "end_date", "disabled", "exempted_role"):
		old, new = before.get(field), doc.get(field)
		if str(old or "") != str(new or ""):
			out[field] = {"from": str(old), "to": str(new)}
	return out


def log_period_change(doc: Any, method: str | None = None) -> None:
	"""on_update: skipped when lock()/reopen() already wrote the specific event.

	The period is named in the payload, not in ``ref_name``: a Dynamic Link from an event
	would make Frappe refuse to delete the period later (link check), and manual desk
	periods must stay deletable. Periods locked through Nyabo *are* linked on purpose.
	"""
	if frappe.flags.get("nyabo_period_action"):
		return
	events.log(
		mn.EVENT_PERIOD_CHANGED,
		company=doc.get("company"),
		payload={"accounting_period": doc.name, "period": doc.get("period_name"), **_changed(doc)},
	)


def log_period_delete(doc: Any, method: str | None = None) -> None:
	"""on_trash: a period Nyabo locked is never deleted (reopen instead); others are logged."""
	if frappe.db.exists(
		"Nyabo Event", {"ref_doctype": "Accounting Period", "ref_name": doc.name, "event_type": mn.EVENT_PERIOD_LOCKED}
	):
		frappe.throw(mn.MSG_PERIOD_DELETE_BLOCKED.format(name=doc.name))
	events.log(
		mn.EVENT_PERIOD_DELETED,
		company=doc.get("company"),
		payload={
			"accounting_period": doc.name,
			"period": doc.get("period_name"),
			"start_date": str(doc.get("start_date")),
			"action": "deleted",
		},
	)
