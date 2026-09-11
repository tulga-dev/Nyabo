"""The rich cards an accountant reads in the chat: dashboard, transactions, bank, reports, answers.

Builders only. Each takes figures ``reports.dashboard`` (or a books query) already computed
and returns a ``rich.Card``; the handlers decide when to send and what to edit. Every sentence
here is deterministic — a template from ``i18n.mn`` filled with ledger figures — so the one
place a model's words appear is ``answer_card``, where the paragraph is the model's sentence
and the table under it is the handler's rows (principle 7: the model writes sentences, code
writes every number).

Callback data on the buttons is ``d:<view>[:<period>]`` (``keyboards.PREFIX_DASHBOARD``): the
view names below, a period where the card can page months. A datum never carries the company —
callback data is attacker-chosen (TG-03), and the handler answers about the caller's own
active company.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from nyabo_mn.core import dates
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.telegram import keyboards, rich
from nyabo_mn.telegram.rich import (
	ALIGN_RIGHT,
	STYLE_LINK,
	STYLE_PRIMARY,
	Button,
	Buttons,
	Card,
	Cell,
	CheckItem,
	Checklist,
	Details,
	Footer,
	Heading,
	Paragraph,
	Table,
	Thinking,
	card,
)

# --- the views a dashboard button can open (the second part of a ``d:`` datum) --------------------
VIEW_HOME = "home"
VIEW_TRANSACTIONS = "tx"
VIEW_BANK = "bank"
VIEW_REPORTS = "rep"
VIEW_TREND = "rev"
VIEW_TOP = "top"
VIEW_TRIAL_BALANCE = "tb"
VIEW_PROFIT_LOSS = "pl"
VIEW_INVENTORY = "inv"
VIEW_PENDING = "pend"
VIEW_UNMATCHED = "unm"
VIEW_STATEMENT_HINT = "stm"
VIEW_TB_PDF = "tbpdf"
VIEW_TB_XLSX = "tbx"
VIEW_RULES = "rules"
VIEWS = (
	VIEW_RULES,
	VIEW_HOME,
	VIEW_TRANSACTIONS,
	VIEW_BANK,
	VIEW_REPORTS,
	VIEW_TREND,
	VIEW_TOP,
	VIEW_TRIAL_BALANCE,
	VIEW_PROFIT_LOSS,
	VIEW_INVENTORY,
	VIEW_PENDING,
	VIEW_UNMATCHED,
	VIEW_STATEMENT_HINT,
	VIEW_TB_PDF,
	VIEW_TB_XLSX,
)

ZERO = Decimal("0")
TB_ROWS_LIMIT = 8


def datum(view: str, *args: Any) -> str:
	return keyboards.encode(keyboards.PREFIX_DASHBOARD, view, *args)


def mnt(value: Any) -> str:
	return f"{fmt_mnt(value)}₮"


def _date(value: Any) -> dt.date:
	if isinstance(value, dt.datetime):
		return value.date()
	if isinstance(value, dt.date):
		return value
	return dt.date.fromisoformat(str(value)[:10])


def _signed(amount: Decimal, direction: str) -> str:
	if direction == "out":
		return f"−{fmt_mnt(abs(amount))}"
	if direction == "in":
		return f"+{fmt_mnt(abs(amount))}"
	return fmt_mnt(amount)


def _delta(pct: int | None) -> str:
	if pct is None:
		return mn.CARD_DELTA_NONE
	return mn.CARD_DELTA.format(sign="+" if pct > 0 else "", pct=pct)


def _header(*labels: str, right_from: int | None = None) -> list[Cell]:
	return [
		Cell(label, header=True, align=ALIGN_RIGHT if right_from is not None and i >= right_from else None)
		for i, label in enumerate(labels)
	]


def _r(value: Any) -> Cell:
	return Cell(value, align=ALIGN_RIGHT)


def _period_row(view: str, period: str) -> Buttons:
	"""← last month · next month → for a card that pages by month."""
	from nyabo_mn.reports.dashboard import shift_period

	previous, following = shift_period(period, -1), shift_period(period, 1)
	return Buttons(
		[
			Button(
				mn.BTN_Q_PREV_PERIOD.format(period=dates.period_label(previous)), data=datum(view, previous)
			),
			Button(
				mn.BTN_Q_NEXT_PERIOD.format(period=dates.period_label(following)), data=datum(view, following)
			),
		]
	)


def _home_row(*extra: Button) -> Buttons:
	return Buttons([*extra, Button(mn.BTN_DASHBOARD, data=datum(VIEW_HOME), style=STYLE_LINK)])


# --- dashboard --------------------------------------------------------------------------------------


def dashboard_card(
	overview: Mapping[str, Any],
	*,
	commands_text: str,
	now: dt.datetime | None = None,
	app_url: str | None = None,
	note: Any = None,
) -> Card:
	"""``app_url`` is the Mini App page (``miniapp.page_url``); None on a site without HTTPS,
	because Telegram opens only https ``web_app`` URLs and a bad one refuses the whole card.
	``note`` is the day's ``insights.Note`` (or None): the accountant's paragraph over the
	signals the detectors found, drawn above «Таны ээлж» with one button per signal."""
	company = str(overview["company"])
	today: dt.date = overview["today"]
	period = str(overview["period"])
	month = overview.get("month")
	banks: Sequence[Mapping[str, Any]] = overview.get("banks") or []
	pending: Mapping[str, int] = overview.get("pending") or {}
	stamp = (now or dt.datetime.now()).strftime("%H:%M")

	blocks: list[Any] = [
		Heading(mn.CARD_DASHBOARD_TITLE.format(company=company), size=3),
		Paragraph(mn.MSG_ACTIVE_COMPANY.format(company=company)),
	]
	if month is None:
		blocks.append(Paragraph(mn.CARD_SECTION_FAILED))
	elif month["revenue"] == ZERO and month["expense"] == ZERO:
		blocks.append(Paragraph(mn.CARD_MONTH_EMPTY))
	else:
		blocks.append(
			Table(
				[
					_header(
						mn.CARD_MONTH_HEADING.format(period=dates.period_label(period)),
						mn.COL_AMOUNT,
						mn.CARD_COL_CHANGE,
						right_from=1,
					),
					[
						mn.CARD_REVENUE,
						_r(rich.bold(mnt(month["revenue"]))),
						_r(_delta(month["revenue_delta_pct"])),
					],
					[mn.CARD_EXPENSE, _r(mnt(month["expense"])), _r(_delta(month["expense_delta_pct"]))],
					[
						mn.CARD_PROFIT,
						_r(rich.bold(mnt(month["profit"]))),
						_r(_delta(month["profit_delta_pct"])),
					],
				]
			)
		)
	blocks.append(Heading(mn.CARD_BANKS_HEADING, size=5))
	if banks:
		rows: list[list[Any]] = [_header(mn.COL_ACCOUNT, mn.COL_BALANCE, mn.CARD_COL_RECON, right_from=1)]
		for row in banks:
			rows.append([_bank_label(row), _r(mnt(row["ledger_balance"])), _r(_recon_cell(row))])
		blocks.append(Table(rows))
	else:
		blocks.append(Paragraph(mn.MSG_RECON_NONE))
	if note is not None and note.text:
		blocks.append(Heading(mn.INS_HEADING, size=5))
		blocks.append(Paragraph(note.text))
		buttons = signal_buttons(note.signals)
		if buttons:
			blocks.append(Buttons(buttons))
	blocks.append(Heading(mn.CARD_YOUR_TURN, size=5))
	todo = [
		CheckItem(mn.CARD_TODO_PROPOSALS.format(count=pending.get("proposals", 0)))
		if pending.get("proposals")
		else None,
		CheckItem(mn.CARD_TODO_UNMATCHED.format(count=pending.get("unmatched", 0)))
		if pending.get("unmatched")
		else None,
		CheckItem(mn.CARD_TODO_RULES.format(count=pending.get("rules", 0))) if pending.get("rules") else None,
	]
	todo = [item for item in todo if item is not None]
	blocks.append(Checklist(todo) if todo else Paragraph(mn.CARD_TODO_NONE))
	blocks.append(
		Buttons(
			[
				Button(mn.BTN_TRANSACTIONS, data=datum(VIEW_TRANSACTIONS, period)),
				Button(mn.BTN_BANK, data=datum(VIEW_BANK)),
				Button(mn.BTN_REPORTS, data=datum(VIEW_REPORTS)),
			]
		)
	)
	second = [Button(mn.BTN_REFRESH, data=datum(VIEW_HOME), style=STYLE_LINK)]
	if pending.get("proposals"):
		second.insert(
			0,
			Button(
				mn.BTN_PROPOSALS.format(count=pending["proposals"]),
				data=datum(VIEW_PENDING),
				style=STYLE_PRIMARY,
			),
		)
	blocks.append(Buttons(second))
	if app_url:
		blocks.append(Buttons([Button(mn.BTN_MINI_APP, web_app=app_url)]))
	blocks.append(Details(mn.CARD_COMMANDS, [Paragraph(commands_text)]))
	blocks.append(Footer(mn.CARD_FOOT_LEDGER.format(time=f"{today.isoformat()} {stamp}")))
	return Card(blocks)


def signal_buttons(found: Sequence[Any]) -> list[Button]:
	"""One button per signal that has somewhere to go, loudest first, at most three."""
	from nyabo_mn.agent import insights

	out: list[Button] = []
	for s in insights.actions(found):
		if s.action_view not in VIEWS:
			continue
		args = (s.action_arg,) if s.action_arg else ()
		out.append(Button(str(s.action_label or s.kind)[:40], data=datum(s.action_view, *args)))
	return out


def notes_card(company: str, text: str, found: Sequence[Any]) -> Card:
	"""The morning push: the note, its buttons, and the way to the dashboard."""
	buttons = signal_buttons(found)
	return card(
		Heading(mn.INS_PUSH_TITLE.format(company=company)),
		Paragraph(text),
		Buttons(buttons) if buttons else None,
		_home_row(),
		Footer(mn.INS_FOOT_CODE),
	)


def _bank_label(row: Mapping[str, Any]) -> str:
	bank = mn.BANK_NAMES_MN.get(str(row.get("bank")), str(row.get("bank") or "—"))
	number = str(row.get("account_number") or "")
	tail = f" …{number[-4:]}" if len(number) >= 4 else ""
	currency = str(row.get("currency") or "MNT")
	return f"{bank}{tail}" + (f" ({currency})" if currency != "MNT" else "")


def _recon_cell(row: Mapping[str, Any]) -> Any:
	if row.get("unmatched"):
		return rich.mark(mn.CARD_RECON_UNMATCHED.format(count=row["unmatched"]))
	if row.get("statement_source") == "transactions" and row.get("statement_balance") == ZERO:
		return mn.CARD_RECON_NO_STATEMENT
	return mn.CARD_RECON_OK


# --- transactions -------------------------------------------------------------------------------------


def transactions_card(vouchers: Mapping[str, Any], pending: Sequence[Mapping[str, Any]]) -> Card:
	period = str(vouchers["period"])
	rows: Sequence[Mapping[str, Any]] = vouchers.get("rows") or []
	label = dates.period_label(period)
	blocks: list[Any] = [Heading(mn.CARD_TX_TITLE.format(period=label))]
	if rows:
		outflow = sum((r["amount"] for r in rows if r["direction"] == "out"), ZERO)
		inflow = sum((r["amount"] for r in rows if r["direction"] == "in"), ZERO)
		blocks.append(
			Paragraph(
				mn.CARD_TX_META.format(
					count=vouchers.get("count", len(rows)), outflow=fmt_mnt(outflow), inflow=fmt_mnt(inflow)
				)
			)
		)
		table: list[list[Any]] = [
			_header(mn.COL_DATE, mn.COL_DESCRIPTION, mn.COL_AMOUNT, mn.CARD_COL_STATUS, right_from=2)
		]
		for r in rows:
			table.append(
				[
					dates.short_date_mn(_date(r["date"])) if r.get("date") else "",
					r["label"],
					_r(_signed(r["amount"], r["direction"])),
					mn.CARD_STATUS_POSTED,
				]
			)
		for p in pending:
			table.append(
				[
					dates.short_date_mn(_date(p["date"])) if p.get("date") else "",
					p["label"],
					_r(f"−{fmt_mnt(p['total'])}"),
					rich.mark(mn.CARD_STATUS_PENDING),
				]
			)
		blocks.append(Table(table, striped=True))
		if vouchers.get("count", 0) > len(rows):
			blocks.append(Paragraph(mn.CARD_TX_SHOWN.format(shown=len(rows), count=vouchers["count"])))
	else:
		blocks.append(Paragraph(mn.CARD_TX_NONE.format(period=label)))
		if pending:
			blocks.append(
				Table(
					[_header(mn.COL_DATE, mn.COL_DESCRIPTION, mn.COL_AMOUNT, right_from=2)]
					+ [
						[
							dates.short_date_mn(_date(p["date"])) if p.get("date") else "",
							p["label"],
							_r(mnt(p["total"])),
						]
						for p in pending
					],
					caption=mn.CARD_PENDING_HEADING.format(count=len(pending)),
				)
			)
	blocks.append(_period_row(VIEW_TRANSACTIONS, period))
	extra = (
		[Button(mn.BTN_PROPOSALS.format(count=len(pending)), data=datum(VIEW_PENDING), style=STYLE_PRIMARY)]
		if pending
		else []
	)
	blocks.append(_home_row(*extra))
	blocks.append(Footer(mn.CARD_FOOT_COMPUTED))
	return Card(blocks)


def pending_card(pending: Sequence[Mapping[str, Any]]) -> Card:
	"""The proposals waiting for a tap, each with the button that brings its own card back."""
	if not pending:
		return card(Paragraph(mn.CARD_PENDING_NONE), _home_row())
	blocks: list[Any] = [Heading(mn.CARD_PENDING_TITLE.format(count=len(pending)))]
	for p in pending:
		date = _date(p["date"]).isoformat() if p.get("date") else "—"
		blocks.append(
			Paragraph(
				mn.CARD_PENDING_LINE.format(date=date, label=p["label"] or "—", total=fmt_mnt(p["total"]))
			)
		)
		blocks.append(
			Buttons([Button(mn.BTN_SHOW, data=keyboards.encode(keyboards.PREFIX_PROPOSAL, p["name"], "sh"))])
		)
	blocks.append(Paragraph(mn.CARD_PENDING_HINT))
	blocks.append(_home_row())
	return Card(blocks)


# --- bank balances --------------------------------------------------------------------------------------


def bank_card(rows: Sequence[Mapping[str, Any]], today: dt.date) -> Card:
	if not rows:
		return card(
			Paragraph(mn.MSG_RECON_NONE),
			_home_row(Button(mn.BTN_SEND_STATEMENT, data=datum(VIEW_STATEMENT_HINT))),
		)
	table: list[list[Any]] = [
		_header(mn.COL_ACCOUNT, mn.CARD_COL_LEDGER, mn.CARD_COL_STATEMENT, mn.CARD_COL_DIFF, right_from=1)
	]
	notes: list[Any] = []
	unmatched_total = 0
	for row in rows:
		diff = row["diff"]
		table.append(
			[
				_bank_label(row),
				_r(fmt_mnt(row["ledger_balance"])),
				_r(fmt_mnt(row["statement_balance"])),
				_r(rich.mark(fmt_mnt(diff)) if diff != ZERO else fmt_mnt(diff)),
			]
		)
		unmatched_total += int(row.get("unmatched") or 0)
		if diff != ZERO or row.get("unmatched"):
			notes.append(
				mn.CARD_BANK_DIFF_NOTE.format(
					bank=_bank_label(row), diff=fmt_mnt(diff), count=int(row.get("unmatched") or 0)
				)
			)
	blocks: list[Any] = [Heading(mn.CARD_BANK_TITLE.format(date=today.isoformat())), Table(table)]
	blocks.extend(Paragraph(note) for note in notes)
	if not notes:
		blocks.append(Paragraph(mn.CARD_BANK_ALL_MATCHED))
	actions = []
	if unmatched_total:
		actions.append(Button(mn.BTN_RECONCILE, data=datum(VIEW_UNMATCHED), style=STYLE_PRIMARY))
	actions.append(Button(mn.BTN_SEND_STATEMENT, data=datum(VIEW_STATEMENT_HINT)))
	blocks.append(Buttons(actions))
	blocks.append(_home_row())
	as_of = max(_date(row["as_of"]) for row in rows)
	blocks.append(Footer(mn.CARD_BANK_SOURCE.format(date=as_of.isoformat())))
	return Card(blocks)


# --- reports ---------------------------------------------------------------------------------------------


def reports_card(period: str, app_url: str | None = None) -> Card:
	return card(
		Heading(mn.CARD_REPORTS_TITLE),
		Paragraph(mn.CARD_REPORTS_HINT),
		Buttons(
			[
				Button(mn.REPORT_TRIAL_BALANCE, data=datum(VIEW_TRIAL_BALANCE, period)),
				Button(mn.BTN_R_PL, data=datum(VIEW_PROFIT_LOSS, period)),
			]
		),
		Buttons(
			[
				Button(mn.BTN_R_TREND, data=datum(VIEW_TREND)),
				Button(mn.BTN_Q_TOP_ACCOUNTS, data=datum(VIEW_TOP, period)),
			]
		),
		Buttons(
			[
				Button(mn.BTN_R_INVENTORY, data=datum(VIEW_INVENTORY)),
				Button(mn.BTN_R_UNMATCHED, data=datum(VIEW_UNMATCHED)),
			]
		),
		Buttons([Button(mn.BTN_MINI_APP, web_app=app_url)]) if app_url else None,
		_home_row(),
		Footer(mn.CARD_REPORTS_FOOT.format(period=dates.period_label(period))),
	)


def trend_card(trend: Sequence[Mapping[str, Any]]) -> Card:
	if not trend:
		return card(Paragraph(mn.CARD_TREND_NONE.format(months=0)), _home_row())
	first, last = str(trend[0]["period"]), str(trend[-1]["period"])
	blocks: list[Any] = [
		Heading(
			mn.CARD_TREND_TITLE.format(
				from_period=dates.period_label(first), to_period=dates.period_label(last)
			)
		)
	]
	if all(row["revenue"] == ZERO and row["expense"] == ZERO for row in trend):
		blocks.append(Paragraph(mn.CARD_TREND_NONE.format(months=len(trend))))
	else:
		best = max(trend, key=lambda r: r["revenue"])
		if best["revenue"] == ZERO:
			best = None  # months with spend but no revenue: a table, but no "best month"
		table: list[list[Any]] = [
			_header(mn.LBL_MONTH, mn.CARD_REVENUE, mn.CARD_EXPENSE, mn.CARD_COL_CHANGE, right_from=1)
		]
		for row in trend:
			revenue = mnt(row["revenue"])
			table.append(
				[
					dates.period_label(str(row["period"])),
					_r(rich.mark(revenue) if row is best else revenue),
					_r(mnt(row["expense"])),
					_r(_delta_short(row["delta_pct"])),
				]
			)
		blocks.append(Table(table, striped=True))
		if best is not None:
			blocks.append(
				Paragraph(
					mn.CARD_TREND_BEST.format(
						period=dates.period_label(str(best["period"])), amount=fmt_mnt(best["revenue"])
					)
				)
			)
	blocks.append(
		_home_row(
			Button(mn.BTN_Q_TOP_ACCOUNTS, data=datum(VIEW_TOP, last)),
			Button(mn.BTN_REPORTS, data=datum(VIEW_REPORTS)),
		)
	)
	blocks.append(Footer(mn.CARD_FOOT_COMPUTED))
	return Card(blocks)


def _delta_short(pct: int | None) -> str:
	if pct is None:
		return "—"
	return f"{'+' if pct > 0 else ''}{pct}%"


def top_expenses_card(top: Mapping[str, Any]) -> Card:
	period = str(top["period"])
	label = dates.period_label(period)
	rows: Sequence[Mapping[str, Any]] = top.get("rows") or []
	blocks: list[Any] = [Heading(mn.CARD_TOP_TITLE.format(period=label))]
	if not rows:
		blocks.append(Paragraph(mn.CARD_TOP_NONE.format(period=label)))
	else:
		lead = rows[0]
		blocks.append(
			Paragraph(
				[
					mn.CARD_TOP_SENTENCE.split("{account}")[0],
					rich.mark(lead["label"]),
					mn.CARD_TOP_SENTENCE.split("{account}")[1].format(
						amount=fmt_mnt(lead["amount"]), pct=lead["share_pct"]
					),
				]
			)
		)
		table: list[list[Any]] = [_header(mn.COL_ACCOUNT, mn.COL_AMOUNT, mn.LBL_RATE_PCT, right_from=1)]
		for r in rows:
			table.append([r["label"], _r(mnt(r["amount"])), _r(f"{r['share_pct']}%")])
		table.append([rich.bold(mn.LBL_TOTAL), _r(rich.bold(mnt(top["total"]))), _r(rich.bold("100%"))])
		blocks.append(Table(table))
		if top.get("count", 0) > len(rows):
			blocks.append(Paragraph(mn.CARD_TOP_MORE.format(count=top["count"], shown=len(rows))))
	blocks.append(_period_row(VIEW_TOP, period))
	blocks.append(_home_row(Button(mn.BTN_TRANSACTIONS, data=datum(VIEW_TRANSACTIONS, period))))
	blocks.append(Footer(mn.CARD_FOOT_COMPUTED))
	return Card(blocks)


def trial_balance_card(tb: Mapping[str, Any], period: str) -> Card:
	rows = sorted(tb.get("rows") or [], key=lambda r: max(r["debit"], r["credit"]), reverse=True)
	label = dates.period_label(period)
	blocks: list[Any] = [
		Heading(mn.CARD_TB_TITLE.format(period=label)),
		Paragraph(mn.CARD_TB_TOTALS.format(debit=fmt_mnt(tb["debit"]), credit=fmt_mnt(tb["credit"]))),
	]
	shown = rows[:TB_ROWS_LIMIT]
	if shown:
		table: list[list[Any]] = [_header(mn.COL_ACCOUNT, mn.COL_DEBIT, mn.COL_CREDIT, right_from=1)]
		for r in shown:
			name = f"{r['account_code']} {_short_account(r['account'])}".strip()
			table.append([name, _r(fmt_mnt(r["debit"])), _r(fmt_mnt(r["credit"]))])
		blocks.append(Table(table, striped=True))
		if len(rows) > len(shown):
			blocks.append(Paragraph(mn.CARD_TB_MORE.format(count=len(rows), shown=len(shown))))
	blocks.append(_period_row(VIEW_TRIAL_BALANCE, period))
	blocks.append(
		Buttons(
			[
				Button(mn.BTN_PDF, data=datum(VIEW_TB_PDF, period)),
				Button(mn.BTN_XLSX, data=datum(VIEW_TB_XLSX, period)),
				Button(mn.BTN_DASHBOARD, data=datum(VIEW_HOME), style=STYLE_LINK),
			]
		)
	)
	blocks.append(Footer(str(tb.get("source") or mn.CARD_FOOT_COMPUTED)))
	return Card(blocks)


def _short_account(account: str) -> str:
	"""``"6210 - Шатахуун - TST"`` -> ``"Шатахуун"``: the chart's own name, without number and abbr."""
	parts = [p.strip() for p in str(account).split(" - ")]
	if len(parts) >= 3:
		return " - ".join(parts[1:-1])
	if len(parts) == 2:
		return parts[1] if parts[0].isdigit() else parts[0]
	return account


