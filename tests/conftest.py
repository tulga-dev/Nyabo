"""Test bootstrap: the repo on sys.path and, without a bench, the in-memory Frappe stub.

Pure-Python tests (core, agent, ...) need nothing from here beyond the path. Tests that
touch Frappe ask for the ``site`` fixture (fresh stub site) or ``company`` (a provisioned
"Тест ХХК"), and use ``as_user`` / ``frappe_flags`` / ``frappe_hooks`` to change the
session, the flags or the hooks for one block.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STUB_ROOT = REPO_ROOT / "tests" / "frappe_stub"
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

try:
	import frappe  # noqa: F401 - a real bench wins when it is importable
except ImportError:
	if str(STUB_ROOT) not in sys.path:
		sys.path.insert(0, str(STUB_ROOT))

TEST_COMPANY = "Тест ХХК"
TEST_ABBR = "TST"
SITE_ROLES = ("Nyabo Admin", "Nyabo Accountant", "Nyabo Owner", "System Manager")
SITE_CURRENCIES = (("MNT", "₮", 1), ("USD", "$", 1))


def _is_stub() -> bool:
	import frappe

	return hasattr(frappe, "_stub")


@pytest.fixture
def site() -> Iterator[Any]:
	"""A fresh stub site: roles, currencies, Administrator + Guest users, Administrator session."""
	import frappe

	if not _is_stub():
		pytest.skip("the site fixture drives the in-memory stub; run bench tests on a real site instead")
	local = frappe._stub.reset()
	for role in SITE_ROLES:
		frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
			ignore_permissions=True
		)
	for name, symbol, enabled in SITE_CURRENCIES:
		frappe.get_doc(
			{
				"doctype": "Currency",
				"currency_name": name,
				"symbol": symbol,
				"enabled": enabled,
				"fraction_units": 100,
			}
		).insert(ignore_permissions=True)
	for email, first_name in (("admin@example.com", "Administrator"), ("guest@example.com", "Guest")):
		user = frappe.get_doc({"doctype": "User", "email": email, "first_name": first_name})
		user.flags.ignore_permissions = True
		user.insert(set_name=first_name)
	frappe.set_user("Administrator")
	yield local
	local.destroy()


@pytest.fixture
def company(site: Any) -> str:
	"""``provision_company("Тест ХХК", "TST", vat_registered=0)`` through the stub; returns the name."""
	from nyabo_mn.setup.provision_company import provision_company

	report = provision_company(TEST_COMPANY, TEST_ABBR, vat_registered=0)
	assert report["verify"]["ok"], report["verify"]["problems"]
	return TEST_COMPANY


@pytest.fixture
def as_user(site: Any) -> Any:
	"""``with as_user("acc@example.com", ["Nyabo Accountant"]): ...`` creates the user if needed."""
	import frappe

	@contextmanager
	def _as_user(name: str, roles: list[str] | tuple[str, ...] = ()) -> Iterator[str]:
		previous = frappe.session.user
		if not frappe.db.exists("User", name):
			doc = frappe.get_doc({"doctype": "User", "email": name, "first_name": name.split("@")[0]})
			doc.flags.ignore_permissions = True
			doc.insert()
		if roles:
			user = frappe.get_doc("User", name)
			user.flags.ignore_permissions = True
			user.add_roles(*roles)
		frappe.set_user(name)
		try:
			yield name
		finally:
			frappe.set_user(previous)

	return _as_user


@pytest.fixture
def frappe_flags(site: Any) -> Any:
	"""``with frappe_flags(stub_strict_links=True): ...`` sets flags and restores them after."""
	import frappe

	@contextmanager
	def _flags(**values: Any) -> Iterator[None]:
		saved = {key: frappe.flags.get(key) for key in values}
		frappe.flags.update(values)
		try:
			yield
		finally:
			for key, value in saved.items():
				if value is None:
					frappe.flags.pop(key, None)
				else:
					frappe.flags[key] = value

	return _flags


@pytest.fixture
def frappe_hooks(site: Any) -> Any:
	"""``with frappe_hooks(doc_events={...}): ...`` adds hooks; ``replace=True`` uses only those."""
	from frappe._stub.hooks import temporary_hooks

	return temporary_hooks
