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

An unpaid invoice is *not* a reconcilable voucher. ``add_payment_entries`` and
``allocate_payment_entries`` only record a link and stamp ``clearance_date``; they post
nothing, so allocating an invoice that still owes money would leave the payable open and
the bank overstated forever. ERPNext says the same thing in
``bank_reconciliation_tool.get_pi_matching_query``, which offers Purchase Invoices only
with ``docstatus = 1 AND is_paid = 1 AND clearance_date IS NULL``: the supported route for
an unpaid invoice is a Payment Entry. ``reconcile`` therefore refuses such a voucher
(``settlement_needed``) and ``settle`` is the tap that creates the Payment Entry, submits
it and reconciles the line against *that*. ``run`` never settles: a Payment Entry reaches
the ledger, and ARCHITECTURE §1.3 keeps posting behind a human tap (BANK-08, BANK-09).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
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


# --- settlement (unpaid invoices) -------------------------------------------------------------------

# A card / QPay / transfer purchase is posted as an invoice that credits the payable; nothing
# has touched a bank account yet, so ``candidates_for`` (which reads the bank GL) cannot see it
# and ``reconcile`` must not allocate it. ``settle`` is the tap that pays it (BANK-08, BANK-09).
INVOICE_DOCTYPES: tuple[str, ...] = ("Purchase Invoice", "Sales Invoice")
# Statuses that mean the invoice has been voided or returned; ERPNext's own repost normally
# zeroes the outstanding too, but nothing here may depend on that having happened.
REVERSED_STATUSES: frozenset[str] = frozenset(
	{"Return", "Debit Note Issued", "Credit Note Issued", "Cancelled", "Closed"}
)
_PARTY_ACCOUNT_FIELD = {"Purchase Invoice": "credit_to", "Sales Invoice": "debit_to"}
_PARTY_NAME_FIELDS = {
	"Purchase Invoice": ("supplier_name", "supplier", "bill_no"),
	"Sales Invoice": ("customer_name", "customer", "po_no"),
}


def _invoice_fields(doctype: str) -> list[str]:
	party_name, party, reference = _PARTY_NAME_FIELDS[doctype]
	return [
		"name",
		"company",
		"docstatus",
		"status",
		"is_return",
		"currency",
		"posting_date",
		"outstanding_amount",
		_PARTY_ACCOUNT_FIELD[doctype],
		party_name,
		party,
		reference,
	]


def invoice_row(doctype: str, name: str) -> dict[str, Any] | None:
	"""Everything the settlement path asks of an invoice, in one round trip."""
	import frappe

	if doctype not in INVOICE_DOCTYPES:
		return None
	row = frappe.db.get_value(doctype, name, _invoice_fields(doctype), as_dict=True)
	return dict(row) if row else None


def _returned_invoices(doctype: str, company: str) -> set[str]:
	"""Invoices of the company that a submitted return (debit / credit note) already voids."""
	import frappe

	rows = frappe.get_all(
		doctype,
		filters={"company": company, "docstatus": 1, "is_return": 1},
		fields=["return_against"],
	)
	return {str(r["return_against"]) for r in rows if r.get("return_against")}


def _is_reversed(doctype: str, row: Mapping[str, Any]) -> bool:
	"""A voided invoice: its own return flag, a reversal status, or a return that names it."""
	import frappe

	if int(row.get("is_return") or 0):
		return True
	if str(row.get("status") or "") in REVERSED_STATUSES:
		return True
	return bool(frappe.db.exists(doctype, {"return_against": row.get("name"), "docstatus": 1}))


def settlement_needed(voucher_doctype: str, voucher_name: str) -> bool:
	"""True when the voucher is a live submitted invoice that still owes money.

	``outstanding_amount > 0`` on a submitted Purchase Invoice is exactly ``is_paid = 0``
	(``purchase_invoice.set_paid_amounts`` subtracts ``base_paid_amount`` from the
	outstanding, so a paid invoice lands at 0 and ``set_status`` calls it "Paid"). Such a
	voucher has no GL row on any bank account: it must be settled by a Payment Entry
	before a statement line can be reconciled against it. A reversed invoice is excluded —
	settling one would credit the bank against a payable that already nets to zero and leave
	a phantom prepayment on the supplier (review finding S16).
	"""
	row = invoice_row(voucher_doctype, voucher_name)
	if not row:
		return False
	if int(row.get("docstatus") or 0) != 1 or to_decimal(row.get("outstanding_amount") or 0) <= 0:
		return False
	return not _is_reversed(voucher_doctype, row)


