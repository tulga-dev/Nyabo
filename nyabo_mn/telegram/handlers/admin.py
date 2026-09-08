"""Admin commands: ``/link <role> <company>`` issues a code, ``/status`` shows site health.

Admins are the link role ``Admin`` or the ids in ``ADMIN_TELEGRAM_IDS``; the second lets
the founder issue the very first accountant code before any link row exists.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.config import get_settings
from nyabo_mn.i18n import mn
from nyabo_mn.telegram import state as chat_state
from nyabo_mn.telegram.context import Ctx


def noop() -> None:
	return None


def handle_link(ctx: Ctx) -> Any:
	if not ctx.is_admin:
		ctx.reply(mn.MSG_ADMIN_ONLY)
		return None
	parts = ctx.args.split(maxsplit=1)
	if len(parts) < 2:
		ctx.reply(mn.MSG_LINK_USAGE)
		return None
	role = chat_state.ROLE_WORDS.get(parts[0].strip().lower())
	if role is None:
		ctx.reply(mn.MSG_LINK_ROLE_UNKNOWN)
		return None
	company = parts[1].strip()
	if not frappe.db.exists("Company", company):
		ctx.reply(mn.MSG_LINK_COMPANY_NOT_FOUND.format(company=company))
		return None
	code = chat_state.issue_link_code(role, company, issued_by=ctx.user)
	ctx.reply(
		mn.MSG_LINK_CODE_ISSUED.format(
			code=code.code,
			role=mn.ROLE_LABELS.get(role, role),
			company=company,
			minutes=chat_state.LINK_CODE_MINUTES,
		)
	)
	return {"code": code.code, "role": role, "company": company}


def handle_status(ctx: Ctx) -> Any:
	if not ctx.is_admin:
		ctx.reply(mn.MSG_ADMIN_ONLY)
		return None
	settings = get_settings()
	missing = [key for keys in settings.report().values() for key in keys]
	config = (
		mn.MSG_STATUS_CONFIG_OK
		if not missing
		else mn.MSG_STATUS_CONFIG_MISSING.format(keys=", ".join(sorted(set(missing))))
	)
	unmatched = frappe.db.count("Bank Transaction", {"status": ["in", ["Pending", "Unreconciled"]]})
	ctx.reply(
		mn.MSG_STATUS.format(
			companies=frappe.db.count("Company"),
			users=frappe.db.count("Nyabo User Link", {"status": "active"}),
			proposals=frappe.db.count("Nyabo Proposal", {"status": "proposed"}),
			unmatched=unmatched,
			config=config,
		)
	)
	return {"missing": missing}
