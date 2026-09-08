"""Browser-callable diagnostics.

A Frappe Cloud site on the plans Nyabo targets gives the founder no shell, so the checks
the RUNBOOK reaches with ``bench execute`` need a second door: the desk console, through
``frappe.call``. Only read-only checks belong here, only for a System Manager, and never
one that returns a secret. Anything that writes stays a bench entry point, where the
person running it has already proved they own the server.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn import config


def _only_system_manager() -> None:
	"""The Administrator always passes; everyone else must hold System Manager."""
	if frappe.session.user != "Administrator":
		frappe.only_for("System Manager")


@frappe.whitelist(methods=["GET", "POST"])
def config_check() -> dict[str, Any]:
	"""Which features are configured. Secrets answer ``<set>`` or ``<missing>``, never a value."""
	_only_system_manager()
	return config.check()


@frappe.whitelist(methods=["GET", "POST"])
def readiness() -> list[dict[str, Any]]:
	"""The compliance readiness table (RUNBOOK §"Readiness"), which reads nothing secret."""
	_only_system_manager()
	from nyabo_mn.compliance import readiness as readiness_mod

	return readiness_mod.run()
