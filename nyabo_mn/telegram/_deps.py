"""Thin shims around the modules the Telegram layer calls but does not own.

Why a shim module: the agent, matching, reports, compliance, evals and setup packages are
built in parallel (docs/ARCHITECTURE.md §3). Handlers import *this* module and call
``_deps.post_proposal(...)`` so that (a) a missing module fails with a clear
``NotImplementedError`` naming the dotted path instead of an ImportError at import time,
and (b) tests monkeypatch one attribute here rather than the real module.

Every function keeps the signature of the contract it wraps; nothing here adds logic.
"""

from __future__ import annotations

import importlib
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


# --- nyabo_mn.agent.pipeline -------------------------------------------------------------------


def process_receipt(document_name: str) -> Any:
	return _call("nyabo_mn.agent.pipeline", "process_receipt", document_name)


def post_proposal(proposal_name: str, approver_user: str, approver_telegram_id: str) -> dict[str, Any]:
	return _call(
		"nyabo_mn.agent.pipeline", "post_proposal", proposal_name, approver_user, approver_telegram_id
	)


def change_account(proposal_name: str, code: str, user: str) -> Any:
	return _call("nyabo_mn.agent.pipeline", "change_account", proposal_name, code, user)


def reject(proposal_name: str, reason: str, user: str) -> Any:
	return _call("nyabo_mn.agent.pipeline", "reject", proposal_name, reason, user)


def top_accounts(company: str, n: int = 6) -> list[tuple[str, str]]:
	return _call("nyabo_mn.agent.pipeline", "top_accounts", company, n=n)


def search_accounts(company: str, query: str) -> list[tuple[str, str]]:
	return _call("nyabo_mn.agent.pipeline", "search_accounts", company, query)


def make_correction_proposal(original_doctype: str, original_name: str, reason: str, user: str) -> str:
	return _call(
		"nyabo_mn.agent.pipeline", "make_correction_proposal", original_doctype, original_name, reason, user
	)


def answer_question(user: str, company: str, text: str) -> str:
	return _call("nyabo_mn.agent.pipeline", "answer_question", user, company, text)


# --- nyabo_mn.matching -------------------------------------------------------------------------


def import_statement(document_name: str) -> dict[str, Any]:
	return _call("nyabo_mn.matching.bank_import", "import_statement", document_name)


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


def inventory_parse_text(text: str) -> list[dict[str, Any]]:
	return _call("nyabo_mn.setup.inventory_intake", "parse_text", text)


def inventory_parse_table(content: bytes, filename: str) -> list[dict[str, Any]]:
	return _call("nyabo_mn.setup.inventory_intake", "parse_table", content, filename)


def inventory_create_intake(company: str, items: list[dict[str, Any]], source: str, user: str) -> str:
	return _call("nyabo_mn.setup.inventory_intake", "create_intake", company, items, source, user)


def inventory_post_intake(intake_name: str, user: str) -> dict[str, Any]:
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
