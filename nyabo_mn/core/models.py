"""Frozen dataclasses shared by the pipeline, the rules engine and the Telegram cards.

Why frozen: a Receipt or ProposedEntry is stored on a Nyabo Proposal as JSON and shown
on a card; nothing may mutate it between the model's proposal and the accountant's
tap, or the audit trail (what was proposed, what was approved) would lie.

Why to_dict/from_dict: the JSON fields on Nyabo Proposal hold these objects. Decimals
are written as strings (never floats) and dates as ISO strings, so a round trip through
json.dumps/json.loads gives back an equal object.

The module imports datetime as `dt` on purpose: several dataclasses have a field named
`date`, which would otherwise shadow the type in annotations.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import types
import typing
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal, TypeVar

T = TypeVar("T", bound="Model")

VatTreatment = Literal["withheld", "in_expense", "exempt", "zero", "none"]
DocumentKind = Literal["purchase_invoice", "journal_entry"]
VerificationStatus = Literal["verified", "unsupported", "mismatch", "not_found"]
ClassificationSource = Literal["rule", "model", "history"]
MatchKind = Literal["exact", "fee", "transfer", "none"]


class Regime(enum.Enum):
	"""The two tax profiles (docs/mn-rules-reference.md §0.2). Only rules code reads these names."""

	VAT_PAYER = "vat_payer"
	SIMPLIFIED_1PCT = "simplified_1pct"


# --- JSON codec ----------------------------------------------------------------------------


def _encode(value: Any) -> Any:
	if value is None:
		return None
	if isinstance(value, Model):
		return value.to_dict()
	if isinstance(value, Decimal):
		return str(value)
	if isinstance(value, enum.Enum):
		return value.value
	if isinstance(value, dt.datetime):
		return value.isoformat()
	if isinstance(value, dt.date):
		return value.isoformat()
	if isinstance(value, (list, tuple)):
		return [_encode(v) for v in value]
	if isinstance(value, Mapping):
		return {str(k): _encode(v) for k, v in value.items()}
	return value


def _strip_optional(hint: Any) -> Any:
	origin = typing.get_origin(hint)
	if origin is typing.Union or origin is types.UnionType:
		args = [a for a in typing.get_args(hint) if a is not type(None)]
		return args[0] if len(args) == 1 else typing.Union[tuple(args)]  # noqa: UP007
	return hint


def _decode(value: Any, hint: Any) -> Any:
	if value is None:
		return None
	hint = _strip_optional(hint)
	origin = typing.get_origin(hint)
	if origin is Literal:
		return value
	if hint is Any:
		return value
	if isinstance(hint, type):
		if issubclass(hint, Model):
			return hint.from_dict(value) if isinstance(value, Mapping) else value
		if issubclass(hint, enum.Enum):
			return value if isinstance(value, hint) else hint(value)
		if hint is Decimal:
			return value if isinstance(value, Decimal) else Decimal(str(value))
		if hint is dt.datetime:
			return value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
		if hint is dt.date:
			if isinstance(value, dt.datetime):
				return value.date()
			return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))
		if hint is bool:
			return bool(value)
		if hint is int:
			return int(value)
		if hint is float:
			return float(value)
		if hint is str:
			return str(value)
	if origin is tuple:
		args = typing.get_args(hint)
		item_hint = args[0] if args else Any
		return tuple(_decode(v, item_hint) for v in value)
	if origin is list:
		args = typing.get_args(hint)
		return [_decode(v, args[0] if args else Any) for v in value]
	if origin in (dict, Mapping) or hint in (dict, Mapping):
		return dict(value)
	return value


class Model:
	"""Mixin giving every frozen dataclass the JSON round trip."""

	def to_dict(self) -> dict[str, Any]:
		return {f.name: _encode(getattr(self, f.name)) for f in dataclasses.fields(self)}  # type: ignore[arg-type]

	@classmethod
	def from_dict(cls: type[T], data: Mapping[str, Any]) -> T:
		hints = typing.get_type_hints(cls)
		kwargs: dict[str, Any] = {}
		for f in dataclasses.fields(cls):  # type: ignore[arg-type]
			if f.name in data:
				kwargs[f.name] = _decode(data[f.name], hints[f.name])
		return cls(**kwargs)


# --- receipts --------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ReceiptLine(Model):
	description: str
	qty: Decimal | None
	amount: Decimal


@dataclasses.dataclass(frozen=True)
class FieldConfidence(Model):
	"""Per-field confidence returned by the extraction model (0..1)."""

	field: str
	confidence: float


@dataclasses.dataclass(frozen=True)
class Receipt(Model):
	seller_name: str
	seller_tin: str | None
	seller_register_no: str | None
	date: dt.date | None
	total: Decimal | None
	vat_amount: Decimal | None
	lines: tuple[ReceiptLine, ...] = ()
	payment_method: str | None = None
	receipt_id: str | None = None
	lottery_no: str | None = None
	confidence: Mapping[str, float] = dataclasses.field(default_factory=dict)
	raw_text: str = ""

	def confidence_of(self, field: str) -> float:
		"""Missing confidence counts as zero: an unknown field must not look certain."""
		return float(self.confidence.get(field, 0.0))


@dataclasses.dataclass(frozen=True)
class SellerInfo(Model):
	name: str
	tin: str | None
	register_no: str | None
	vat_payer: bool | None
	found: bool
	source: str


@dataclasses.dataclass(frozen=True)
class ReceiptVerification(Model):
	status: VerificationStatus
	reason: str
	checked_at: dt.datetime | None = None


# --- proposals -------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Classification(Model):
	account_code: str
	vat_treatment: VatTreatment
	reason_mn: str
	confidence: float
	source: ClassificationSource
	rule_name: str | None = None


@dataclasses.dataclass(frozen=True)
class Citation(Model):
	instrument: str
	section: str | None
	verified: bool
	url: str | None = None
	quote: str | None = None


@dataclasses.dataclass(frozen=True)
class ProposedLine(Model):
	account_code: str
	debit: Decimal
	credit: Decimal
	description: str = ""
	party_type: str | None = None
	party: str | None = None


@dataclasses.dataclass(frozen=True)
class ProposedEntry(Model):
	company: str
	posting_date: dt.date
	lines: tuple[ProposedLine, ...]
	pattern_id: str
	citation: Citation
	explanation: str
	document_kind: DocumentKind
	vat_treatment: VatTreatment
	warnings: tuple[str, ...] = ()
	total: Decimal = Decimal("0.00")
	vat_amount: Decimal = Decimal("0.00")
	supplier: str | None = None

	@property
	def total_debit(self) -> Decimal:
		return sum((line.debit for line in self.lines), Decimal("0"))

	@property
	def total_credit(self) -> Decimal:
		return sum((line.credit for line in self.lines), Decimal("0"))


# --- regimes ---------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RegimeContext(Model):
	"""What the rest of the app is allowed to know about a company's tax regime on a date."""

	regime: Regime
	is_vat_payer: bool
	input_vat_recoverable: bool
	summary_kind: str
	effective_from: dt.date | None = None


# --- bank statements ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class BankLine(Model):
	"""One statement row. `amount` is signed (inflow positive); debit/credit are the split."""

	date: dt.date
	description: str
	debit: Decimal
	credit: Decimal
	amount: Decimal
	balance: Decimal | None
	reference: str
	currency: str
	row_index: int
	row_hash: str


@dataclasses.dataclass(frozen=True)
class MatchCandidate(Model):
	doctype: str
	name: str
	date: dt.date
	amount: Decimal
	party_name: str = ""
	reference: str = ""


@dataclasses.dataclass(frozen=True)
class MatchResult(Model):
	line: BankLine
	candidate: MatchCandidate | None
	score: float
	kind: MatchKind
	reason: str
