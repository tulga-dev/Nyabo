"""Vision extraction of one receipt photo (docs/ARCHITECTURE.md §5.3 step 2).

The model returns ``ReceiptExtraction`` (schema-validated, no tools); this module turns
it into the domain ``Receipt`` (``nyabo_mn.core.models``) with Decimal money and a real
``date``, and scans the free-text fields for instruction-looking content so the pipeline
can log ``injection_suspected`` and never act on it.

Two shapes leave this module on purpose. ``Receipt`` is the frozen domain object the
rules engine, the cards and ``Nyabo Proposal.extracted_json`` use; it has no room for
call metadata. ``ExtractOutcome.receipt_dict`` keeps everything the model said (notes,
confidence, prompt version, model id, the injection fragment) for the proposal record
and the evals. Where the two disagree - ``Receipt`` requires a seller name and a line
amount, the model may return null - the dict keeps the null and ``warnings`` names the
substitution so the card can show ⚠️ instead of a silently invented value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from nyabo_mn.agent import prompts
from nyabo_mn.agent.llm_client import ImagePart, LlmClient, LlmResult, LlmSchemaError, Part, TextPart
from nyabo_mn.agent.schemas import ReceiptExtraction, json_schema
from nyabo_mn.core.models import Receipt, ReceiptLine
from nyabo_mn.core.quarantine import fence, find_injection

PROMPT_NAME = "receipt_extract"
PURPOSE = "extract"
SCHEMA_NAME = "receipt_extraction"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
SUPPORTED_MIMES = ("image/jpeg", "image/png", "image/webp", "image/gif")

WARN_SELLER_NAME_MISSING = "seller_name_missing"
WARN_LINE_AMOUNT_MISSING = "line_amount_missing"
WARN_INJECTION_SUSPECTED = "injection_suspected"

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class ExtractOutcome:
	receipt: Receipt
	receipt_dict: dict[str, Any]
	extraction: ReceiptExtraction
	llm: LlmResult
	injection_suspected: bool
	injection_fragment: str | None
	warnings: tuple[str, ...] = ()


def _money(value: Decimal | None) -> Decimal | None:
	return None if value is None else Decimal(value).quantize(Decimal("0.01"))


def extraction_to_dict(extraction: ReceiptExtraction, *, prompt_version: str, model: str) -> dict[str, Any]:
	"""Everything the model said, as domain types: Decimal money, ``date`` object, plus the injection flag."""
	texts = [extraction.seller_name or "", extraction.notes or ""] + [
		line.description or "" for line in extraction.lines
	]
	fragment = next((f for f in (find_injection(t) for t in texts) if f), None)
	return {
		"seller_name": extraction.seller_name,
		"seller_register_no": extraction.seller_register_no,
		"seller_tin": extraction.seller_tin,
		"date": date.fromisoformat(extraction.date) if extraction.date else None,
		"total": _money(extraction.total),
		"vat_amount": _money(extraction.vat_amount),
		"lines": [
			{
				"description": line.description,
				"qty": None if line.qty is None else Decimal(line.qty),
				"amount": _money(line.amount),
			}
			for line in extraction.lines
		],
		"payment_method": extraction.payment_method,
		"receipt_id": extraction.receipt_id,
		"lottery_no": extraction.lottery_no,
		"confidence": extraction.confidence.model_dump(),
		"notes": extraction.notes,
		"injection_suspected": fragment is not None,
		"injection_fragment": fragment,
		"prompt_version": prompt_version,
		"model": model,
	}


def to_receipt(receipt_dict: dict[str, Any]) -> tuple[Receipt, tuple[str, ...]]:
	"""Build the frozen ``Receipt``; the warnings name every null the domain type cannot hold.

	``Receipt.seller_name`` and ``ReceiptLine.amount`` are required by ``core.models``;
	an unreadable value becomes ``""`` / ``0.00`` with a warning rather than dropping the
	line, so the accountant still sees the description and the ⚠️ marker.
	"""
	warnings: list[str] = []
	seller_name = receipt_dict.get("seller_name") or ""
	if not seller_name:
		warnings.append(WARN_SELLER_NAME_MISSING)
	lines: list[ReceiptLine] = []
	for raw in receipt_dict.get("lines") or []:
		amount = raw.get("amount")
		if amount is None:
			warnings.append(WARN_LINE_AMOUNT_MISSING)
			amount = ZERO
		lines.append(
			ReceiptLine(
				description=raw.get("description") or "",
				qty=None if raw.get("qty") is None else Decimal(raw["qty"]),
				amount=Decimal(amount),
			)
		)
	if receipt_dict.get("injection_suspected"):
		warnings.append(WARN_INJECTION_SUSPECTED)
	confidence = {str(k): float(v) for k, v in (receipt_dict.get("confidence") or {}).items()}
	receipt = Receipt(
		seller_name=str(seller_name),
		seller_tin=receipt_dict.get("seller_tin"),
		seller_register_no=receipt_dict.get("seller_register_no"),
		date=receipt_dict.get("date"),
		total=receipt_dict.get("total"),
		vat_amount=receipt_dict.get("vat_amount"),
		lines=tuple(lines),
		payment_method=receipt_dict.get("payment_method"),
		receipt_id=receipt_dict.get("receipt_id"),
		lottery_no=receipt_dict.get("lottery_no"),
		confidence=confidence,
		raw_text=receipt_dict.get("notes") or "",
	)
	return receipt, tuple(dict.fromkeys(warnings))


def build_user_parts(image_bytes: bytes, mime: str, *, company_context: str, now: datetime) -> list[Part]:
	"""The user message: trusted context, the fenced note about the image, timestamp last, then the image."""
	text, _version = prompts.load(PROMPT_NAME)
	_system, user_template = prompts.split(text)
	user_text = prompts.fill(
		user_template,
		COMPANY_CONTEXT=company_context.strip() or "(none)",
		UNTRUSTED=fence("[receipt photo attached as an image part]", label="receipt_image"),
		NOW=now.isoformat(timespec="minutes"),
	)
	return [TextPart(user_text), ImagePart(image_bytes, mime)]


def extract_receipt(
	client: LlmClient,
	image_bytes: bytes,
	mime: str,
	*,
	company_context: str,
	now: datetime,
) -> tuple[Receipt, LlmResult]:
	"""Contract entry point: ``(Receipt, LlmResult)``; ``extract_receipt_full`` adds the flags."""
	outcome = extract_receipt_full(client, image_bytes, mime, company_context=company_context, now=now)
	return outcome.receipt, outcome.llm


def extract_receipt_full(
	client: LlmClient,
	image_bytes: bytes,
	mime: str,
	*,
	company_context: str,
	now: datetime,
) -> ExtractOutcome:
	if mime not in SUPPORTED_MIMES:
		raise ValueError(f"unsupported image type {mime!r}; expected one of {SUPPORTED_MIMES}")
	if not image_bytes:
		raise ValueError("empty image")
	if len(image_bytes) > MAX_IMAGE_BYTES:
		raise ValueError(f"image larger than {MAX_IMAGE_BYTES} bytes")

	text, version = prompts.load(PROMPT_NAME)
	system, _user_template = prompts.split(text)
	prompt_version = prompts.version_tag(PROMPT_NAME, version)
	user = build_user_parts(image_bytes, mime, company_context=company_context, now=now)

	llm = client.structured(
		purpose=PURPOSE,
		system=system,
		user=user,
		schema=json_schema(ReceiptExtraction),
		schema_name=SCHEMA_NAME,
		temperature=0,
		prompt_version=prompt_version,
	)
	try:
		extraction = ReceiptExtraction.model_validate(llm.data or {})
	except ValidationError as exc:
		raise LlmSchemaError(f"receipt extraction failed validation: {exc.error_count()} error(s)") from exc

	receipt_dict = extraction_to_dict(extraction, prompt_version=prompt_version, model=llm.model)
	receipt, warnings = to_receipt(receipt_dict)
	return ExtractOutcome(
		receipt=receipt,
		receipt_dict=receipt_dict,
		extraction=extraction,
		llm=llm,
		injection_suspected=bool(receipt_dict["injection_suspected"]),
		injection_fragment=receipt_dict["injection_fragment"],
		warnings=warnings,
	)


__all__ = [
	"MAX_IMAGE_BYTES",
	"PROMPT_NAME",
	"PURPOSE",
	"SCHEMA_NAME",
	"SUPPORTED_MIMES",
	"WARN_INJECTION_SUSPECTED",
	"WARN_LINE_AMOUNT_MISSING",
	"WARN_SELLER_NAME_MISSING",
	"ExtractOutcome",
	"build_user_parts",
	"extract_receipt",
	"extract_receipt_full",
	"extraction_to_dict",
	"to_receipt",
]
