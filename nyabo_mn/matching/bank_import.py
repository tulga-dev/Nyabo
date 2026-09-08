"""Nyabo Document (bank_statement) -> ERPNext Bank Transactions (ARCHITECTURE §5.4).

Idempotent by design: a statement re-sent next month overlaps last month's rows, so
every row is fingerprinted (bank account + date + deposit + withdrawal + narrative) and
also keyed by the core ``row_hash`` stored in ``transaction_id``; an existing row is
counted as ``dup`` and never re-created. Transactions are inserted and submitted, as
ERPNext's own Bank Statement Import does (``submit_after_import`` defaults to 1), so
the reconciliation tool and ``match.run`` can allocate against them.

An unknown layout is not an error: the summary carries ``unknown_layout = True``, the
first rows and the generic guess so the bot can ask the accountant to map columns.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from nyabo_mn.core.models import BankLine
from nyabo_mn.core.statements import LayoutError, LayoutSpec, parse_rows
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.matching import common
from nyabo_mn.parsers import detect as detect_mod
from nyabo_mn.parsers import excel

DOCUMENT_DOCTYPE = "Nyabo Document"
PREVIEW_ROWS = 5


class BankImportError(ValueError):
	def __init__(self, message_mn: str):
		super().__init__(message_mn)
		self.message_mn = message_mn


# --- loading --------------------------------------------------------------------------------------


def load_document(document_name: str) -> Any:
	import frappe

	if not frappe.db.exists(DOCUMENT_DOCTYPE, document_name):
		raise BankImportError(mn.MSG_STATEMENT_NOT_A_STATEMENT)
	doc = frappe.get_doc(DOCUMENT_DOCTYPE, document_name)
	if doc.doc_type != "bank_statement":
		raise BankImportError(mn.MSG_STATEMENT_NOT_A_STATEMENT)
	return doc


def file_bytes(doc: Any) -> tuple[bytes, str]:
	"""Bytes and file name of the document's attachment (File by file_url)."""
	import frappe

	file_url = doc.file
	if not file_url:
		raise BankImportError(mn.MSG_STATEMENT_FILE_UNREADABLE.format(filename=""))
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		raise BankImportError(mn.MSG_STATEMENT_FILE_UNREADABLE.format(filename=os.path.basename(file_url)))
	file_doc = frappe.get_doc("File", name)
	return file_doc.get_content(), str(file_doc.file_name or os.path.basename(file_url))


def guess_bank(rows: Sequence[Sequence[Any]]) -> str | None:
	"""Bank named in the title block (English key or Mongolian name), for the unknown-layout card."""
	names = {key: [key.lower(), value.lower()] for key, value in mn.BANK_NAMES_MN.items()}
	names.setdefault("Khan Bank", []).append("хаан")
	names.setdefault("Golomt Bank", []).append("голомт")
	names.setdefault("XacBank", []).append("хас банк")
	names.setdefault("TDB", []).append("ххб")
	for row in list(rows)[: PREVIEW_ROWS * 3]:
		for cell in row:
			text = str(cell or "").lower()
			if not text:
				continue
			for bank, needles in names.items():
				if any(needle in text for needle in needles):
					return bank
	return None


# --- bank account resolution ----------------------------------------------------------------------


def resolve_bank_row(
	company: str,
	bank: str,
	currency: str,
	rows: Sequence[Sequence[Any]],
) -> dict[str, Any] | None:
	"""Settings row for the statement: by the account number in the file, else bank + currency."""
	settings_rows = [r for r in common.bank_rows(company) if r.get("erpnext_bank_account")]
	number = detect_mod.find_account_number(rows, [r.get("account_number") or "" for r in settings_rows])
	if number:
		for row in settings_rows:
			if str(row.get("account_number") or "") == number:
				return row
	same_bank = [r for r in settings_rows if r.get("bank") == bank]
	for row in same_bank:
		if (row.get("currency") or "MNT") == currency:
			return row
	if len(same_bank) == 1:
		return same_bank[0]
	return None


def statement_currency(lines: Sequence[BankLine], layout: LayoutSpec) -> str:
	counts: dict[str, int] = {}
	for line in lines:
		counts[line.currency or layout.currency_default] = (
			counts.get(line.currency or layout.currency_default, 0) + 1
		)
	if not counts:
		return layout.currency_default
	return max(counts.items(), key=lambda item: item[1])[0]


# --- idempotent creation --------------------------------------------------------------------------


