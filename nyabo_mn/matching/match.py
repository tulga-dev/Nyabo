"""Bank Transaction <-> voucher matching on the ERPNext side (ARCHITECTURE §5.4).

Candidates are whatever already hit the bank GL account: submitted Purchase Invoices
(paid ones), Sales Invoices (POS payments), Journal Entries and Payment Entries whose
GL rows touch the account and that have no clearance date yet. Reading the GL instead
of each DocType's own amount fields guarantees that what ``core.matching.pick`` accepts
is exactly what ERPNext's ``allocate_payment_entries`` can allocate (it looks at the
same rows), so an accepted match never fails inside ERPNext.

Reconciliation mirrors ``bank_reconciliation_tool.reconcile_vouchers`` (version-16):
``add_payment_entries`` -> ``validate_duplicate_references`` -> ``allocate_payment_entries``
-> ``update_allocated_amount`` -> ``set_status`` -> ``save``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

from nyabo_mn import access
from nyabo_mn.core import matching as core_matching
from nyabo_mn.core.models import BankLine, MatchCandidate
from nyabo_mn.core.money import quantize, to_decimal
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_error, log_event
from nyabo_mn.matching import common
from nyabo_mn.matching import rules as rules_mod

VOUCHER_DOCTYPES: tuple[str, ...] = ("Payment Entry", "Journal Entry", "Purchase Invoice", "Sales Invoice")
TOP_CANDIDATES = 5


class MatchError(ValueError):
	def __init__(self, message_mn: str):
		super().__init__(message_mn)
		self.message_mn = message_mn


# --- candidates -----------------------------------------------------------------------------------


def reconcilable_doctypes() -> tuple[str, ...]:
	"""ERPNext's ``bank_reconciliation_doctypes`` hook minus Bank Transaction itself."""
	import frappe

	hooked = frappe.get_hooks("bank_reconciliation_doctypes") or []
	allowed = tuple(d for d in hooked if d in VOUCHER_DOCTYPES)
	return allowed or VOUCHER_DOCTYPES


def voucher_bank_effects(gl_account: str, company: str) -> dict[tuple[str, str], Decimal]:
	"""Signed bank movement per voucher: debit − credit on the bank GL account (inflow positive)."""
	import frappe

	rows = frappe.get_all(
		"GL Entry",
		filters={
			"account": gl_account,
			"company": company,
			"is_cancelled": 0,
			"voucher_type": ["in", list(reconcilable_doctypes())],
		},
		fields=["voucher_type", "voucher_no", "debit_in_account_currency", "credit_in_account_currency"],
	)
	out: dict[tuple[str, str], Decimal] = {}
	for row in rows:
		key = (str(row.voucher_type), str(row.voucher_no))
		movement = to_decimal(row.debit_in_account_currency or 0) - to_decimal(
			row.credit_in_account_currency or 0
		)
		out[key] = quantize(out.get(key, Decimal("0")) + movement)
	return out


def is_cleared(doctype: str, name: str) -> bool:
	"""ERPNext clears a voucher by stamping clearance_date (Sales Invoice: on its payment rows)."""
	import frappe

	if doctype == "Sales Invoice":
		rows = frappe.get_all(
			"Sales Invoice Payment",
			filters={"parent": name, "parenttype": doctype},
			fields=["clearance_date"],
		)
		return bool(rows) and all(r.clearance_date for r in rows)
	return bool(frappe.db.get_value(doctype, name, "clearance_date"))


def allocated_elsewhere(doctype: str, name: str) -> Decimal:
	"""What submitted Bank Transactions already allocated to this voucher."""
	import frappe

	total = Decimal("0")
	for row in frappe.get_all(
		"Bank Transaction Payments",
		filters={"payment_document": doctype, "payment_entry": name},
		fields=["parent", "allocated_amount"],
	):
		if int(frappe.db.get_value("Bank Transaction", row.parent, "docstatus") or 0) == 1:
			total += to_decimal(row.allocated_amount or 0)
	return quantize(total)


