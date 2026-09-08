from __future__ import annotations

import datetime as dt
from decimal import Decimal

from nyabo_mn.core import matching as mt
from nyabo_mn.core.models import BankLine, MatchCandidate
from nyabo_mn.i18n import mn

D = dt.date(2026, 9, 2)


def _line(
	amount: str, description: str, date: dt.date = D, reference: str = "", row_index: int = 0
) -> BankLine:
	value = Decimal(amount)
	return BankLine(
		date=date,
		description=description,
		debit=-value if value < 0 else Decimal("0"),
		credit=value if value > 0 else Decimal("0"),
		amount=value,
		balance=None,
		reference=reference,
		currency="MNT",
		row_index=row_index,
		row_hash=f"h{row_index}",
	)


def _cand(name: str, amount: str, party: str, date: dt.date = D, reference: str = "") -> MatchCandidate:
	return MatchCandidate("Purchase Invoice", name, date, Decimal(amount), party, reference)


# --- names ---------------------------------------------------------------------------------------


def test_name_similarity_ignores_legal_form_case_and_order():
	assert mt.name_similarity("Петровис ХХК", "ПЕТРОВИС") == 1.0
	assert mt.name_similarity("Номин Супермаркет ХХК", "супермаркет номин") == 1.0
	assert mt.name_similarity("Nomin LLC", "NOMIN Co., Ltd") == 1.0
	assert mt.name_similarity("Петровис ХХК шатахуун төлбөр", "Петровис ХХК") >= 0.8
	assert mt.name_similarity("Петровис ХХК", "Номин ХХК") < 0.5
	assert mt.name_similarity("", "Номин") == 0.0
	assert mt.name_similarity("ХХК", "ХХК") == 0.0  # legal form alone carries no identity


def test_normalize_name():
	assert mt.normalize_name("Петровис ХХК, салбар №5") == "петровис салбар 5"
	assert mt.normalize_name("Ёлка LLC") == "елка"


# --- score ---------------------------------------------------------------------------------------


def test_score_exact_amount_same_day_with_name_matches():
	line = _line("-85000", "Петровис ХХК шатахуун")
	assert mt.score(line, _cand("PINV-1", "85000", "Петровис ХХК")) >= mt.DEFAULT_THRESHOLD


def test_score_requires_name_or_reference_on_top_of_amount_and_date():
	# ARCHITECTURE 5.4: amount + date + name; an unknown party goes to the accountant.
	line = _line("-85000", "QPay 5012345678 шилжүүлэг")
	anonymous = mt.score(line, _cand("PINV-1", "85000", ""))
	assert 0 < anonymous < mt.DEFAULT_THRESHOLD
	with_reference = mt.score(
		_line("-85000", "төлбөр INV-2026-15", reference="INV-2026-15"),
		_cand("PINV-1", "85000", "", reference="INV-2026-15"),
	)
	assert with_reference >= mt.DEFAULT_THRESHOLD


def test_score_ignores_a_reference_too_short_to_identify():
	# A handwritten supplier bill_no of "5" or a bill_no that is the year must not auto-match:
	# every narrative carries a date, an account number and an amount. CORE-10/§5.4 ask for a
	# name or a reference, and a wrong automatic match is worse than an unmatched line.
	line = _line("-85000", "QPay 5012345678 шилжүүлэг 2026.09.02")
	for short in ("5", "1", "12", "2026", "042"):
		assert mt.score(line, _cand("PINV-1", "85000", "", reference=short)) < mt.DEFAULT_THRESHOLD
		assert mt.pick(line, [_cand("PINV-1", "85000", "", reference=short)]).kind == "none"
	# A reference is only credited as a whole token, not inside a longer number or word.
	assert not mt.reference_matches("012345", _line("-85000", "QPay 5012345678 шилжүүлэг"))
	assert not mt.reference_matches("INV-2026", _line("-85000", "төлбөр INV-2026-15"))
	# Long enough and standing on its own: the reference still carries the match, and says so.
	digits = _line("-85000", "QPay 900123456 шилжүүлэг")
	assert mt.score(digits, _cand("PINV-1", "85000", "", reference="900123456")) >= mt.DEFAULT_THRESHOLD
	assert (
		mn.MATCH_REASON_REFERENCE
		in mt.pick(digits, [_cand("PINV-1", "85000", "", reference="900123456")]).reason
	)


def test_score_date_window():
	line = _line("-85000", "Петровис ХХК")
	same_day = mt.score(line, _cand("a", "85000", "Петровис ХХК", D))
	three_days = mt.score(line, _cand("b", "85000", "Петровис ХХК", D + dt.timedelta(days=3)))
	four_days = mt.score(line, _cand("c", "85000", "Петровис ХХК", D - dt.timedelta(days=4)))
	assert same_day > three_days >= mt.DEFAULT_THRESHOLD
	assert four_days == 0.0
	assert mt.date_score(0) == mt.date_score(1) == 1.0
	assert mt.date_score(2) == mt.date_score(3) == 0.5
	assert mt.date_score(4) == 0.0


def test_score_amount_must_be_exact_within_one_togrog():
	line = _line("-85000", "Петровис ХХК")
	assert mt.score(line, _cand("a", "85000.50", "Петровис ХХК")) >= mt.DEFAULT_THRESHOLD
	assert mt.score(line, _cand("b", "85002", "Петровис ХХК")) == 0.0
	assert (
		mt.score(line, _cand("c", "-85000", "Петровис ХХК")) >= mt.DEFAULT_THRESHOLD
	)  # sign convention of the candidate does not matter


