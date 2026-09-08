"""Opening inventory from an owner's list (docs/ARCHITECTURE.md §5.2 step 4).

Text lines `нэр, тоо, үнэ` or a spreadsheet with name/qty/rate columns become a Nyabo
Inventory Intake; after the owner confirms the total, `post_intake` creates the Items
and one opening document: a submitted Stock Reconciliation (purpose "Opening Stock")
when the company runs perpetual inventory, otherwise a submitted Journal Entry
Дт inventory_goods — Кт temporary_opening (both resolved through account roles).

Guards: the intake must be confirmed and Nyabo Company Settings must exist (a company
that never finished onboarding has no regime and no chart scheme). Money is Decimal
until it reaches ERPNext, which stores floats.

ERPNext field names used here were checked against tests/frappe_stub/erpnext_meta.json
(Item, Item Group, UOM, Warehouse, Stock Reconciliation, Stock Reconciliation Item,
Journal Entry, Journal Entry Account).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import frappe
from frappe.utils import getdate, nowtime

from nyabo_mn.core.money import ZERO, MoneyParseError, parse_mnt, quantize
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.rules import aliases

DOCTYPE = "Nyabo Inventory Intake"
STATUS_DRAFT = "draft"
STATUS_CONFIRMED = "confirmed"
STATUS_POSTED = "posted"
STATUS_FAILED = "failed"

INVENTORY_ROLE = "inventory_goods"
OPENING_ROLE = "temporary_opening"
STORES_WAREHOUSE = "Stores"
STOCK_RECONCILIATION_SERIES = "MAT-RECO-.YYYY.-"
JOURNAL_ENTRY_SERIES = "ACC-JV-.YYYY.-"

HEADER_KEYWORDS: dict[str, tuple[str, ...]] = {
	"name": ("нэр", "бараа", "барааны нэр", "name", "item", "description"),
	"qty": ("тоо", "тоо хэмжээ", "тоо ширхэг", "ширхэг", "qty", "quantity", "count"),
	"rate": ("үнэ", "нэгж үнэ", "нэгжийн үнэ", "rate", "price", "unit price"),
	"uom": ("нэгж", "хэмжих нэгж", "uom", "unit"),
}
# A comma glued to a three-digit group ("12,500") is a thousands separator; ", 100" is a column break.
_COMMA_SPLIT = re.compile(r"\s*,(?!\d{3}(?!\d))\s*")
_HARD_SEPARATORS = ("\t", "|", ";")


def _split_line(line: str) -> list[str]:
	for separator in _HARD_SEPARATORS:
		if separator in line:
			return [part.strip() for part in line.split(separator)]
	return [part.strip() for part in _COMMA_SPLIT.split(line)]


class IntakeParseError(ValueError):
	"""A line or table that cannot become rows; `message_mn` is ready for the chat."""

	def __init__(self, message_mn: str):
		super().__init__(message_mn)
		self.message_mn = message_mn


@dataclass(frozen=True)
class IntakeRow:
	item_name: str
	qty: Decimal
	rate: Decimal
	uom: str = mn.UOM_PIECE

	@property
	def amount(self) -> Decimal:
		return quantize(self.qty * self.rate)

	def as_child(self) -> dict[str, Any]:
		return {
			"item_name": self.item_name,
			"qty": float(self.qty),
			"uom": self.uom,
			"rate": float(self.rate),
			"amount": float(self.amount),
		}


# --- parsing --------------------------------------------------------------------------------


def _number(text: Any) -> Decimal | None:
	if isinstance(text, (int, float, Decimal)) and not isinstance(text, bool):
		return Decimal(str(text))
	value = str(text or "").strip()
	if not value:
		return None
	try:
		return parse_mnt(value)
	except MoneyParseError:
		return None


def _row(name: Any, qty: Any, rate: Any, uom: Any = None) -> IntakeRow | None:
	item_name = " ".join(str(name or "").split())
	qty_value = _number(qty)
	rate_value = _number(rate)
	if not item_name or qty_value is None or rate_value is None:
		return None
	if qty_value <= ZERO or rate_value <= ZERO:
		raise IntakeParseError(mn.MSG_INTAKE_QTY_RATE_POSITIVE.format(item=item_name))
	uom_value = " ".join(str(uom or "").split()) or mn.UOM_PIECE
	return IntakeRow(item_name=item_name, qty=qty_value, rate=rate_value, uom=uom_value)


def parse_text(text: str) -> list[IntakeRow]:
	"""`нэр, тоо, үнэ` per line (also `;`, tab or `|` separated; an optional 4th column is the UOM)."""
	rows: list[IntakeRow] = []
	for index, raw in enumerate(str(text or "").splitlines(), start=1):
		line = raw.strip().strip("`")
		if not line:
			continue
		parts = _split_line(line)
		if len(parts) < 3:
			raise IntakeParseError(mn.MSG_INTAKE_LINE_UNREADABLE.format(line=index, text=line))
		# A name may itself contain a comma: qty and rate are the last two numeric cells.
		name, qty, rate = ", ".join(parts[:-2]), parts[-2], parts[-1]
		uom = None
		if _number(rate) is None and len(parts) >= 4 and _number(parts[-3]) is not None:
			name, qty, rate, uom = ", ".join(parts[:-3]), parts[-3], parts[-2], parts[-1]
		row = _row(name, qty, rate, uom)
		if row is None:
			raise IntakeParseError(mn.MSG_INTAKE_LINE_UNREADABLE.format(line=index, text=line))
		rows.append(row)
	if not rows:
		raise IntakeParseError(mn.MSG_INTAKE_EMPTY)
	return rows


def _header_map(cells: Sequence[Any]) -> dict[str, int] | None:
	found: dict[str, int] = {}
	for index, cell in enumerate(cells):
		text = " ".join(str(cell or "").casefold().split())
		if not text:
			continue
		for role, keywords in HEADER_KEYWORDS.items():
			if role not in found and any(text == k or text.startswith(k) for k in keywords):
				found[role] = index
				break
	return found if {"name", "qty", "rate"} <= set(found) else None


def parse_table(rows: Iterable[Sequence[Any]]) -> list[IntakeRow]:
	"""Rows from xlsx/csv: the header row is found by keywords (нэр/name, тоо/qty, үнэ/rate, нэгж/uom).

	Without a header the first three columns are taken as name, qty, rate. Blank rows and
	total rows (no name or no numbers) are skipped.
	"""
	table = [list(r) for r in rows]
	columns: dict[str, int] | None = None
	start = 0
	for index, cells in enumerate(table[:15]):
		columns = _header_map(cells)
		if columns:
			start = index + 1
			break
	if columns is None:
		if not table:
			raise IntakeParseError(mn.MSG_INTAKE_EMPTY)
		columns = {"name": 0, "qty": 1, "rate": 2}
		if _row(*(_cell(table[0], columns, k) for k in ("name", "qty", "rate"))) is None:
			raise IntakeParseError(mn.MSG_INTAKE_HEADER_NOT_FOUND)
	out: list[IntakeRow] = []
	for cells in table[start:]:
		if not any(str(c or "").strip() for c in cells):
			continue
		row = _row(
			_cell(cells, columns, "name"),
			_cell(cells, columns, "qty"),
			_cell(cells, columns, "rate"),
			_cell(cells, columns, "uom"),
		)
		if row is not None:
			out.append(row)
	if not out:
		raise IntakeParseError(mn.MSG_INTAKE_EMPTY)
	return out


def _cell(cells: Sequence[Any], columns: dict[str, int], role: str) -> Any:
	index = columns.get(role)
	if index is None or index >= len(cells):
		return None
	return cells[index]


def total_of(rows: Iterable[IntakeRow]) -> Decimal:
	return quantize(sum((r.amount for r in rows), ZERO))


# --- documents ---------------------------------------------------------------------------------


def create_intake(
	company: str,
	source: str,
	rows: Sequence[IntakeRow],
	posting_date: dt.date | str,
	file_url: str | None = None,
) -> Any:
	"""A draft Nyabo Inventory Intake for the confirmation card."""
	if not rows:
		raise IntakeParseError(mn.MSG_INTAKE_EMPTY)
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"company": company,
			"source": source,
			"file": file_url,
			"posting_date": getdate(posting_date),
			"status": STATUS_DRAFT,
			"items": [r.as_child() for r in rows],
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def confirm_intake(name: str, user: str) -> Any:
	"""The [Батлах] tap: records who confirmed the total."""
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status == STATUS_POSTED:
		frappe.throw(mn.MSG_INTAKE_ALREADY_POSTED.format(name=name))
	doc.status = STATUS_CONFIRMED
	doc.confirmed_by = user
	doc.flags.ignore_permissions = True
	doc.save()
	return doc


def post_intake(name: str, user: str) -> dict[str, Any]:
	"""Create the Items and the opening document; returns the created document names."""
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status == STATUS_POSTED:
		frappe.throw(mn.MSG_INTAKE_ALREADY_POSTED.format(name=name))
	if doc.status != STATUS_CONFIRMED:
		frappe.throw(mn.MSG_INTAKE_NOT_CONFIRMED.format(name=name))
	if not frappe.db.exists("Nyabo Company Settings", {"company": doc.company}):
		frappe.throw(mn.MSG_INTAKE_NO_SETTINGS.format(company=doc.company))
	if not doc.confirmed_by:
		doc.confirmed_by = user
	try:
		created = _post(doc)
	except Exception as exc:
		doc.status = STATUS_FAILED
		doc.error = str(exc)[:500]
		doc.flags.ignore_permissions = True
		doc.save()
		log_event("inventory_intake.failed", level="error", intake=name, error=repr(exc))
		raise
	doc.status = STATUS_POSTED
	doc.error = None
	doc.created_docs_json = json.dumps(created, ensure_ascii=False)
	doc.flags.ignore_permissions = True
	doc.save()
	log_event("inventory_intake.posted", intake=name, company=doc.company, user=user, **created)
	return created


def _post(doc: Any) -> dict[str, Any]:
	warehouse = _default_warehouse(doc.company)
	items: list[str] = []
	for row in doc.items:
		row.item_code = ensure_item(row.item_name, row.uom or mn.UOM_PIECE)
		if not row.warehouse:
			row.warehouse = warehouse
		items.append(row.item_code)
	created: dict[str, Any] = {"items": items}
	perpetual = bool(int(frappe.db.get_value("Company", doc.company, "enable_perpetual_inventory") or 0))
	if perpetual:
		created["stock_reconciliation"] = _opening_stock_reconciliation(doc)
	else:
		created["journal_entry"] = _opening_journal_entry(doc)
	return created


def ensure_item_group() -> str:
	name = mn.ITEM_GROUP_INVENTORY
	if not frappe.db.exists("Item Group", name):
		values: dict[str, Any] = {"doctype": "Item Group", "item_group_name": name, "is_group": 0}
		if frappe.db.exists("Item Group", "All Item Groups"):
			values["parent_item_group"] = "All Item Groups"
		frappe.get_doc(values).insert(ignore_permissions=True)
	return name


def ensure_uom(uom: str) -> str:
	"""ERPNext ships English UOMs only; a Mongolian unit ("ш") is created on first use."""
	if not frappe.db.exists("UOM", uom):
		frappe.get_doc({"doctype": "UOM", "uom_name": uom, "enabled": 1}).insert(ignore_permissions=True)
	return uom


def ensure_item(item_name: str, uom: str) -> str:
	"""A stock Item named by the item name (Item is named by item_code); existing items are reused."""
	existing = frappe.db.get_value("Item", {"item_name": item_name}, "name") or frappe.db.exists(
		"Item", item_name
	)
	if existing:
		return str(existing)
	doc = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_name,
			"item_name": item_name,
			"item_group": ensure_item_group(),
			"stock_uom": ensure_uom(uom),
			"is_stock_item": 1,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _default_warehouse(company: str) -> str | None:
	name = frappe.db.get_value("Warehouse", {"company": company, "warehouse_name": STORES_WAREHOUSE}, "name")
	if name:
		return name
	return frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")


def _opening_stock_reconciliation(doc: Any) -> str:
	"""Submitted Stock Reconciliation "Opening Stock"; the difference account must be a Balance Sheet one."""
	reco = frappe.get_doc(
		{
			"doctype": "Stock Reconciliation",
			"naming_series": STOCK_RECONCILIATION_SERIES,
			"company": doc.company,
			"purpose": "Opening Stock",
			"posting_date": doc.posting_date,
			"posting_time": nowtime(),
			"set_posting_time": 1,
			"expense_account": aliases.account_for(doc.company, f"role:{OPENING_ROLE}"),
			"cost_center": frappe.db.get_value("Company", doc.company, "cost_center"),
			"items": [
				{
					"item_code": row.item_code,
					"item_name": row.item_name,
					"warehouse": row.warehouse,
					"qty": row.qty,
					"valuation_rate": row.rate,
				}
				for row in doc.items
			],
		}
	)
	reco.flags.ignore_permissions = True
	reco.insert()
	reco.submit()
	return reco.name


def _opening_journal_entry(doc: Any) -> str:
	"""Submitted opening JE: Дт inventory_goods — Кт temporary_opening for the intake total."""
	total = float(quantize(Decimal(str(doc.total_amount or 0))))
	explanation = mn.EXPL_INVENTORY_OPENING.format(intake=doc.name)
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"naming_series": JOURNAL_ENTRY_SERIES,
			"voucher_type": "Opening Entry",
			"is_opening": "Yes",
			"company": doc.company,
			"posting_date": doc.posting_date,
			"user_remark": explanation,
			"nyabo_explanation": explanation,
			"nyabo_primary_document_ref": doc.name,
			"accounts": [
				{
					"account": aliases.account_for(doc.company, f"role:{INVENTORY_ROLE}"),
					"debit_in_account_currency": total,
				},
				{
					"account": aliases.account_for(doc.company, f"role:{OPENING_ROLE}"),
					"credit_in_account_currency": total,
				},
			],
		}
	)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name
