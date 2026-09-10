"""The Telegram Mini App behind «Дэлгэрэнгүй самбар»: who is asking, and the figures for them.

A Mini App is a web page Telegram opens inside the chat (``web_app`` button). It has no Frappe
session — the page is served to a guest — so every request it makes carries Telegram's
``initData``: the user, an ``auth_date`` and a ``hash`` signed with the bot token
(HMAC-SHA256, ``secret = HMAC("WebAppData", bot_token)``, ``hash = HMAC(secret,
data_check_string)``, Telegram's "Validating data received via the Mini App", read
2026-09-10). ``verify_init_data`` checks the signature in constant time and refuses anything
older than a day; the Telegram id inside it is then resolved to the same ``Nyabo User Link``
the bot uses, the request runs as that link's user, and the company is the link's active
company — never something the page sent (TG-03: what the client says is attacker-chosen).

The figures are ``reports.dashboard``'s, the same reads the chat cards make, formatted here
because the page has no ``fmt_mnt``. Every label the page shows comes from ``i18n.mn`` through
``labels`` so the wording lives in one place with the rest of the product's Mongolian.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl

import frappe

from nyabo_mn.core import dates
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.reports import dashboard as data_mod

PAGE_PATH = "/nyabo_app"
MAX_AGE_SECONDS = 24 * 3600
VOUCHERS_LIMIT = 30


class InitDataInvalid(ValueError):
	"""The signed data Telegram hands a Mini App did not check out; nothing was read."""


# --- initData -------------------------------------------------------------------------------------------


def verify_init_data(init_data: str, bot_token: str, *, now: float | None = None) -> dict[str, Any]:
	"""The fields of ``initData`` once its ``hash`` is proven to be the bot token's, else raise."""
	if not init_data or not bot_token:
		raise InitDataInvalid("missing")
	pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
	given = pairs.pop("hash", "")
	if not given:
		raise InitDataInvalid("no hash")
	check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
	secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
	expected = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
	if not hmac.compare_digest(expected.encode("ascii"), given.lower().encode("ascii")):
		raise InitDataInvalid("bad hash")
	try:
		auth_date = int(pairs.get("auth_date") or 0)
	except ValueError as exc:
		raise InitDataInvalid("bad auth_date") from exc
	moment = now if now is not None else time.time()
	if auth_date <= 0 or moment - auth_date > MAX_AGE_SECONDS:
		raise InitDataInvalid("stale")
	out: dict[str, Any] = dict(pairs)
	try:
		out["user"] = json.loads(pairs.get("user") or "{}")
	except ValueError as exc:
		raise InitDataInvalid("bad user") from exc
	return out


def sign_init_data(fields: dict[str, Any], bot_token: str) -> str:
	"""What Telegram would hand the page for these fields — for tests and the simulator only."""
	from urllib.parse import urlencode

	plain = {
		k: (json.dumps(v, ensure_ascii=False, separators=(",", ":")) if isinstance(v, dict) else str(v))
		for k, v in fields.items()
	}
	check_string = "\n".join(f"{key}={value}" for key, value in sorted(plain.items()))
	secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
	plain["hash"] = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
	return urlencode(plain)


# --- who is asking ----------------------------------------------------------------------------------------


def _resolve(init_data: str) -> tuple[Any, str]:
	"""``(link, company)`` for a verified request, running the rest of it as the link's user."""
	from nyabo_mn.config import get_settings
	from nyabo_mn.telegram import state as chat_state

	try:
		fields = verify_init_data(init_data, get_settings().telegram_bot_token)
	except InitDataInvalid as exc:
		log_event("miniapp.init_data_refused", level="warning", reason=str(exc))
		frappe.throw(mn.MSG_MINIAPP_BAD_INITDATA, frappe.PermissionError)
	telegram_id = (fields.get("user") or {}).get("id")
	link = chat_state.get_link(telegram_id) if telegram_id else None
	if link is None:
		frappe.throw(mn.MSG_MINIAPP_NOT_LINKED, frappe.PermissionError)
	company = chat_state.active_company(link)
	if not company:
		frappe.throw(mn.MSG_NO_COMPANY, frappe.PermissionError)
	frappe.set_user(link.user)
	return link, company


