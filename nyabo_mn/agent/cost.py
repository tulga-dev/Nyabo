"""Cost estimate per call, USD, from a price table the founder has not yet confirmed.

The numbers were read from the vendors' public model pages on 2026-09-08
(https://developers.openai.com/api/docs/models: gpt-6-astra $10/$50, gpt-5.6-sol $4/$20,
gpt-5.6-terra $2/$12, gpt-5.6-luna $0.20/$1.20 per 1M input/output tokens;
https://platform.claude.com/docs/en/docs/about-claude/models/overview: claude-fable-5-1
$10/$50, claude-opus-5 $5/$25, claude-sonnet-5 $2/$10, claude-haiku-4-5 $1/$5). They stay
``verified: false`` with ``checked_on: null`` until the founder confirms them against the
billing page, because the estimate goes into ``Nyabo LLM Call.cost_usd`` and a wrong
price there misleads the quality report. Cached-input and batch discounts are ignored
(conservative: the estimate is an upper bound).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from nyabo_mn.agent.llm_client import LlmResult

ONE_MILLION = Decimal(1_000_000)
USD_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class Price:
	input_per_1m: Decimal
	output_per_1m: Decimal
	verified: bool = False
	checked_on: str | None = None


PRICE_TABLE: dict[str, dict[str, Any]] = {
	"gpt-6-astra": {"input_per_1m": "10.00", "output_per_1m": "50.00", "verified": False, "checked_on": None},
	"gpt-5.6-sol": {"input_per_1m": "4.00", "output_per_1m": "20.00", "verified": False, "checked_on": None},
	"gpt-5.6-terra": {
		"input_per_1m": "2.00",
		"output_per_1m": "12.00",
		"verified": False,
		"checked_on": None,
	},
	"gpt-5.6-luna": {"input_per_1m": "0.20", "output_per_1m": "1.20", "verified": False, "checked_on": None},
	"claude-fable-5-1": {
		"input_per_1m": "10.00",
		"output_per_1m": "50.00",
		"verified": False,
		"checked_on": None,
	},
	"claude-opus-5": {
		"input_per_1m": "5.00",
		"output_per_1m": "25.00",
		"verified": False,
		"checked_on": None,
	},
	"claude-sonnet-5": {
		"input_per_1m": "2.00",
		"output_per_1m": "10.00",
		"verified": False,
		"checked_on": None,
	},
	"claude-haiku-4-5": {
		"input_per_1m": "1.00",
		"output_per_1m": "5.00",
		"verified": False,
		"checked_on": None,
	},
	"mock-model": {"input_per_1m": "0", "output_per_1m": "0", "verified": True, "checked_on": "2026-09-08"},
}


def price_for(model: str) -> Price | None:
	"""Exact id first, then the longest table key the id starts with (dated snapshots)."""
	row = PRICE_TABLE.get(model)
	if row is None:
		candidates = [k for k in PRICE_TABLE if model.startswith(k)]
		if not candidates:
			return None
		row = PRICE_TABLE[max(candidates, key=len)]
	return Price(
		input_per_1m=Decimal(str(row["input_per_1m"])),
		output_per_1m=Decimal(str(row["output_per_1m"])),
		verified=bool(row.get("verified", False)),
		checked_on=row.get("checked_on"),
	)


def estimate_tokens(model: str, tokens_in: int, tokens_out: int) -> Decimal:
	"""USD for the given token counts; ``0`` when the model is not in the table."""
	price = price_for(model)
	if price is None:
		return Decimal("0").quantize(USD_PLACES)
	cost = (Decimal(tokens_in) * price.input_per_1m + Decimal(tokens_out) * price.output_per_1m) / ONE_MILLION
	return cost.quantize(USD_PLACES, rounding=ROUND_HALF_UP)


def estimate(result: LlmResult) -> Decimal:
	return estimate_tokens(result.model, result.tokens_in, result.tokens_out)


__all__ = ["PRICE_TABLE", "Price", "estimate", "estimate_tokens", "price_for"]
