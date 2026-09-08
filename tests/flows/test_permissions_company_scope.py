"""SEC-06: a linked accountant sees only their own clients' rows.

The Telegram handlers check the company on every callback, but those checks are the first
line only. These tests exercise the second line: the ``permission_query_conditions`` and
``has_permission`` hooks, and the Frappe ``User Permission`` rows a link creates.
"""

from __future__ import annotations

import frappe
import pytest

from nyabo_mn import permissions
from nyabo_mn.telegram import state

OTHER_COMPANY = "Өөр ХХК"
OTHER_ABBR = "OTH"
ACCOUNTANT_A = "acc-a@example.com"
ACCOUNTANT_B = "acc-b@example.com"


def _company_b() -> str:
	from nyabo_mn.setup.provision_company import provision_company

	if not frappe.db.exists("Company", OTHER_COMPANY):
		provision_company(OTHER_COMPANY, OTHER_ABBR, vat_registered=0)
	return OTHER_COMPANY


def _link(user: str, telegram_id: str, company: str, role: str = "Accountant") -> str:
	"""A link straight through the production path, so User Permissions are written too."""
	if not frappe.db.exists("User", user):
		doc = frappe.get_doc({"doctype": "User", "email": user, "first_name": user.split("@")[0]})
		doc.flags.ignore_permissions = True
		doc.insert()
	code = state.issue_link_code(role, company, "Administrator")
	link = state.consume_link_code(code.code, {"id": telegram_id, "first_name": user.split("@")[0]})
	link.user = user
	link.flags.ignore_permissions = True
	link.save()
	permissions.sync_user_permissions(link.name)
	return link.name


def _proposal(company: str) -> str:
	document = frappe.get_doc(
		{
			"doctype": "Nyabo Document",
			"company": company,
			"doc_type": "receipt",
			"file": "/private/files/r.jpg",
			"file_hash": f"h-{company}",
		}
	).insert(ignore_permissions=True)
	return (
		frappe.get_doc(
			{
				"doctype": "Nyabo Proposal",
				"company": company,
				"document": document.name,
				"kind": "receipt",
				"status": "proposed",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def test_allowed_companies_follows_the_link(company):
	other = _company_b()
	_link(ACCOUNTANT_A, "8801", company)
	assert permissions.allowed_companies(ACCOUNTANT_A) == [company]
	_link(ACCOUNTANT_B, "8802", other)
	assert permissions.allowed_companies(ACCOUNTANT_B) == [other]
	# The Administrator and the admin roles read across companies by design.
	assert permissions.allowed_companies("Administrator") is None


def test_a_user_with_no_link_sees_nothing():
	condition = permissions.query_conditions("stranger@example.com", doctype="Nyabo Proposal")
	assert "1 = 0" in condition


def test_query_condition_names_only_the_linked_companies(company):
	other = _company_b()
	_link(ACCOUNTANT_A, "8801", company)
	condition = permissions.query_conditions(ACCOUNTANT_A, doctype="Nyabo Proposal")
	assert "`tabNyabo Proposal`.company" in condition
	assert company in condition and other not in condition


def test_has_permission_denies_another_companys_proposal(company):
	other = _company_b()
	_link(ACCOUNTANT_A, "8801", company)
	mine = frappe.get_doc("Nyabo Proposal", _proposal(company))
	theirs = frappe.get_doc("Nyabo Proposal", _proposal(other))
	assert permissions.has_permission(mine, user=ACCOUNTANT_A) is True
	assert permissions.has_permission(theirs, user=ACCOUNTANT_A) is False
	# The admin path is unaffected.
	assert permissions.has_permission(theirs, user="Administrator") is True


def test_company_settings_are_scoped_by_name(company):
	other = _company_b()
	_link(ACCOUNTANT_A, "8801", company)
	condition = permissions.query_conditions(ACCOUNTANT_A, doctype="Nyabo Company Settings")
	assert "`tabNyabo Company Settings`.name" in condition and other not in condition
	theirs = frappe.get_doc("Nyabo Company Settings", other)
	assert permissions.has_permission(theirs, user=ACCOUNTANT_A) is False


def test_linking_writes_and_prunes_user_permissions(company):
	other = _company_b()
	link_name = _link(ACCOUNTANT_A, "8801", company)
	values = frappe.get_all(
		"User Permission", filters={"user": ACCOUNTANT_A, "allow": "Company"}, pluck="for_value"
	)
	assert values == [company]

	link = frappe.get_doc("Nyabo User Link", link_name)
	link.append("companies", {"company": other})
	link.flags.ignore_permissions = True
	link.save()
	permissions.sync_user_permissions(link_name)
	assert sorted(
		frappe.get_all(
			"User Permission", filters={"user": ACCOUNTANT_A, "allow": "Company"}, pluck="for_value"
		)
	) == sorted([company, other])

	# Removing the company removes the permission, so access does not outlive the link.
	link = frappe.get_doc("Nyabo User Link", link_name)
	link.companies = [row for row in link.companies if row.company != other]
	link.flags.ignore_permissions = True
	link.save()
	permissions.sync_user_permissions(link_name)
	assert frappe.get_all(
		"User Permission", filters={"user": ACCOUNTANT_A, "allow": "Company"}, pluck="for_value"
	) == [company]


def test_every_scoped_doctype_is_registered_in_hooks():
	from nyabo_mn import hooks

	expected = set(permissions.SCOPED_BY_COMPANY) | set(permissions.SCOPED_BY_NAME)
	assert set(hooks.permission_query_conditions) == expected
	assert set(hooks.has_permission) == expected
	for doctype in expected:
		assert frappe.db.exists("DocType", doctype), doctype


@pytest.mark.parametrize("doctype", sorted(permissions.SCOPED_BY_COMPANY))
def test_scoped_doctypes_really_have_a_company_field(doctype: str):
	assert frappe.get_meta(doctype).has_field("company"), doctype