def voucher_details(doctype: str, name: str) -> tuple[dt.date, str, str]:
	"""(posting date, party name, reference) as the matcher's name similarity needs them."""
	import frappe

	if doctype == "Purchase Invoice":
		row = frappe.db.get_value(
			doctype, name, ["posting_date", "supplier_name", "supplier", "bill_no"], as_dict=True
		)
		return (
			common.to_date(row.posting_date),
			str(row.supplier_name or row.supplier or ""),
			str(row.bill_no or ""),
		)
	if doctype == "Sales Invoice":
		row = frappe.db.get_value(
			doctype, name, ["posting_date", "customer_name", "customer", "po_no"], as_dict=True
		)
		return (
			common.to_date(row.posting_date),
			str(row.customer_name or row.customer or ""),
			str(row.po_no or ""),
		)
	if doctype == "Payment Entry":
		row = frappe.db.get_value(
			doctype, name, ["posting_date", "party_name", "party", "reference_no"], as_dict=True
		)
		return (
			common.to_date(row.posting_date),
			str(row.party_name or row.party or ""),
			str(row.reference_no or ""),
		)
	row = frappe.db.get_value(
		doctype, name, ["posting_date", "pay_to_recd_from", "title", "cheque_no"], as_dict=True
	)
	party = row.pay_to_recd_from or ""
	if not party:
		accounts = frappe.get_all(
			"Journal Entry Account", filters={"parent": name, "parenttype": doctype}, fields=["party"]
		)
		party = next((a.party for a in accounts if a.party), "") or row.title or ""
	return common.to_date(row.posting_date), str(party), str(row.cheque_no or "")


def candidates_for(company: str, gl_account: str, *, direction: int | None = None) -> list[MatchCandidate]:
	"""Open vouchers on the bank GL account; ``direction`` −1 keeps outflows, +1 inflows."""
	out: list[MatchCandidate] = []
	for (doctype, name), movement in voucher_bank_effects(gl_account, company).items():
		if movement == 0:
			continue
		if direction is not None and (movement < 0) != (direction < 0):
			continue
		if is_cleared(doctype, name):
			continue
		remaining = abs(movement) - allocated_elsewhere(doctype, name)
		if remaining <= 0:
			continue
		posting_date, party, reference = voucher_details(doctype, name)
		out.append(
			MatchCandidate(
				doctype=doctype,
				name=name,
				date=posting_date,
				amount=quantize(remaining if movement > 0 else -remaining),
				party_name=party,
				reference=reference,
			)
		)
	return out


# --- transactions ---------------------------------------------------------------------------------


def unallocated_transactions(
	company: str, bank_account: str | None = None, names: Iterable[str] | None = None
) -> list[dict[str, Any]]:
	import frappe

	filters: dict[str, Any] = {"company": company, "docstatus": 1, "unallocated_amount": [">", 0]}
	if bank_account:
		filters["bank_account"] = bank_account
	if names is not None:
		filters["name"] = ["in", list(names)]
	rows = frappe.get_all(
		"Bank Transaction",
		filters=filters,
		fields=[
			"name",
			"date",
			"deposit",
			"withdrawal",
			"description",
			"reference_number",
			"currency",
			"bank_account",
		],
		order_by="date asc, name asc",
	)
	return [dict(r) for r in rows]