def profit_loss_card(month: Mapping[str, Any], top: Mapping[str, Any]) -> Card:
	period = str(month["period"])
	label = dates.period_label(period)
	if month["revenue"] == ZERO and month["expense"] == ZERO:
		return card(
			Heading(mn.CARD_PL_TITLE.format(period=label)),
			Paragraph(mn.CARD_PL_NONE.format(period=label)),
			_period_row(VIEW_PROFIT_LOSS, period),
			_home_row(),
		)
	table: list[list[Any]] = [
		_header("", mn.COL_AMOUNT, mn.CARD_COL_CHANGE, right_from=1),
		[
			rich.bold(mn.CARD_REVENUE),
			_r(rich.bold(mnt(month["revenue"]))),
			_r(_delta_short(month["revenue_delta_pct"])),
		],
	]
	for r in top.get("rows") or []:
		table.append([f"  {r['label']}", _r(mnt(r["amount"])), _r(f"{r['share_pct']}%")])
	table.append(
		[
			rich.bold(mn.CARD_EXPENSE),
			_r(rich.bold(mnt(month["expense"]))),
			_r(_delta_short(month["expense_delta_pct"])),
		]
	)
	table.append(
		[
			rich.bold(mn.CARD_PROFIT),
			_r(rich.bold(mnt(month["profit"]))),
			_r(_delta_short(month["profit_delta_pct"])),
		]
	)
	return card(
		Heading(mn.CARD_PL_TITLE.format(period=label)),
		Table(table),
		_period_row(VIEW_PROFIT_LOSS, period),
		_home_row(Button(mn.BTN_Q_TOP_ACCOUNTS, data=datum(VIEW_TOP, period))),
		Footer(mn.CARD_FOOT_COMPUTED),
	)