def page_url() -> str | None:
	"""Where the page lives, or None when the site is not on HTTPS (Telegram opens only https)."""
	try:
		url = frappe.utils.get_url(PAGE_PATH)
	except Exception:  # noqa: BLE001 - no site URL, no button
		return None
	return url if str(url).startswith("https://") else None


# --- the figures ----------------------------------------------------------------------------------------------


def _mnt(value: Any) -> str:
	return f"{fmt_mnt(value)}₮"


def _num(value: Any) -> float:
	return float(Decimal(str(value or 0)))


def _period(arg: str | None, today: dt.date) -> str:
	if arg:
		try:
			year, month = dates.parse_period(arg)
			return f"{year:04d}-{month:02d}"
		except ValueError:
			pass
	return dates.period_of(today)


def _labels() -> dict[str, str]:
	return {
		"dashboard": mn.BTN_DASHBOARD,
		"transactions": mn.BTN_TRANSACTIONS,
		"bank": mn.BTN_BANK,
		"stock": mn.BTN_R_INVENTORY,
		"revenue": mn.CARD_REVENUE,
		"expense": mn.CARD_EXPENSE,
		"profit": mn.CARD_PROFIT,
		"change": mn.CARD_COL_CHANGE,
		"delta_none": mn.CARD_DELTA_NONE,
		"trend_title": mn.BTN_R_TREND,
		"top_title": mn.BTN_Q_TOP_ACCOUNTS,
		"account": mn.COL_ACCOUNT,
		"amount": mn.COL_AMOUNT,
		"share": mn.LBL_RATE_PCT,
		"date": mn.COL_DATE,
		"description": mn.COL_DESCRIPTION,
		"status": mn.CARD_COL_STATUS,
		"posted": mn.CARD_STATUS_POSTED,
		"pending": mn.CARD_STATUS_PENDING,
		"ledger": mn.CARD_COL_LEDGER,
		"statement": mn.CARD_COL_STATEMENT,
		"diff": mn.CARD_COL_DIFF,
		"unmatched": mn.CARD_RECON_UNMATCHED,
		"matched": mn.CARD_RECON_OK,
		"no_banks": mn.MSG_RECON_NONE,
		"item": mn.CARD_COL_ITEM,
		"qty": mn.CARD_COL_QTY,
		"rate": mn.CARD_COL_RATE,
		"total": mn.LBL_TOTAL,
		"no_stock": mn.CARD_INV_NONE,
		"no_vouchers": mn.CARD_TX_NONE,
		"month_empty": mn.CARD_MONTH_EMPTY,
		"your_turn": mn.CARD_YOUR_TURN,
		"todo_proposals": mn.CARD_TODO_PROPOSALS,
		"todo_unmatched": mn.CARD_TODO_UNMATCHED,
		"todo_rules": mn.CARD_TODO_RULES,
		"todo_none": mn.CARD_TODO_NONE,
		"export": mn.BTN_MINIAPP_EXPORT,
		"source": mn.CARD_FOOT_COMPUTED,
	}


def _delta(pct: int | None) -> str:
	if pct is None:
		return mn.CARD_DELTA_NONE
	return mn.CARD_DELTA.format(sign="+" if pct > 0 else "", pct=pct)


