"""Нягтлангийн тэмдэглэл: code notices what an accountant would notice; the model says it the way one would.

The split is the product's own (principle 7). Every *signal* is found by a deterministic
detector over the ledger — a cost that jumped against last month, a supplier paid every
month and not this one, statement lines nobody matched for a week, cash below zero, rules
that will refuse a posting, revenue closing on the simplified-regime threshold — and each
one carries its own Mongolian sentence and the figures it rests on. The model's job is the
one a good accountant does over coffee: put the signals in the order that matters, connect
the ones that explain each other, and say it in three or four plain sentences. It is handed
the signals as facts, may not add a number, and its note is checked word by word against
those figures (``questions.numbers_in``): a note with a figure the detectors did not produce
is dropped for the detectors' own sentences, so the card can never carry an invented amount.

The note is cached per company for a few hours keyed on the signals themselves, so a
dashboard tap is a read, not a model call, and the same signals get the same note.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import frappe

from nyabo_mn.agent import prompts, questions
from nyabo_mn.agent.llm_client import LlmError, TextPart
from nyabo_mn.agent.schemas import InsightNote, json_schema
from nyabo_mn.core import dates
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.core.quarantine import fence
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_error, log_event
from nyabo_mn.reports import dashboard as data

PROMPT_NAME = "insight"
PURPOSE = "question"  # Astra: the reasoning model, same routing as a question
SCHEMA_NAME = "insight_note"
CACHE_SECONDS = 6 * 3600
NOTE_MAX_CHARS = 700
EVENT_SENT = "insight_sent"

SPIKE_RATIO = Decimal("1.3")
SPIKE_MIN = Decimal("300000")
DROP_RATIO = Decimal("0.7")
RECURRING_MONTHS = 3
RECURRING_GRACE_DAYS = 5
UNMATCHED_AGE_DAYS = 7
PROPOSAL_AGE_DAYS = 2
MONTH_END_FROM_DAY = 25
THRESHOLD_SHARE = Decimal("0.8")
MAX_ACTIONS = 3

ZERO = Decimal("0")


@dataclass(frozen=True)
class Signal:
	"""One thing worth saying: what it is, how loud, the sentence, the figures, the button."""

	kind: str
	severity: int  # 1 worth knowing · 2 needs a look · 3 act today
	text: str
	facts: dict[str, Any] = field(default_factory=dict)
	action_label: str | None = None
	action_view: str | None = None  # a richcards view (``d:<view>``), or a command word
	action_arg: str | None = None


@dataclass(frozen=True)
class Note:
	text: str
	signals: tuple[Signal, ...]
	from_model: bool

	@property
	def severity(self) -> int:
		return max((s.severity for s in self.signals), default=0)


# --- detectors ------------------------------------------------------------------------------------------


def _label(period: str) -> str:
	return dates.period_label(period)


def _expense_signals(company: str, period: str) -> list[Signal]:
	previous = data.shift_period(period, -1)
	now_rows = {r["account"]: r for r in data.top_expenses(company, period, limit=50)["rows"]}
	before = {r["account"]: r for r in data.top_expenses(company, previous, limit=50)["rows"]}
	out: list[Signal] = []
	for account, row in now_rows.items():
		prior = before.get(account)
		if not prior or prior["amount"] <= ZERO:
			continue
		if row["amount"] >= prior["amount"] * SPIKE_RATIO and row["amount"] - prior["amount"] >= SPIKE_MIN:
			pct = int(round((row["amount"] - prior["amount"]) / prior["amount"] * 100))
			out.append(
				Signal(
					kind="expense_spike",
					severity=2,
					text=mn.INS_EXPENSE_SPIKE.format(
						account=row["label"],
						amount=fmt_mnt(row["amount"]),
						previous=fmt_mnt(prior["amount"]),
						pct=pct,
					),
					facts={
						"account": row["label"],
						"this_month": fmt_mnt(row["amount"]),
						"last_month": fmt_mnt(prior["amount"]),
						"change_pct": pct,
					},
					action_label=mn.BTN_Q_TOP_ACCOUNTS,
					action_view="top",
					action_arg=period,
				)
			)
	return sorted(out, key=lambda s: s.facts["change_pct"], reverse=True)[:2]


def _revenue_signal(company: str, period: str, today: dt.date) -> Signal | None:
	if today.day < MONTH_END_FROM_DAY:
		return None  # a month three weeks in is not yet comparable to a whole one
	month = data.month_with_delta(company, period)
	if month["revenue_previous"] <= ZERO or month["revenue"] <= ZERO:
		return None
	if month["revenue"] <= month["revenue_previous"] * DROP_RATIO:
		return Signal(
			kind="revenue_drop",
			severity=2,
			text=mn.INS_REVENUE_DROP.format(
				amount=fmt_mnt(month["revenue"]),
				previous=fmt_mnt(month["revenue_previous"]),
				pct=abs(month["revenue_delta_pct"] or 0),
			),
			facts={
				"this_month": fmt_mnt(month["revenue"]),
				"last_month": fmt_mnt(month["revenue_previous"]),
				"change_pct": month["revenue_delta_pct"],
			},
			action_label=mn.BTN_R_TREND,
			action_view="rev",
		)
	return None


def _recurring_signals(company: str, period: str, today: dt.date) -> list[Signal]:
	"""Suppliers paid in each of the last months and not this one, once their usual day is past."""
	if not frappe.db.exists("DocType", "Purchase Invoice"):
		return []
	start = dates.period_bounds(data.shift_period(period, -RECURRING_MONTHS))[0]
	rows = frappe.get_all(
		"Purchase Invoice",
		filters={
			"company": company,
			"docstatus": 1,
			"is_return": 0,
			"posting_date": ["between", [start.isoformat(), today.isoformat()]],
		},
		fields=["supplier", "supplier_name", "posting_date", "grand_total"],
	)
	seen: dict[str, dict[str, list[Any]]] = {}
	names: dict[str, str] = {}
	for row in rows:
		day = (
			row.posting_date
			if isinstance(row.posting_date, dt.date)
			else dt.date.fromisoformat(str(row.posting_date)[:10])
		)
		months = seen.setdefault(row.supplier, {})
		months.setdefault(dates.period_of(day), []).append(day)
		names[row.supplier] = row.supplier_name or row.supplier
	expected = [data.shift_period(period, -i) for i in range(1, RECURRING_MONTHS + 1)]
	out: list[Signal] = []
	for supplier, months in seen.items():
		if period in months or not all(m in months for m in expected):
			continue
		usual_day = max(max(d.day for d in months[m]) for m in expected)
		if today.day <= usual_day + RECURRING_GRACE_DAYS:
			continue
		out.append(
			Signal(
				kind="recurring_missing",
				severity=2,
				text=mn.INS_RECURRING_MISSING.format(
					supplier=names[supplier], months=RECURRING_MONTHS, day=usual_day
				),
				facts={"supplier": names[supplier], "months_seen": RECURRING_MONTHS, "usual_day": usual_day},
				action_label=mn.BTN_TRANSACTIONS,
				action_view="tx",
				action_arg=period,
			)
		)
	return out[:2]


def _unmatched_signal(company: str, today: dt.date) -> Signal | None:
	rows = frappe.get_all(
		"Bank Transaction",
		filters={"company": company, "docstatus": 1, "status": ["in", ["Pending", "Unreconciled"]]},
		fields=["date"],
	)
	if not rows:
		return None
	oldest = min(_as_date(r.date) for r in rows)
	age = (today - oldest).days
	if age < UNMATCHED_AGE_DAYS:
		return None
	return Signal(
		kind="unmatched_aging",
		severity=3 if age >= 30 else 2,
		text=mn.INS_UNMATCHED_AGING.format(count=len(rows), days=age),
		facts={"count": len(rows), "oldest_days": age, "oldest_date": oldest.isoformat()},
		action_label=mn.BTN_RECONCILE,
		action_view="unm",
	)


def _proposals_signal(company: str, today: dt.date) -> Signal | None:
	if not frappe.db.exists("DocType", "Nyabo Proposal"):
		return None
	rows = frappe.get_all(
		"Nyabo Proposal", filters={"company": company, "status": "proposed"}, fields=["creation"]
	)
	if not rows:
		return None
	oldest = min(_as_date(r.creation) for r in rows)
	age = (today - oldest).days
	if age < PROPOSAL_AGE_DAYS:
		return None
	return Signal(
		kind="proposals_waiting",
		severity=2,
		text=mn.INS_PROPOSALS_WAITING.format(count=len(rows), days=age),
		facts={"count": len(rows), "oldest_days": age},
		action_label=mn.BTN_PROPOSALS.format(count=len(rows)),
		action_view="pend",
	)


def _cash_signal(company: str, today: dt.date) -> Signal | None:
	from erpnext.accounts.utils import get_balance_on

	from nyabo_mn.reports import accounts as report_accounts

	cash = report_accounts.role_account_or_none(company, "cash")
	if not cash:
		return None
	balance = Decimal(str(get_balance_on(cash, today.isoformat(), company=company) or 0))
	if balance >= ZERO:
		return None
	return Signal(
		kind="cash_negative",
		severity=3,
		text=mn.INS_CASH_NEGATIVE.format(balance=fmt_mnt(balance)),
		facts={"cash_balance": fmt_mnt(balance)},
		action_label=mn.BTN_TRANSACTIONS,
		action_view="tx",
		action_arg=dates.period_of(today),
	)


def _rules_signal(company: str) -> Signal | None:
	from nyabo_mn.rules import verify

	pending = verify.pending(company=company)
	if not pending:
		return None
	return Signal(
		kind="rules_blocking",
		severity=2,
		text=mn.INS_RULES_BLOCKING.format(count=len(pending)),
		facts={"count": len(pending)},
		action_label=mn.INS_BTN_RULES,
		action_view="rules",
	)


def _month_end_signal(company: str, today: dt.date, pending: dict[str, int]) -> Signal | None:
	if today.day < MONTH_END_FROM_DAY:
		return None
	open_items = int(pending.get("proposals", 0)) + int(pending.get("unmatched", 0))
	if not open_items:
		return None
	return Signal(
		kind="month_end_due",
		severity=1,
		text=mn.INS_MONTH_END.format(period=_label(dates.period_of(today)), count=open_items),
		facts={"open_items": open_items},
		action_label=mn.BTN_PROPOSALS.format(count=pending.get("proposals", 0))
		if pending.get("proposals")
		else mn.BTN_RECONCILE,
		action_view="pend" if pending.get("proposals") else "unm",
	)


def _threshold_signal(company: str, today: dt.date) -> Signal | None:
	"""Revenue this year against the simplified regime's threshold, for a company inside it."""
	from nyabo_mn.reports import month_end, simplified_summary

	try:
		if month_end.is_vat_payer(company, today) is not False:
			return None
		eligibility = simplified_summary.eligibility(company, today)
	except Exception:  # noqa: BLE001 - an unverified parameter or a missing regime: no signal
		return None
	threshold = eligibility.get("threshold")
	if not threshold:
		return None
	threshold = Decimal(str(threshold))
	ytd = sum(
		(
			data.month_totals(company, f"{today.year:04d}-{m:02d}")["revenue"]
			for m in range(1, today.month + 1)
		),
		ZERO,
	)
	if ytd < threshold * THRESHOLD_SHARE:
		return None
	pct = int(round(ytd / threshold * 100))
	return Signal(
		kind="threshold_near",
		severity=3 if ytd >= threshold else 2,
		text=mn.INS_THRESHOLD.format(revenue=fmt_mnt(ytd), threshold=fmt_mnt(threshold), pct=pct),
		facts={"ytd_revenue": fmt_mnt(ytd), "threshold": fmt_mnt(threshold), "share_pct": pct},
		action_label=mn.BTN_R_TREND,
		action_view="rev",
	)