def inventory_card(stock: Mapping[str, Any], today: dt.date) -> Card:
	rows: Sequence[Mapping[str, Any]] = stock.get("rows") or []
	blocks: list[Any] = [Heading(mn.CARD_INV_TITLE.format(date=today.isoformat()))]
	if not rows:
		blocks.append(Paragraph(mn.CARD_INV_NONE))
	else:
		table: list[list[Any]] = [
			_header(mn.CARD_COL_ITEM, mn.CARD_COL_QTY, mn.CARD_COL_RATE, mn.COL_AMOUNT, right_from=1)
		]
		for r in rows:
			table.append([r["label"], _r(fmt_mnt(r["qty"])), _r(fmt_mnt(r["rate"])), _r(fmt_mnt(r["value"]))])
		table.append([rich.bold(mn.LBL_TOTAL), "", "", _r(rich.bold(mnt(stock["total"])))])
		blocks.append(Table(table, striped=True))
		if stock.get("count", 0) > len(rows):
			blocks.append(Paragraph(mn.CARD_INV_MORE.format(count=stock["count"], shown=len(rows))))
	blocks.append(_home_row(Button(mn.BTN_REPORTS, data=datum(VIEW_REPORTS))))
	blocks.append(Footer(mn.CARD_INV_SOURCE))
	return Card(blocks)


