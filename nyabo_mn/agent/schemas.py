"""Output schemas for every model call (pydantic v2).

Why pydantic models and not hand-written JSON Schema: the same class validates the
model's answer (``model_validate``) and produces the schema sent to the provider
(``json_schema``), so the two can never drift.

Constraints that OpenAI strict mode does not allow in the schema (``minimum``,
``maxLength``, ``pattern``, ``format`` …) are enforced with validators instead, and
described in the field description so the model still sees them. Sources:
- https://developers.openai.com/api/docs/guides/structured-outputs (strict mode: every
  property listed in ``required``, ``additionalProperties: false`` on every object,
  nullable via ``anyOf`` with ``{"type": "null"}``, ``$defs``/``$ref`` supported,
  ``minLength``/``maxLength``/``pattern``/``minimum``/``maximum``/``format`` unsupported).
- https://platform.claude.com/docs/en/api/messages (tool ``input_schema`` is plain JSON
  Schema; the same object works as a forced tool's schema, and with ``strict: true`` the
  API guarantees the input validates against it).
- openai-python ``src/openai/lib/_pydantic.py`` (``to_strict_json_schema``, read
  2026-09-08): the vendor's own converter keeps pydantic's ``anyOf: [{type}, {type: null}]``
  for Optional fields, recurses into every ``anyOf`` variant, sets ``additionalProperties:
  false`` on objects and lists every property in ``required`` - exactly what ``json_schema``
  below produces, so the two agree on the nullable form.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_validator

# Money crosses the model boundary as a JSON number but lives as Decimal in domain
# code (docs/ARCHITECTURE.md §10). WithJsonSchema replaces pydantic's default Decimal
# schema (number|string with a ``pattern``) because ``pattern`` is rejected by strict mode.
Money = Annotated[Decimal, WithJsonSchema({"type": "number"})]
Quantity = Annotated[Decimal, WithJsonSchema({"type": "number"})]

PaymentMethod = Literal["cash", "card", "transfer", "qpay", "unknown"]
VatTreatment = Literal["withheld", "in_expense", "exempt", "zero", "none"]

REASON_MAX_CHARS = 160

_STRICT_UNSUPPORTED_KEYWORDS = frozenset(
	{
		"minLength",
		"maxLength",
		"pattern",
		"format",
		"minimum",
		"maximum",
		"exclusiveMinimum",
		"exclusiveMaximum",
		"multipleOf",
		"minItems",
		"maxItems",
		"uniqueItems",
		"minProperties",
		"maxProperties",
		"default",
	}
)


class StrictModel(BaseModel):
	"""Base for every output model: unknown keys are an error, not silently dropped."""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _unit_interval(value: float) -> float:
	"""Clamp confidences into [0, 1]: a model reporting 1.2 is over-confident, not invalid."""
	if value != value:  # NaN
		return 0.0
	return max(0.0, min(1.0, float(value)))


class FieldConfidence(StrictModel):
	"""Per-field confidence, 0 (guess) to 1 (clearly printed and legible)."""

	seller_name: float = Field(description="0..1 confidence for seller_name")
	date: float = Field(description="0..1 confidence for date")
	total: float = Field(description="0..1 confidence for total")
	vat_amount: float = Field(description="0..1 confidence for vat_amount")
	lines: float = Field(description="0..1 confidence for the line items as a whole")

	@field_validator("seller_name", "date", "total", "vat_amount", "lines")
	@classmethod
	def _clamp(cls, value: float) -> float:
		return _unit_interval(value)


class ReceiptLine(StrictModel):
	description: str | None = Field(description="Item text as printed; null if unreadable")
	qty: Quantity | None = Field(description="Quantity as printed; null if not shown")
	amount: Money | None = Field(description="Line amount in MNT as printed; null if not shown")


class ReceiptExtraction(StrictModel):
	"""What the vision call returns for one receipt photo. Every field is required; use null when unknown."""

	seller_name: str | None = Field(description="Seller / merchant name as printed")
	seller_register_no: str | None = Field(
		description="Seller register number (РД), digits/letters as printed"
	)
	seller_tin: str | None = Field(description="Seller taxpayer number (ТТД / TIN), digits only")
	date: str | None = Field(description="Receipt date as ISO YYYY-MM-DD; null if not readable")
	total: Money | None = Field(description="Amount paid in MNT: the 'Төлөх дүн' / 'Төлсөн' line")
	vat_amount: Money | None = Field(description="VAT in MNT: the printed 'НӨАТ' line; null if none printed")
	lines: list[ReceiptLine] = Field(description="Line items in printed order; empty list if none")
	payment_method: PaymentMethod = Field(description="cash, card, transfer, qpay or unknown")
	receipt_id: str | None = Field(description="ebarimt receipt id ДДТД (long digit string); null if absent")
	lottery_no: str | None = Field(description="'Сугалааны дугаар' lottery number; null if absent")
	confidence: FieldConfidence
	notes: str | None = Field(description="Short remark about ambiguities, in English; null if none")

	@field_validator("date")
	@classmethod
	def _iso_date(cls, value: str | None) -> str | None:
		"""Accept only YYYY-MM-DD; anything else becomes null so code never guesses a date."""
		if value is None:
			return None
		try:
			return date.fromisoformat(value.strip()).isoformat()
		except ValueError:
			return None

	@field_validator("total", "vat_amount")
	@classmethod
	def _non_negative_money(cls, value: Decimal | None) -> Decimal | None:
		if value is None:
			return None
		try:
			value = Decimal(value)
		except (InvalidOperation, TypeError) as exc:
			raise ValueError("amount is not numeric") from exc
		if value.is_nan() or value < 0:
			raise ValueError("amount must be a non-negative number")
		return value.quantize(Decimal("0.01"))

	@field_validator("seller_tin", "receipt_id", "lottery_no")
	@classmethod
	def _empty_to_null(cls, value: str | None) -> str | None:
		return value or None


class ClassificationResult(StrictModel):
	"""Which leaf account and VAT treatment the model proposes for one receipt."""

	account_code: str = Field(description="One code from the provided leaf accounts list, exactly as listed")
	vat_treatment: VatTreatment = Field(description="withheld, in_expense, exempt, zero or none")
	reason_mn: str = Field(description="One sentence in Mongolian Cyrillic, at most 160 characters")
	confidence: float = Field(description="0..1 confidence in the account choice")

	@field_validator("reason_mn")
	@classmethod
	def _cap_reason(cls, value: str) -> str:
		"""Truncate rather than reject: the card has one line for it and the choice is still usable."""
		value = " ".join(value.split())
		if len(value) > REASON_MAX_CHARS:
			return value[: REASON_MAX_CHARS - 1].rstrip() + "…"
		return value

	@field_validator("confidence")
	@classmethod
	def _clamp(cls, value: float) -> float:
		return _unit_interval(value)


class QuestionAnswer(StrictModel):
	"""Final shape of a question-answering turn (built by code from the tool trace)."""

	answer_mn: str = Field(description="The answer in polite Mongolian Cyrillic")
	used_tool: str | None = Field(description="Name of the tool whose result the answer is based on, or null")
	needs_escalation: bool = Field(description="True when the question was handed to the admin")


class InsightNote(StrictModel):
	"""The accountant's note over the signals the detectors found (agent.insights)."""

	note_mn: str = Field(description="Two to four short sentences in polite Mongolian Cyrillic")
	order: list[str] = Field(description="The signal kinds in the order the note mentions them")


