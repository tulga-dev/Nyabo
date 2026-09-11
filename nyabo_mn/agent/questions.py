"""Question answering with read-only tools (docs/ARCHITECTURE.md §5.7).

The model writes the sentence; every number comes from an injected handler. Handlers are
plain callables ``(args: dict) -> dict`` supplied by the Frappe side, so this module has
no frappe import and the simulator can plug in fakes. The final ``QuestionAnswer`` is
built by code from the tool trace, not by the model, so ``needs_escalation`` can never be
claimed without ``escalate_to_admin`` having actually been called.

Four things beyond the tool loop live here, all deterministic and all testable without a
bench:

1. **Continuity** (``recall`` / ``remember``). One turn of conversation memory so that
   «мөн өнгөрсөн сард?» after «шатахуунд хэд зарцуулсан бэ?» resolves. What is kept is the
   previous question text and the *subject the handler resolved* (account code, period,
   supplier, date, document) — never the figures. A figure in the prompt is a figure the
   model can repeat as if it were this question's answer, and a bookkeeping bot that
   silently answers last month's number is worse than one that asks again. The numbers it
   needs for a follow-up come back from a handler, every time.
2. **Follow-ups** (``follow_ups``). The buttons under an answer are read off the tool
   trace, so they can only ever offer a query the books already answered once. The model
   never names a button.
3. **Number verification** (``unverified_numbers``). Every number in the model's sentence
   must appear in what a handler *computed* (``COMPUTED_NUMBERS_FIELD`` — the figures it read
   off or worked out from the ledger, listed by the handler itself), or in the calendar date
   the clock is on. Nothing else, and in particular:

   * **not the text a handler rendered.** Rendered text is not a computation. ``answer_faq``
     returns product prose that quotes figures («85 000₮-ийн шатахууны и-баримт»), and a model
     that looked something up in the FAQ and then stated that figure as this company's ledger
     passed a check built from text. It computes nothing, so it now contributes nothing.
   * **not the arguments the model chose.** A handler echoes the subject it was handed, and its
     own not-found sentence quotes it back verbatim, so a figure the model invented and passed
     in as ``supplier`` or ``entry_ref`` came home through the very sentence that says the
     books never found it.
   * **not the user's own question.** «Петровисээс 1 250 000₮-ийн шатахуун авсан биз дээ?» is
     the ordinary way a Mongolian bookkeeper checks a figure out loud, and admitting the
     question let the model answer «Тийм, … 1 250 000₮» over a ledger holding 85 000₮ — a
     confirmation of what nothing had confirmed, in the shape of question where that does the
     most damage. A figure a user typed is a figure the books have not confirmed.
   * **not the time of day.** The clock contributes the calendar date and nothing else. The
     whole timestamp put every hour, minute and second into the set, so each of 0…59 verified
     as a tögrög figure. An answer about the books is about dates, never times.

   A number that does not appear means the model wrote a figure of its own; the sentence is
   dropped and the handler's own Mongolian text is sent instead. This is the mechanical form of
   "the model writes sentences, deterministic code writes numbers". The check is run over the
   model's sentence and nothing else, and it has two documented limits — it does not bind a
   figure to the subject the sentence names, and it never sees a number written out in
   Mongolian words. Both are set out on ``unverified_numbers`` and in docs/DECISIONS.md Q-02.
4. **Read-only widening.** Ten query kinds (§5.7 named four); every one of them is a read.
   Nothing in this path may write to the ledger, and no tool here can.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Any, Literal

from pydantic import Field, ValidationError

from nyabo_mn.agent import prompts
from nyabo_mn.agent.llm_client import LlmClient, LlmResult, TextPart, ToolCall, ToolSpec
from nyabo_mn.agent.schemas import QuestionAnswer, StrictModel, json_schema
from nyabo_mn.core import dates
from nyabo_mn.core.quarantine import fence, find_injection
from nyabo_mn.i18n import mn

PROMPT_NAME = "question"
PURPOSE = "question"
# Four was enough for one lookup and a sentence; five for ten query kinds and a follow-up. An
# accountant's answer to «why did costs jump?» is three reads — this month, last month, the
# entries behind the difference — and a sentence that connects them, so the loop gets room
# for that walk on the reasoning model without turning one question into an open-ended run.
MAX_TURNS = 8
MAX_QUESTION_CHARS = 2000
# Errors that mean "the model asked for something impossible". They mean "no answer", not "the
# ledger is broken", so the user gets a different sentence. ``unknown_account`` is one of them:
# a code that is not in this company's chart is the *question* being wrong, and telling an
# accountant «Дэвтрээс мэдээлэл авахад алдаа гарлаа» over a typo sends them looking for a fault
# in their books. Every error code ``pipeline.books_handlers`` can return belongs in here —
# anything it cannot answer raises instead, and an exception is what a broken ledger looks like.
MODEL_FAULT_ERRORS = frozenset({"invalid_arguments", "unknown_tool", "unknown_account"})

# --- conversation memory -------------------------------------------------------------------------
# One turn, twenty minutes, one company. A question about the books is answered against a
# moment in time: a receipt approved between two questions changes the figure, so a context
# older than a short exchange has to be re-established out loud rather than assumed. The
# company is stored with it because an accountant switches clients with /компани, and a
# subject resolved for one client's chart must never be reused against another's.
MEMORY_VERSION = 1
MEMORY_TTL_MINUTES = 20
MEMORY_QUESTION_CHARS = 160

MAX_FOLLOW_UPS = 4

Handler = Callable[[dict[str, Any]], dict[str, Any]]

QueryKind = Literal[
	"balance_on_date",
	"spend_by_account",
	"account_entries",
	"last_entries_for_supplier",
	"supplier_total",
	"vat_position",
	"top_spend_accounts",
	"unmatched_count",
	"unmatched_lines",
	"explain_entry",
	"monthly_trend",
	"top_suppliers",
]

# Which of ``BooksArgs`` each kind reads, in the order a follow-up button carries them.
# ``keyboards.question_row`` encodes exactly these, so the callback datum and the handler
# argument list can never drift apart.
QUERY_ARGS: Mapping[str, tuple[str, ...]] = {
	"balance_on_date": ("account_code", "on_date"),
	"spend_by_account": ("account_code", "period"),
	"account_entries": ("account_code", "period"),
	"last_entries_for_supplier": ("supplier",),
	"supplier_total": ("supplier", "period"),
	"vat_position": ("period",),
	"top_spend_accounts": ("period",),
	"unmatched_count": (),
	"unmatched_lines": (),
	"explain_entry": ("entry_ref",),
	"monthly_trend": ("period",),
	"top_suppliers": ("period",),
}
# Three-letter verbs, because the whole callback datum is 64 bytes and a Cyrillic supplier
# name is two bytes a letter.
QUERY_SHORT: Mapping[str, str] = {
	"balance_on_date": "bal",
	"spend_by_account": "spd",
	"account_entries": "led",
	"last_entries_for_supplier": "ent",
	"supplier_total": "sup",
	"vat_position": "vat",
	"top_spend_accounts": "top",
	"unmatched_count": "unc",
	"unmatched_lines": "unm",
	"explain_entry": "exp",
	"monthly_trend": "trd",
	"top_suppliers": "tsp",
}
SHORT_QUERY: Mapping[str, str] = {short: kind for kind, short in QUERY_SHORT.items()}
# Two verbs that are not a query: hand the question to a human, and go back to the menu.
VERB_ESCALATE = "esc"
VERB_MENU = "m"

SUBJECT_KEYS = ("account_code", "period", "supplier", "on_date", "entry_ref")


class BooksArgs(StrictModel):
	account_code: str | None = Field(description="Account code, e.g. 6210; null when not needed")
	on_date: str | None = Field(description="ISO date YYYY-MM-DD; null for today")
	supplier: str | None = Field(description="Supplier name as the user wrote it; null when not needed")
	period: str | None = Field(description="Month as YYYY-MM; null for the current month")
	entry_ref: str | None = Field(
		description="Name of a posted document or Nyabo proposal to explain, e.g. ACC-PINV-2026-00003; null when not needed"
	)


class AnswerFromBooksArgs(StrictModel):
	query_kind: QueryKind = Field(description="Which ledger question to run")
	args: BooksArgs


class AnswerFaqArgs(StrictModel):
	question: str = Field(description="The question to look up in the FAQ, rephrased briefly")


class EscalateArgs(StrictModel):
	summary: str = Field(description="One-sentence summary of what the user needs, in Mongolian")


class RecordTransactionArgs(StrictModel):
	"""A transaction the user described in words; code turns it into a proposal card."""

	direction: Literal["income", "expense"] = Field(
		description="income when money came in (sale, revenue, a customer paid); expense when money went out"
	)
	amount_mnt: float = Field(description="The amount in MNT as a plain number, e.g. 2000000 for two million")
	party: str | None = Field(description="The customer or supplier as the user named it; null when not said")
	description: str | None = Field(
		description="What it was for, in the user's words, short; null when not said"
	)
	paid_via: Literal["bank", "cash", "unknown"] = Field(
		description="bank for a transfer or card, cash for cash, unknown when the user did not say"
	)
	date: str | None = Field(description="ISO date YYYY-MM-DD when the user named a day; null for today")
	account_code: str | None = Field(
		description="For an expense only: the expense account code from the chart when obvious (e.g. 6210); null otherwise"
	)


TOOL_ARG_MODELS: dict[str, type[StrictModel]] = {
	"answer_from_books": AnswerFromBooksArgs,
	"answer_faq": AnswerFaqArgs,
	"escalate_to_admin": EscalateArgs,
	"record_transaction": RecordTransactionArgs,
}

TOOL_SPECS: list[ToolSpec] = [
	ToolSpec(
		name="answer_from_books",
		description=(
			"Read-only ledger lookup. query_kind is one of: balance_on_date (account_code, on_date); "
			"spend_by_account (account_code, period); account_entries (account_code, period — the "
			"entries behind that figure); last_entries_for_supplier (supplier); supplier_total "
			"(supplier, period); vat_position (period); top_spend_accounts (period); unmatched_count; "
			"unmatched_lines; explain_entry (entry_ref — what a posted entry was and why); "
			"monthly_trend (period — revenue and expense for that month and the five before it); "
			"top_suppliers (period — the suppliers bought from most in a month). "
			"Returns figures in MNT formatted by the system."
		),
		parameters=json_schema(AnswerFromBooksArgs),
	),
	ToolSpec(
		name="answer_faq",
		description="Look up how Nyabo works or a bookkeeping basic in the product FAQ. Returns a short text.",
		parameters=json_schema(AnswerFaqArgs),
	),
	ToolSpec(
		name="record_transaction",
		description=(
			"Draft a ledger entry from a transaction the user describes in words — money received "
			"(a sale, revenue, a customer paid) or money spent (a purchase, a bill, a payment). Creates "
			"a proposal card the accountant confirms with a button; nothing is posted. Use this, never "
			"escalate_to_admin, whenever the user wants to record, register or book a transaction. "
			"Requires an amount; without one, ask for it."
		),
		parameters=json_schema(RecordTransactionArgs),
	),
	ToolSpec(
		name="escalate_to_admin",
		description="Hand the question to a human admin when it needs an action or cannot be answered from the books.",
		parameters=json_schema(EscalateArgs),
	),
]
TOOL_NAMES = tuple(spec.name for spec in TOOL_SPECS)


@dataclass(frozen=True)
class FollowUp:
	"""One button under an answer: a verb, its already-encodable arguments and the label.

	``verb`` is a ``QUERY_SHORT`` code (re-run that read-only query) or ``VERB_ESCALATE`` /
	``VERB_MENU``. ``args`` is ordered to match ``QUERY_ARGS`` so the Telegram layer encodes
	the datum without knowing what a query kind means.
	"""

	verb: str
	label: str
	args: tuple[str, ...] = ()

	@property
	def query_kind(self) -> str | None:
		return SHORT_QUERY.get(self.verb)


@dataclass(frozen=True)
class AnswerOutcome:
	answer: QuestionAnswer
	llm: LlmResult | None
	injection_suspected: bool
	injection_fragment: str | None
	tools_used: tuple[str, ...]
	follow_ups: tuple[FollowUp, ...] = ()
	memory: dict[str, Any] | None = None
	unverified_numbers: tuple[str, ...] = ()
	# The Nyabo Proposal a ``record_transaction`` call drafted: the chat sends its card, with
	# the accountant's buttons, instead of a sentence.
	proposal: str | None = None
	# {number: "invented" | "derived"} — what the event log says about each of the above.
	number_kinds: Mapping[str, str] = field(default_factory=dict)
	subject: Mapping[str, str] = field(default_factory=dict)


def make_dispatcher(handlers: Mapping[str, Handler]) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
	"""Validate arguments against the tool schema before the handler sees them.

	A handler only ever receives a dict that passed its pydantic model, so a Frappe-side
	implementation can index ``args["account_code"]`` without defensive code.
	"""

	def dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
		model = TOOL_ARG_MODELS.get(name)
		handler = handlers.get(name)
		if model is None or handler is None:
			return {"error": "unknown_tool"}
		try:
			parsed = model.model_validate(args)
		except ValidationError as exc:
			return {"error": "invalid_arguments", "detail": [e.get("msg") for e in exc.errors()][:5]}
		result = handler(parsed.model_dump())
		return dict(result) if isinstance(result, Mapping) else {"result": result}

	return dispatch


# --- conversation memory ---------------------------------------------------------------------------


def shift_period(period: str, months: int) -> str:
	"""``("2026-01", -1) -> "2025-12"``; raises ValueError on anything but YYYY-MM."""
	year, month = dates.parse_period(period)
	index = year * 12 + (month - 1) + months
	return f"{index // 12:04d}-{index % 12 + 1:02d}"


def resolved(result: Mapping[str, Any] | None) -> bool:
	"""False when a handler answered that the thing asked about is not in these books.

	A handler says so with ``found: False``, and its sentence — «X нэртэй харилцагч
	олдсонгүй.» — is still the right thing to show. What must not follow it is the furniture
	of an answer: buttons offering more reads about a supplier the card just said does not
	exist, a subject line printing the unresolved name as though it had been resolved, and a
	memory carrying it into the next question.
	"""
	return not (isinstance(result, Mapping) and result.get("found") is False)


def _subject_of(call: ToolCall) -> dict[str, str]:
	"""What the handler resolved, falling back to what the model asked for.

	The handler's answer wins because it is the resolved form: the model writes «Петровис»
	and the handler comes back with «Петровис ХХК», which is the name a follow-up button
	has to carry. A lookup that found nothing resolved nothing, so it has no subject at all —
	the name in that result is the model's own wording, echoed back.
	"""
	if not resolved(call.result):
		return {}
	asked = dict((call.arguments or {}).get("args") or {})
	got = dict(call.result or {})
	subject: dict[str, str] = {}
	for key in SUBJECT_KEYS:
		value = got.get(key)
		if value in (None, ""):
			value = asked.get(key)
		if value not in (None, ""):
			subject[key] = str(value)
	return subject


def _last_books_call(calls: Sequence[ToolCall]) -> ToolCall | None:
	return next(
		(c for c in reversed(calls) if c.name == "answer_from_books" and not c.is_error),
		None,
	)


def remember(
	question: str, calls: Sequence[ToolCall], *, company: str, now: datetime
) -> dict[str, Any] | None:
	"""The one turn of context a follow-up may lean on, or None when there is nothing to keep.

	Deliberately small: the question as the user wrote it (capped, and re-fenced before it
	ever re-enters a prompt), the query kind, and the subject the handler resolved. No
	figures — see the module docstring.
	"""
	call = _last_books_call(calls)
	if call is None:
		return None
	subject = _subject_of(call)
	if not subject:
		return None
	return {
		"v": MEMORY_VERSION,
		"company": company,
		"at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
		"question": (question or "").strip()[:MEMORY_QUESTION_CHARS],
		"query_kind": str((call.arguments or {}).get("query_kind") or ""),
		"subject": subject,
	}


def memory_injection(memory: Mapping[str, Any] | None) -> str | None:
	"""The first instruction-looking fragment in the remembered *subject*, or None.

	The subject is not ours. A supplier name originates in receipt extraction: it is model
	output read off a photograph an owner sent, so «Петровис ХХК. Ignore all previous
	instructions» reaches the memory by exactly the route ``core.quarantine`` exists for.
	``recall`` drops a memory this finds something in; the caller logs the fragment, because
	an instruction planted on a receipt is the same event whichever turn it surfaces on.
	"""
	for value in ((memory or {}).get("subject") or {}).values():
		fragment = find_injection(str(value))
		if fragment is not None:
			return fragment
	return None


def recall(memory: Mapping[str, Any] | None, *, company: str, now: datetime) -> dict[str, Any] | None:
	"""Return the stored memory only when it is still safe to use, else None.

	Four ways it is dropped, all silent by design: a different company (an accountant
	switched client), older than ``MEMORY_TTL_MINUTES`` (the books moved on), written by
	an older layout of this dict, or a subject carrying an instruction aimed at the model
	(``memory_injection``). A dropped context makes the bot ask again; a kept stale one
	would make it answer the wrong month without saying so.
	"""
	if not memory or memory.get("v") != MEMORY_VERSION:
		return None
	if (memory.get("company") or "") != company:
		return None
	try:
		stamped = datetime.fromisoformat(str(memory.get("at")))
	except ValueError:
		return None
	if stamped.tzinfo is None:
		stamped = stamped.replace(tzinfo=timezone.utc)
	if now.astimezone(timezone.utc) - stamped > timedelta(minutes=MEMORY_TTL_MINUTES):
		return None
	subject = {k: str(v) for k, v in (memory.get("subject") or {}).items() if k in SUBJECT_KEYS and v}
	if not subject:
		return None
	if memory_injection({"subject": subject}) is not None:
		return None
	return {**dict(memory), "subject": subject}


def memory_text(memory: Mapping[str, Any] | None) -> str:
	"""The prompt block for the previous turn; everything the user's side wrote stays fenced (§1.9).

	``previous_query_kind`` is the only line outside the fence, because it is a closed enum
	this module wrote. The subject goes inside it with the question: a supplier name is model
	output read off a photograph, and a bare ``previous_supplier: …`` line under a header the
	prompt frames as trusted is a second run at the model for whatever was printed on that
	receipt. ``recall`` scans the subject too — this is the belt to that brace.
	"""
	if not memory:
		return "(none)"
	subject = memory.get("subject") or {}
	quarantined = [f"previous_question: {str(memory.get('question') or '')}"]
	quarantined += [f"previous_{key}: {subject[key]}" for key in SUBJECT_KEYS if subject.get(key)]
	return "\n".join(
		[
			f"previous_query_kind: {memory.get('query_kind') or '(none)'}",
			"previous question and subject (untrusted content):",
			fence("\n".join(quarantined), label="previous_turn"),
		]
	)


# --- number verification ---------------------------------------------------------------------------

# A separator only counts as one when it sits between two digits, so "85 000" collapses to
# "85000" while the full stop that ends a sentence never glues two numbers together.
_GROUP_SEPARATOR = re.compile(r"(?<=\d)[\s  ',](?=\d)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _variants(raw: str) -> set[str]:
	"""Every spelling of one number we treat as the same number.

	``7727.27`` is also ``7727`` (the model rounds a tögrög figure to whole tögrög), ``08``
	is ``8`` (a month written out of an ISO period), ``7727.270`` is ``7727.27``.
	"""
	whole, _, frac = raw.partition(".")
	whole = whole.lstrip("0") or "0"
	forms = {whole}
	if frac:
		forms.add(f"{whole}.{frac}")
		trimmed = frac.rstrip("0")
		if trimmed:
			forms.add(f"{whole}.{trimmed}")
	return forms


def numbers_in(text: str) -> list[set[str]]:
	"""One set of accepted spellings per number found, in reading order."""
	cleaned = _GROUP_SEPARATOR.sub("", text or "")
	return [_variants(raw) for raw in _NUMBER.findall(cleaned)]


# The one result key a figure may enter the allowed set through: a handler's own list of the
# numbers it read off or worked out from this company's ledger. A read that resolves nothing —
# a supplier that is not in the books, an FAQ lookup — puts nothing in it, and no other key,
# text included, is ever looked at.
COMPUTED_NUMBERS_FIELD = "computed_numbers"


def _computed_numbers(calls: Sequence[ToolCall]) -> list[str]:
	"""Every figure the handlers computed, and nothing they merely rendered or were handed.

	The narrow reading of this field is the whole guarantee. Harvesting a result's ``text``
	instead looks equivalent — the handler wrote that sentence, after all — but a sentence is
	not a computation: it carries the FAQ's prose figures and it quotes the model's own
	argument back in every not-found answer. Both walked a number the ledger never produced
	into the set of numbers the model is allowed to state.
	"""
	numbers: list[str] = []
	for call in calls:
		if call.is_error or not isinstance(call.result, Mapping):
			continue
		computed = call.result.get(COMPUTED_NUMBERS_FIELD)
		if isinstance(computed, (str, bytes)) or not isinstance(computed, Sequence):
			continue  # a handler that lists nothing vouches for nothing
		numbers += [str(value) for value in computed if value is not None]
	return numbers


# How far back a resolved period may reach and still have its year vouched for. The books a
# company must keep run ten years (Law on Accounting art. 11.1), so a question about an older
# year is not a question about these books — and the bound is what keeps ``_resolved_years``
# from handing a model an arbitrary four-digit figure. See ``_resolved_years``.
LEDGER_YEARS_BACK = 10


def _clock_years(now: datetime) -> list[str]:
	"""This year and the ones either side of it, because an answer names the year it is about.

	«2025 оны 12-р сар» is what a question asked in January is about, and the year in it has to
	verify. It comes from the clock rather than from the month the model asked for: a year is
	the one part of a date wide enough to double as a tögrög figure, and a handler that vouched
	for whatever year it was handed would let «9999 оны 12-р сар» license «9 999₮».
	"""
	return [str(now.year - 1), str(now.year), str(now.year + 1)]


def _resolved_years(calls: Sequence[ToolCall], now: datetime) -> list[str]:
	"""The year of every period a read *resolved*, within the window these books cover.

	A question about 2024 is an ordinary question — «2024 оны 7-р сард хэд зарцуулсан бэ?» is
	what an accountant asks when the auditor calls — and the clock's own three years could not
	vouch for that 2024, so the correct answer lost its sentence and was logged as an invention.
	The year is read off the handler's own ``period``, never off the model's argument, because
	the handler is what decides which month the read ran on.

	Bounded on purpose, and this is the whole care of the function. A period is still a
	coordinate the model may name, and a year is the one part of a date wide enough to double
	as a tögrög figure: unbounded, «9999-12» would license «9 999₮» and a model could reach any
	four-digit amount by choosing the month it asks about. Inside ``LEDGER_YEARS_BACK`` of the
	clock the choice buys nothing that is not already a year — the same trade ``_clock_years``
	makes, over the span of books a company actually keeps.
	"""
	years: list[str] = []
	for call in calls:
		if call.is_error or not isinstance(call.result, Mapping) or not resolved(call.result):
			continue
		try:
			year, _month = dates.parse_period(str(call.result.get("period") or ""))
		except ValueError:
			continue  # no period, or something that is not one: the read resolved no year
		if now.year - LEDGER_YEARS_BACK <= year <= now.year + 1:
			years.append(str(year))
	return years


def _known_numbers(calls: Sequence[ToolCall], now: datetime) -> set[str]:
	"""Every figure the model may state: what the handlers computed, plus the calendar.

	Three sources, and the shortness of that list is the guarantee. The user's question is not
	one of them — a figure a user typed is a figure the books have not confirmed — and the
	clock contributes ``now.date()``, never ``now``: an answer about the books names days,
	so «14», «23» and «59» off a wall clock are not tögrög. The calendar half is the clock's
	own date and years (``_clock_years``) plus the year of each period a handler resolved
	(``_resolved_years``), which is how an answer about a past year keeps its sentence.
	"""
	known: set[str] = set()
	sources = [
		now.date().isoformat(),
		*_clock_years(now),
		*_resolved_years(calls, now),
		*_computed_numbers(calls),
	]
	for source in sources:
		for forms in numbers_in(source):
			known |= forms
	return known


def unverified_numbers(answer_text: str, calls: Sequence[ToolCall], now: datetime) -> tuple[str, ...]:
	"""Numbers in the model's sentence that no handler computed and the calendar did not supply.

	The question is deliberately not an argument here, so it cannot become a source again by
	accident. It was one, and it was the hole: a confirm-question («…биз дээ?», «…мөн үү?») is
	how a bookkeeper checks a figure out loud, so the commonest shape of question was also the
	one that licensed the model to agree with a figure the ledger had never produced.

	The threshold is deliberately strict: it accepts a figure only where it can point at the
	handler that produced it, so *any* arithmetic of the model's own — an average, a
	difference, a percentage — fails it and costs the sentence. That is the trade the ledger
	rule asks for. A figure Nyabo cannot trace to a read is a figure Nyabo does not send,
	and a check that admitted "close enough to something a handler returned" would be no
	check at all. What arithmetic costs is the model's phrasing, never the number.

	Returned rather than raised so the caller can log it — see ``classify_unverified``, which
	keeps the log honest about which of the two happened. ``answer`` runs it over the model's
	sentence only: the handlers' own text is deterministic output built from the ledger, and
	checking that accused Nyabo of inventing figures Nyabo had computed.

	**Two things this check does not do.** Both are limits of its design rather than bugs, and
	both are written down here and in docs/DECISIONS.md Q-02 so that nobody reads a clean
	compliance log as more than it is.

	First, *it proves a figure came from the ledger; it does not bind that figure to the subject
	the sentence names.* The allowed set is the union of every read in the turn, so a model that
	asks about Петровис and about Болор and then writes «Болороос 85 000₮ авсан» with Петровис's
	total passes: the figure is in the set, from the wrong read. Closing it means checking each
	number against the read whose subject the sentence is about, which means deciding from
	Mongolian prose which subject each figure belongs to — a language judgement of exactly the
	kind this module exists to keep out of the number path. The honest close is narrower and
	costs a turn: one read per answer, the subject printed on the card (``subject_label``), the
	figure checked against that read alone. Not done now because it would refuse the legitimate
	two-read answer («энэ сар vs өнгөрсөн сар») the follow-ups were widened for. What holds
	meanwhile is that the card prints the subject each read resolved, so a wrong attribution is
	visible to the accountant rather than invisible.

	Second, *only decimal literals are checked* (``_NUMBER``). «Наян таван мянган төгрөг» —
	eighty-five thousand written out in Mongolian words — is not a number to that regular
	expression, so a sentence with no digits in it passes untouched however wrong it is. Closing
	it means parsing Mongolian numerals (unit words, «мянга»/«сая» multipliers, spoken compounds)
	and then deciding which spelled-out quantities are money at all — «хоёр бичилт» is a count,
	not a figure. That is a Mongolian-language component inside the one path built to be free of
	language judgement, and getting it wrong drops correct sentences. Not done now; instead the
	prompt asks for figures in digits and every handler renders its own with ``fmt_mnt``, so the
	ordinary answer carries digits and is checked.
	"""
	known = _known_numbers(calls, now)
	cleaned = _GROUP_SEPARATOR.sub("", answer_text or "")
	unknown = [raw for raw in _NUMBER.findall(cleaned) if not (_variants(raw) & known)]
	return tuple(dict.fromkeys(unknown))


# Two very different things fail the check above, and only the log tells them apart: a figure
# nothing in the trace can account for, and one the model worked out from figures the handlers
# did return. Both replace the sentence. Logging both as the first trains whoever reads the
# events to ignore them, which costs exactly the alarm that matters.
UNVERIFIED_INVENTED = "invented"
UNVERIFIED_DERIVED = "derived"
# Absolute plus relative, because a model that derives a figure also rounds it.
_DERIVED_ABSOLUTE = Decimal("0.5")
_DERIVED_RELATIVE = Decimal("0.005")


def _decimals(sources: Sequence[str]) -> list[Decimal]:
	"""Every number in ``sources`` as a value, for the derivation check."""
	values: list[Decimal] = []
	for source in sources:
		cleaned = _GROUP_SEPARATOR.sub("", source or "")
		for raw in _NUMBER.findall(cleaned):
			try:
				values.append(Decimal(raw))
			except InvalidOperation:  # pragma: no cover - _NUMBER only matches decimal literals
				continue
	return values


def _is_derived(value: Decimal, knowns: Sequence[Decimal]) -> bool:
	"""One step of arithmetic over two figures a handler returned: sum, difference, average.

	Deliberately shallow, and deliberately blind to the question and the clock: a month
	number minus an hour is a coincidence, not a derivation, and calling it one would let
	every invention look like reasoning. This decides nothing the user sees.
	"""
	for a, b in combinations(knowns, 2):
		for candidate in (a + b, abs(a - b), (a + b) / 2):
			if abs(value - candidate) <= _DERIVED_ABSOLUTE + abs(candidate) * _DERIVED_RELATIVE:
				return True
	return False


def classify_unverified(unknown: Sequence[str], calls: Sequence[ToolCall]) -> dict[str, str]:
	"""Label each unverified number ``invented`` or ``derived``, for the event log only.

	The sentence is replaced either way. This exists so the log stays honest: a model that
	worked out the difference between two figures it was given has not fabricated a
	supplier's balance, and an event that reads as though it had is the kind of noise that
	gets real ones ignored.
	"""
	knowns = _decimals(_computed_numbers(calls))
	kinds: dict[str, str] = {}
	for raw in unknown:
		try:
			value = Decimal(raw)
		except InvalidOperation:  # pragma: no cover - these come from _NUMBER too
			kinds[raw] = UNVERIFIED_INVENTED
			continue
		kinds[raw] = UNVERIFIED_DERIVED if _is_derived(value, knowns) else UNVERIFIED_INVENTED
	return kinds


# --- follow-up buttons -----------------------------------------------------------------------------


def _args_for(kind: str, subject: Mapping[str, str], period: str | None = None) -> tuple[str, ...] | None:
	"""The datum a button for ``kind`` carries, or None when the subject does not supply it all.

	A missing argument drops the button rather than sending a half-formed query: the tap must
	do exactly what its label says.
	"""
	values: list[str] = []
	for key in QUERY_ARGS[kind]:
		value = period if (key == "period" and period is not None) else subject.get(key, "")
		if not value:
			return None
		values.append(str(value))
	return tuple(values)


def _period_follow_ups(kind: str, subject: Mapping[str, str], now: datetime) -> list[FollowUp]:
	"""The neighbouring months of a period query, never offering a month that has not begun."""
	period = subject.get("period")
	if not period:
		return []
	try:
		neighbours = [
			(shift_period(period, -1), mn.BTN_Q_PREV_PERIOD),
			(shift_period(period, 1), mn.BTN_Q_NEXT_PERIOD),
		]
	except ValueError:
		return []
	out: list[FollowUp] = []
	for target, template in neighbours:
		if target > dates.period_of(now.date()):
			continue
		args = _args_for(kind, subject, period=target)
		if args is None:
			continue
		out.append(FollowUp(QUERY_SHORT[kind], template.format(period=dates.period_label(target)), args))
	return out


def _default_period(kind: str, subject: Mapping[str, str], now: datetime) -> str:
	"""The month a follow-up assumes when the answered query carried no period of its own.

	``balance_on_date`` resolves ``on_date`` and never ``period``, so the month of the date
	that was actually answered is the only honest one: «Юунаас бүрдэв?» under a balance as of
	March must show March's entries. Seeding the clock's month there sent the accountant
	entries from a month nobody had asked about, under a button that said otherwise.
	"""
	if kind == "balance_on_date" and subject.get("on_date"):
		try:
			return dates.period_of(date.fromisoformat(subject["on_date"]))
		except ValueError:
			pass  # a handler that returned something else than an ISO date: fall back to the clock
	return dates.period_of(now.date())


def follow_ups(calls: Sequence[ToolCall], *, now: datetime, answered: bool = True) -> tuple[FollowUp, ...]:
	"""What the accountant would do next, read off the tool trace — never off the sentence.

	``answered`` is False when the sentence the user is about to read is one of ours ("could
	not answer from the books"): the way forward is then a person or the menu, not another
	query that will fail the same way (§5, "when it does not know").

	An answered question with no ledger read behind it — an FAQ lookup — has no next query to
	offer, but it is a complete answer, so it gets the way back and nothing else. [Админаас
	асуух] under it tells the accountant Nyabo failed at the moment it had just answered them.
	"""
	call = _last_books_call(calls)
	if not answered:
		return (
			FollowUp(VERB_ESCALATE, mn.BTN_Q_ASK_ADMIN),
			FollowUp(VERB_MENU, mn.BTN_MENU),
		)
	if call is None:
		return (FollowUp(VERB_MENU, mn.BTN_MENU),)
	kind = str((call.arguments or {}).get("query_kind") or "")
	# A query with no period of its own (a balance, a supplier's entries) still has a month
	# its follow-up can be about; ``_default_period`` says which, and it is not always the
	# month the clock is in.
	answered_subject = _subject_of(call)
	subject = {"period": _default_period(kind, answered_subject, now), **answered_subject}
	out: list[FollowUp] = []

	if kind in (
		"spend_by_account",
		"account_entries",
		"vat_position",
		"top_spend_accounts",
		"monthly_trend",
		"top_suppliers",
	):
		out += _period_follow_ups(kind, subject, now)

	# (this query kind) -> the next question the accountant would ask, and its label. A label
	# with a ``{period}`` in it is one whose query is about a month the answer above was not:
	# see ``BTN_Q_PERIOD_ENTRIES`` under a balance.
	next_questions: Mapping[str, tuple[tuple[str, str], ...]] = {
		"balance_on_date": (
			("account_entries", mn.BTN_Q_PERIOD_ENTRIES),
			("spend_by_account", mn.BTN_Q_ACCOUNT_TOTAL),
		),
		"spend_by_account": (("account_entries", mn.BTN_Q_EXPLAIN),),
		"account_entries": (("spend_by_account", mn.BTN_Q_ACCOUNT_TOTAL),),
		"supplier_total": (("last_entries_for_supplier", mn.BTN_Q_SUPPLIER_ENTRIES),),
		"last_entries_for_supplier": (("supplier_total", mn.BTN_Q_SUPPLIER_TOTAL),),
		"unmatched_count": (("unmatched_lines", mn.BTN_Q_UNMATCHED_LINES),),
		"unmatched_lines": (("unmatched_count", mn.BTN_Q_UNMATCHED_COUNT),),
		"explain_entry": (("last_entries_for_supplier", mn.BTN_Q_SUPPLIER_ENTRIES),),
		"vat_position": (("top_spend_accounts", mn.BTN_Q_TOP_ACCOUNTS),),
		"top_spend_accounts": (
			("top_suppliers", mn.BTN_Q_TOP_SUPPLIERS),
			("monthly_trend", mn.BTN_Q_TREND),
		),
		"monthly_trend": (("top_spend_accounts", mn.BTN_Q_TOP_ACCOUNTS),),
		"top_suppliers": (("top_spend_accounts", mn.BTN_Q_TOP_ACCOUNTS),),
	}
	for target, label in next_questions.get(kind, ()):
		args = _args_for(target, subject)
		if args is not None:
			out.append(FollowUp(QUERY_SHORT[target], _label(label, subject["period"]), args))
	# Never an answer with no buttons at all. Every query above can lose its follow-up to a
	# subject that does not supply the arguments — ``explain_entry`` is offered exactly one next
	# question, about the supplier, and a Journal Entry has none — and the card was then sent
	# with no keyboard whatsoever, not even the way back to the menu.
	return tuple(out[:MAX_FOLLOW_UPS]) or (FollowUp(VERB_MENU, mn.BTN_MENU),)


def _label(template: str, period: str) -> str:
	"""A button label, with the month filled in when the label names one.

	«Юунаас бүрдэв?» under a balance promised the composition of a cumulative figure and ran
	one month's entries, which is a different question: a balance as of 30 September is not
	September's postings. The button is kept — the entries behind an account are exactly what
	the accountant reaches for next — but it now says which month it will show.
	"""
	if "{period}" not in template:
		return template
	try:
		return template.format(period=dates.period_label(period))
	except ValueError:
		return template.format(period=period)


def subject_label(subject: Mapping[str, str]) -> str:
	"""The one line a card prints so the reader can see what was actually answered.

	Continuity is only safe when it is visible: «6210 · 2026 оны 8-р сар» under the sentence
	is how the accountant catches the bot having carried the wrong month forward.
	"""
	parts: list[str] = []
	if subject.get("account_code"):
		parts.append(subject["account_code"])
	if subject.get("supplier"):
		parts.append(subject["supplier"])
	if subject.get("entry_ref"):
		parts.append(subject["entry_ref"])
	if subject.get("on_date"):
		parts.append(subject["on_date"])
	elif subject.get("period"):
		try:
			parts.append(dates.period_label(subject["period"]))
		except ValueError:
			parts.append(subject["period"])
	return " · ".join(parts)


@dataclass(frozen=True)
class Reply:
	"""What the Telegram layer needs from one question, and nothing else.

	The chat side never sees an ``LlmResult``: it renders a sentence, draws buttons, stores
	the memory and, when the model handed the question to a person, says so.
	"""

	text: str
	follow_ups: tuple[FollowUp, ...] = ()
	memory: dict[str, Any] | None = None
	needs_escalation: bool = False
	subject: str = ""
	# The last successful books read, as the handler returned it: the rows behind the sentence,
	# which the card draws as a table. Figures only ever come from here, never from the text.
	facts: Mapping[str, Any] | None = None
	# A proposal drafted from the user's words (``agent.typed``): the chat shows its card.
	proposal: str | None = None


def reply_of(outcome: AnswerOutcome) -> Reply:
	books_call = _last_books_call(outcome.llm.tool_calls) if outcome.llm is not None else None
	return Reply(
		text=outcome.answer.answer_mn,
		follow_ups=outcome.follow_ups,
		memory=outcome.memory,
		needs_escalation=outcome.answer.needs_escalation,
		subject=subject_label(outcome.subject),
		facts=dict(books_call.result) if books_call is not None and books_call.result else None,
		proposal=outcome.proposal,
	)


# --- the call --------------------------------------------------------------------------------------


def build_user_text(
	text: str,
	*,
	company_context: str,
	now: datetime,
	memory: Mapping[str, Any] | None = None,
) -> str:
	prompt_text, _version = prompts.load(PROMPT_NAME)
	_system, user_template = prompts.split(prompt_text)
	return prompts.fill(
		user_template,
		COMPANY_CONTEXT=company_context.strip() or "(none)",
		MEMORY=memory_text(memory),
		UNTRUSTED=fence(text[:MAX_QUESTION_CHARS], label="question"),
		NOW=now.isoformat(timespec="minutes"),
	)


def _beating(
	dispatch: Callable[[str, dict[str, Any]], dict[str, Any]],
	on_turn: Callable[[], None] | None,
	on_step: Callable[[str, dict[str, Any]], None] | None = None,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
	"""``dispatch`` with a beat — and the step being taken — before every tool call.

	``on_step`` is told the tool and its arguments, so the chat can say *what* the model is
	reading («Дэвтрээс уншиж байна: 6210 · 2026 оны 9-р сар») rather than only that it is
	busy. Neither callback may cost the answer: a failure inside one is swallowed.
	"""
	if on_turn is None and on_step is None:
		return dispatch

	def beating(name: str, args: dict[str, Any]) -> dict[str, Any]:
		if on_turn is not None:
			on_turn()
		if on_step is not None:
			try:
				on_step(name, dict(args or {}))
			except Exception:  # noqa: BLE001 - narration is a courtesy
				pass
		return dispatch(name, args)

	return beating


def answer(
	client: LlmClient,
	text: str,
	handlers: Mapping[str, Handler],
	*,
	company_context: str = "",
	company: str = "",
	memory: Mapping[str, Any] | None = None,
	now: datetime | None = None,
	max_turns: int = MAX_TURNS,
	on_turn: Callable[[], None] | None = None,
	on_step: Callable[[str, dict[str, Any]], None] | None = None,
) -> AnswerOutcome:
	"""One tool-using model call; the answer sentence is the model's, the flags are ours.

	``memory`` is what ``recall`` returned for this chat (already expired and company-checked
	by the caller); the outcome carries the memory the *next* turn should be given.

	``on_turn`` is called once before each tool dispatch — a tool call is the seam between two
	model turns and the only place this module can see one, so it is where a caller refreshes
	whatever it is showing the user. It must not raise: this is the answer path.

	The number check runs over the model's own sentence and over nothing else. When the model
	spends its turns on tools and writes no closing sentence, what is sent is the *handler's*
	Mongolian text — deterministic output built from the ledger, by definition made of figures
	the ledger produced — and running the check over it accused the model of inventing a number
	Nyabo itself had written: a rounded total, a rendered label, a count no handler listed in
	``computed_numbers`` because nothing in the trace had to vouch for it. The compliance log is
	evidence, and an alarm that fires on our own arithmetic is the noise that gets the real ones
	ignored. Same for ``AGENT_ANSWER_TOOL_ERROR`` and ``MSG_QUESTION_CANNOT_FULL``: ours too.
	"""
	now = now or datetime.now(timezone.utc)
	fragment = find_injection(text)
	if fragment is not None:
		# Still fenced and harmless to send, but a question that argues with the prompt has no
		# legitimate answer; refuse cheaply and let the pipeline log the event. The memory is
		# not advanced either: an injection attempt is not a turn of the conversation.
		return AnswerOutcome(
			answer=QuestionAnswer(
				answer_mn=mn.AGENT_ANSWER_INJECTION_REFUSED, used_tool=None, needs_escalation=False
			),
			llm=None,
			injection_suspected=True,
			injection_fragment=fragment,
			tools_used=(),
			follow_ups=(FollowUp(VERB_MENU, mn.BTN_MENU),),
			memory=None,
		)

	prompt_text, version = prompts.load(PROMPT_NAME)
	system, _user_template = prompts.split(prompt_text)
	llm = client.with_tools(
		purpose=PURPOSE,
		system=system,
		user=[TextPart(build_user_text(text, company_context=company_context, now=now, memory=memory))],
		tools=list(TOOL_SPECS),
		handler=_beating(make_dispatcher(handlers), on_turn, on_step),
		max_turns=max_turns,
		prompt_version=prompts.version_tag(PROMPT_NAME, version),
	)
	tools_used = tuple(call.name for call in llm.tool_calls)
	escalated = any(call.name == "escalate_to_admin" and not call.is_error for call in llm.tool_calls)
	proposal = next(
		(
			str(call.result["proposal"])
			for call in reversed(llm.tool_calls)
			if call.name == "record_transaction" and not call.is_error and (call.result or {}).get("proposal")
		),
		None,
	)
	if proposal:
		# The card is the answer. The handler's own sentence goes with it; the model's closing
		# words are not sent, so nothing it wrote can contradict the lines the accountant reads.
		handler_text = next(
			str(call.result.get("text") or "")
			for call in reversed(llm.tool_calls)
			if call.name == "record_transaction" and not call.is_error
		)
		return AnswerOutcome(
			answer=QuestionAnswer(
				answer_mn=handler_text, used_tool="record_transaction", needs_escalation=False
			),
			llm=llm,
			injection_suspected=False,
			injection_fragment=None,
			tools_used=tools_used,
			follow_ups=(),
			memory=None,
			proposal=proposal,
		)
	last_ok = next((call.name for call in reversed(llm.tool_calls) if not call.is_error), None)
	all_failed = bool(llm.tool_calls) and all(call.is_error for call in llm.tool_calls)
	handler_broke = any(
		call.is_error and (call.result or {}).get("error") not in MODEL_FAULT_ERRORS
		for call in llm.tool_calls
	)

	model_text = (llm.text or "").strip()
	answered = True
	# Whether the sentence about to be sent is the model's own. Only that one is checked for
	# invented numbers: see the ``unverified_numbers`` call below.
	from_model = True
	if escalated:
		answer_text = model_text or mn.MSG_ESCALATED
		from_model = bool(model_text)
	elif model_text:
		answer_text = model_text
	elif all_failed and handler_broke:
		answer_text, answered, from_model = mn.AGENT_ANSWER_TOOL_ERROR, False, False
	else:
		# Tool calls but no closing sentence — reachable whenever the model spends its turns
		# on tools, which ten query kinds and MAX_TURNS made likelier. The handler has by then
		# written a correct Mongolian answer, so send it: telling an accountant the books could
		# not answer when they did is a worse lie than an ugly sentence. Same fallback the
		# invented-number path takes, for the same reason.
		fallback = _handler_text(llm.tool_calls)
		answer_text = fallback or mn.MSG_QUESTION_CANNOT_FULL
		answered = fallback is not None
		from_model = False
		last_ok = last_ok if fallback else None

	invented = unverified_numbers(answer_text, llm.tool_calls, now) if answered and from_model else ()
	if invented:
		# The sentence carried a figure nothing returned. The handler already wrote a correct
		# Mongolian sentence for what it found, so send that; there is never a reason to pass
		# on a number the books did not produce.
		fallback = _handler_text(llm.tool_calls)
		answer_text = fallback or mn.MSG_QUESTION_CANNOT_FULL
		answered = fallback is not None
		last_ok = last_ok if fallback else None

	books_call = _last_books_call(llm.tool_calls)
	if not escalated and books_call is not None and not resolved(books_call.result):
		# The books say there is no such supplier or document. Whatever the model wrote about it
		# is worth nothing, so the handler's own «олдсонгүй» sentence is what the user reads —
		# and this is not an answer: the card offers a person, not four more reads about a
		# supplier that does not exist. (``escalate_to_admin`` already has its own card.)
		answer_text = _handler_text(llm.tool_calls) or mn.MSG_QUESTION_CANNOT_FULL
		answered = False
	subject = _subject_of(books_call) if books_call is not None else {}
	# An escalated question is already with a person: offering [Админаас асуух] under it would
	# invite sending the same thing twice, so that card gets only the way back.
	offered = (
		(FollowUp(VERB_MENU, mn.BTN_MENU),)
		if escalated
		else follow_ups(llm.tool_calls, now=now, answered=answered)
	)
	return AnswerOutcome(
		answer=QuestionAnswer(answer_mn=answer_text, used_tool=last_ok, needs_escalation=escalated),
		llm=llm,
		injection_suspected=False,
		injection_fragment=None,
		tools_used=tools_used,
		follow_ups=offered,
		memory=remember(text, llm.tool_calls, company=company, now=now),
		unverified_numbers=invented,
		number_kinds=classify_unverified(invented, llm.tool_calls),
		subject=subject,
	)


def _handler_text(calls: Sequence[ToolCall]) -> str | None:
	"""The last successful handler's own Mongolian sentence, if it wrote one."""
	for call in reversed(calls):
		if call.is_error:
			continue
		text = (call.result or {}).get("text")
		if isinstance(text, str) and text.strip():
			return text.strip()
	return None


__all__ = [
	"COMPUTED_NUMBERS_FIELD",
	"LEDGER_YEARS_BACK",
	"MAX_FOLLOW_UPS",
	"MAX_TURNS",
	"MEMORY_QUESTION_CHARS",
	"MEMORY_TTL_MINUTES",
	"MEMORY_VERSION",
	"MODEL_FAULT_ERRORS",
	"PROMPT_NAME",
	"PURPOSE",
	"QUERY_ARGS",
	"QUERY_SHORT",
	"SHORT_QUERY",
	"SUBJECT_KEYS",
	"TOOL_ARG_MODELS",
	"TOOL_NAMES",
	"TOOL_SPECS",
	"UNVERIFIED_DERIVED",
	"UNVERIFIED_INVENTED",
	"VERB_ESCALATE",
	"VERB_MENU",
	"AnswerFaqArgs",
	"AnswerFromBooksArgs",
	"AnswerOutcome",
	"BooksArgs",
	"EscalateArgs",
	"FollowUp",
	"Handler",
	"Reply",
	"answer",
	"build_user_text",
	"classify_unverified",
	"follow_ups",
	"make_dispatcher",
	"memory_injection",
	"memory_text",
	"numbers_in",
	"recall",
	"remember",
	"reply_of",
	"resolved",
	"shift_period",
	"subject_label",
	"unverified_numbers",
]