def fingerprint(
	bank_account: str, line_date: Any, deposit: Decimal, withdrawal: Decimal, description: str
) -> str:
	payload = "|".join(
		[
			bank_account,
			common.to_date(line_date).isoformat(),
			common.decimal_str(deposit),
			common.decimal_str(withdrawal),
			" ".join(str(description or "").split()).lower(),
		]
	)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def existing_keys(bank_account: str, lines: Sequence[BankLine]) -> tuple[set[str], set[str]]:
	"""(fingerprints, transaction_ids) of rows already stored for the statement's date span."""
	import frappe

	if not lines:
		return set(), set()
	dates = [line.date for line in lines]
	rows = frappe.get_all(
		"Bank Transaction",
		filters={
			"bank_account": bank_account,
			"docstatus": ["in", [0, 1]],
			"date": ["between", [min(dates).isoformat(), max(dates).isoformat()]],
		},
		fields=["name", "date", "deposit", "withdrawal", "description", "transaction_id"],
	)
	prints = {
		fingerprint(
			bank_account,
			r.date,
			Decimal(str(r.deposit or 0)),
			Decimal(str(r.withdrawal or 0)),
			str(r.description or ""),
		)
		for r in rows
	}
	ids = {str(r.transaction_id) for r in rows if r.transaction_id}
	return prints, ids


def create_bank_transactions(
	lines: Sequence[BankLine],
	*,
	company: str,
	bank_account: str,
	currency: str,
) -> tuple[list[str], list[str], int]:
	"""Insert + submit one Bank Transaction per new line. Returns (created, all row hashes, dup count)."""
	import frappe

	prints, ids = existing_keys(bank_account, lines)
	created: list[str] = []
	hashes: list[str] = []
	dup = 0
	for line in lines:
		hashes.append(line.row_hash)
		key = fingerprint(bank_account, line.date, line.credit, line.debit, line.description)
		if key in prints or line.row_hash in ids:
			dup += 1
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"date": line.date,
				"deposit": float(line.credit),
				"withdrawal": float(line.debit),
				"description": line.description,
				"reference_number": line.reference or line.row_hash,
				"transaction_id": line.row_hash,
				"bank_account": bank_account,
				"company": company,
				"currency": line.currency or currency,
				"status": "Pending",
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		doc.submit()
		created.append(doc.name)
		prints.add(key)
		ids.add(line.row_hash)
	return created, hashes, dup


# --- the flow -------------------------------------------------------------------------------------


def _layout_dict(layout: LayoutSpec | None) -> dict[str, Any] | None:
	if layout is None:
		return None
	return {
		"layout_id": layout.layout_id,
		"bank": layout.bank,
		"header_row_hint": layout.header_row_hint,
		"header_signature": list(layout.header_signature),
		"column_map": dict(layout.column_map),
		"amount_style": layout.amount_style,
		"verified": layout.verified,
	}


def _set_status(doc: Any, status: str, error: str | None = None) -> None:
	doc.db_set("status", status)
	if error is not None:
		doc.db_set("error", error[:1000])