def _strictify(node: Any) -> Any:
	"""Make a JSON Schema node strict-mode compatible, recursively."""
	if isinstance(node, list):
		return [_strictify(item) for item in node]
	if not isinstance(node, dict):
		return node
	out: dict[str, Any] = {}
	for key, value in node.items():
		if key in _STRICT_UNSUPPORTED_KEYWORDS:
			continue
		if key == "title" and not isinstance(value, dict):
			# Titles are legal but pure noise for the model; dropped to keep prompts short.
			continue
		out[key] = _strictify(value)
	if out.get("type") == "object" or "properties" in out:
		props = out.get("properties", {})
		out["properties"] = props
		out["required"] = list(props.keys())
		out["additionalProperties"] = False
	return out


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
	"""Schema for ``model`` that satisfies OpenAI strict mode and Anthropic tool input.

	Every object gets ``additionalProperties: false`` and a ``required`` list naming
	all of its properties; unsupported constraint keywords are removed. The result is a
	deep copy, safe to mutate by callers.
	"""
	raw = model.model_json_schema()
	return copy.deepcopy(_strictify(raw))


__all__ = [
	"REASON_MAX_CHARS",
	"ClassificationResult",
	"FieldConfidence",
	"Money",
	"PaymentMethod",
	"QuestionAnswer",
	"ReceiptExtraction",
	"ReceiptLine",
	"StrictModel",
	"VatTreatment",
	"json_schema",
]