def _as_date(value: Any) -> dt.date:
	if isinstance(value, dt.datetime):
		return value.date()
	if isinstance(value, dt.date):
		return value
	return dt.date.fromisoformat(str(value)[:10])


def signals(company: str, today: dt.date | None = None) -> list[Signal]:
	"""Everything the detectors found, loudest first; a detector that fails is a logged gap."""
	today = today or dt.date.today()
	period = dates.period_of(today)
	found: list[Signal] = []

	def run(name: str, detect: Any) -> None:
		try:
			result = detect()
		except Exception as exc:  # noqa: BLE001 - one detector must not silence the others
			log_error(f"insights.{name}_failed", exc, company=company)
			return
		if isinstance(result, Signal):
			found.append(result)
		elif result:
			found.extend(result)

	pending = data.section("pending", lambda: data.pending_counts(company), {}, company=company)
	run("cash", lambda: _cash_signal(company, today))
	run("threshold", lambda: _threshold_signal(company, today))
	run("unmatched", lambda: _unmatched_signal(company, today))
	run("proposals", lambda: _proposals_signal(company, today))
	run("rules", lambda: _rules_signal(company))
	run("expense", lambda: _expense_signals(company, period))
	run("revenue", lambda: _revenue_signal(company, period, today))
	run("recurring", lambda: _recurring_signals(company, period, today))
	run("month_end", lambda: _month_end_signal(company, today, pending))
	return sorted(found, key=lambda s: -s.severity)