# --- onboarding: one card, redrawn per step ------------------------------------------------------------

# Which of the seven strip labels (``mn.ONB_STEP_LABELS``) a wizard step belongs to.
WIZARD_GROUPS = {
	"vat": 0,
	"400m": 1,
	"banks": 2,
	"cur": 3,
	"cur_other": 3,
	"acct": 3,
	"inv": 4,
	"inv_wait": 4,
	"inv_confirm": 4,
	"acc_name": 5,
	"micpa": 5,
	"summary": 6,
}


def wizard_card(
	company: str,
	step: str,
	answered: Sequence[str],
	question: str,
	note: str | None = None,
	*,
	open_answers: bool = False,
) -> Card:
	"""The setup wizard's one card: title, the step strip, what was answered, the question.

	The question is the LAST line of the plain twin on purpose: a client that cannot draw the
	card still ends on the thing to answer, right above the buttons. The answers so far sit in
	a collapsed ``details`` (open on the summary step, where they are the thing to confirm), so
	a wrong one is visible before Буцах and nothing on the card is a surprise on confirm.
	"""
	group = WIZARD_GROUPS.get(step, 0)
	total = len(mn.ONB_STEP_LABELS)
	strip: list[Any] = [mn.ONB_CARD_STEP.format(n=group + 1, total=total)]
	for index, label in enumerate(mn.ONB_STEP_LABELS):
		strip.append(" · ")
		strip.append(rich.bold(label) if index == group else label)
	blocks: list[Any] = [Heading(mn.ONB_CARD_TITLE.format(company=company)), Paragraph(strip)]
	if answered:
		blocks.append(Details(mn.ONB_ANSWERED, [Paragraph(line) for line in answered], open=open_answers))
	if note:
		blocks.append(Paragraph(note))
	blocks.append(Paragraph(rich.bold(question)))
	return Card(blocks)