def outstanding_of(voucher_doctype: str, voucher_name: str) -> Decimal:
	import frappe

	return quantize(to_decimal(frappe.db.get_value(voucher_doctype, voucher_name, "outstanding_amount") or 0))


def open_invoice_candidates(
	company: str, *, direction: int, currency: str | None = None
) -> list[MatchCandidate]:
	"""Submitted, live invoices with an outstanding balance, as match candidates.

	``candidates_for`` cannot see these: they never touched a bank GL account. An outflow
	can only settle a Purchase Invoice, an inflow only a Sales Invoice; the candidate's
	amount is signed the same way a Bank Transaction line is (inflow positive).

	Two queries, whatever the number of invoices: one for the rows (with the party and
	reference columns the matcher needs, so there is no ``voucher_details`` per row) and one
	for the returns that void them. ``currency`` keeps a foreign-currency invoice off a
	statement line it cannot settle — ``outstanding_amount`` is in the invoice's currency and
	the line's amount in the bank account's, so the two are only comparable when they agree
	(review findings S5, S13).
	"""
	import frappe

	doctype = "Sales Invoice" if direction > 0 else "Purchase Invoice"
	filters: dict[str, Any] = {
		"company": company,
		"docstatus": 1,
		"outstanding_amount": [">", 0],
		"is_return": 0,
	}
	if currency:
		filters["currency"] = currency
	rows = frappe.get_all(doctype, filters=filters, fields=_invoice_fields(doctype))
	if not rows:
		return []
	returned = _returned_invoices(doctype, company)
	party_name_field, party_field, reference_field = _PARTY_NAME_FIELDS[doctype]
	out: list[MatchCandidate] = []
	for row in rows:
		if str(row.get("status") or "") in REVERSED_STATUSES or str(row["name"]) in returned:
			continue
		outstanding = quantize(to_decimal(row.get("outstanding_amount") or 0))
		if outstanding <= 0:
			continue
		out.append(
			MatchCandidate(
				doctype=doctype,
				name=str(row["name"]),
				date=common.to_date(row.get("posting_date")),
				amount=quantize(outstanding if direction > 0 else -outstanding),
				party_name=str(row.get(party_name_field) or row.get(party_field) or ""),
				reference=str(row.get(reference_field) or ""),
			)
		)
	return out


def pick_settlement(line: BankLine, candidates: Sequence[MatchCandidate]) -> MatchCandidate | None:
	"""The one open invoice this line clearly pays, out of an already-built candidate list."""
	if line.amount == 0 or not candidates:
		return None
	result = core_matching.pick(line, list(candidates))
	return result.candidate if result.kind == "exact" else None


