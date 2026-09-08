from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from nyabo_mn.agent.schemas import (
	REASON_MAX_CHARS,
	ClassificationResult,
	QuestionAnswer,
	ReceiptExtraction,
	json_schema,
)

UNSUPPORTED = {"minLength", "maxLength", "pattern", "format", "minimum", "maximum", "default"}


def _walk(node):
	if isinstance(node, dict):
		yield node
		for value in node.values():
			yield from _walk(value)
	elif isinstance(node, list):
		for item in node:
			yield from _walk(item)


def _good_receipt() -> dict:
	return {
		"seller_name": "Петровис ХХК",
		"seller_register_no": "2550385",
		"seller_tin": "37200019261",
		"date": "2026-09-05",
		"total": 85000,
		"vat_amount": 7727.27,
		"lines": [{"description": "АИ-92", "qty": 40.5, "amount": 85000}],
		"payment_method": "qpay",
		"receipt_id": "0001234567890123",
		"lottery_no": "AB12345678",
		"confidence": {"seller_name": 0.9, "date": 0.9, "total": 0.99, "vat_amount": 0.8, "lines": 0.7},
		"notes": None,
	}


@pytest.mark.parametrize("model", [ReceiptExtraction, ClassificationResult, QuestionAnswer])
def test_schema_is_openai_strict_compatible(model):
	schema = json_schema(model)
	for node in _walk(schema):
		if node.get("type") == "object" or "properties" in node:
			assert node.get("additionalProperties") is False, node
			assert sorted(node["required"]) == sorted(node["properties"].keys()), node
		assert not (set(node) & UNSUPPORTED), node


def test_receipt_schema_has_every_field_and_nullable_money():
	schema = json_schema(ReceiptExtraction)
	assert set(schema["properties"]) == set(_good_receipt())
	total = schema["properties"]["total"]
	assert {"type": "null"} in total["anyOf"] and {"type": "number"} in total["anyOf"]
	assert "pattern" not in str(schema)
	assert schema["properties"]["payment_method"]["enum"] == ["cash", "card", "transfer", "qpay", "unknown"]


def test_receipt_round_trip_uses_decimal():
	receipt = ReceiptExtraction.model_validate(_good_receipt())
	assert isinstance(receipt.total, Decimal) and receipt.total == Decimal("85000.00")
	assert receipt.vat_amount == Decimal("7727.27")
	assert isinstance(receipt.lines[0].qty, Decimal)


def test_receipt_rejects_extra_and_missing_fields():
	bad = _good_receipt()
	bad["extra"] = 1
	with pytest.raises(ValidationError):
		ReceiptExtraction.model_validate(bad)
	missing = _good_receipt()
	del missing["lottery_no"]
	with pytest.raises(ValidationError):
		ReceiptExtraction.model_validate(missing)


def test_receipt_bad_date_becomes_null_and_negative_money_rejected():
	data = _good_receipt()
	data["date"] = "05.09.2026"
	assert ReceiptExtraction.model_validate(data).date is None
	data = _good_receipt()
	data["total"] = -5
	with pytest.raises(ValidationError):
		ReceiptExtraction.model_validate(data)


def test_confidence_is_clamped():
	data = _good_receipt()
	data["confidence"]["total"] = 1.7
	data["confidence"]["date"] = -0.2
	receipt = ReceiptExtraction.model_validate(data)
	assert receipt.confidence.total == 1.0 and receipt.confidence.date == 0.0


def test_classification_reason_capped_and_enum_enforced():
	result = ClassificationResult.model_validate(
		{"account_code": "6210", "vat_treatment": "in_expense", "reason_mn": "а" * 300, "confidence": 2}
	)
	assert len(result.reason_mn) == REASON_MAX_CHARS and result.confidence == 1.0
	with pytest.raises(ValidationError):
		ClassificationResult.model_validate(
			{"account_code": "6210", "vat_treatment": "maybe", "reason_mn": "x", "confidence": 0.5}
		)


def test_question_answer_schema():
	schema = json_schema(QuestionAnswer)
	assert schema["required"] == ["answer_mn", "used_tool", "needs_escalation"]
	assert QuestionAnswer(answer_mn="Тийм", used_tool=None, needs_escalation=False).needs_escalation is False