def _send_card(bank_transaction: str, company: str, document: str | None = None) -> bool:
	"""The [Баримт хайх] [Зардал бүртгэх] [Дараа] card for one unmatched line (ARCHITECTURE §5.4).

	The card and its keyboard belong to ``telegram.handlers.bank``; this only resolves the
	chat (the statement's chat, else the accountant's) and hands the line over. A missing
	Telegram layer, an unknown chat and a Telegram hiccup are logged, never raised, so a
	statement import is not rolled back by a failed message; anything else surfaces.
	"""
	try:
		from nyabo_mn.config import MissingSettingError  # type: ignore[import-not-found]
		from nyabo_mn.telegram import api  # type: ignore[import-not-found]
		from nyabo_mn.telegram.api import TelegramApiError
		from nyabo_mn.telegram.handlers import bank as bank_handler
	except ImportError:
		return False
	chat_id = bank_handler.chat_id_for(company, document)
	if not chat_id:
		log_event("bank.card_no_chat", level="warning", bank_transaction=bank_transaction, company=company)
		return False
	try:
		bank_handler.send_bank_card(api.get_bot(), chat_id, bank_transaction)
	except (TelegramApiError, MissingSettingError) as exc:
		log_error("bank.card_failed", exc, bank_transaction=bank_transaction)
		return False
	return True


def _pair_transfers(rows: Sequence[dict[str, Any]], numbers: Sequence[str]) -> list[tuple[str, str]]:
	"""(withdrawal name, deposit name) for own transfers between two different bank accounts."""
	lines = [common.line_from_transaction(r) for r in rows]
	by_name = {r["name"]: r for r in rows}
	pairs: list[tuple[str, str]] = []
	for a, b in core_matching.pair_transfers(lines, numbers):
		if by_name[a.row_hash]["bank_account"] == by_name[b.row_hash]["bank_account"]:
			continue
		pairs.append((a.row_hash, b.row_hash))
	return pairs


def run(
	company: str,
	bank_account: str | None = None,
	*,
	transactions: Iterable[str] | None = None,
	send_cards: bool = True,
	document: str | None = None,
) -> dict[str, Any]:
	"""Match every unallocated Bank Transaction of the company (or one account / list).

	Exact matches are reconciled through ERPNext; fee lines and own transfers get a
	proposal; the rest gets a Telegram card. Lines that already carry an open proposal
	are left alone so a re-run never doubles cards or proposals.
	"""
	rows = unallocated_transactions(company, bank_account, transactions)
	stats: dict[str, Any] = {
		"considered": len(rows),
		"matched": 0,
		"fee_proposals": 0,
		"transfers": 0,
		"unmatched": 0,
		"cards_sent": 0,
		"skipped_proposed": 0,
		"errors": 0,
		"details": [],
	}
	# Transfers are paired across all accounts before line-by-line matching, because
	# each side would otherwise look like an unexplained outflow / inflow.
	scope_rows = unallocated_transactions(company) if bank_account or transactions else rows
	handled: set[str] = set()
	for out_name, in_name in _pair_transfers(scope_rows, common.own_account_numbers(company)):
		if out_name not in {r["name"] for r in rows} and in_name not in {r["name"] for r in rows}:
			continue
		try:
			proposal = rules_mod.propose_transfer(out_name, in_name, document=document)
		except rules_mod.ProposalError as exc:
			stats["errors"] += 1
			log_error("bank.transfer_proposal_failed", exc, withdrawal=out_name, deposit=in_name)
			continue
		handled.update((out_name, in_name))
		stats["transfers"] += 1
		stats["details"].append({"name": out_name, "kind": "transfer", "proposal": proposal, "pair": in_name})

	candidate_cache: dict[str, list[MatchCandidate]] = {}
	for row in rows:
		name = row["name"]
		if name in handled:
			continue
		if rules_mod.existing_proposal(name):
			stats["skipped_proposed"] += 1
			continue
		line = common.line_from_transaction(row)
		gl_account = common.gl_account_of(row["bank_account"]) or ""
		key = f"{gl_account}:{'-' if line.amount < 0 else '+'}"
		if key not in candidate_cache:
			candidate_cache[key] = candidates_for(company, gl_account, direction=-1 if line.amount < 0 else 1)
		result = core_matching.pick(line, candidate_cache[key])
		detail: dict[str, Any] = {"name": name, "kind": result.kind, "reason": result.reason}
		try:
			if result.kind == "exact" and result.candidate is not None:
				reconcile(name, result.candidate.doctype, result.candidate.name, None, reason=result.reason)
				candidate_cache[key] = [c for c in candidate_cache[key] if c.name != result.candidate.name]
				stats["matched"] += 1
				detail["voucher"] = f"{result.candidate.doctype} {result.candidate.name}"
			elif result.kind == "fee":
				detail["proposal"] = rules_mod.propose_for_line(name, document=document)
				stats["fee_proposals"] += 1
			else:
				stats["unmatched"] += 1
				if send_cards and _send_card(name, company, document):
					stats["cards_sent"] += 1
		except (MatchError, rules_mod.ProposalError) as exc:
			stats["errors"] += 1
			detail["error"] = exc.message_mn
			log_error("bank.match_failed", exc, bank_transaction=name)
		stats["details"].append(detail)
	log_event(
		"bank.match_run",
		company=company,
		bank_account=bank_account,
		**{k: v for k, v in stats.items() if k != "details"},
	)
	return stats