# --- pick ----------------------------------------------------------------------------------------


def test_pick_best_candidate_with_reason():
	line = _line("-85000", "Петровис ХХК шатахуун")
	candidates = [
		_cand("PINV-1", "85000", "Петровис ХХК"),
		_cand("PINV-2", "85000", "Номин ХХК"),
		_cand("PINV-3", "12000", "Петровис ХХК"),
	]
	result = mt.pick(line, candidates)
	assert result.kind == "exact" and result.candidate is not None and result.candidate.name == "PINV-1"
	assert result.score >= 0.8
	assert mn.MATCH_REASON_EXACT.format(days=0) in result.reason
	assert "харилцагчийн нэр таарсан" in result.reason


def test_pick_false_match_guard_same_amount_other_party():
	# Same amount, same day, but the narrative names a different supplier: never auto-match.
	line = _line("-85000", "Номин ХХК төлбөр")
	result = mt.pick(line, [_cand("PINV-1", "85000", "Петровис ХХК")])
	assert result.kind == "none" and result.candidate is None
	assert result.reason == mn.MATCH_REASON_LOW_SCORE.format(score=70, threshold=80)


def test_pick_ambiguous_when_two_candidates_tie():
	line = _line("-85000", "Петровис ХХК")
	result = mt.pick(
		line, [_cand("PINV-1", "85000", "Петровис ХХК"), _cand("PINV-2", "85000", "Петровис ХХК")]
	)
	assert result.kind == "none" and result.candidate is None
	assert result.reason == mn.MATCH_REASON_AMBIGUOUS


def test_pick_fee_and_none():
	fee = mt.pick(_line("-1500", "Гүйлгээний шимтгэл"), [])
	assert fee.kind == "fee" and fee.reason == mn.MATCH_REASON_FEE
	nothing = mt.pick(_line("-1500", "Юу ч биш"), [])
	assert nothing.kind == "none" and nothing.reason == mn.MATCH_REASON_NONE
	# A fee line that exactly matches a voucher is a match, not a fee.
	matched = mt.pick(_line("-1500", "Хаан банк хураамж"), [_cand("JV-1", "1500", "Хаан банк")])
	assert matched.kind == "exact"


def test_pick_threshold_is_configurable():
	line = _line("-85000", "QPay шилжүүлэг")
	assert mt.pick(line, [_cand("PINV-1", "85000", "")]).kind == "none"
	assert mt.pick(line, [_cand("PINV-1", "85000", "")], threshold=0.6).kind == "exact"


# --- fees and transfers ------------------------------------------------------------------------------


def test_is_bank_fee_keywords():
	assert mt.is_bank_fee("Гүйлгээний хураамж")
	assert mt.is_bank_fee("Үйлчилгээний төлбөр 09 сар")
	assert mt.is_bank_fee("SMS service charge")
	assert mt.is_bank_fee("Шимтгэл")
	assert not mt.is_bank_fee("Петровис ХХК шатахуун")
	assert not mt.is_bank_fee("")


def test_is_own_transfer_matches_contiguous_digit_groups_only():
	own = ["5012345678", "MN12 0050 0123 4567 89"]
	assert mt.is_own_transfer("Шилжүүлэг 5012345678 руу", own)
	assert mt.is_own_transfer(
		"Transfer to 500501234567890", own
	)  # IBAN-like number, digits joined inside the string
	assert not mt.is_own_transfer("Шилжүүлэг 5099999999 руу", own)
	assert not mt.is_own_transfer(
		"2026.09.02 12345678", ["20260902"]
	)  # date + amount must not spell a number
	assert not mt.is_own_transfer("", own)
	assert not mt.is_own_transfer("данс 123", ["123"])  # too short to be an account number


def test_pair_transfers_equal_and_opposite_same_day():
	out = _line("-200000", "Шилжүүлэг 5012345678 руу", row_index=1)
	back = _line("200000", "Шилжүүлэг 5099999999-с", row_index=2)
	other_day = _line("200000", "Шилжүүлэг 5099999999-с", date=D + dt.timedelta(days=1), row_index=3)
	customer = _line("200000", "Номин ХХК төлбөр", row_index=4)
	pairs = mt.pair_transfers([customer, other_day, back, out])
	assert pairs == [(out, back)]  # outflow first; the earlier row wins, the customer receipt stays unpaired


def test_pair_transfers_with_own_numbers_excludes_customer_receipts():
	out = _line("-200000", "Шилжүүлэг 5012345678 руу", row_index=1)
	customer = _line("200000", "Номин ХХК төлбөр", row_index=2)
	assert mt.pair_transfers([out, customer], ["5012345678", "5099999999"]) == []
	back = _line("200000", "5099999999 данснаас", row_index=3)
	pairs = mt.pair_transfers([customer, back, out], ["5012345678", "5099999999"])
	assert pairs == [(out, back)]
	results = mt.transfer_results(pairs)
	assert [r.kind for r in results] == ["transfer", "transfer"]
	assert all(r.reason == mn.MATCH_REASON_TRANSFER and r.score == 1.0 for r in results)


def test_pair_transfers_uses_each_line_once():
	a = _line("-100", "x", row_index=1)
	b = _line("100", "y", row_index=2)
	c = _line("100", "z", row_index=3)
	pairs = mt.pair_transfers([a, b, c])
	assert pairs == [(a, b)]