def settlement_candidate(
	bank_transaction_name: str, candidates: Sequence[MatchCandidate] | None = None
) -> MatchCandidate | None:
	"""The one open invoice this line clearly pays, or None.

	Same bar as an automatic match (``core.matching.pick``): exact amount, three-day
	window, name or reference. It only ever produces a *button*, never a posting. A line
	that a Nyabo Proposal already explains has none: it has been spoken for, and offering
	the tap would credit the bank a second time for one statement line (S10).

	``candidates`` lets a caller that already built the list for this company, direction and
	currency reuse it (``run`` does, once per import instead of once per line).
	"""
	import frappe

	if not frappe.db.exists("Bank Transaction", bank_transaction_name):
		return None
	if rules_mod.existing_proposal(bank_transaction_name):
		return None
	transaction = frappe.get_doc("Bank Transaction", bank_transaction_name).as_dict()
	line = common.line_from_transaction(transaction)
	if line.amount == 0:
		return None
	if candidates is None:
		candidates = open_invoice_candidates(
			str(transaction["company"]),
			direction=1 if line.amount > 0 else -1,
			currency=line.currency or None,
		)
	return pick_settlement(line, candidates)


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
	proposal; the rest gets a Telegram card. Lines that a Nyabo Proposal already explains
	are left alone so a re-run never doubles cards or proposals.

	A run never creates a Payment Entry. Candidates come from the bank GL account, so an
	unpaid invoice is not among them; when the line clearly pays one, the card offers
	[Төлбөр бүртгэх] and the accountant taps (``settlement_offered`` counts those lines).
	"""
	rows = unallocated_transactions(company, bank_account, transactions)
	stats: dict[str, Any] = {
		"considered": len(rows),
		"matched": 0,
		"fee_proposals": 0,
		"transfers": 0,
		"unmatched": 0,
		"settlement_offered": 0,
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

	# One candidate list per (bank account, direction) and one open-invoice list per
	# (direction, currency), built on first use and reused for every line of the run: the
	# scan used to be O(open invoices) per line, per card and per [Буцах] tap (S5).
	candidate_cache: dict[str, list[MatchCandidate]] = {}
	settlement_cache: dict[str, list[MatchCandidate]] = {}
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
				# An open invoice is never settled automatically: ``settle`` submits a Payment
				# Entry, and ARCHITECTURE §1.3 keeps every posting behind a human tap. The line
				# stays unmatched and the card carries [Төлбөр бүртгэх].
				settle_key = f"{'-' if line.amount < 0 else '+'}:{line.currency}"
				if settle_key not in settlement_cache:
					settlement_cache[settle_key] = open_invoice_candidates(
						company,
						direction=-1 if line.amount < 0 else 1,
						currency=line.currency or None,
					)
				settlement = pick_settlement(line, settlement_cache[settle_key])
				if settlement is not None:
					stats["settlement_offered"] += 1
					detail["settlement_candidate"] = f"{settlement.doctype} {settlement.name}"
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
	"""Top vouchers for the [Баримт хайх] tap: number/name similarity plus amount proximity.

	Unpaid invoices are offered too (``needs_settlement``): the accountant is looking for
	the document behind the line, and refusing to show the very invoice this payment
	settles would send them away empty-handed. Choosing one leads to [Төлбөр бүртгэх],
	not to a reconcile — ``reconcile`` refuses it.
	"""
	import frappe

	if not frappe.db.exists("Bank Transaction", bank_transaction_name):
		raise MatchError(mn.MSG_BANK_TRANSACTION_NOT_FOUND.format(name=bank_transaction_name))
	bt = frappe.get_doc("Bank Transaction", bank_transaction_name).as_dict()
	line = common.line_from_transaction(bt)
	gl_account = common.gl_account_of(str(bt["bank_account"])) or ""
	direction = -1 if line.amount < 0 else 1
	candidates = candidates_for(str(bt["company"]), gl_account, direction=direction)
	# The open-invoice list is exactly the set that needs a Payment Entry, so membership in it
	# is the ``needs_settlement`` flag: no ``settlement_needed`` round trip per candidate (S5).
	open_invoices = open_invoice_candidates(
		str(bt["company"]), direction=direction, currency=line.currency or None
	)
	settlement_keys = {(c.doctype, c.name) for c in open_invoices}
	candidates += open_invoices
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
		item["needs_settlement"] = (candidate.doctype, candidate.name) in settlement_keys
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
	if settlement_needed(voucher_doctype, voucher_name):
		# Allocating here would only stamp a clearance date: the payable would stay open and
		# the bank balance overstated. See the module docstring and DECISIONS BANK-08.
		raise MatchError(mn.MSG_BANK_NEEDS_PAYMENT_ENTRY.format(doctype=voucher_doctype, name=voucher_name))
	transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)
	# The company is taken from the line, so a named caller must be linked to it (TG-03);
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


def check_can_settle(company: str, user: str) -> None:
	"""Only an accountant/admin of *this* company may settle: a Payment Entry posts.

	Two questions, both asked before anything is built: the company boundary (TG-03 —
	callback data is attacker-chosen and document names are a global sequence) and the role
	(ARCHITECTURE §1.3, §5.3 step 7 — posting to the ledger is an accountant's tap).
	"""
	from nyabo_mn.agent import post

	access.require_company(user, company)
	if post.approver_kind(company, user) != "accountant":
		raise MatchError(mn.MSG_ACCOUNTANT_ONLY)


def _settlement_currencies(transaction: Any, doctype: str, row: Mapping[str, Any], gl_account: str) -> None:
	"""Refuse unless the invoice, the party account and the bank account share one currency.

	``outstanding_amount`` is in the invoice's currency and ``unallocated_amount`` in the bank
	account's, so comparing them — which is what the over-allocation guard and the allocated
	amount do — is only meaningful when they agree. Converting properly means writing
	``paid_amount``, ``received_amount`` and ``allocated_amount`` in three different currencies
	through the invoice's ``conversion_rate``; until that is built and tested against a real
	bench, a foreign-currency invoice is the accountant's to post by hand (BANK-09, S13).
	"""
	import frappe

	bank_currency = str(
		frappe.db.get_value("Account", gl_account, "account_currency") or transaction.currency or ""
	)
	invoice_currency = str(row.get("currency") or "")
	party_account = str(row.get(_PARTY_ACCOUNT_FIELD[doctype]) or "")
	party_currency = str(frappe.db.get_value("Account", party_account, "account_currency") or "")
	line_currency = str(transaction.currency or bank_currency)
	if len({c for c in (bank_currency, invoice_currency, party_currency, line_currency) if c}) > 1:
		raise MatchError(
			mn.MSG_BANK_SETTLE_CURRENCY_MISMATCH.format(
				bank=bank_currency or line_currency or "?",
				invoice=invoice_currency or "?",
				party=party_currency or "?",
			)
		)


def _discard_payment_entry(name: str | None) -> None:
	"""Undo a Payment Entry a failed settlement left behind (best effort, never raises).

	On a site the savepoint rollback has already removed the row and this is a no-op; the
	test harness has no real transaction, so the explicit cancel + delete is what makes the
	invariant ("a failed settle leaves nothing behind") observable there. Any error here is
	logged, never raised: the caller is already re-raising the real failure.
	"""
	import frappe

	if not name:
		return
	try:
		if not frappe.db.exists("Payment Entry", name):
			return
		doc = frappe.get_doc("Payment Entry", name)
		doc.flags.ignore_permissions = True
		if int(doc.docstatus or 0) == 1:
			doc.cancel()
		frappe.delete_doc("Payment Entry", name, ignore_permissions=True, force=True)
	except Exception as exc:  # noqa: BLE001 - cleanup must not mask the failure it is cleaning up
		log_error("bank.settle_cleanup_failed", exc, payment_entry=name)


def settle(
	bank_transaction_name: str,
	voucher_doctype: str,
	voucher_name: str,
	user: str,
	*,
	telegram_id: str | None = None,
) -> dict[str, Any]:
	"""[Төлбөр бүртгэх]: pay an unpaid invoice from the statement line, then reconcile.

	Builds ERPNext's own Payment Entry
	(``payment_entry.get_payment_entry(dt, dn, bank_account=<the bank GL account>)`` —
	that parameter is handed to ``get_default_bank_cash_account(..., account=...)``, so it
	is a GL Account name; the ERPNext *Bank Account* row goes on ``bank_account``, as
	``bank_reconciliation_tool.create_payment_entry_bts`` sets ``company_bank_account``),
	dates it on the statement line, carries the line's reference number, allocates the
	smaller of the line and the invoice's outstanding amount, submits it and reconciles the
	Bank Transaction against the new Payment Entry.

	Everything that can be checked is checked before anything is written: the caller's
	company and role, the invoice's company (a name out of callback data is not proof of
	anything), the direction (only a withdrawal pays a Purchase Invoice, only a deposit
	collects a Sales Invoice), a line another proposal already explains, a reversed invoice,
	the currencies, the bank GL account, the closed period, and the over-allocation. A line
	larger than what the invoice still owes is refused rather than parked as an advance on
	the supplier: the accountant splits it or picks another document.

	The three writes that remain — insert, submit, reconcile — run inside one savepoint, so
	a failure in any of them leaves no submitted Payment Entry behind and the accountant can
	tap again (review finding S3).
	"""
	import frappe
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	from nyabo_mn.agent import post

	if not frappe.db.exists("Bank Transaction", bank_transaction_name):
		raise MatchError(mn.MSG_BANK_TRANSACTION_NOT_FOUND.format(name=bank_transaction_name))
	transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)
	company = str(transaction.company or "")
	check_can_settle(company, user)

	row = invoice_row(voucher_doctype, voucher_name)
	# The company is the line's, never the voucher's: an invoice of another company reaching
	# ``get_payment_entry`` builds a Payment Entry in *that* company's books with this
	# company's bank account on it, and only ``submit`` notices (S1 / S12).
	if not row or str(row.get("company") or "") != company:
		raise MatchError(mn.MSG_BANK_VOUCHER_NOT_FOUND.format(doctype=voucher_doctype, name=voucher_name))

	line = common.line_from_transaction(transaction.as_dict())
	expected = "Purchase Invoice" if line.amount < 0 else "Sales Invoice"
	if line.amount == 0 or voucher_doctype != expected:
		raise MatchError(
			mn.MSG_BANK_SETTLE_WRONG_DIRECTION.format(doctype=voucher_doctype, name=voucher_name)
		)

	proposal = rules_mod.existing_proposal(bank_transaction_name)
	if proposal:
		# The line already reached the ledger (or is on its way) through a Nyabo Proposal;
		# settling it as well credits the bank twice for one statement line (S10).
		raise MatchError(mn.MSG_BANK_SETTLE_ALREADY_PROPOSED.format(proposal=proposal))
	if _is_reversed(voucher_doctype, row):
		raise MatchError(mn.MSG_BANK_SETTLE_REVERSED.format(doctype=voucher_doctype, name=voucher_name))
	if not settlement_needed(voucher_doctype, voucher_name):
		raise MatchError(mn.MSG_BANK_SETTLE_NOT_NEEDED.format(doctype=voucher_doctype, name=voucher_name))

	gl_account = common.gl_account_of(str(transaction.bank_account)) or ""
	if not gl_account:
		# Without it ``get_payment_entry`` silently falls back to Company.default_bank_account
		# and credits a bank the statement line never touched.
		raise MatchError(mn.MSG_BANK_SETTLE_NO_BANK_ACCOUNT)
	_settlement_currencies(transaction, voucher_doctype, row, gl_account)

	unallocated = quantize(to_decimal(transaction.unallocated_amount or 0))
	if unallocated <= 0:
		raise MatchError(mn.MSG_BANK_LINE_ALREADY_RECONCILED)
	outstanding = quantize(to_decimal(row.get("outstanding_amount") or 0))
	if unallocated > outstanding:
		raise MatchError(
			mn.MSG_BANK_SETTLE_OVER_ALLOCATION.format(
				name=voucher_name,
				outstanding=common.decimal_str(outstanding),
				amount=common.decimal_str(unallocated),
			)
		)
	allocated = min(unallocated, outstanding)  # partial payments are allowed, over-allocation is not
	posting_date = common.to_date(transaction.date)
	# The same Mongolian refusal every other posting path gives (S15); ERPNext refuses a
	# Payment Entry in a closed period too, in English, which reaches the accountant as the
	# generic "error, admin notified".
	post.refuse_if_closed(company, "Payment Entry", posting_date)
	reference_no = str(transaction.reference_number or "") or bank_transaction_name

	savepoint = "nyabo_settle"
	frappe.db.savepoint(savepoint)
	payment_name: str | None = None
	try:
		payment = get_payment_entry(voucher_doctype, voucher_name, bank_account=gl_account)
		if payment.payment_type != ("Pay" if line.amount < 0 else "Receive"):
			# ERPNext derives the type from the invoice's own sign, so a credit note that slipped
			# past the guards above would move the bank the wrong way (S2 / S11).
			raise MatchError(
				mn.MSG_BANK_SETTLE_WRONG_DIRECTION.format(doctype=voucher_doctype, name=voucher_name)
			)
		payment.posting_date = posting_date
		payment.reference_no = reference_no
		payment.reference_date = posting_date
		payment.bank_account = str(transaction.bank_account)
		payment.paid_amount = float(allocated)
		payment.received_amount = float(allocated)
		for reference in payment.references:
			reference.allocated_amount = float(allocated)
		_stamp_settlement(payment, transaction, voucher_doctype, voucher_name, user)
		# ignore_permissions like every other Nyabo posting path (agent.post.post_proposal):
		# ``check_can_settle`` above is the authorisation, and a linked accountant carries
		# ERPNext's Accounts User role from ``state.ensure_frappe_user`` (TG-05) — the flag is
		# what keeps a site whose roles were provisioned differently from failing the tap.
		payment.flags.ignore_permissions = True
		payment.insert()
		payment_name = payment.name
		payment.submit()
		result = reconcile(
			bank_transaction_name,
			"Payment Entry",
			payment.name,
			user,
			telegram_id=telegram_id,
			reason=mn.MATCH_REASON_SETTLED.format(name=voucher_name),
		)
	except frappe.PermissionError as exc:
		frappe.db.rollback(save_point=savepoint)
		_discard_payment_entry(payment_name)
		log_error("bank.settle_no_permission", exc, bank_transaction=bank_transaction_name, user=user)
		raise MatchError(mn.MSG_BANK_SETTLE_ERPNEXT_PERMISSION) from exc
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		_discard_payment_entry(payment_name)
		raise
	frappe.db.release_savepoint(savepoint)

	common.write_event(
		"bank_line_settled",
		company=company,
		ref_doctype="Bank Transaction",
		ref_name=bank_transaction_name,
		actor_user=user,
		actor_telegram_id=telegram_id,
		payload={
			"voucher_doctype": voucher_doctype,
			"voucher_name": voucher_name,
			"payment_entry": payment.name,
			"allocated": str(allocated),
			"outstanding_before": str(outstanding),
			"outstanding_after": str(outstanding_of(voucher_doctype, voucher_name)),
			"status": result["status"],
		},
	)
	return {
		"payment_entry": payment.name,
		"allocated": str(allocated),
		"voucher_doctype": voucher_doctype,
		"voucher_name": voucher_name,
	}


def _stamp_settlement(
	payment: Any, transaction: Any, voucher_doctype: str, voucher_name: str, user: str
) -> None:
	"""The Nyabo audit fields every posted document carries (COMP-10, art. 13.7 / 15).

	The statement is the primary document, so ``source_document`` is the Nyabo Document of
	the import; the explanation says in Mongolian which payable this credit closed and which
	bank account it left. Fields the site has not migrated yet are simply skipped.
	"""
	line = common.line_from_transaction(transaction.as_dict())
	credit_code = common.account_code_of(common.gl_account_of(str(transaction.bank_account)))
	template = mn.EXPL_BANK_SETTLE if line.amount < 0 else mn.EXPL_BANK_SETTLE_RECEIVE
	explanation = template.format(
		description=(line.description or "")[:80],
		voucher=voucher_name,
		credit_code=credit_code,
		debit_code=credit_code,
	)
	values = {
		"nyabo_explanation": explanation[:300],
		"nyabo_approved_by": user,
		"source_document": rules_mod.source_document_of(str(transaction.name)),
		"nyabo_primary_document_ref": f"{voucher_doctype} {voucher_name}",
	}
	for fieldname, value in values.items():
		if value and payment.meta.has_field(fieldname):
			payment.set(fieldname, value)


def line_of(bank_transaction_name: str) -> BankLine:
	import frappe

	return common.line_from_transaction(frappe.get_doc("Bank Transaction", bank_transaction_name).as_dict())


__all__ = [
	"INVOICE_DOCTYPES",
	"MatchError",
	"VOUCHER_DOCTYPES",
	"candidates_for",
	"check_can_settle",
	"find_candidates",
	"invoice_row",
	"line_of",
	"open_invoice_candidates",
	"outstanding_of",
	"pick_settlement",
	"reconcilable_doctypes",
	"reconcile",
	"run",
	"settle",
	"settlement_candidate",
	"settlement_needed",
	"unallocated_transactions",
	"voucher_bank_effects",
]
