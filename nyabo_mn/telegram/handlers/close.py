"""``/хаалт YYYY-MM`` month-end (docs/ARCHITECTURE.md §5.5): checklist → summaries → PDFs → lock.

Accountant only: closing a period is the act the Law on Accounting attaches to the
accountant of record, and an owner tapping [Хаах] by accident would block their own
bookkeeping for the month. The lock itself is ``compliance.period.lock``; its refusals
(month not over, already closed, unverified rules used) come back as Mongolian text.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.core import dates
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram import _deps, cards, keyboards
from nyabo_mn.telegram.context import Ctx


def handle_command(ctx: Ctx) -> Any:
	if not ctx.company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	if not ctx.is_accountant:
		ctx.reply(mn.MSG_NO_PERMISSION)
		return {"refused": "role"}
	try:
		year, month = dates.parse_period(ctx.args)
	except ValueError:
		ctx.reply(mn.MSG_CLOSE_USAGE)
		return None
	period = f"{year:04d}-{month:02d}"
	checklist = _deps.checklist(ctx.company, period) or {}
	summaries = _deps.summaries(ctx.company, period) or {}
	ctx.reply(cards.close_card(ctx.company, period, checklist, summaries))
	for pdf in summaries.get("pdfs") or []:
		filename, content, title = _pdf_parts(pdf, period)
		ctx.send_document(
			content, filename, caption=mn.MSG_CLOSE_PDF_CAPTION.format(title=title, period=period)
		)
	ctx.reply(mn.MSG_CLOSE_CONFIRM, keyboards.close_confirm(period))
	return {"period": period, "checklist": checklist}


def _pdf_parts(pdf: Any, period: str) -> tuple[str, bytes, str]:
	"""Accept ``(filename, bytes)``, ``(filename, bytes, title)`` or a dict from the reports module."""
	if isinstance(pdf, dict):
		return (
			pdf.get("filename") or f"nyabo-{period}.pdf",
			pdf["content"],
			pdf.get("title") or pdf.get("filename") or "",
		)
	filename, content = pdf[0], pdf[1]
	title = pdf[2] if len(pdf) > 2 else filename
	return filename, content, title


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``c:<period>:confirm|cancel``."""
	if len(parts) < 3:
		return None
	_prefix, period, action = parts[:3]
	if not ctx.is_accountant:
		ctx.answer(mn.MSG_NO_PERMISSION, show_alert=True)
		return {"refused": "role"}
	if action == "cancel":
		ctx.edit(ctx.callback_message_id, mn.MSG_CLOSE_CANCELLED, keyboards.empty_markup())
		return {"cancelled": True}
	if action != "confirm" or not ctx.company:
		return None
	try:
		result = _deps.lock_period(ctx.company, period, ctx.user)
	except frappe.ValidationError as exc:
		reason = getattr(exc, "message_mn", None) or str(exc)
		ctx.edit(
			ctx.callback_message_id, mn.MSG_CLOSE_BLOCKED.format(reason=reason), keyboards.empty_markup()
		)
		log_event("telegram.close.blocked", period=period, company=ctx.company, reason=reason)
		return {"locked": False, "reason": reason}
	name = result.get("name") if isinstance(result, dict) else getattr(result, "name", result)
	ctx.edit(
		ctx.callback_message_id,
		mn.MSG_CLOSE_DONE.format(period=dates.period_label(period), name=name),
		keyboards.empty_markup(),
	)
	log_event("telegram.close.locked", period=period, company=ctx.company, name=name, user=ctx.user)
	return {"locked": True, "name": name}
