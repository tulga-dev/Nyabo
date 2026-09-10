"""Thin shims around the modules the Telegram layer calls but does not own.

Why a shim module: the agent, matching, reports, compliance, evals and setup packages are
built in parallel (docs/ARCHITECTURE.md §3). Handlers import *this* module and call
``_deps.post_proposal(...)`` so that (a) a missing module fails with a clear
``NotImplementedError`` naming the dotted path instead of an ImportError at import time,
and (b) tests monkeypatch one attribute here rather than the real module.

Every function keeps the signature of the contract it wraps; nothing here adds logic. The
inventory group below is the one exception and says why in its own header: the intake module
speaks ``IntakeRow`` dataclasses and wants a spreadsheet already read into cells, while the
handler and ``cards.py`` carry plain dicts and hand over a raw upload.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable
from typing import Any


class DependencyMissing(NotImplementedError):
	"""Raised when a sibling module has not landed in this checkout yet."""


def _call(module: str, function: str, *args: Any, **kwargs: Any) -> Any:
	try:
		mod = importlib.import_module(module)
	except ImportError as exc:
		raise DependencyMissing(f"{module}.{function} is not available: {exc}") from exc
	fn = getattr(mod, function, None)
	if fn is None:
		raise DependencyMissing(f"{module}.{function} is not available")
	return fn(*args, **kwargs)


# --- nyabo_mn.agent.pipeline / nyabo_mn.agent.post ----------------------------------------------
# The pipeline reads documents and answers questions; ``agent.post`` owns everything that
# touches an accounting document (approve, change account, reject, correct) - see agent/post.py.


def process_receipt(document_name: str) -> Any:
	return _call("nyabo_mn.agent.pipeline", "process_receipt", document_name)


def post_proposal(proposal_name: str, approver_user: str, approver_telegram_id: str) -> dict[str, Any]:
	return _call("nyabo_mn.agent.post", "post_proposal", proposal_name, approver_user, approver_telegram_id)


def change_account(proposal_name: str, code: str, user: str) -> Any:
	return _call("nyabo_mn.agent.post", "change_account", proposal_name, code, user)


def reject(proposal_name: str, reason_code: str, user: str, reason_text: str | None = None) -> Any:
	return _call("nyabo_mn.agent.post", "reject", proposal_name, reason_code, user, reason_text=reason_text)


def top_accounts(company: str, n: int = 6) -> list[tuple[str, str]]:
	return _call("nyabo_mn.agent.post", "top_accounts", company, n=n)


def search_accounts(company: str, query: str) -> list[tuple[str, str]]:
	return _call("nyabo_mn.agent.post", "search_accounts", company, query)


def make_correction_proposal(original_doctype: str, original_name: str, reason_code: str, user: str) -> str:
	return _call(
		"nyabo_mn.agent.post", "make_correction_proposal", original_doctype, original_name, reason_code, user
	)


def answer_question(
	user: str,
	company: str,
	text: str,
	memory: dict[str, Any] | None = None,
	on_turn: Callable[[], None] | None = None,
) -> Any:
	"""``agent.questions.Reply``: the sentence, its follow-up buttons and the memory to store.

	``on_turn`` is called between model turns, so the chat can keep showing a sign of life
	through an answer that takes several of them. It must not raise.
	"""
	return _call(
		"nyabo_mn.agent.pipeline", "answer_question", user, company, text, memory=memory, on_turn=on_turn
	)


def books_answer(company: str, query_kind: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
	"""One read-only query with no model in the loop: what a follow-up button under an answer runs."""
	return _call("nyabo_mn.agent.pipeline", "books_answer", company, query_kind, args)


def escalate_question(user: str, company: str, question: str, summary: str) -> dict[str, Any]:
	return _call("nyabo_mn.agent.pipeline", "escalate_question", user, company, question, summary)


# --- nyabo_mn.matching -------------------------------------------------------------------------


def import_statement(document_name: str) -> dict[str, Any]:
	return _call("nyabo_mn.matching.bank_import", "import_statement", document_name)


def bank_import_error() -> type[Exception]:
	"""``bank_import.BankImportError``, resolved late like every other target here.

	The importer raises it with a Mongolian message the accountant can act on (no bank
	account configured, no lines, an unreadable file), so the handler shows that text
	instead of the generic "admin notified" reply. ``ValueError`` (its base) stands in
	when the matching package has not landed, which matches nothing the importer raises.
	"""
	try:
		module = importlib.import_module("nyabo_mn.matching.bank_import")
	except ImportError:
		return ValueError
	error = getattr(module, "BankImportError", None)
	return error if isinstance(error, type) and issubclass(error, Exception) else ValueError


def recon_status(company: str) -> str:
	"""The ``/данс`` card: statement vs ledger balance per bank account, as text."""
	return _call("nyabo_mn.matching.status", "render", company)


def render_bank_line(bank_transaction: str) -> str:
	return _call("nyabo_mn.matching.cards", "render_bank_line", bank_transaction)


def find_candidates(bank_transaction: str, query: str) -> list[Any]:
	return _call("nyabo_mn.matching.match", "find_candidates", bank_transaction, query)


def reconcile(bank_transaction: str, voucher_doctype: str, voucher_name: str, user: str) -> Any:
	return _call(
		"nyabo_mn.matching.match", "reconcile", bank_transaction, voucher_doctype, voucher_name, user
	)


def settle(
	bank_transaction: str, voucher_doctype: str, voucher_name: str, user: str, telegram_id: str
) -> Any:
	"""[Төлбөр бүртгэх]: the Payment Entry that pays an open invoice from this statement line."""
	return _call(
		"nyabo_mn.matching.match",
		"settle",
		bank_transaction,
		voucher_doctype,
		voucher_name,
		user,
		telegram_id=telegram_id,
	)


def settlement_candidate(bank_transaction: str) -> Any:
	"""The open invoice this line clearly pays, or None (a button, never a posting)."""
	return _call("nyabo_mn.matching.match", "settlement_candidate", bank_transaction)


def propose_bank_expense(bank_transaction: str, account_code: str, user: str) -> str:
	# UNVERIFIED: not in the stated contract; the matching agent owns the shape. Returns a proposal name.
	return _call("nyabo_mn.matching.match", "propose_expense", bank_transaction, account_code, user)


# --- nyabo_mn.reports / compliance / evals -----------------------------------------------------


def checklist(company: str, period: str) -> dict[str, Any]:
	return _call("nyabo_mn.reports.month_end", "checklist", company, period)


def summaries(company: str, period: str) -> dict[str, Any]:
	return _call("nyabo_mn.reports.month_end", "summaries", company, period)


def lock_period(company: str, period: str, user: str) -> Any:
	return _call("nyabo_mn.compliance.period", "lock", company, period, user)


def reverse(doctype: str, name: str, reason_code: str, reason_text: str, user: str) -> dict[str, Any]:
	return _call("nyabo_mn.compliance.reversal", "reverse", doctype, name, reason_code, reason_text, user)


def policy_pdf(company: str) -> bytes:
	return _call("nyabo_mn.compliance.policy_doc", "generate_pdf", company)


def quality_summary(company: str, days: int = 30) -> dict[str, Any]:
	return _call("nyabo_mn.evals.metrics", "quality_summary", company, days=days)


# --- nyabo_mn.setup / rules --------------------------------------------------------------------


# The inventory shims are the exception the module docstring names: they translate between the
# two shapes rather than only forwarding. The chat side owns plain dicts (``cards.inventory_total``
# reads ``item.get("qty")``) and an uploaded file as bytes; ``setup.inventory_intake`` owns
# ``IntakeRow`` and expects a table already read into cells.


def _intake_items(rows: Iterable[Any]) -> list[dict[str, Any]]:
	"""``IntakeRow`` -> the dicts the preview card and the intake document both read."""
	return [row.as_child() if hasattr(row, "as_child") else dict(row) for row in rows]


class _NeverRaised(Exception):
	"""Stands in for an error class whose module has not landed; nothing ever raises it."""


def intake_parse_error() -> type[Exception]:
	"""``inventory_intake.IntakeParseError``, resolved late like every other target here.

	It carries ``message_mn``, a Mongolian sentence Nyabo wrote for the chat, so the handler
	shows that instead of the generic "could not read the list". Unlike ``bank_import_error``
	this does not fall back to ``ValueError``: the caller catches the generic case separately
	and a stand-in that matched every ValueError would send unrelated failures down the path
	that prints ``message_mn``.
	"""
	try:
		module = importlib.import_module("nyabo_mn.setup.inventory_intake")
	except ImportError:
		return _NeverRaised
	error = getattr(module, "IntakeParseError", None)
	return error if isinstance(error, type) and issubclass(error, Exception) else _NeverRaised


def inventory_parse_text(text: str) -> list[dict[str, Any]]:
	return _intake_items(_call("nyabo_mn.setup.inventory_intake", "parse_text", text))


def inventory_parse_table(content: bytes, filename: str) -> list[dict[str, Any]]:
	"""Upload bytes -> rows -> items: ``parse_table`` takes read cells, never a file."""
	rows = _call("nyabo_mn.parsers.excel", "read_rows", content, filename)
	return _intake_items(_call("nyabo_mn.setup.inventory_intake", "parse_table", rows))


def inventory_create_intake(
	company: str, items: list[dict[str, Any]], source: str, user: str, file_url: str | None = None
) -> str:
	"""The draft intake behind the confirmation card; returns its name for the button data.

	The argument order here is the chat's, not the target's - keeping them apart is what the
	live crash needed: ``create_intake(company, source, rows, posting_date)`` was being fed
	the item list as ``source`` and the Telegram user id as ``posting_date``, so ``getdate``
	tried to read "tg-...@nyabo.local" as a date. Opening stock is dated today
	(``frappe.utils.today()`` -> "Return today's date in `yyyy-mm-dd` format" - frappe/utils/data.py);
	``user`` stays in the signature because the router already runs as that user, so Frappe
	stamps the document ``owner``, and the same user is recorded again on the confirming tap.
	"""
	# Imported here, not at module top, so the shim layer stays importable without a bench.
	from frappe.utils import today

	doc = _call(
		"nyabo_mn.setup.inventory_intake",
		"create_intake",
		company,
		source,
		items,
		today(),
		file_url=file_url,
	)
	return str(getattr(doc, "name", doc))


def inventory_cancel_intake(intake_name: str, user: str) -> Any:
	"""The draft behind a confirmation card the accountant left: cancelled, not deleted."""
	return _call("nyabo_mn.setup.inventory_intake", "cancel_intake", intake_name, user)


def inventory_post_intake(intake_name: str, user: str) -> dict[str, Any]:
	"""The [Батлах] tap: record the human confirmation, then post the opening documents.

	``post_intake`` refuses an intake that is still a draft, and this tap on the confirmation
	card is the human approval the ledger rule asks for - nothing else in the flow calls
	``confirm_intake``, so the tap used to be answered with «...баталгаажаагүй» and no opening
	stock was ever posted.
	"""
	_call("nyabo_mn.setup.inventory_intake", "confirm_intake", intake_name, user)
	return _call("nyabo_mn.setup.inventory_intake", "post_intake", intake_name, user)


def apply_onboarding(
	company: str,
	vat_registered: bool,
	banks: list[dict[str, Any]],
	has_inventory: bool,
	accountant_name: str,
	micpa: str,
) -> dict[str, Any]:
	return _call(
		"nyabo_mn.setup.provision_company",
		"apply_onboarding",
		company,
		vat_registered,
		banks,
		has_inventory,
		accountant_name,
		micpa,
	)


def set_regime(company: str, regime: str, effective_from: Any) -> Any:
	return _call("nyabo_mn.rules.regime", "set_regime", company, regime, effective_from)


# --- nyabo_mn.rules.verify (the door MSG_UNVERIFIED_RULE_BLOCKED points at) ----------------------


def pending_rules(limit: int | None = None, company: str | None = None) -> list[Any]:
	"""``rules.verify.PendingRule`` rows: the unverified rules that are blocking real postings.

	With a company, the rules that company's accountant has already accepted are left out: the
	list answers «what will refuse my postings», and those will not.
	"""
	return _call("nyabo_mn.rules.verify", "pending", limit=limit, company=company)


def rule_kinds() -> tuple[str, ...]:
	"""``("p", "t")`` — the kinds that ride in the callback datum, owned by ``rules.verify``."""
	return _call("nyabo_mn.rules.verify", "kinds")


def rule_evidence(kind: str, rule: str, company: str | None = None) -> Any:
	"""``rules.verify.RuleEvidence`` for one rule, or None when the row is gone.

	``company`` adds that company's own acceptance to the evidence, so the card can say which of
	the three provenances (seed citation, site admin, this company's accountant) clears the rule.
	"""
	return _call("nyabo_mn.rules.verify", "evidence", kind, rule, company)


def verify_rule(kind: str, rule: str, user: str, telegram_id: str | int | None = None) -> dict[str, Any]:
	return _call("nyabo_mn.rules.verify", "verify", kind, rule, user, telegram_id=telegram_id)


def accept_rule(
	kind: str, rule: str, company: str, user: str, telegram_id: str | int | None = None
) -> dict[str, Any]:
	"""[Манай компанид хамаарна]: this company's accountant applying an uncited rule to its books."""
	return _call("nyabo_mn.rules.verify", "accept", kind, rule, company, user, telegram_id=telegram_id)


def rule_acceptance(company: str | None, rule: str) -> Any:
	"""That company's acceptance of the rule, or None — the question the guard asks."""
	return _call("nyabo_mn.rules.verify", "acceptance", company, rule)


def blocked_proposal(rule: str, company: str | None, telegram_id: str | int | None) -> str | None:
	"""The proposal this person's own refused [Батлах] was about, so an acceptance can finish it."""
	return _call("nyabo_mn.rules.verify", "blocked_proposal", rule, company, telegram_id)


def record_rule_block(
	rule: str,
	company: str | None = None,
	proposal: str | None = None,
	telegram_id: str | int | None = None,
	user: str | None = None,
) -> str:
	"""The Nyabo Event behind every refused [Батлах]: which rule stopped which document."""
	return _call(
		"nyabo_mn.rules.verify",
		"record_block",
		rule,
		company,
		proposal,
		telegram_id,
		user=user,
	)


def recent_rule_request(rule: str, company: str | None = None) -> Any:
	"""An earlier, still-recent request about the same rule and company, or None (dedupe)."""
	return _call("nyabo_mn.rules.verify", "recent_request", rule, company)


def rule_requesters(rule: str, company: str | None = None) -> list[str]:
	"""The chats this rule stopped recently — the people owed the news that it was cleared.

	``company`` narrows them to the books an acceptance actually unblocks; a global verification
	passes nothing and reaches everyone.
	"""
	return _call("nyabo_mn.rules.verify", "requesters", rule, company=company)


def request_rule_verification(
	rule: str,
	company: str | None = None,
	user: str | None = None,
	telegram_id: str | int | None = None,
	admins_notified: int = 0,
	proposal: str | None = None,
) -> str:
	"""The Nyabo Event behind «the request has been recorded» in the refusal reply."""
	return _call(
		"nyabo_mn.rules.verify",
		"request_verification",
		rule,
		company=company,
		user=user,
		telegram_id=telegram_id,
		admins_notified=admins_notified,
		proposal=proposal,
	)


def unverified_rule_error() -> type[Exception]:
	"""``rules.guard.UnverifiedRuleError``, resolved late like ``bank_import_error``.

	No ``ValueError`` fallback: this class is used in an ``except`` clause that turns a refusal
	into the verification offer, and a stand-in matching a whole family of errors would answer
	unrelated failures with «an admin must verify this rule». ``_NeverRaised`` keeps the clause
	inert instead, and the router's generic handler stays in charge.
	"""
	try:
		module = importlib.import_module("nyabo_mn.rules.guard")
	except ImportError:
		return _NeverRaised
	error = getattr(module, "UnverifiedRuleError", None)
	return error if isinstance(error, type) and issubclass(error, Exception) else _NeverRaised