# --- the note ----------------------------------------------------------------------------------------------


def deterministic_note(found: Sequence[Signal]) -> str:
	return " ".join(s.text for s in found)


def _allowed_numbers(found: Sequence[Signal]) -> set[str]:
	"""Every spelling of every figure the detectors produced — what the model may say."""
	corpus = " ".join(" ".join(str(v) for v in s.facts.values()) + " " + s.text for s in found)
	allowed: set[str] = set()
	for variants in questions.numbers_in(corpus):
		allowed |= variants
	return allowed


def note_is_honest(note: str, found: Sequence[Signal]) -> bool:
	"""True when every number in the note is one a detector produced (any accepted spelling)."""
	allowed = _allowed_numbers(found)
	return all(bool(variants & allowed) for variants in questions.numbers_in(note))


def _fingerprint(found: Sequence[Signal]) -> str:
	raw = json.dumps(
		[[s.kind, s.severity, s.facts] for s in found], ensure_ascii=False, sort_keys=True, default=str
	)
	return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def narrate(company: str, found: Sequence[Signal], *, client: Any = None) -> tuple[str, bool]:
	"""The model's note over the signals, or the detectors' sentences when it cannot be trusted."""
	fallback = deterministic_note(found)
	if not found:
		return "", False
	try:
		if client is None:
			from nyabo_mn.agent import frappe_log
			from nyabo_mn.agent.llm_client import get_client
			from nyabo_mn.agent.pipeline import _settings_obj, _simulation

			client = get_client(
				_settings_obj(),
				"mock" if _simulation() else "auto",
				record_call=frappe_log.recorder(company=company),
			)
		prompt_text, version = prompts.load(PROMPT_NAME)
		system, user_template = prompts.split(prompt_text)
		facts = [
			{"kind": s.kind, "severity": s.severity, "facts": s.facts, "sentence": s.text} for s in found
		]
		user = prompts.fill(
			user_template,
			COMPANY=fence(company, label="company"),
			UNTRUSTED=fence(json.dumps(facts, ensure_ascii=False, indent=1, default=str), label="signals"),
			NOW=dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
		)
		result = client.structured(
			purpose=PURPOSE,
			system=system,
			user=[TextPart(user)],
			schema=json_schema(InsightNote),
			schema_name=SCHEMA_NAME,
			prompt_version=prompts.version_tag(PROMPT_NAME, version),
		)
		note = str((result.data or {}).get("note_mn") or "").strip()
	except (LlmError, Exception) as exc:  # noqa: BLE001 - the note is a courtesy; the figures are not
		log_event("insights.narrate_failed", level="warning", company=company, error=type(exc).__name__)
		return fallback, False
	if not note or len(note) > NOTE_MAX_CHARS or not note_is_honest(note, found):
		log_event("insights.note_rejected", level="warning", company=company, length=len(note))
		return fallback, False
	return note, True


