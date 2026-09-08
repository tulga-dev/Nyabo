"""Bank statement rows -> BankLine, driven by layout data.

A layout (Nyabo Bank Layout / bank_layouts.json) says which header cells identify a
bank's export and which column holds the date, narrative, debit, credit, balance and
reference. Code never hard-codes a column index: an unknown export falls back to a
keyword guess that is flagged `verified=False`, so the bot asks the accountant to
confirm the mapping and the admin to verify the layout before it is trusted.

Input rows are plain lists of cell values as produced by the Excel/CSV reader
(strings, numbers, dates); this module owns the conversion.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from nyabo_mn.core.models import BankLine
from nyabo_mn.core.money import ZERO, MoneyParseError, parse_mnt, quantize, to_decimal

HEADER_SCAN_ROWS = 15
COLUMN_ROLES: tuple[str, ...] = (
	"date",
	"description",
	"debit",
	"credit",
	"amount",
	"balance",
	"reference",
	"currency",
)
DEFAULT_DATE_FORMATS: tuple[str, ...] = (
	"%Y-%m-%d",
	"%Y.%m.%d",
	"%d.%m.%Y",
	"%Y/%m/%d",
	"%d/%m/%Y",
	"%Y-%m-%d %H:%M:%S",
	"%Y-%m-%d %H:%M",
	"%Y.%m.%d %H:%M:%S",
	"%Y.%m.%d %H:%M",
	"%d.%m.%Y %H:%M:%S",
	"%d.%m.%Y %H:%M",
)
AMOUNT_STYLES = ("separate_debit_credit", "signed_amount")

# Header keywords for the generic fallback, most specific first per role. A cell matches a
# role when it contains one of the keywords; roles are assigned in this order so "үлдэгдэл"
# (balance) is taken before "дүн" (amount) and "орлого" (credit) before "утга" (description).
GENERIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
	("balance", ("үлдэгдэл", "balance")),
	("date", ("огноо", "date")),
	("debit", ("дебит", "зарлага", "debit", "withdrawal")),
	("credit", ("кредит", "орлого", "credit", "deposit")),
	("reference", ("лавлах", "reference", "гүйлгээний дугаар", "transaction id")),
	("currency", ("валют", "currency")),
	("description", ("гүйлгээний утга", "утга", "description", "details", "narrative", "тайлбар")),
	("amount", ("дүн", "amount")),
)
# Narrative fragments that mark opening/closing/total rows, which are not transactions.
SUMMARY_ROW_MARKERS: tuple[str, ...] = (
	"эхний үлдэгдэл",
	"эцсийн үлдэгдэл",
	"нийт",
	"opening balance",
	"closing balance",
	"total",
)


@dataclass(frozen=True)
class LayoutSpec:
	"""Mirror of Nyabo Bank Layout. `column_map` values are column indexes or header texts."""

	layout_id: str
	bank: str
	header_signature: tuple[str, ...] = ()
	column_map: Mapping[str, int | str] = field(default_factory=dict)
	amount_style: str = "separate_debit_credit"
	date_formats: tuple[str, ...] = DEFAULT_DATE_FORMATS
	header_row_hint: int | None = None
	verified: bool = False
	currency_default: str = "MNT"
	keywords: Mapping[str, tuple[str, ...]] | None = None
	notes: str = ""

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> LayoutSpec:
		"""Accepts the seed shape and the DocType shape (header_signature_json / column_map_json)."""
		signature = data.get("header_signature", data.get("header_signature_json")) or []
		column_map = data.get("column_map", data.get("column_map_json")) or {}
		formats = data.get("date_formats") or ()
		if isinstance(formats, str):
			formats = [f.strip() for f in formats.splitlines() if f.strip()]
		keywords = data.get("keywords")
		hint = data.get("header_row_hint")
		return cls(
			layout_id=str(data["layout_id"]),
			bank=str(data.get("bank") or "Other"),
			header_signature=tuple(str(h) for h in signature),
			column_map={str(k): v for k, v in dict(column_map).items()},
			amount_style=str(data.get("amount_style") or "separate_debit_credit"),
			date_formats=tuple(formats) or DEFAULT_DATE_FORMATS,
			header_row_hint=int(hint) if hint not in (None, "") else None,
			verified=bool(data.get("verified", False)),
			currency_default=str(data.get("currency_default") or "MNT"),
			keywords={str(k): tuple(v) for k, v in keywords.items()} if keywords else None,
			notes=str(data.get("notes") or ""),
		)

	@property
	def is_generic(self) -> bool:
		return self.keywords is not None


class LayoutError(ValueError):
	"""The layout cannot be applied to these rows (header not found, column missing)."""


# --- cell helpers ------------------------------------------------------------------------------


def norm_header(text: Any) -> str:
	"""Case- and whitespace-insensitive header text."""
	return " ".join(str(text if text is not None else "").lower().split())


def cell_text(value: Any) -> str:
	if value is None:
		return ""
	if isinstance(value, float) and value.is_integer():
		return str(int(value))
	return str(value).strip()


def parse_cell_date(value: Any, formats: Iterable[str] = DEFAULT_DATE_FORMATS) -> dt.date | None:
	"""Date from a cell: datetime/date objects as is, strings by the listed formats."""
	if value is None or value == "":
		return None
	if isinstance(value, dt.datetime):
		return value.date()
	if isinstance(value, dt.date):
		return value
	text = str(value).strip()
	if not text:
		return None
	candidates = [text, text.split()[0]] if " " in text else [text]
	for candidate in candidates:
		for fmt in formats:
			try:
				return dt.datetime.strptime(candidate, fmt).date()
			except ValueError:
				continue
	return None


def parse_cell_amount(value: Any) -> Decimal | None:
	"""Decimal from a cell; empty, '-' and unparseable text give None (the caller decides)."""
	if value is None:
		return None
	if isinstance(value, bool):
		return None
	if isinstance(value, (int, float, Decimal)):
		return quantize(to_decimal(value))
	text = str(value).strip()
	if text in ("", "-", "—", "–"):
		return None
	try:
		return parse_mnt(text)
	except MoneyParseError:
		return None


def row_hash(date: dt.date, amount: Decimal, description: str, reference: str, row_index: int) -> str:
	"""Idempotency key for a statement row (ARCHITECTURE §5.4)."""
	payload = "|".join(
		[date.isoformat(), str(quantize(amount)), description.strip(), reference.strip(), str(row_index)]
	)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- detection ------------------------------------------------------------------------------------


def _header_cells(rows: Sequence[Sequence[Any]], limit: int = HEADER_SCAN_ROWS) -> list[list[str]]:
	return [[norm_header(c) for c in row] for row in list(rows)[:limit]]


def _signature_present(cells: list[list[str]], signature: Iterable[str]) -> bool:
	flat = [c for row in cells for c in row if c]
	for header in signature:
		wanted = norm_header(header)
		if not wanted or not any(wanted == c or wanted in c for c in flat):
			return False
	return True


def detect_layout(rows: Sequence[Sequence[Any]], layouts: Iterable[LayoutSpec]) -> LayoutSpec | None:
	"""The first layout whose whole header signature appears in the first 15 rows.

	Layouts with more signature headers are tried first (more specific). Placeholder
	layouts with an empty signature never match. Generic keyword layouts are tried last
	and return a concrete, unverified LayoutSpec built by `guess_layout`.
	"""
	cells = _header_cells(rows)
	specific = [layout for layout in layouts if not layout.is_generic]
	generic = [layout for layout in layouts if layout.is_generic]
	for layout in sorted(specific, key=lambda lo: len(lo.header_signature), reverse=True):
		if layout.header_signature and _signature_present(cells, layout.header_signature):
			return layout
	for layout in generic:
		guessed = guess_layout(rows, template=layout)
		if guessed is not None:
			return guessed
	return None


def guess_layout(rows: Sequence[Sequence[Any]], template: LayoutSpec | None = None) -> LayoutSpec | None:
	"""Best-effort column mapping from Mongolian/English header keywords, always verified=False.

	Needs at least a date column, a narrative column and one of debit/credit/amount.
	"""
	keywords: Iterable[tuple[str, tuple[str, ...]]] = (
		tuple((role, tuple(words)) for role, words in template.keywords.items())
		if template is not None and template.keywords
		else GENERIC_KEYWORDS
	)
	ordered_roles = [role for role, _ in GENERIC_KEYWORDS]
	keyword_map = dict(keywords)
	for row_index, row in enumerate(list(rows)[:HEADER_SCAN_ROWS]):
		headers = [norm_header(c) for c in row]
		if sum(1 for h in headers if h) < 3:
			continue
		column_map: dict[str, int | str] = {}
		taken: set[int] = set()
		for role in ordered_roles:
			words = keyword_map.get(role, ())
			for col, header in enumerate(headers):
				if col in taken or not header:
					continue
				if any(word in header for word in words):
					column_map[role] = col
					taken.add(col)
					break
		has_amount = any(r in column_map for r in ("debit", "credit", "amount"))
		if "date" in column_map and "description" in column_map and has_amount:
			style = (
				"signed_amount"
				if "amount" in column_map and "debit" not in column_map and "credit" not in column_map
				else "separate_debit_credit"
			)
			return LayoutSpec(
				layout_id=template.layout_id if template else "generic_mn",
				bank=template.bank if template else "Other",
				header_signature=tuple(headers[c] for c in sorted(taken)),
				column_map=column_map,
				amount_style=style,
				date_formats=template.date_formats if template else DEFAULT_DATE_FORMATS,
				header_row_hint=row_index,
				verified=False,
				currency_default=template.currency_default if template else "MNT",
				notes=template.notes if template else "",
			)
	return None


# --- parsing ---------------------------------------------------------------------------------------


def _find_header_row(rows: Sequence[Sequence[Any]], layout: LayoutSpec) -> int | None:
	"""Row index of the header, from the hint or by looking for the mapped header texts."""
	if layout.header_row_hint is not None and 0 <= layout.header_row_hint < len(rows):
		return layout.header_row_hint
	# JSON from the desk may carry column indexes as digit strings; those are not header texts.
	wanted = [norm_header(v) for v in layout.column_map.values() if isinstance(v, str) and not v.isdigit()]
	if not wanted:
		wanted = [norm_header(h) for h in layout.header_signature]
	if not wanted:
		return None
	for index, row in enumerate(list(rows)[:HEADER_SCAN_ROWS]):
		headers = [norm_header(c) for c in row]
		if all(any(w == h or w in h for h in headers) for w in wanted):
			return index
	return None


def resolve_columns(rows: Sequence[Sequence[Any]], layout: LayoutSpec) -> tuple[int | None, dict[str, int]]:
	"""(header row index, role -> column index) with header texts resolved against the header row."""
	header_index = _find_header_row(rows, layout)
	headers = [norm_header(c) for c in rows[header_index]] if header_index is not None else []
	columns: dict[str, int] = {}
	for role, ref in layout.column_map.items():
		if role not in COLUMN_ROLES:
			continue
		if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
			columns[role] = int(ref)
			continue
		wanted = norm_header(ref)
		match = next((i for i, h in enumerate(headers) if h == wanted), None)
		if match is None:
			match = next((i for i, h in enumerate(headers) if wanted and wanted in h), None)
		if match is None:
			raise LayoutError(f"layout {layout.layout_id}: header {ref!r} for {role} not found")
		columns[role] = match
	if "date" not in columns or "description" not in columns:
		raise LayoutError(f"layout {layout.layout_id}: date and description columns are required")
	if layout.amount_style == "signed_amount" and "amount" not in columns:
		raise LayoutError(f"layout {layout.layout_id}: signed_amount needs an amount column")
	if layout.amount_style == "separate_debit_credit" and "debit" not in columns and "credit" not in columns:
		raise LayoutError(f"layout {layout.layout_id}: separate_debit_credit needs debit or credit")
	return header_index, columns


def _get(row: Sequence[Any], columns: Mapping[str, int], role: str) -> Any:
	col = columns.get(role)
	if col is None or col >= len(row):
		return None
	return row[col]


def parse_rows(rows: Sequence[Sequence[Any]], layout: LayoutSpec) -> list[BankLine]:
	"""Statement rows -> BankLines. Header, blank, summary and undated rows are skipped.

	Amounts accept spaces, commas, ₮, parentheses and minus signs; `amount` is signed
	(inflow positive) for both amount styles.
	"""
	header_index, columns = resolve_columns(rows, layout)
	start = header_index + 1 if header_index is not None else 0
	lines: list[BankLine] = []
	for row_index in range(start, len(rows)):
		row = rows[row_index]
		if row is None or all(cell_text(c) == "" for c in row):
			continue
		date = parse_cell_date(_get(row, columns, "date"), layout.date_formats)
		description = cell_text(_get(row, columns, "description"))
		if date is None:
			continue
		if any(marker in description.lower() for marker in SUMMARY_ROW_MARKERS) and _no_amount(
			row, columns, layout
		):
			continue
		if layout.amount_style == "signed_amount":
			amount = parse_cell_amount(_get(row, columns, "amount"))
			if amount is None:
				continue
			debit = -amount if amount < 0 else ZERO
			credit = amount if amount > 0 else ZERO
		else:
			debit = parse_cell_amount(_get(row, columns, "debit")) or ZERO
			credit = parse_cell_amount(_get(row, columns, "credit")) or ZERO
			if debit == ZERO and credit == ZERO:
				continue
			debit, credit = abs(debit), abs(credit)
			amount = credit - debit
		balance = parse_cell_amount(_get(row, columns, "balance"))
		reference = cell_text(_get(row, columns, "reference"))
		currency = cell_text(_get(row, columns, "currency")) or layout.currency_default
		lines.append(
			BankLine(
				date=date,
				description=description,
				debit=quantize(debit),
				credit=quantize(credit),
				amount=quantize(amount),
				balance=balance,
				reference=reference,
				currency=currency,
				row_index=row_index,
				row_hash=row_hash(date, amount, description, reference, row_index),
			)
		)
	return lines


def _no_amount(row: Sequence[Any], columns: Mapping[str, int], layout: LayoutSpec) -> bool:
	roles = ("amount",) if layout.amount_style == "signed_amount" else ("debit", "credit")
	return all(parse_cell_amount(_get(row, columns, r)) in (None, ZERO) for r in roles)
