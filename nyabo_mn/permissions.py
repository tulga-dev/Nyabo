"""Company scoping for Nyabo's own DocTypes (SEC-06).

An accountant serves several clients, and a Telegram link grants them one company at a
time. Until now the DocType permission tables gave the `Nyabo Accountant` role read and
write on *every* row of `Nyabo Proposal`, `Nyabo Document` and the rest, so any linked
user reaching Frappe's ORM (desk, REST, a report, a future endpoint) saw every client's
proposals and the private URLs of their receipt photos. The handler-level checks in the
Telegram layer are the first line; this module is the second, so one missed check is not
a cross-tenant read.

Two mechanisms, deliberately both:

1. `permission_query_conditions` and `has_permission` hooks (this module) narrow every
   list, report and `frappe.get_doc` on a Nyabo DocType to the caller's linked companies.
2. `sync_user_permissions` writes a Frappe `User Permission` per linked company, which
   Frappe applies to *every* DocType with a Company link, so ERPNext's own documents
   (Purchase Invoice, Journal Entry, GL Entry, Bank Transaction) are scoped too.

Anyone holding `System Manager` or `Nyabo Admin` is unrestricted: the admin runs
provisioning and reads across companies by design.
"""

from __future__ import annotations

from typing import Any

import frappe

USER_LINK = "Nyabo User Link"
UNRESTRICTED_ROLES = ("System Manager", "Nyabo Admin", "Administrator")

# DocTypes with a `company` Link field that Nyabo owns. `Nyabo Company Settings` is named
# by company, so it is scoped on `name` instead (see `_condition`).
SCOPED_BY_COMPANY = (
	"Nyabo Document",
	"Nyabo Proposal",
	"Nyabo Correction",
	"Nyabo Event",
	"Nyabo Rule",
	"Nyabo Account Alias",
	"Nyabo Inventory Intake",
	"Nyabo Eval Case",
	"Nyabo LLM Call",
)
SCOPED_BY_NAME = ("Nyabo Company Settings",)


def is_unrestricted(user: str | None = None) -> bool:
	"""True for the admin roles and for the Administrator, who work across companies."""
	user = user or frappe.session.user
	if user in ("Administrator", "Guest"):
		return user == "Administrator"
	roles = set(frappe.get_roles(user))
	return bool(roles.intersection(UNRESTRICTED_ROLES))


def allowed_companies(user: str | None = None) -> list[str] | None:
	"""The companies a user may see, or ``None`` when they are unrestricted.

	An empty list means "linked to nothing yet": the caller must then see no rows at all,
	which is why `None` (unrestricted) and `[]` (nothing) are different answers.
	"""
	user = user or frappe.session.user
	if is_unrestricted(user):
		return None
	link = frappe.db.get_value(USER_LINK, {"user": user, "status": "active"}, "name")
	if not link:
		return []
	rows = frappe.get_all(
		"Nyabo User Company", filters={"parent": link, "parenttype": USER_LINK}, pluck="company"
	)
	return sorted({row for row in rows if row})


def _condition(doctype: str, user: str | None = None) -> str:
	"""The SQL fragment Frappe appends to every list query for `doctype`."""
	companies = allowed_companies(user)
	if companies is None:
		return ""
	column = "name" if doctype in SCOPED_BY_NAME else "company"
	table = f"`tab{doctype}`"
	if not companies:
		return f"{table}.{column} IS NULL AND 1 = 0"
	values = ", ".join(frappe.db.escape(company) for company in companies)
	# A row with no company (a global rule, an event about the site) stays visible to the
	# linked user; only rows belonging to someone else's company are hidden.
	if column == "company":
		return f"({table}.company IN ({values}) OR {table}.company IS NULL OR {table}.company = '')"
	return f"{table}.{column} IN ({values})"


def _permitted(doc: Any, user: str | None = None) -> bool:
	companies = allowed_companies(user)
	if companies is None:
		return True
	doctype = getattr(doc, "doctype", None) or (doc.get("doctype") if hasattr(doc, "get") else None)
	value = doc.get("name") if doctype in SCOPED_BY_NAME else doc.get("company")
	if not value:
		return True
	return value in companies


def build_hooks() -> tuple[dict[str, str], dict[str, str]]:
	"""(permission_query_conditions, has_permission) entries for hooks.py."""
	query = {dt: "nyabo_mn.permissions.query_conditions" for dt in SCOPED_BY_COMPANY + SCOPED_BY_NAME}
	permission = {dt: "nyabo_mn.permissions.has_permission" for dt in SCOPED_BY_COMPANY + SCOPED_BY_NAME}
	return query, permission


def query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	"""``frappe.call(handler, self.user, doctype=self.doctype)`` (frappe/model/db_query.py, v16)."""
	if not doctype:
		return ""
	return _condition(doctype, user)


def has_permission(doc: Any, ptype: str | None = None, user: str | None = None, debug: bool = False) -> bool:
	"""``frappe.call(method, doc=doc, ptype=ptype, user=user, debug=debug)`` (frappe/permissions.py, v16).

	A controller hook can only deny, never widen, so returning True here leaves the
	DocType's own permission table in charge.
	"""
	return _permitted(doc, user)


def sync_user_permissions(link_name: str) -> list[str]:
	"""One Frappe `User Permission` (Company) per company on a `Nyabo User Link`.

	This is what scopes ERPNext's own documents for a linked accountant. Admin links are
	left unrestricted. Returns the company list now in force.
	"""
	link = frappe.get_doc(USER_LINK, link_name)
	user = link.user
	companies = sorted({row.company for row in link.get("companies") or [] if row.company})
	existing = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Company"},
		fields=["name", "for_value"],
	)
	if is_unrestricted(user):
		for row in existing:
			frappe.delete_doc("User Permission", row.name, ignore_permissions=True, force=True)
		return []
	have = {row.for_value: row.name for row in existing}
	for company in companies:
		if company in have:
			continue
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Company",
				"for_value": company,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
	for company, name in have.items():
		if company not in companies:
			frappe.delete_doc("User Permission", name, ignore_permissions=True, force=True)
	return companies