def figures(company: str, period: str, today: dt.date) -> dict[str, Any]:
	"""Everything the page draws, JSON-ready: formatted strings for reading, floats for the bars."""
	month = data_mod.month_with_delta(company, period)
	trend = data_mod.revenue_trend(company, period)
	top = data_mod.top_expenses(company, period)
	vouchers = data_mod.recent_vouchers(company, period, limit=VOUCHERS_LIMIT)
	pending = data_mod.section("pending", lambda: data_mod.pending_counts(company), {}, company=company)
	banks = data_mod.section("banks", lambda: data_mod.bank_summary(company, today), [], company=company)
	stock = data_mod.section(
		"inventory", lambda: data_mod.inventory(company), {"rows": [], "total": 0}, company=company
	)
	return {
		"company": company,
		"today": today.isoformat(),
		"period": period,
		"period_label": dates.period_label(period),
		"prev_period": data_mod.shift_period(period, -1),
		"next_period": data_mod.shift_period(period, 1),
		"month": {
			"empty": month["revenue"] == 0 and month["expense"] == 0,
			"revenue": _mnt(month["revenue"]),
			"expense": _mnt(month["expense"]),
			"profit": _mnt(month["profit"]),
			"revenue_delta": _delta(month["revenue_delta_pct"]),
			"expense_delta": _delta(month["expense_delta_pct"]),
			"profit_delta": _delta(month["profit_delta_pct"]),
			"profit_negative": month["profit"] < 0,
		},
		"trend": [
			{
				"period": row["period"],
				"label": dates.period_label(str(row["period"])),
				"revenue": _num(row["revenue"]),
				"expense": _num(row["expense"]),
				"revenue_fmt": _mnt(row["revenue"]),
				"expense_fmt": _mnt(row["expense"]),
			}
			for row in trend
		],
		"top": [
			{"label": r["label"], "amount": _mnt(r["amount"]), "share_pct": r["share_pct"]}
			for r in top["rows"]
		],
		"top_total": _mnt(top["total"]),
		"vouchers": [
			{
				"date": str(r["date"]),
				"label": r["label"],
				"amount": fmt_mnt(r["amount"]),
				"direction": r["direction"],
			}
			for r in vouchers["rows"]
		],
		"vouchers_count": vouchers["count"],
		"pending": pending,
		"banks": [
			{
				"label": _bank_label(row),
				"ledger": fmt_mnt(row["ledger_balance"]),
				"statement": fmt_mnt(row["statement_balance"]),
				"diff": fmt_mnt(row["diff"]),
				"unmatched": int(row.get("unmatched") or 0),
			}
			for row in banks
		],
		"inventory": {
			"rows": [
				{
					"label": r["label"],
					"qty": fmt_mnt(r["qty"]),
					"rate": fmt_mnt(r["rate"]),
					"value": fmt_mnt(r["value"]),
				}
				for r in stock.get("rows") or []
			],
			"total": _mnt(stock.get("total") or 0),
			"count": stock.get("count", 0),
		},
		"labels": _labels(),
	}


def _bank_label(row: dict[str, Any]) -> str:
	bank = mn.BANK_NAMES_MN.get(str(row.get("bank")), str(row.get("bank") or "—"))
	number = str(row.get("account_number") or "")
	tail = f" …{number[-4:]}" if len(number) >= 4 else ""
	currency = str(row.get("currency") or "MNT")
	return f"{bank}{tail}" + (f" ({currency})" if currency != "MNT" else "")


# --- endpoints ----------------------------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
def data(init_data: str, period: str | None = None) -> dict[str, Any]:
	"""The page's one read: the dashboard figures for the caller's company and the month asked for."""
	_link, company = _resolve(init_data)
	today = dt.date.today()
	return figures(company, _period(period, today), today)


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def export_xlsx(init_data: str, period: str | None = None) -> None:
	"""The month's vouchers as an .xlsx — what the Mini App's main button downloads."""
	from nyabo_mn.reports import export

	_link, company = _resolve(init_data)
	month = _period(period, dt.date.today())
	vouchers = data_mod.recent_vouchers(company, month, limit=10_000)
	columns = [
		{"label": mn.COL_DATE, "fieldname": "date", "fieldtype": "Date"},
		{"label": mn.COL_DESCRIPTION, "fieldname": "label", "fieldtype": "Data"},
		{"label": mn.COL_VOUCHER_NO, "fieldname": "voucher_no", "fieldtype": "Data"},
		{"label": mn.COL_AMOUNT, "fieldname": "amount", "fieldtype": "Currency"},
	]
	rows = [
		{"date": r["date"], "label": r["label"], "voucher_no": r["voucher_no"], "amount": r["amount"]}
		for r in vouchers["rows"]
	]
	frappe.response["filename"] = f"nyabo_{month}.xlsx"
	frappe.response["filecontent"] = export.rows_to_xlsx(mn.BTN_TRANSACTIONS, columns, rows)
	frappe.response["type"] = "binary"


__all__ = [
	"InitDataInvalid",
	"data",
	"export_xlsx",
	"figures",
	"page_url",
	"sign_init_data",
	"verify_init_data",
]
