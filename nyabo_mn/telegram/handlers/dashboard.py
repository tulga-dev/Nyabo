"""The dashboard and the cards a tap on it opens: ``/меню`` and every ``d:<view>`` callback.

One entry point per view, all read-only: the dashboard reads the ledger, the bank status, the
proposal table and the rules that would refuse a post, and draws what the accountant should
do next. Nothing here changes the books — the one action a card offers (a proposal's «Харах»,
a bank line's «Тулгах») brings the *existing* card back with its own buttons, so approval
keeps going through ``handlers.approve`` and ``handlers.bank`` and their guards.

A tap edits the card it came from in place (``ctx.edit_card``): the chat does not fill with
dashboards. A command sends a fresh one. Either way the company is the caller's active
company, never something read off the datum (TG-03).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import frappe

from nyabo_mn.core import dates
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_error, log_event
from nyabo_mn.reports import dashboard as data
from nyabo_mn.telegram import richcards
from nyabo_mn.telegram.context import Ctx


def _today() -> dt.date:
	return dt.date.today()


def _period(arg: str | None, today: dt.date) -> str:
	"""A ``YYYY-MM`` off the datum, else this month; a bad one is this month, not an error."""
	if arg:
		try:
			year, month = dates.parse_period(arg)
			return f"{year:04d}-{month:02d}"
		except ValueError:
			log_event("telegram.dashboard.bad_period", level="warning", period=arg[:16])
	return dates.period_of(today)


def _commands_text(ctx: Ctx) -> str:
	text = mn.MSG_MENU
	if ctx.is_admin:
		text += "\n\n" + mn.MSG_ADMIN_HELP
	return text


def home_card(ctx: Ctx, company: str) -> Any:
	overview = data.overview(company, _today())
	from nyabo_mn import miniapp

	return richcards.dashboard_card(overview, commands_text=_commands_text(ctx), app_url=miniapp.page_url())


def send_home(ctx: Ctx, company: str) -> Any:
	"""A fresh dashboard (``/меню``, ``/start``, the [Цэс] escape)."""
	ctx.reply_card(home_card(ctx, company))
	return {"view": richcards.VIEW_HOME, "company": company}


# --- the callback: d:<view>[:<period>] ---------------------------------------------------------------


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	ctx.answer()  # first, so the client stops spinning while the ledger is read
	company = ctx.company
	if not company or company not in ctx.companies:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	view = parts[1] if len(parts) > 1 else richcards.VIEW_HOME
	arg = parts[2] if len(parts) > 2 else None
	if view not in richcards.VIEWS:
		log_event("telegram.dashboard.unknown_view", level="warning", data=ctx.callback_data[:64])
		view = richcards.VIEW_HOME
	today = _today()
	message_id = ctx.callback_message_id
	try:
		return _open(ctx, company, view, arg, today, message_id)
	except Exception as exc:  # noqa: BLE001 - the dashboard is the way to everything else
		log_error("telegram.dashboard.failed", exc, view=view, company=company)
		ctx.reply(mn.MSG_ERROR_NO_BUTTON)
		return {"view": view, "error": type(exc).__name__}


def _open(ctx: Ctx, company: str, view: str, arg: str | None, today: dt.date, message_id: int | None) -> Any:
	V = richcards
	if view == V.VIEW_HOME:
		ctx.edit_card(message_id, home_card(ctx, company))
	elif view == V.VIEW_TRANSACTIONS:
		period = _period(arg, today)
		ctx.edit_card(
			message_id,
			richcards.transactions_card(
				data.recent_vouchers(company, period), data.pending_proposals(company)
			),
		)
	elif view == V.VIEW_PENDING:
		ctx.edit_card(message_id, richcards.pending_card(data.pending_proposals(company)))
	elif view == V.VIEW_BANK:
		ctx.edit_card(message_id, richcards.bank_card(data.bank_summary(company, today), today))
	elif view == V.VIEW_REPORTS:
		from nyabo_mn import miniapp

		ctx.edit_card(message_id, richcards.reports_card(_period(arg, today), miniapp.page_url()))
	elif view == V.VIEW_TREND:
		ctx.edit_card(message_id, richcards.trend_card(data.trend_rows(company, today)))
	elif view == V.VIEW_TOP:
		ctx.edit_card(
			message_id, richcards.top_expenses_card(data.top_expenses(company, _period(arg, today)))
		)
	elif view == V.VIEW_PROFIT_LOSS:
		period = _period(arg, today)
		ctx.edit_card(
			message_id,
			richcards.profit_loss_card(
				data.month_with_delta(company, period), data.top_expenses(company, period)
			),
		)
	elif view == V.VIEW_TRIAL_BALANCE:
		period = _period(arg, today)
		from nyabo_mn.reports import month_end

		ctx.edit_card(
			message_id, richcards.trial_balance_card(month_end.trial_balance(company, period), period)
		)
	elif view in (V.VIEW_TB_PDF, V.VIEW_TB_XLSX):
		return _send_trial_balance_file(ctx, company, _period(arg, today), xlsx=view == V.VIEW_TB_XLSX)
	elif view == V.VIEW_INVENTORY:
		ctx.edit_card(message_id, richcards.inventory_card(data.inventory(company), today))
	elif view == V.VIEW_UNMATCHED:
		return _send_unmatched(ctx, company)
	elif view == V.VIEW_STATEMENT_HINT:
		ctx.reply(mn.CARD_STATEMENT_HINT)
	return {"view": view, "company": company}


def _send_trial_balance_file(ctx: Ctx, company: str, period: str, *, xlsx: bool) -> Any:
	"""The trial balance as a file: the rows the card summarised, on the report form."""
	from nyabo_mn.reports import export, month_end

	start, end = dates.period_bounds(period)
	filters = {"company": company, "from_date": start.isoformat(), "to_date": end.isoformat()}
	label = dates.period_label(period)
	tb = month_end.trial_balance(company, period)
	columns = [
		{"label": mn.COL_ACCOUNT_CODE, "fieldname": "account_code", "fieldtype": "Data"},
		{"label": mn.COL_ACCOUNT, "fieldname": "account", "fieldtype": "Data"},
		{"label": mn.COL_DEBIT, "fieldname": "debit", "fieldtype": "Currency"},
		{"label": mn.COL_CREDIT, "fieldname": "credit", "fieldtype": "Currency"},
	]
	rows = [
		*tb["rows"],
		{"account": mn.LBL_TOTAL, "account_code": "", "debit": tb["debit"], "credit": tb["credit"]},
	]
	if xlsx:
		content = export.rows_to_xlsx(mn.REPORT_TRIAL_BALANCE, columns, rows)
		filename = f"trial_balance_{period}.xlsx"
	else:
		content = export.rows_to_pdf(mn.REPORT_TRIAL_BALANCE, company, label, columns, rows, filters)
		filename = f"trial_balance_{period}.pdf"
	ctx.send_document(content, filename, caption=f"{mn.REPORT_TRIAL_BALANCE} · {label}")
	return {"view": "tbfile", "filename": filename}


def _send_unmatched(ctx: Ctx, company: str, limit: int = 3) -> Any:
	"""The unmatched statement lines' own cards, newest first — each with its matching buttons."""
	from nyabo_mn.telegram.handlers import bank as bank_handler

	rows = frappe.get_all(
		"Bank Transaction",
		filters={"company": company, "docstatus": 1, "status": ["in", ["Pending", "Unreconciled"]]},
		fields=["name"],
		order_by="date desc, name desc",
		limit=limit,
	)
	if not rows:
		ctx.reply(mn.CARD_UNMATCHED_NONE)
		return {"view": richcards.VIEW_UNMATCHED, "sent": 0}
	for row in rows:
		bank_handler.send_bank_card(ctx.bot, ctx.chat_id, row["name"])
	return {"view": richcards.VIEW_UNMATCHED, "sent": len(rows)}


__all__ = ["handle_callback", "home_card", "send_home"]
