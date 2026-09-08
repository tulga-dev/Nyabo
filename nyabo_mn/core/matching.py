"""Bank line to voucher matching.

The matcher is deliberately conservative: a wrong automatic match is worse than an
unmatched line, because the accountant only reviews what the bot flags. So an exact
amount is required, the date window is three days, and two candidates that score the
same leave the line unmatched with an "ambiguous" reason instead of guessing.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from decimal import Decimal

from nyabo_mn.core.models import BankLine, MatchCandidate, MatchResult
from nyabo_mn.i18n import mn

AMOUNT_TOLERANCE = Decimal("1")
DATE_WINDOW_DAYS = 3
NAME_SIMILARITY_MIN = 0.8
DEFAULT_THRESHOLD = 0.8

# Score composition: an exact amount within the date window earns the base; the date and
# the party name add the rest. Base + full date score reaches the default threshold on
# its own, so a same-day exact amount matches even when the party name is unknown.
SCORE_BASE = 0.55
SCORE_DATE = 0.25
SCORE_NAME = 0.20

_LEGAL_FORMS = {
	"ххк",
	"хк",
	"тбб",
	"хзх",
	"аан",
	"llc",
	"ltd",
	"co",
	"inc",
	"jsc",
	"company",
	"компани",
}
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")

FEE_KEYWORDS: tuple[str, ...] = (
	"хураамж",
	"шимтгэл",
	"үйлчилгээний төлбөр",
	"үйлчилгээний хураамж",
	"comission",
	"commission",
	"service charge",
	"fee",
)


def normalize_name(text: str) -> str:
	"""Lowercase, drop legal-form tokens (ХХК, LLC...) and punctuation, collapse spaces."""
	lowered = (text or "").lower().replace("ё", "е")
	cleaned = _PUNCT.sub(" ", lowered)
	tokens = [t for t in _WS.split(cleaned) if t and t not in _LEGAL_FORMS]
	return " ".join(tokens)


def name_similarity(a: str, b: str) -> float:
	"""Token-set ratio in 0..1 (the fuzzywuzzy idea, on difflib): word order and extra words matter little."""
	ta = set(normalize_name(a).split())
	tb = set(normalize_name(b).split())
	if not ta or not tb:
		return 0.0
	common = " ".join(sorted(ta & tb))
	left = (common + " " + " ".join(sorted(ta - tb))).strip()
	right = (common + " " + " ".join(sorted(tb - ta))).strip()

	def ratio(x: str, y: str) -> float:
		return difflib.SequenceMatcher(None, x, y).ratio() if x and y else 0.0

	return max(ratio(common, left), ratio(common, right), ratio(left, right))


def amount_matches(a: Decimal, b: Decimal, tolerance: Decimal = AMOUNT_TOLERANCE) -> bool:
	return abs(abs(a) - abs(b)) <= tolerance


def date_score(days: int) -> float:
	"""1.0 at 0-1 days, 0.5 at 2, 0.0 at 3 or more."""
	if days <= 1:
		return 1.0
	if days >= DATE_WINDOW_DAYS:
		return 0.0
	return (DATE_WINDOW_DAYS - days) / (DATE_WINDOW_DAYS - 1)


def is_bank_fee(description: str) -> bool:
	text = (description or "").lower()
	return any(keyword in text for keyword in FEE_KEYWORDS)


def is_own_transfer(description: str, own_account_numbers: Iterable[str]) -> bool:
	"""True when one of the company's own account numbers appears in the narrative."""
	digits_in_text = _DIGITS.findall(description or "")
	if not digits_in_text:
		return False
	joined = "".join(digits_in_text)
	for number in own_account_numbers:
		clean = "".join(_DIGITS.findall(str(number)))
		if len(clean) >= 6 and clean in joined:
			return True
	return False


