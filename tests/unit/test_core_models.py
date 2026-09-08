from __future__ import annotations

import dataclasses
import datetime as dt
import json
from decimal import Decimal

import pytest

from nyabo_mn.core import models as m


def _receipt() -> m.Receipt:
	return m.Receipt(
		seller_name="Петровис ХХК",
		seller_tin="37200019261",
		seller_register_no="2550385",
		date=dt.date(2026, 9, 5),
		total=Decimal("85000.00"),
		vat_amount=Decimal("7727.27"),
		lines=(m.ReceiptLine("АИ-92 бензин", Decimal("40.5"), Decimal("85000.00")),),
		payment_method="QPay",
		receipt_id="00012345678901234567890123",
		lottery_no="AB12345678",
		confidence={"total": 0.98, "date": 0.9, "vat_amount": 0.7},
		raw_text="Петровис ХХК\nТөлөх дүн: 85 000",
	)


def _entry() -> m.ProposedEntry:
	return m.ProposedEntry(
		company="Тест ХХК",
		posting_date=dt.date(2026, 9, 5),
		lines=(
			m.ProposedLine("6210", Decimal("77272.73"), Decimal("0.00"), "Шатахуун"),
			m.ProposedLine("1810", Decimal("7727.27"), Decimal("0.00"), "НӨАТ"),
			m.ProposedLine("2110", Decimal("0.00"), Decimal("85000.00"), party_type="Supplier", party="Петровис ХХК"),
		),
		pattern_id="purchase_expense_vat_payer",
		citation=m.Citation("Заавар 116 (2000)", None, False, url="https://legalinfo.mn/mn/detail?lawId=205201"),
		explanation="Шатахуун авсан тул 6210 дебетлэв.",
		document_kind="purchase_invoice",
		vat_treatment="withheld",
		warnings=("Дүрэм баталгаажаагүй",),
		total=Decimal("85000.00"),
		vat_amount=Decimal("7727.27"),
		supplier="Петровис ХХК",
	)


def _round_trip(obj: m.Model) -> m.Model:
	"""to_dict -> json text -> from_dict, the same path a Nyabo Proposal JSON field takes."""
	text = json.dumps(obj.to_dict(), ensure_ascii=False)
	return type(obj).from_dict(json.loads(text))


def test_receipt_round_trip_keeps_decimals_and_dates():
	receipt = _receipt()
	data = receipt.to_dict()
	assert data["total"] == "85000.00"  # str, never float
	assert data["date"] == "2026-09-05"
	assert data["lines"][0]["qty"] == "40.5"
	back = _round_trip(receipt)
	assert back == receipt
	assert isinstance(back.total, Decimal)
	assert isinstance(back.date, dt.date)
	assert isinstance(back.lines, tuple)
	assert back.confidence_of("total") == 0.98
	assert back.confidence_of("missing") == 0.0


def test_receipt_optional_fields_none_survive():
	receipt = m.Receipt("Дэлгүүр", None, None, None, None, None)
	back = _round_trip(receipt)
	assert back == receipt
	assert back.date is None and back.total is None and back.lines == ()


def test_seller_info_and_verification_round_trip():
	seller = m.SellerInfo("Петровис ХХК", "37200019261", "2550385", True, True, "registry")
	assert _round_trip(seller) == seller
	checked = dt.datetime(2026, 9, 5, 14, 32, 10)
	verification = m.ReceiptVerification("unsupported", "Баримт шалгагдаагүй", checked)
	back = _round_trip(verification)
	assert back == verification
	assert isinstance(back.checked_at, dt.datetime)


def test_classification_and_citation_round_trip():
	classification = m.Classification("6210", "withheld", "Шатахуун", 0.91, "model", rule_name=None)
	assert _round_trip(classification) == classification
	citation = m.Citation("Заавар 116 (2000)", "3.4", True, "https://legalinfo.mn", "иш")
	assert _round_trip(citation) == citation


def test_proposed_entry_round_trip_and_totals():
	entry = _entry()
	back = _round_trip(entry)
	assert back == entry
	assert back.total_debit == Decimal("85000.00")
	assert back.total_credit == Decimal("85000.00")
	assert back.lines[2].party == "Петровис ХХК"
	assert isinstance(back.citation, m.Citation)
	assert back.warnings == ("Дүрэм баталгаажаагүй",)


def test_regime_enum_and_context_round_trip():
	assert m.Regime("vat_payer") is m.Regime.VAT_PAYER
	assert m.Regime("simplified_1pct") is m.Regime.SIMPLIFIED_1PCT
	assert {r.value for r in m.Regime} == {"vat_payer", "simplified_1pct"}
	ctx = m.RegimeContext(m.Regime.SIMPLIFIED_1PCT, False, False, "simplified_quarterly", dt.date(2027, 1, 1))
	data = ctx.to_dict()
	assert data["regime"] == "simplified_1pct"
	back = _round_trip(ctx)
	assert back == ctx
	assert back.regime is m.Regime.SIMPLIFIED_1PCT


def test_bank_line_and_match_result_round_trip():
	line = m.BankLine(
		date=dt.date(2026, 9, 1),
		description="Петровис ХХК төлбөр",
		debit=Decimal("85000.00"),
		credit=Decimal("0.00"),
		amount=Decimal("-85000.00"),
		balance=Decimal("1000000.00"),
		reference="TX123",
		currency="MNT",
		row_index=7,
		row_hash="abc",
	)
	candidate = m.MatchCandidate("Purchase Invoice", "ACC-PINV-0001", dt.date(2026, 9, 1), Decimal("-85000.00"), "Петровис ХХК")
	result = m.MatchResult(line, candidate, 0.94, "exact", "дүн таарч")
	back = _round_trip(result)
	assert back == result
	assert isinstance(back.line, m.BankLine)
	assert isinstance(back.candidate, m.MatchCandidate)
	none_result = m.MatchResult(line, None, 0.0, "none", "олдсонгүй")
	assert _round_trip(none_result) == none_result


def test_models_are_frozen():
	receipt = _receipt()
	with pytest.raises(dataclasses.FrozenInstanceError):
		receipt.total = Decimal("1")  # type: ignore[misc]
	with pytest.raises(dataclasses.FrozenInstanceError):
		_entry().lines = ()  # type: ignore[misc]


def test_from_dict_ignores_unknown_keys_and_coerces_types():
	data = {"account_code": "6210", "debit": 100, "credit": "0", "description": "x", "extra": "ignored"}
	line = m.ProposedLine.from_dict(data)
	assert line.debit == Decimal("100") and isinstance(line.credit, Decimal)
	assert line.party is None
