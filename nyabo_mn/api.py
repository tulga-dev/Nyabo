"""Browser-callable setup and diagnostics.

A Frappe Cloud site on the plans Nyabo targets gives the founder no shell: the site's
Actions tab offers migrations, backups and a SQL playground, and no Python console. So
everything the RUNBOOK reaches with ``bench execute`` needs a second door — the desk
console, through ``frappe.call``. Without it the bot could never be pointed at the site
at all.

What belongs here: the read-only checks, and the one-off setup calls that configure
Nyabo's own Telegram bot. What does not: anything that posts to the ledger (a human taps
for that, principle 3), anything that returns a secret, and anything a person who is not a
System Manager should be able to run. Every function here guards on that role first.
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
	"""Which features are configured, and which model each purpose will run on.

	Secrets answer ``<set>`` or ``<missing>``, never a value. ``models.by_purpose`` is the
	routing resolved, not the keys that are set: a purpose with no key of its own still runs
	the model chosen in code, so this is the only place the founder can see - without a
	shell - that extraction is on Terra and classification on Astra, and check it against
	the model recorded on the last ``Nyabo LLM Call``.
	"""
	_only_system_manager()
	return config.check()


@frappe.whitelist(methods=["GET", "POST"])
def readiness() -> list[dict[str, Any]]:
	"""The compliance readiness table (RUNBOOK §"Readiness"), which reads nothing secret."""
	_only_system_manager()
	from nyabo_mn.compliance import readiness as readiness_mod

	return readiness_mod.run()


@frappe.whitelist(methods=["POST"])
def setup_webhook(site_url: str | None = None) -> dict[str, Any]:
	"""Point the Telegram bot at this site. Idempotent; answers the URL Telegram accepted.

	POST only, because it changes where Telegram delivers every update. It reaches nothing
	but the founder's own bot, and the token never leaves the site: ``set_webhook`` sends
	the secret to Telegram, and what comes back here names only the URL.
	"""
	_only_system_manager()
	from nyabo_mn.telegram import webhook as webhook_mod

	return webhook_mod.setup_webhook(site_url)


@frappe.whitelist(methods=["POST"])
def setup_commands() -> dict[str, Any]:
	"""Register the ☰ command menu with Telegram. Idempotent; answers the commands sent."""
	_only_system_manager()
	from nyabo_mn.telegram import commands as commands_mod

	return commands_mod.setup_commands()


@frappe.whitelist(methods=["POST"])
def seed_demo(company: str, allow_existing_postings: int | str = 0) -> dict[str, Any]:
	"""Fill a test company's ledger with six months of demo vouchers (``setup.demo``).

	POST only, System Manager only, and the module refuses a ledger that already holds a
	posting unless ``allow_existing_postings=1`` says this is the test company whose own trial
	receipts are in it — so a mis-typed company name answers with the refusal.
	"""
	_only_system_manager()
	from nyabo_mn.setup import demo

	try:
		return demo.seed(company, allow_existing_postings=bool(int(allow_existing_postings or 0)))
	except demo.DemoRefused as exc:
		frappe.throw(str(exc))
		raise  # unreachable


@frappe.whitelist(methods=["POST"])
def unseed_demo(company: str) -> dict[str, Any]:
	"""Cancel the demo vouchers ``seed_demo`` wrote (they stay, cancelled); nothing else is touched."""
	_only_system_manager()
	from nyabo_mn.setup import demo

	try:
		return demo.unseed(company)
	except demo.DemoRefused as exc:
		frappe.throw(str(exc))
		raise  # unreachable
