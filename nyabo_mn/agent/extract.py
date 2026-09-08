"""Vision extraction of one receipt photo (docs/ARCHITECTURE.md §5.3 step 2).

The model returns ``ReceiptExtraction`` (schema-validated, no tools); this module turns
it into the domain ``Receipt`` (``nyabo_mn.core.models``) with Decimal money and a real
``date``, and scans the free-text fields for instruction-looking content so the pipeline
can log ``injection_suspected`` and never act on it.

``core.models`` is owned by another agent and may not exist yet in this checkout. The
conversion targets the dict shape below (docs/ARCHITECTURE.md §3 lists the dataclass
names only); ``to_receipt`` uses ``Receipt.from_dict`` when present, else ``Receipt(**d)``
when the field names match, else returns the dict itself so callers can proceed.

Receipt dict shape::

    {
      "seller_name": str | None, "seller_register_no": str | None, "seller_tin": str | None,
      "date": datetime.date | None, "total": Decimal | None, "vat_amount": Decimal | None,
      "lines": [{"description": str | None, "qty": Decimal | None, "amount": Decimal | None}],
      "payment_method": "cash|card|transfer|qpay|unknown",
      "receipt_id": str | None, "lottery_no": str | None,
      "confidence": {"seller_name": float, "date": float, "total": float, "vat_amount": float, "lines": float},
      "notes": str | None, "injection_suspected": bool, "prompt_version": str, "model": str,
    }
"""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from nyabo_mn.agent import prompts
from nyabo_mn.agent.llm_client import ImagePart, LlmClient, LlmResult, LlmSchemaError, TextPart
from nyabo_mn.agent.schemas import ReceiptExtraction, json_schema
from nyabo_mn.core.quarantine import fence, find_injection

PROMPT_NAME = "receipt_extract"
PURPOSE = "extract"
SCHEMA_NAME = "receipt_extraction"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
SUPPORTED_MIMES = ("image/jpeg", "image/png", "image/webp", "image/gif")


@dataclass(frozen=True)
class ExtractOutcome:
	receipt: Any
	receipt_dict: dict[str, Any]
	extraction: ReceiptExtraction
	llm: LlmResult
	injection_suspected: bool
	injection_fragment: str | None


def _money(value: Decimal | None) -> Decimal | None:
	return None if value is None else Decimal(value).quantize(Decimal("0.01"))


def extraction_to_dict(extraction: ReceiptExtraction, *, prompt_version: str, model: str) -> dict[str, Any]:
	"""Domain dict: Decimal money, ``date`` object, plus the injection flag."""
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


def to_receipt(receipt_dict: dict[str, Any]) -> Any:
	"""Build ``core.models.Receipt`` if that module exists; otherwise return the dict."""
	try:
		from nyabo_mn.core import models  # type: ignore[attr-defined]
	except ImportError:
		return receipt_dict
	receipt_cls = getattr(models, "Receipt", None)
	if receipt_cls is None:
		return receipt_dict
	from_dict = getattr(receipt_cls, "from_dict", None)
	if callable(from_dict):
		return from_dict(receipt_dict)
	if is_dataclass(receipt_cls):
		names = {f.name for f in dataclass_fields(receipt_cls)}
		if {"seller_name", "total", "lines"} <= names:
			return receipt_cls(**{k: v for k, v in receipt_dict.items() if k in names})
	return receipt_dict


def build_user_parts(image_bytes: bytes, mime: str, *, company_context: str, now: datetime) -> list:
	"""The user message: trusted context, the fenced note about the image, timestamp last, then the image."""
	text, version = prompts.load(PROMPT_NAME)
	_system, user_template = prompts.split(text)
	user_text = prompts.fill(
		user_template,
		COMPANY_CONTEXT=company_context.strip() or "(none)",
		UNTRUSTED=fence("[receipt photo attached as an image part]", label="receipt_image"),
		NOW=now.isoformat(timespec="minutes"),
	)
	del version
	return [TextPart(user_text), ImagePart(image_bytes, mime)]


def extract_receipt(
	client: LlmClient,
	image_bytes: bytes,
	mime: str,
	*,
	company_context: str,
	now: datetime,
) -> tuple[Any, LlmResult]:
	"""Run the vision call and return ``(Receipt, LlmResult)``; see ``extract_receipt_full`` for the flags."""
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
	return ExtractOutcome(
		receipt=to_receipt(receipt_dict),
		receipt_dict=receipt_dict,
		extraction=extraction,
		llm=llm,
		injection_suspected=bool(receipt_dict["injection_suspected"]),
		injection_fragment=receipt_dict["injection_fragment"],
	)


__all__ = [
	"MAX_IMAGE_BYTES",
	"PROMPT_NAME",
	"PURPOSE",
	"SCHEMA_NAME",
	"SUPPORTED_MIMES",
	"ExtractOutcome",
	"build_user_parts",
	"extract_receipt",
	"extract_receipt_full",
	"extraction_to_dict",
	"to_receipt",
]