# --- manual matching ------------------------------------------------------------------------------


def _amount_proximity(line_amount: Decimal, candidate_amount: Decimal) -> float:
	base = max(abs(line_amount), Decimal("1"))
	diff = abs(abs(line_amount) - abs(candidate_amount))
	return max(0.0, 1.0 - float(diff / base))


def _query_score(query: str, candidate: MatchCandidate) -> float:
	q = (query or "").strip()
	if not q:
		return 0.0
	haystack = " ".join((candidate.name, candidate.party_name, candidate.reference)).lower()
	if q.lower() in haystack:
		return 1.0
	return core_matching.name_similarity(q, candidate.party_name)


def find_candidates(
	bank_transaction_name: str, query: str | None = None, limit: int = TOP_CANDIDATES
) -> list[dict[str, Any]]:
	"""Top vouchers for the [Баримт хайх] tap: number/name similarity plus amount proximity."""
	import frappe

	if not frappe.db.exists("Bank Transaction", bank_transaction_name):
		raise MatchError(mn.MSG_BANK_TRANSACTION_NOT_FOUND.format(name=bank_transaction_name))
	bt = frappe.get_doc("Bank Transaction", bank_transaction_name).as_dict()
	line = common.line_from_transaction(bt)
	gl_account = common.gl_account_of(str(bt["bank_account"])) or ""
	candidates = candidates_for(str(bt["company"]), gl_account, direction=-1 if line.amount < 0 else 1)
	scored: list[tuple[float, MatchCandidate]] = []
	for candidate in candidates:
		proximity = _amount_proximity(line.amount, candidate.amount)
		name_score = (
			_query_score(query or "", candidate)
			if query
			else core_matching.name_similarity(line.description, candidate.party_name)
		)
		days = abs((line.date - candidate.date).days)
		date_score = 1.0 if days <= core_matching.DATE_WINDOW_DAYS else max(0.0, 1.0 - days / 90.0)
		total = 0.5 * proximity + 0.35 * name_score + 0.15 * date_score
		scored.append((round(total, 4), candidate))
	scored.sort(key=lambda item: (item[0], item[1].date), reverse=True)
	out: list[dict[str, Any]] = []
	for score, candidate in scored[:limit]:
		item = candidate.to_dict()
		item["score"] = score
		item["amount_diff"] = str(quantize(abs(abs(line.amount) - abs(candidate.amount))))
		# The Telegram bank handler reads voucher_doctype / voucher_name / party (ARCHITECTURE §5.4);
		# both spellings are kept so neither side needs to translate.
		item["voucher_doctype"] = candidate.doctype
		item["voucher_name"] = candidate.name
		item["party"] = candidate.party_name
		out.append(item)
	return out


