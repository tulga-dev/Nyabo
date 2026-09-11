"""A transaction described in words («Ганзориг ХХК-аас 2 сая орлого орлоо») becomes a proposal card.

This is the third intake beside the receipt photo and the bank statement, and it keeps their
rule: the model reads, deterministic code writes the entry, the accountant taps. The model's
part is the ``record_transaction`` tool call inside the question loop — it turns a sentence
into a direction, an amount, a party, how it was paid and (for an expense) an account code.
Everything after that is this module: the amount is re-read as a Decimal and refused unless
positive, the accounts are resolved from the chart by role (bank, cash, sales revenue, output
VAT, the default expense), the posting lines are built the way the seeded pattern says, and
the message itself is filed as the primary document (art. 13.7: for a typed entry the record
IS the typed text, exactly as a typed stock list is for the opening inventory). The result is
a ``Nyabo Proposal`` with ``needs_accountant`` set — a typed entry has no paper behind it, so
only the accountant may post it — and the chat shows the same card, with the same [Батлах]
[Данс солих] [Татгалзах], that a receipt gets. Nothing is posted here.

What the model may not do: pick an account for income (always the sales revenue role), skip
VAT for a VAT payer (the output VAT line is computed from the verified rate), or post. What the
code will not do: guess an amount — a sentence without one is answered as a question, not as
an entry.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from nyabo_mn.core.models import ProposedEntry, ProposedLine
from nyabo_mn.core.money import fmt_mnt, quantize, to_decimal, vat_from_gross
from nyabo_mn.core.rules_engine import MissingRuleError
from nyabo_mn.i18n import mn

KIND = "text"
DIRECTION_INCOME = "income"
DIRECTION_EXPENSE = "expense"
DIRECTIONS = (DIRECTION_INCOME, DIRECTION_EXPENSE)
PAID_VIA = ("bank", "cash", "unknown")
MAX_TEXT_CHARS = 500
PATTERN_INCOME_VAT = "sale_cash_vat_payer"
PATTERN_INCOME_NON_VAT = "sale_cash_non_vat"
PATTERN_EXPENSE = "bank_line_expense"
WARN_TYPED = "typed_no_document"
ZERO = Decimal("0.00")


def _error(detail: str, code: str = "invalid_arguments") -> dict[str, Any]:
	return {"error": code, "detail": [detail]}


def _money_account(company: str, paid_via: str) -> tuple[str, str]:
	"""``(account name, code)`` of the bank or cash the money moved through."""
	from nyabo_mn.matching import common
	from nyabo_mn.reports import accounts as report_accounts

	if paid_via == "cash":
		account = report_accounts.role_account(company, "cash")
	else:
		account = None
		for row in common.bank_rows(company):
			gl = row.get("gl_account") or (
				common.gl_account_of(str(row["erpnext_bank_account"]))
				if row.get("erpnext_bank_account")
				else None
			)
			if gl:
				account = str(gl)
				break
		account = account or report_accounts.role_account(company, "bank")
	return account, common.account_code_of(account)


def _expense_account(company: str, wanted: str | None) -> tuple[str, str]:
	"""The model's code when it is an expense leaf of this chart, else the company's default."""
	from nyabo_mn.matching import rules as bank_rules

	code = str(wanted or "").strip()
	if code:
		account, resolved = bank_rules.resolve_account(company, code)
		if account and _root_type(account) == "Expense":
			return account, str(resolved)
	account, resolved = bank_rules.default_expense(company)
	if not account:
		raise MissingRuleError("default_expense")
	return account, str(resolved)


def _root_type(account: str) -> str:
	import frappe

	return str(frappe.db.get_value("Account", account, "root_type") or "")


def _role(company: str, role: str) -> tuple[str, str]:
	from nyabo_mn.matching import common
	from nyabo_mn.reports import accounts as report_accounts

	account = report_accounts.role_account(company, role)
	return account, common.account_code_of(account)


def _file_message(company: str, user: str, text: str, source: Mapping[str, Any] | None) -> str | None:
	"""The typed message as a Nyabo Document — the primary record behind the entry."""
	from nyabo_mn.log import log_event
	from nyabo_mn.telegram import files

	source = source or {}
	stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
	body = f"{text}\n".encode()
	try:
		doc = files.save_document(
			company,
			dict(source.get("sender") or {}),
			KIND,
			body,
			f"message-{stamp}.txt",
			mime="text/plain",
			chat_id=source.get("chat_id"),
			message_id=source.get("message_id"),
			sender_user=user,
		)
	except files.DuplicateDocument as dup:
		log_event("typed.document_duplicate", existing=dup.existing_name, company=company)
		return dup.existing_name
	return doc.name


def propose(
	company: str,
	user: str,
	args: Mapping[str, Any],
	*,
	text: str,
	source: Mapping[str, Any] | None = None,
	today: dt.date | None = None,
) -> dict[str, Any]:
	"""The tool handler: a proposal for the accountant, or an error the model can explain."""
	import frappe

	from nyabo_mn.agent import pipeline
	from nyabo_mn.matching import rules as bank_rules

	today = today or dt.date.today()
	direction = str(args.get("direction") or "")
	if direction not in DIRECTIONS:
		return _error(f"direction must be one of {DIRECTIONS}")
	try:
		amount = quantize(to_decimal(args.get("amount_mnt") or 0))
	except (InvalidOperation, ValueError, TypeError):
		return _error("amount_mnt is not a number")
	if amount <= ZERO:
		return _error("amount_mnt must be positive")
	when = str(args.get("date") or "").strip()
	try:
		posting_date = dt.date.fromisoformat(when) if when else today
	except ValueError:
		return _error("date must be YYYY-MM-DD")
	paid_via = str(args.get("paid_via") or "unknown")
	if paid_via not in PAID_VIA:
		paid_via = "unknown"
	party = str(args.get("party") or "").strip()[:140]
	description = str(args.get("description") or text).strip()[:140]

	try:
		regime = pipeline.regime_context(company, posting_date)
	except MissingRuleError:
		return _error("no tax regime on that date", code="no_regime")

	money_account, money_code = _money_account(company, "cash" if paid_via == "cash" else "bank")
	warnings: list[str] = [mn.WARN_TYPED_NO_DOCUMENT]
	vat_amount = ZERO
	lines: list[ProposedLine]
	if direction == DIRECTION_INCOME:
		revenue_account, revenue_code = _role(company, "revenue_sales")
		pattern_id = PATTERN_INCOME_VAT if regime.is_vat_payer else PATTERN_INCOME_NON_VAT
		lines = [ProposedLine(account_code=money_code, debit=amount, credit=ZERO, description=description)]
		if regime.is_vat_payer:
			try:
				rate = pipeline.vat_rate(posting_date, company=company)
			except Exception as exc:  # noqa: BLE001 - an unverified rate is a refusal, not a guess
				return _error(f"vat rate unavailable: {type(exc).__name__}", code="vat_rate_unavailable")
			vat_amount = vat_from_gross(amount, rate)
			_vat_account, vat_code = _role(company, "output_vat")
			lines.append(
				ProposedLine(
					account_code=revenue_code,
					debit=ZERO,
					credit=quantize(amount - vat_amount),
					description=description,
				)
			)
			lines.append(
				ProposedLine(account_code=vat_code, debit=ZERO, credit=vat_amount, description=description)
			)
		else:
			lines.append(
				ProposedLine(account_code=revenue_code, debit=ZERO, credit=amount, description=description)
			)
		account, code = revenue_account, revenue_code
		explanation = mn.EXPL_TYPED_INCOME.format(
			party=party or mn.VALUE_UNKNOWN,
			amount=fmt_mnt(amount),
			debit_code=money_code,
			credit_code=revenue_code,
		)
	else:
		account, code = _expense_account(company, args.get("account_code"))
		pattern_id = PATTERN_EXPENSE
		lines = [
			ProposedLine(account_code=code, debit=amount, credit=ZERO, description=description),
			ProposedLine(account_code=money_code, debit=ZERO, credit=amount, description=description),
		]
		explanation = mn.EXPL_TYPED_EXPENSE.format(
			party=party or mn.VALUE_UNKNOWN, amount=fmt_mnt(amount), debit_code=code, credit_code=money_code
		)

	citation = bank_rules.pattern_citation(pattern_id)
	if not bank_rules.pattern_cleared(pattern_id, company, citation):
		warnings.append(mn.WARN_UNVERIFIED_RULE)
	entry = ProposedEntry(
		company=company,
		posting_date=posting_date,
		lines=tuple(lines),
		pattern_id=pattern_id,
		citation=citation,
		explanation=explanation,
		document_kind="journal_entry",
		vat_treatment="none",
		warnings=tuple(warnings),
		total=amount,
		vat_amount=vat_amount,
	)
	document = _file_message(company, user, text[:MAX_TEXT_CHARS], source)
	extracted = {
		"seller_name": party or None,
		"date": posting_date.isoformat(),
		"total": float(amount),
		"vat_amount": float(vat_amount),
		"direction": direction,
		"paid_via": paid_via,
		"source": "text",
		"text": text[:MAX_TEXT_CHARS],
	}
	doc = frappe.get_doc(
		{
			"doctype": "Nyabo Proposal",
			"kind": KIND,
			"status": "proposed",
			"document": document,
			"company": company,
			"needs_accountant": 1,
			"posting_date": posting_date,
			"total": float(amount),
			"vat_amount": float(vat_amount),
			"vat_treatment": "none",
			"account_code": code,
			"account": account,
			"posting_pattern": bank_rules.pattern_link(pattern_id),
			"explanation": explanation,
			"citation": bank_rules.citation_suffix(citation).strip(" —"),
			"entry_json": json.dumps(entry.to_dict(), ensure_ascii=False),
			"extracted_json": json.dumps(extracted, ensure_ascii=False),
			"confidence_json": json.dumps({"account_code": 0.0}, ensure_ascii=False),
			"warnings_json": json.dumps(list(warnings), ensure_ascii=False),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	pipeline.write_event(
		"typed_transaction_proposed",
		company=company,
		actor_user=user,
		ref_doctype="Nyabo Proposal",
		ref_name=doc.name,
		payload={"direction": direction, "total": str(amount), "paid_via": paid_via, "pattern": pattern_id},
	)
	label = mn.TYPED_INCOME_LABEL if direction == DIRECTION_INCOME else mn.TYPED_EXPENSE_LABEL
	return {
		"proposal": doc.name,
		"direction": direction,
		"total": fmt_mnt(amount),
		"party": party,
		"date": posting_date.isoformat(),
		"text": mn.MSG_TYPED_PROPOSED.format(
			kind=label, amount=fmt_mnt(amount), date=posting_date.isoformat()
		),
		"computed_numbers": [fmt_mnt(amount), fmt_mnt(vat_amount), *posting_date.isoformat().split("-")[1:]],
	}


__all__ = ["DIRECTIONS", "KIND", "PAID_VIA", "propose"]