def wizard_done_card(summary_text: str) -> Card:
	"""Setup is done: the summary as filed, and the first thing to do with the books."""
	return card(
		Heading(mn.ONB_DONE_TITLE),
		Paragraph(summary_text),
		Paragraph(mn.ONB_DONE_NEXT),
		Buttons([Button(mn.BTN_DASHBOARD, data=datum(VIEW_HOME), style=STYLE_PRIMARY)]),
	)


def welcome_card(linked: bool = False) -> Card:
	"""``/start`` before a link: what Нябо does in three rows, and how to get in."""
	rows: list[list[Any]] = [_header("", mn.WELCOME_COL_YOU, mn.WELCOME_COL_NYABO)]
	for index, (you, nyabo) in enumerate(mn.WELCOME_STEPS, start=1):
		rows.append([str(index), you, nyabo])
	return card(
		Heading(mn.WELCOME_TITLE, size=3),
		Paragraph(mn.MSG_WELCOME),
		Table(rows, bordered=False),
		None if linked else Paragraph(mn.MSG_NOT_LINKED),
	)


# --- answers -----------------------------------------------------------------------------------------------


def thinking_card(text: str) -> Card:
	return card(Thinking(text))


def answer_card(
	text: str, subject: str, follow_ups: Sequence[Any], facts: Mapping[str, Any] | None = None
) -> Card:
	"""The model's (or the handler's) sentence, the handler's rows as a table, the next reads.

	When the sentence *is* the handler's text — the model spent its turns on tools and wrote
	nothing — its figures are already listed line by line, and the table would repeat them;
	only the first line (the heading sentence) is kept and the rows go into the table.
	"""
	from nyabo_mn.telegram import cards

	body = (text or "").strip() or mn.MSG_QUESTION_CANNOT_FULL
	table = _facts_table(facts)
	if table is not None and facts and body == str(facts.get("text") or "").strip():
		body = body.split("\n", 1)[0]
	blocks: list[Any] = [Paragraph(body)]
	if table is not None:
		blocks.append(table)
	markup = keyboards.question_keyboard(follow_ups) if follow_ups else None
	for row in (markup or {}).get("inline_keyboard") or []:
		blocks.append(Buttons([Button(b["text"], data=b["callback_data"]) for b in row]))
	if subject:
		blocks.append(
			Footer(mn.MSG_QUESTION_SUBJECT.format(subject=cards._clip(subject, cards.CARD_MAX_LINE_CHARS)))
		)
	return Card(blocks)