def score(line: BankLine, candidate: MatchCandidate) -> float:
	"""0.0 unless the amount is exact (within 1₮) and the date within 3 days; else base + date + name."""
	if not amount_matches(line.amount, candidate.amount):
		return 0.0
	days = abs((line.date - candidate.date).days)
	if days > DATE_WINDOW_DAYS:
		return 0.0
	total = SCORE_BASE + SCORE_DATE * date_score(days)
	name_bonus = 0.0
	similarity = name_similarity(line.description, candidate.party_name)
	if similarity >= NAME_SIMILARITY_MIN:
		name_bonus = SCORE_NAME * similarity
	reference = (candidate.reference or "").strip()
	if reference and (reference in (line.reference or "") or reference in (line.description or "")):
		name_bonus = max(name_bonus, SCORE_NAME)
	return round(min(1.0, total + name_bonus), 4)


def pick(
	line: BankLine,
	candidates: Sequence[MatchCandidate],
	threshold: float = DEFAULT_THRESHOLD,
) -> MatchResult:
	"""Best candidate at or above the threshold, else a fee line, else no match."""
	scored = sorted(((score(line, c), c) for c in candidates), key=lambda sc: sc[0], reverse=True)
	if scored and scored[0][0] >= threshold:
		best_score, best = scored[0]
		if len(scored) > 1 and scored[1][0] == best_score and scored[1][1].name != best.name:
			return MatchResult(line, None, best_score, "none", mn.MATCH_REASON_AMBIGUOUS)
		return MatchResult(line, best, best_score, "exact", _reason(line, best))
	if is_bank_fee(line.description):
		return MatchResult(line, None, 0.0, "fee", mn.MATCH_REASON_FEE)
	if scored and scored[0][0] > 0:
		return MatchResult(
			line,
			None,
			scored[0][0],
			"none",
			mn.MATCH_REASON_LOW_SCORE.format(score=int(scored[0][0] * 100), threshold=int(threshold * 100)),
		)
	return MatchResult(line, None, 0.0, "none", mn.MATCH_REASON_NONE)


def pair_transfers(
	lines: Sequence[BankLine],
	own_account_numbers: Iterable[str] = (),
) -> list[tuple[BankLine, BankLine]]:
	"""Equal-and-opposite lines on the same day, each used once.

	When own account numbers are given, both narratives must mention one of them, so a
	coincidental customer receipt equal to a supplier payment is not paired.
	"""
	numbers = [str(n) for n in own_account_numbers]
	used: set[int] = set()
	pairs: list[tuple[BankLine, BankLine]] = []
	ordered = sorted(range(len(lines)), key=lambda i: (lines[i].date, lines[i].row_index))
	for i in ordered:
		if i in used:
			continue
		a = lines[i]
		if a.amount == 0:
			continue
		if numbers and not is_own_transfer(a.description, numbers):
			continue
		for j in ordered:
			if j == i or j in used:
				continue
			b = lines[j]
			if b.date != a.date or b.amount != -a.amount:
				continue
			if numbers and not is_own_transfer(b.description, numbers):
				continue
			used.update((i, j))
			pairs.append((a, b) if a.amount < 0 else (b, a))
			break
	return pairs


def transfer_results(pairs: Iterable[tuple[BankLine, BankLine]]) -> list[MatchResult]:
	"""MatchResults of kind 'transfer' for both sides of every pair."""
	out: list[MatchResult] = []
	for a, b in pairs:
		out.append(MatchResult(a, None, 1.0, "transfer", mn.MATCH_REASON_TRANSFER))
		out.append(MatchResult(b, None, 1.0, "transfer", mn.MATCH_REASON_TRANSFER))
	return out


def _reason(line: BankLine, candidate: MatchCandidate) -> str:
	days = abs((line.date - candidate.date).days)
	parts = [mn.MATCH_REASON_EXACT.format(days=days)]
	similarity = name_similarity(line.description, candidate.party_name)
	if similarity >= NAME_SIMILARITY_MIN:
		parts.append(mn.MATCH_REASON_NAME.format(similarity=int(similarity * 100)))
	reference = (candidate.reference or "").strip()
	if reference and (reference in (line.reference or "") or reference in (line.description or "")):
		parts.append(mn.MATCH_REASON_REFERENCE)
	return "; ".join(parts)