def import_statement(document_name: str, *, run_matching: bool = True) -> dict[str, Any]:
	"""Rows -> layout -> Bank Transactions -> match.run. See the module docstring for the contract."""
	from nyabo_mn.matching import match as match_mod

	doc = load_document(document_name)
	company = str(doc.company)
	summary: dict[str, Any] = {
		"document": document_name,
		"bank": None,
		"layout": None,
		"count": 0,
		"new": 0,
		"dup": 0,
		"matched": 0,
		"unmatched": 0,
		"unknown_layout": False,
		"preview_rows": [],
		"guess": None,
		"bank_account": None,
		"transactions": [],
		"match": None,
	}
	try:
		data, filename = file_bytes(doc)
		rows = excel.read_rows(data, filename)
	except excel.StatementFileError as exc:
		_set_status(doc, "failed", exc.message_mn)
		raise BankImportError(exc.message_mn) from exc

	summary["preview_rows"] = excel.preview_rows(rows, PREVIEW_ROWS)
	layout, guess = detect_mod.detect(rows, company)
	summary["guess"] = _layout_dict(guess)
	if layout is None:
		summary["unknown_layout"] = True
		summary["bank"] = (guess.bank if guess and guess.bank != "Other" else None) or guess_bank(rows)
		common.write_event(
			"statement_layout_unknown",
			company=company,
			ref_doctype=DOCUMENT_DOCTYPE,
			ref_name=document_name,
			payload={
				"preview_rows": summary["preview_rows"],
				"guess": summary["guess"],
				"bank": summary["bank"],
			},
		)
		return summary

	summary["layout"] = layout.layout_id
	summary["bank"] = layout.bank
	try:
		lines = parse_rows(rows, layout)
	except LayoutError as exc:
		_set_status(doc, "failed", str(exc))
		raise BankImportError(mn.MSG_STATEMENT_FILE_UNREADABLE.format(filename=filename)) from exc
	summary["count"] = len(lines)
	if not lines:
		_set_status(doc, "failed", mn.MSG_STATEMENT_NO_LINES)
		raise BankImportError(mn.MSG_STATEMENT_NO_LINES)

	currency = statement_currency(lines, layout)
	row = resolve_bank_row(company, layout.bank, currency, rows)
	if row is None:
		message = mn.MSG_STATEMENT_NO_BANK_ACCOUNT.format(bank=mn.BANK_NAMES_MN.get(layout.bank, layout.bank))
		_set_status(doc, "failed", message)
		raise BankImportError(message)
	bank_account = str(row["erpnext_bank_account"])
	summary["bank_account"] = bank_account

	created, hashes, dup = create_bank_transactions(
		lines, company=company, bank_account=bank_account, currency=currency
	)
	summary.update({"new": len(created), "dup": dup, "transactions": created})
	_set_status(doc, "extracted")

	closing = next((line for line in reversed(lines) if line.balance is not None), None)
	payload: dict[str, Any] = {
		"document": document_name,
		"bank": layout.bank,
		"layout": layout.layout_id,
		"bank_account": bank_account,
		"currency": currency,
		"count": len(lines),
		"new": len(created),
		"dup": dup,
		"transactions": created,
		"row_hashes": hashes,
		"closing_balance": common.decimal_str(closing.balance) if closing else None,
		"closing_date": closing.date.isoformat() if closing else max(line.date for line in lines).isoformat(),
	}
	if run_matching and created:
		stats = match_mod.run(company, bank_account, transactions=created)
		summary["match"] = {k: v for k, v in stats.items() if k != "details"}
		summary["matched"] = int(stats["matched"]) + int(stats["transfers"])
		summary["unmatched"] = int(stats["unmatched"]) + int(stats["fee_proposals"])
		payload["match"] = summary["match"]
	common.write_event(
		"statement_imported",
		company=company,
		ref_doctype=DOCUMENT_DOCTYPE,
		ref_name=document_name,
		payload=payload,
	)
	log_event(
		"bank.statement_imported",
		company=company,
		document=document_name,
		layout=layout.layout_id,
		count=len(lines),
		new=len(created),
		dup=dup,
	)
	return summary


def summary_text(summary: dict[str, Any]) -> str:
	"""The one-line import reply (MSG_STATEMENT_IMPORTED) or the unknown-layout question."""
	if summary.get("unknown_layout"):
		preview = "\n".join(" | ".join(cells) for cells in summary.get("preview_rows") or [])
		return mn.MSG_STATEMENT_LAYOUT_UNKNOWN.format(preview=preview)
	bank = summary.get("bank") or ""
	return mn.MSG_STATEMENT_IMPORTED.format(
		bank=mn.BANK_NAMES_MN.get(bank, bank),
		count=summary.get("count", 0),
		new=summary.get("new", 0),
		dup=summary.get("dup", 0),
		matched=summary.get("matched", 0),
		unmatched=summary.get("unmatched", 0),
	)


def import_event_payloads(company: str, bank_account: str | None = None) -> list[dict[str, Any]]:
	"""statement_imported payloads, newest first (used by status.summary for closing balances)."""
	import frappe

	rows = frappe.get_all(
		"Nyabo Event",
		filters={"event_type": "statement_imported", "company": company},
		fields=["name", "creation", "payload_json"],
		order_by="creation desc",
	)
	out: list[dict[str, Any]] = []
	for row in rows:
		payload = common.event_payload(row)
		if bank_account and payload.get("bank_account") != bank_account:
			continue
		out.append(payload)
	return out


__all__ = [
	"BankImportError",
	"create_bank_transactions",
	"fingerprint",
	"guess_bank",
	"import_event_payloads",
	"import_statement",
	"resolve_bank_row",
	"summary_text",
]


def _json(value: Any) -> str:  # pragma: no cover - debugging aid
	return json.dumps(value, ensure_ascii=False, default=str)
