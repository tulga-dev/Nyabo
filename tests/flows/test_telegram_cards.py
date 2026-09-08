"""Cards, keyboards and callback data: pure renderers pinned by snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import api, cards, keyboards

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "telegram" / "receipt_card.txt"

SAMPLE = {
	"name": "NYP-00001",
	"supplier_name": "Петровис ХХК",
	"posting_date": "2026-08-14",
	"total": "85000",
	"vat_amount": "7727.27",
	"vat_treatment": "in_expense",
	"account_code": "6210",
	"account_name": "Шатахуун",
	"explanation": "Шатахуун авсан тул 6210 дебетлэж, касс кредитлэв.",
	"citation": "purchase_expense_non_vat · Заавар 116, 3.2",
	"extracted_json": {"seller_name": "Петровис ХХК", "vat_rate": 0.1},
	"verification_json": {"seller": {"found": True}, "receipt": {"status": "unsupported"}},
	"warnings_json": [mn.WARN_LOW_CONFIDENCE.format(field=mn.FIELD_LABELS["date"], confidence=62)],
	"supplier_is_new": 1,
}


def test_receipt_card_matches_snapshot():
	text = cards.receipt_card(SAMPLE)
	expected = FIXTURE.read_text(encoding="utf-8").rstrip("\n")
	assert text == expected


def test_receipt_card_anatomy():
	lines = cards.receipt_card(SAMPLE).split("\n")
	assert lines[0] == "🧾 Петровис ХХК · 2026-08-14 (Ба)"
	assert lines[1].startswith("💵 85 000₮ · НӨАТ 7 727.27₮ (10%, зардалд орно) · ")
	assert mn.VERIFICATION_SELLER_OK in lines[1] and "ebarimt ✓" not in lines[1]
	assert lines[2] == "📒 6210 Шатахуун · санал"
	assert lines[3] == "«Шатахуун авсан тул 6210 дебетлэж, касс кредитлэв.»"
	assert lines[4] == "⚠️ огноо тодорхойгүй (62%)"
	assert lines[5] == "⚠️ " + mn.WARN_NEW_SUPPLIER
	assert lines[6] == "📜 purchase_expense_non_vat · Заавар 116, 3.2"


def test_receipt_card_without_vat_and_with_rule():
	data = dict(
		SAMPLE,
		vat_amount="0",
		vat_treatment="none",
		rule_applied="NYR-00007",
		warnings_json=[],
		supplier_is_new=0,
	)
	text = cards.receipt_card(data)
	assert "НӨАТ-гүй" in text
	assert mn.CARD_REASON_RULE.format(rule="NYR-00007") in text
	assert "⚠️" not in text


def test_receipt_card_accepts_json_strings_and_erpnext_account_names():
	data = dict(SAMPLE, extracted_json='{"seller_name": "X"}', verification_json="{}", warnings_json="[]")
	data.pop("account_name")
	data["account"] = "6210 - Шатахуун - TST"
	text = cards.receipt_card(data)
	assert "📒 6210 Шатахуун" in text
	assert mn.VERIFICATION_SELLER_NOT_FOUND in text


def test_posted_and_rejected_footers():
	assert cards.posted_card(SAMPLE, "ACC-JV-2026-00001", "Сараа").endswith(
		mn.MSG_POSTED_CARD_FOOTER.format(doc_name="ACC-JV-2026-00001", approver="Сараа")
	)
	assert cards.rejected_card(SAMPLE, mn.REJECT_PERSONAL).endswith(
		mn.MSG_REJECTED_CARD_FOOTER.format(reason=mn.REJECT_PERSONAL)
	)


def test_bank_line_card():
	text = cards.bank_line_card(
		{
			"bank": "Khan Bank",
			"date": "2026-08-03",
			"deposit": 0,
			"withdrawal": 120000,
			"description": "Түлш",
		},
		{"account_code": "6210", "account_name": "Шатахуун", "rule_applied": "bank_fee"},
	)
	assert text.split("\n")[0] == "🏦 Khan Bank · 2026-08-03 · -120 000₮ · «Түлш»"
	assert "📒 Санал: 6210 Шатахуун · дүрэм: bank_fee" in text


def test_close_card_december_adds_inventory_line():
	text = cards.close_card(
		"Тест ХХК",
		"2026-12",
		{
			"open_proposals": 1,
			"unmatched_bank_lines": 2,
			"unverified_documents": 0,
			"pending_suppliers": 0,
			"unverified_rules_used": 0,
		},
		{
			"trial_balance": {"debit": 1000, "credit": 1000},
			"simplified": {"revenue": 500, "tax": 5, "quarter": "2026 оны 4-р улирал"},
		},
	)
	assert mn.MSG_CLOSE_INVENTORY_COUNT in text
	assert "Гүйлгээ баланс: дебет 1 000₮ · кредит 1 000₮" in text
	assert "1% татвар 5₮" in text
	assert mn.PERIOD_LABEL.format(year=2026, month=mn.MONTHS[11]) in text


def test_onboarding_summary():
	text = cards.onboarding_summary(
		{
			"vat_registered": False,
			"banks": [{"bank": "Khan Bank", "currencies": ["MNT", "USD"]}],
			"has_inventory": True,
			"inventory_count": 3,
			"accountant_name": "Сараа",
			"micpa": "A-12",
		},
		"Тест ХХК",
	)
	assert mn.ONB_SUMMARY_REGIME_SIMPLIFIED in text
	assert "Khan Bank (MNT/USD)" in text
	assert "3 бараа" in text and "Сараа (A-12)" in text


# --- keyboards ---------------------------------------------------------------------------------------


def test_callback_data_is_at_most_64_bytes_everywhere():
	markups = [
		keyboards.receipt_keyboard("NYP-00001"),
		keyboards.account_chooser("p", "NYP-00001", [("6210", "Шатахуун"), ("6910", "Бусад")]),
		keyboards.reject_reasons("NYP-00001"),
		keyboards.correction_reasons("ACC-JV-2026-00001"),
		keyboards.posted_keyboard("Purchase Invoice", "ACC-PINV-2026-00001"),
		keyboards.bank_line_keyboard("ACC-BTN-2026-00001"),
		keyboards.bank_candidates("ACC-BTN-2026-00001", 9),
		keyboards.close_confirm("2026-08"),
		keyboards.onboarding_banks(["Khan Bank"]),
		keyboards.onboarding_currencies(["MNT"]),
		keyboards.intake_confirm("NYI-00001"),
		keyboards.layout_column_roles(7),
		keyboards.company_chooser(["Тест ХХК", "Хоёр дахь компани ХХК"]),
	]
	for markup in markups:
		for row in markup["inline_keyboard"]:
			assert 1 <= len(row) <= keyboards.MAX_PER_ROW
			for button in row:
				assert len(button["callback_data"].encode("utf-8")) <= api.MAX_CALLBACK_DATA_BYTES
				assert button["text"]


def test_encode_refuses_long_data_and_separator():
	with pytest.raises(keyboards.CallbackDataTooLong):
		keyboards.encode("p", "N" * 70, "ap")
	with pytest.raises(ValueError):
		keyboards.encode("p", "a:b", "ap")
	assert keyboards.decode(keyboards.encode("p", "NYP-00001", "acc", "6210")) == [
		"p",
		"NYP-00001",
		"acc",
		"6210",
	]


def test_primary_button_alone_on_top():
	markup = keyboards.receipt_keyboard("NYP-00001")
	assert [b["text"] for b in markup["inline_keyboard"][0]] == [mn.BTN_APPROVE]
	assert [b["text"] for b in markup["inline_keyboard"][1]] == [mn.BTN_CHANGE_ACCOUNT, mn.BTN_REJECT]
	assert markup["inline_keyboard"][0][0]["callback_data"] == "p:NYP-00001:ap"


def test_every_mn_string_referenced_by_the_telegram_layer_exists():
	"""ARCHITECTURE §8.1: a typo in an ``mn.X`` name must fail here, not in a user's chat."""
	import re

	root = Path(__file__).resolve().parent.parent.parent / "nyabo_mn" / "telegram"
	pattern = re.compile(r"\bmn\.([A-Z][A-Z0-9_]+)")
	missing = set()
	for path in root.rglob("*.py"):
		for name in pattern.findall(path.read_text(encoding="utf-8")):
			if not hasattr(mn, name):
				missing.add(f"{path.name}: mn.{name}")
	assert not missing, sorted(missing)


