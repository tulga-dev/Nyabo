from __future__ import annotations

from decimal import Decimal

from nyabo_mn.agent import cost
from nyabo_mn.agent.llm_client import DEFAULT_ANTHROPIC_MODEL, DEFAULT_OPENAI_MODEL, LlmResult


def _result(model: str, tokens_in: int, tokens_out: int) -> LlmResult:
	return LlmResult(
		data=None,
		text=None,
		tokens_in=tokens_in,
		tokens_out=tokens_out,
		latency_ms=1,
		model=model,
		provider="x",
	)


def test_defaults_are_priced_but_unverified():
	for model in (DEFAULT_OPENAI_MODEL, DEFAULT_ANTHROPIC_MODEL):
		row = cost.PRICE_TABLE[model]
		assert row["verified"] is False and row["checked_on"] is None
		assert cost.price_for(model) is not None


def test_estimate_is_decimal_usd():
	value = cost.estimate(_result("gpt-5.6-terra", 1_000_000, 100_000))
	assert isinstance(value, Decimal) and value == Decimal("3.200000")  # 2.00 + 0.1 * 12.00
	assert cost.estimate(_result("claude-sonnet-5", 500, 100)) == Decimal("0.002000")
	assert cost.estimate(_result("mock-model", 10_000, 10_000)) == Decimal("0")


def test_unknown_model_costs_zero_and_snapshots_match_prefix():
	assert cost.estimate(_result("gpt-99-unknown", 1000, 1000)) == Decimal("0")
	assert cost.price_for("claude-sonnet-5-20270101") == cost.price_for("claude-sonnet-5")


def test_rounding_to_micro_dollars():
	assert cost.estimate_tokens("gpt-5.6-luna", 1, 1) == Decimal("0.000001")
	assert cost.estimate_tokens("gpt-5.6-luna", 0, 0) == Decimal("0.000000")