def _facts_table(facts: Mapping[str, Any] | None) -> Table | None:
	"""The rows a books query returned, as the table an accountant would have drawn."""
	if not facts:
		return None
	accounts = facts.get("accounts")
	if isinstance(accounts, list) and accounts and isinstance(accounts[0], Mapping):
		rows: list[list[Any]] = [_header(mn.COL_ACCOUNT, mn.COL_AMOUNT, right_from=1)]
		rows.extend(
			[str(a.get("shown") or a.get("account") or ""), _r(f"{a.get('amount', '')}₮")] for a in accounts
		)
		return Table(rows)
	lines = facts.get("lines")
	if isinstance(lines, list) and lines and isinstance(lines[0], Mapping):
		rows = [_header(mn.COL_DATE, mn.COL_AMOUNT, mn.COL_DESCRIPTION, right_from=1)]
		rows.extend(
			[
				str(line.get("date") or ""),
				_r(f"{line.get('amount', '')}₮"),
				Cell(str(line.get("description") or "")),
			]
			for line in lines
		)
		return Table(rows, striped=True)
	months = facts.get("months")
	if isinstance(months, list) and months and isinstance(months[0], Mapping):
		rows = [_header(mn.LBL_MONTH, mn.CARD_REVENUE, mn.CARD_EXPENSE, right_from=1)]
		rows.extend(
			[
				str(m.get("label") or m.get("period") or ""),
				_r(f"{m.get('revenue', '')}₮"),
				_r(f"{m.get('expense', '')}₮"),
			]
			for m in months
		)
		return Table(rows, striped=True)
	suppliers = facts.get("suppliers")
	if isinstance(suppliers, list) and suppliers and isinstance(suppliers[0], Mapping):
		rows = [_header(mn.COL_PARTY, mn.COL_AMOUNT, right_from=1)]
		rows.extend([str(s.get("supplier") or ""), _r(f"{s.get('amount', '')}₮")] for s in suppliers)
		return Table(rows)
	entries = facts.get("entries")
	if isinstance(entries, list) and entries and isinstance(entries[0], Mapping):
		rows = [_header(mn.COL_DATE, mn.CARD_COL_ENTRY, mn.COL_AMOUNT, right_from=2)]
		rows.extend(
			[str(e.get("date") or ""), str(e.get("voucher") or ""), _r(f"{e.get('amount', '')}₮")]
			for e in entries
		)
		return Table(rows, striped=True)
	return None


__all__ = [
	"VIEWS",
	"answer_card",
	"bank_card",
	"dashboard_card",
	"datum",
	"inventory_card",
	"notes_card",
	"pending_card",
	"profit_loss_card",
	"reports_card",
	"thinking_card",
	"top_expenses_card",
	"transactions_card",
	"trend_card",
	"trial_balance_card",
	"welcome_card",
	"wizard_card",
	"wizard_done_card",
]