def test_chunk_text_splits_on_newlines():
	text = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
	chunks = api.chunk_text(text)
	assert len(chunks) > 1
	assert all(len(c) <= api.MAX_TEXT_CHARS for c in chunks)
	assert "\n".join(chunks) == text


def test_verification_text_reads_the_shape_the_pipeline_writes():
	"""agent/pipeline.py stores {"seller": ..., "receipt": ...}; a flat row must still render."""
	nested_found = {
		"seller": {"name": "Петровис ХХК", "tin": "37200019261", "vat_payer": True, "found": True},
		"receipt": {"status": "unsupported"},
		"qr_data": None,
	}
	nested_missing = {"seller": {"found": False}, "receipt": {"status": "unsupported"}}
	assert mn.VERIFICATION_SELLER_OK in cards.verification_text(nested_found)
	assert mn.VERIFICATION_SELLER_NOT_FOUND in cards.verification_text(nested_missing)
	assert cards.verification_text(nested_found) != cards.verification_text(nested_missing)
	# a registered non-VAT payer is still found
	assert mn.VERIFICATION_SELLER_OK in cards.verification_text(
		{"seller": {"found": True, "vat_payer": False}, "receipt": {"status": "unsupported"}}
	)
	# a verified receipt drops the "unchecked" half
	assert cards.verification_text({"seller": {"found": True}, "receipt": {"status": "verified"}}) == (
		mn.VERIFICATION_SELLER_OK
	)
	# older flat rows keep rendering
	assert mn.VERIFICATION_SELLER_OK in cards.verification_text({"seller_found": True})
	assert cards.verification_text(None) == (
		f"{mn.VERIFICATION_SELLER_NOT_FOUND} · {mn.VERIFICATION_RECEIPT_UNCHECKED}"
	)
