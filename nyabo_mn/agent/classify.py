"""Account classification of one receipt (docs/ARCHITECTURE.md §5.3 step 4).

The model chooses from the leaf accounts it is given; deterministic code then refuses
anything outside that list, forces the VAT treatment the regime allows, and replaces an
instruction-looking reason. Every override is reported in ``ClassifyOutcome.warnings``
so the card can show ⚠️ and the accountant sees what happened.

``ctx`` keys (all optional): ``company``, ``is_vat_payer`` (bool), ``regime`` (str),
``default_expense_code`` (str), ``seller_vat_payer`` (bool | None), ``now`` (datetime).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from nyabo_mn.agent import prompts
from nyabo_mn.agent.llm_client import LlmClient, LlmResult, LlmSchemaError, TextPart
from nyabo_mn.agent.schemas import ClassificationResult, json_schema
from nyabo_mn.core.quarantine import fence, looks_like_injection
from nyabo_mn.i18n import mn

PROMPT_NAME = "classify"
PURPOSE = "classify"
SCHEMA_NAME = "classification_result"
MAX_EXAMPLES = 20

WARN_CODE_NOT_IN_CHART = "code_not_in_chart"
WARN_VAT_FORCED_IN_EXPENSE = "vat_forced_in_expense"
WARN_REASON_REPLACED = "reason_replaced"


@dataclass(frozen=True)
class ClassifyOutcome:
	result: ClassificationResult
	llm: LlmResult
	warnings: tuple[str, ...]
	proposed_code: str


def _json_default(value: Any) -> Any:
	if isinstance(value, Decimal):
		return str(value)
	if isinstance(value, datetime):
		return value.isoformat()
	if hasattr(value, "isoformat"):
		return value.isoformat()
	return str(value)


def format_accounts(chart_leaves: Iterable[tuple[str, str]]) -> str:
	return "\n".join(f"{code} — {name}" for code, name in chart_leaves) or "(none)"


def format_examples(examples: Iterable[Mapping[str, Any]]) -> str:
	rows = [
		json.dumps(dict(e), ensure_ascii=False, default=_json_default) for e in list(examples)[:MAX_EXAMPLES]
	]
	return "\n".join(rows) or "(none)"


def format_context(ctx: Mapping[str, Any]) -> str:
	keys = ("company", "regime", "is_vat_payer", "default_expense_code", "seller_vat_payer")
	lines = [
		f"{k}: {json.dumps(ctx.get(k), ensure_ascii=False, default=_json_default)}" for k in keys if k in ctx
	]
	return "\n".join(lines) or "(none)"


def build_user_text(
	receipt_dict: Mapping[str, Any],
	chart_leaves: list[tuple[str, str]],
	examples: list[Mapping[str, Any]],
	ctx: Mapping[str, Any],
) -> str:
	text, _version = prompts.load(PROMPT_NAME)
	_system, user_template = prompts.split(text)
	now = ctx.get("now") or datetime.now(timezone.utc)
	receipt_json = json.dumps(dict(receipt_dict), ensure_ascii=False, default=_json_default, indent=1)
	return prompts.fill(
		user_template,
		COMPANY_CONTEXT=format_context(ctx),
		ACCOUNTS=format_accounts(chart_leaves),
		EXAMPLES=fence(format_examples(examples), label="examples"),
		UNTRUSTED=fence(receipt_json, label="receipt"),
		NOW=now.isoformat(timespec="minutes"),
	)


def enforce(
	result: ClassificationResult,
	chart_leaves: list[tuple[str, str]],
	ctx: Mapping[str, Any],
) -> tuple[ClassificationResult, tuple[str, ...]]:
	"""Deterministic guard: only listed codes, no withholding for non-VAT payers, sane reason."""
	warnings: list[str] = []
	codes = {code for code, _name in chart_leaves}
	if not codes:
		raise LlmSchemaError("classification needs at least one leaf account")
	updates: dict[str, Any] = {}

	if result.account_code not in codes:
		default = str(ctx.get("default_expense_code") or "")
		if default not in codes:
			raise LlmSchemaError(
				f"model proposed {result.account_code!r} which is not a leaf account and no default_expense_code is available"
			)
		updates["account_code"] = default
		updates["confidence"] = 0.0
		updates["reason_mn"] = mn.AGENT_REASON_CODE_NOT_IN_CHART
		warnings.append(WARN_CODE_NOT_IN_CHART)

	if ctx.get("is_vat_payer") is False and result.vat_treatment == "withheld":
		updates["vat_treatment"] = "in_expense"
		if "reason_mn" not in updates:
			updates["reason_mn"] = mn.AGENT_REASON_VAT_NOT_PAYER
		warnings.append(WARN_VAT_FORCED_IN_EXPENSE)

	reason = updates.get("reason_mn", result.reason_mn)
	if not reason.strip() or looks_like_injection(reason):
		updates["reason_mn"] = mn.AGENT_REASON_UNAVAILABLE
		warnings.append(WARN_REASON_REPLACED)

	if updates:
		result = result.model_copy(update=updates)
	return result, tuple(warnings)


def classify_full(
	client: LlmClient,
	receipt_dict: Mapping[str, Any],
	chart_leaves: list[tuple[str, str]],
	examples: list[Mapping[str, Any]],
	ctx: Mapping[str, Any],
) -> ClassifyOutcome:
	text, version = prompts.load(PROMPT_NAME)
	system, _user_template = prompts.split(text)
	prompt_version = prompts.version_tag(PROMPT_NAME, version)
	user_text = build_user_text(receipt_dict, chart_leaves, examples, ctx)

	llm = client.structured(
		purpose=PURPOSE,
		system=system,
		user=[TextPart(user_text)],
		schema=json_schema(ClassificationResult),
		schema_name=SCHEMA_NAME,
		temperature=0,
		prompt_version=prompt_version,
	)
	try:
		proposed = ClassificationResult.model_validate(llm.data or {})
	except ValidationError as exc:
		raise LlmSchemaError(f"classification failed validation: {exc.error_count()} error(s)") from exc

	result, warnings = enforce(proposed, chart_leaves, ctx)
	return ClassifyOutcome(result=result, llm=llm, warnings=warnings, proposed_code=proposed.account_code)


def classify(
	client: LlmClient,
	receipt_dict: Mapping[str, Any],
	chart_leaves: list[tuple[str, str]],
	examples: list[Mapping[str, Any]],
	ctx: Mapping[str, Any],
) -> ClassificationResult:
	"""Contract entry point: the guarded result only. ``classify_full`` adds warnings and usage."""
	return classify_full(client, receipt_dict, chart_leaves, examples, ctx).result


__all__ = [
	"MAX_EXAMPLES",
	"PROMPT_NAME",
	"PURPOSE",
	"SCHEMA_NAME",
	"WARN_CODE_NOT_IN_CHART",
	"WARN_REASON_REPLACED",
	"WARN_VAT_FORCED_IN_EXPENSE",
	"ClassifyOutcome",
	"build_user_text",
	"classify",
	"classify_full",
	"enforce",
	"format_accounts",
	"format_context",
	"format_examples",
]