def propose_expense(bank_transaction_name: str, account_code: str, user: str | None = None) -> str:
	"""[Зардал бүртгэх] → account chooser: the bank_line proposal debiting the chosen account.

	A line that already carries an open proposal gets its account changed through the
	pipeline (a Nyabo Correction is recorded, like on a receipt card) instead of a
	second proposal. Returns the proposal name.
	"""
	import frappe

	access.require_company(
		user, str(frappe.db.get_value("Bank Transaction", bank_transaction_name, "company") or "")
	)
	existing = rules_mod.existing_proposal(bank_transaction_name)
	if existing:
		from nyabo_mn.agent import post

		post.change_account(existing, account_code, user or "Administrator")
		return existing
	return rules_mod.propose_for_line(bank_transaction_name, account_code=account_code)


def reconcile(
	bank_transaction_name: str,
	voucher_doctype: str,
	voucher_name: str,
	user: str | None,
	*,
	telegram_id: str | None = None,
	reason: str | None = None,
) -> dict[str, Any]:
	"""Allocate a voucher to a Bank Transaction exactly as ERPNext's reconciliation tool does."""
	import frappe

	if voucher_doctype not in reconcilable_doctypes():
		raise MatchError(mn.MSG_BANK_VOUCHER_NOT_ALLOWED.format(doctype=voucher_doctype))
	if not frappe.db.exists(voucher_doctype, voucher_name):
		raise MatchError(mn.MSG_BANK_VOUCHER_NOT_FOUND.format(doctype=voucher_doctype, name=voucher_name))
	if not frappe.db.exists("Bank Transaction", bank_transaction_name):
		raise MatchError(mn.MSG_BANK_TRANSACTION_NOT_FOUND.format(name=bank_transaction_name))
	transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)
	# The company is taken from the line, so a named caller must be linked to it (SEC-02);
	# ``user`` is None for the automatic matcher, which already runs per company.
	access.require_company(user, str(transaction.company or ""))
	if float(transaction.unallocated_amount or 0) <= 0:
		raise MatchError(mn.MSG_BANK_LINE_ALREADY_RECONCILED)
	line = common.line_from_transaction(transaction.as_dict())
	gl_account = common.gl_account_of(str(transaction.bank_account)) or ""
	movement = voucher_bank_effects(gl_account, str(transaction.company)).get((voucher_doctype, voucher_name))
	amount = float(abs(movement)) if movement is not None else float(abs(line.amount))
	vouchers = [{"payment_doctype": voucher_doctype, "payment_name": voucher_name, "amount": amount}]
	transaction.flags.ignore_permissions = True
	transaction.add_payment_entries(vouchers)
	transaction.validate_duplicate_references()
	transaction.allocate_payment_entries()
	transaction.update_allocated_amount()
	transaction.set_status()
	transaction.save()
	allocated = next(
		(
			float(p.allocated_amount)
			for p in transaction.payment_entries
			if p.payment_document == voucher_doctype and p.payment_entry == voucher_name
		),
		0.0,
	)
	common.write_event(
		"bank_line_matched",
		company=str(transaction.company),
		ref_doctype="Bank Transaction",
		ref_name=bank_transaction_name,
		reason=reason,
		actor_user=user,
		actor_telegram_id=telegram_id,
		payload={
			"voucher_doctype": voucher_doctype,
			"voucher_name": voucher_name,
			"allocated_amount": allocated,
			"unallocated_amount": float(transaction.unallocated_amount or 0),
			"manual": user is not None,
		},
	)
	return {
		"bank_transaction": bank_transaction_name,
		"voucher_doctype": voucher_doctype,
		"voucher_name": voucher_name,
		"allocated_amount": allocated,
		"unallocated_amount": float(transaction.unallocated_amount or 0),
		"status": transaction.status,
	}


def line_of(bank_transaction_name: str) -> BankLine:
	import frappe

	return common.line_from_transaction(frappe.get_doc("Bank Transaction", bank_transaction_name).as_dict())


__all__ = [
	"MatchError",
	"VOUCHER_DOCTYPES",
	"candidates_for",
	"find_candidates",
	"line_of",
	"reconcilable_doctypes",
	"reconcile",
	"run",
	"unallocated_transactions",
	"voucher_bank_effects",
]