def note_for(company: str, today: dt.date | None = None, *, client: Any = None) -> Note | None:
	"""The day's note for a company, from the cache when the signals have not changed."""
	today = today or dt.date.today()
	found = tuple(signals(company, today))
	if not found:
		return None
	key = f"nyabo:insight:{company}:{today.isoformat()}:{_fingerprint(found)}"
	cached = frappe.cache().get_value(key)
	if isinstance(cached, dict) and cached.get("text"):
		return Note(text=str(cached["text"]), signals=found, from_model=bool(cached.get("from_model")))
	text, from_model = narrate(company, found, client=client)
	frappe.cache().set_value(key, {"text": text, "from_model": from_model}, expires_in_sec=CACHE_SECONDS)
	return Note(text=text, signals=found, from_model=from_model)


def actions(found: Sequence[Signal], limit: int = MAX_ACTIONS) -> list[Signal]:
	"""The signals whose button is worth a row, one per view, loudest first."""
	out: list[Signal] = []
	seen: set[str] = set()
	for s in found:
		if not s.action_view or s.action_view in seen:
			continue
		seen.add(s.action_view)
		out.append(s)
		if len(out) >= limit:
			break
	return out


# --- the morning push ----------------------------------------------------------------------------------------


def _sent_today(company: str, today: dt.date) -> bool:
	"""The day rides in ``reason`` rather than being read off ``creation``: the scheduler's clock
	and the ledger's day can differ across midnight, and a test hands the day in."""
	rows = frappe.get_all(
		"Nyabo Event",
		filters={"event_type": EVENT_SENT, "company": company, "reason": today.isoformat()},
		limit=1,
		pluck="name",
	)
	return bool(rows)


def push_daily(today: dt.date | None = None) -> dict[str, Any]:
	"""Scheduler: one morning note per company whose signals need a look, to its accountant's chat."""
	from nyabo_mn.matching import common
	from nyabo_mn.telegram import api as telegram_api
	from nyabo_mn.telegram import rich, richcards
	from nyabo_mn.telegram.handlers import bank as bank_handler

	today = today or dt.date.today()
	sent: list[str] = []
	skipped: list[str] = []
	bot = None
	for row in frappe.get_all("Nyabo Company Settings", fields=["company"]):
		company = row.company
		try:
			if _sent_today(company, today):
				skipped.append(company)
				continue
			note = note_for(company, today)
			if note is None or note.severity < 2:
				skipped.append(company)
				continue
			chat_id = bank_handler.chat_id_for(company)
			if not chat_id:
				skipped.append(company)
				continue
			bot = bot or telegram_api.get_bot()
			card = richcards.notes_card(company, note.text, actions(note.signals))
			text, markup = rich.render_text(card)
			bot.send_rich_message(chat_id, rich.render_html(card), fallback_text=text, fallback_markup=markup)
			common.write_event(
				EVENT_SENT,
				company=company,
				reason=today.isoformat(),
				payload={"kinds": [s.kind for s in note.signals], "from_model": note.from_model},
			)
			sent.append(company)
		except Exception as exc:  # noqa: BLE001 - one company's failure must not silence the others
			log_error("insights.push_failed", exc, company=company)
			skipped.append(company)
	log_event("insights.push_daily", sent=len(sent), skipped=len(skipped))
	return {"sent": sent, "skipped": skipped}


__all__ = [
	"Note",
	"Signal",
	"actions",
	"deterministic_note",
	"narrate",
	"note_for",
	"note_is_honest",
	"push_daily",
	"signals",
]
