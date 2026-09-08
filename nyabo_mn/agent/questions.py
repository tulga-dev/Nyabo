"""Question answering with read-only tools (docs/ARCHITECTURE.md §5.7).

The model writes the sentence; every number comes from an injected handler. Handlers are
plain callables ``(args: dict) -> dict`` supplied by the Frappe side, so this module has
no frappe import and the simulator can plug in fakes. The final ``QuestionAnswer`` is
built by code from the tool trace, not by the model, so ``needs_escalation`` can never be
claimed without ``escalate_to_admin`` having actually been called.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, ValidationError

from nyabo_mn.agent import prompts
from nyabo_mn.agent.llm_client import LlmClient, LlmResult, TextPart, ToolSpec
from nyabo_mn.agent.schemas import QuestionAnswer, StrictModel, json_schema
from nyabo_mn.core.quarantine import fence, find_injection
from nyabo_mn.i18n import mn

PROMPT_NAME = "question"
PURPOSE = "question"
MAX_TURNS = 4
MAX_QUESTION_CHARS = 2000
# Errors the dispatcher itself produces (the model asked for something impossible). They
# mean "no answer", not "the ledger is broken", so the user gets a different sentence.
MODEL_FAULT_ERRORS = frozenset({"invalid_arguments", "unknown_tool"})

Handler = Callable[[dict[str, Any]], dict[str, Any]]

QueryKind = Literal["balance_on_date", "spend_by_account", "last_entries_for_supplier", "unmatched_count"]


class BooksArgs(StrictModel):
	account_code: str | None = Field(description="Account code, e.g. 6210; null when not needed")
	on_date: str | None = Field(description="ISO date YYYY-MM-DD; null for today")
	supplier: str | None = Field(description="Supplier name as the user wrote it; null when not needed")
	period: str | None = Field(description="Month as YYYY-MM; null for the current month")


class AnswerFromBooksArgs(StrictModel):
	query_kind: QueryKind = Field(description="Which ledger question to run")
	args: BooksArgs


class AnswerFaqArgs(StrictModel):
	question: str = Field(description="The question to look up in the FAQ, rephrased briefly")


class EscalateArgs(StrictModel):
	summary: str = Field(description="One-sentence summary of what the user needs, in Mongolian")


TOOL_ARG_MODELS: dict[str, type[StrictModel]] = {
	"answer_from_books": AnswerFromBooksArgs,
	"answer_faq": AnswerFaqArgs,
	"escalate_to_admin": EscalateArgs,
}

TOOL_SPECS: list[ToolSpec] = [
	ToolSpec(
		name="answer_from_books",
		description=(
			"Read-only ledger lookup: balance_on_date (account_code, on_date), spend_by_account "
			"(account_code, period), last_entries_for_supplier (supplier), unmatched_count (no args). "
			"Returns figures in MNT formatted by the system."
		),
		parameters=json_schema(AnswerFromBooksArgs),
	),
	ToolSpec(
		name="answer_faq",
		description="Look up how Nyabo works or a bookkeeping basic in the product FAQ. Returns a short text.",
		parameters=json_schema(AnswerFaqArgs),
	),
	ToolSpec(
		name="escalate_to_admin",
		description="Hand the question to a human admin when it needs an action or cannot be answered from the books.",
		parameters=json_schema(EscalateArgs),
	),
]
TOOL_NAMES = tuple(spec.name for spec in TOOL_SPECS)


@dataclass(frozen=True)
class AnswerOutcome:
	answer: QuestionAnswer
	llm: LlmResult | None
	injection_suspected: bool
	injection_fragment: str | None
	tools_used: tuple[str, ...]


def make_dispatcher(handlers: Mapping[str, Handler]) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
	"""Validate arguments against the tool schema before the handler sees them.

	A handler only ever receives a dict that passed its pydantic model, so a Frappe-side
	implementation can index ``args["account_code"]`` without defensive code.
	"""

	def dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
		model = TOOL_ARG_MODELS.get(name)
		handler = handlers.get(name)
		if model is None or handler is None:
			return {"error": "unknown_tool"}
		try:
			parsed = model.model_validate(args)
		except ValidationError as exc:
			return {"error": "invalid_arguments", "detail": [e.get("msg") for e in exc.errors()][:5]}
		result = handler(parsed.model_dump())
		return dict(result) if isinstance(result, Mapping) else {"result": result}

	return dispatch


def build_user_text(text: str, *, company_context: str, now: datetime) -> str:
	prompt_text, _version = prompts.load(PROMPT_NAME)
	_system, user_template = prompts.split(prompt_text)
	return prompts.fill(
		user_template,
		COMPANY_CONTEXT=company_context.strip() or "(none)",
		UNTRUSTED=fence(text[:MAX_QUESTION_CHARS], label="question"),
		NOW=now.isoformat(timespec="minutes"),
	)


def answer(
	client: LlmClient,
	text: str,
	handlers: Mapping[str, Handler],
	*,
	company_context: str = "",
	now: datetime | None = None,
	max_turns: int = MAX_TURNS,
) -> AnswerOutcome:
	"""One tool-using model call; the answer sentence is the model's, the flags are ours."""
	now = now or datetime.now(timezone.utc)
	fragment = find_injection(text)
	if fragment is not None:
		# Still fenced and harmless to send, but a question that argues with the prompt has no
		# legitimate answer; refuse cheaply and let the pipeline log the event.
		return AnswerOutcome(
			answer=QuestionAnswer(
				answer_mn=mn.AGENT_ANSWER_INJECTION_REFUSED, used_tool=None, needs_escalation=False
			),
			llm=None,
			injection_suspected=True,
			injection_fragment=fragment,
			tools_used=(),
		)

	prompt_text, version = prompts.load(PROMPT_NAME)
	system, _user_template = prompts.split(prompt_text)
	llm = client.with_tools(
		purpose=PURPOSE,
		system=system,
		user=[TextPart(build_user_text(text, company_context=company_context, now=now))],
		tools=list(TOOL_SPECS),
		handler=make_dispatcher(handlers),
		max_turns=max_turns,
		prompt_version=prompts.version_tag(PROMPT_NAME, version),
	)
	tools_used = tuple(call.name for call in llm.tool_calls)
	escalated = any(call.name == "escalate_to_admin" and not call.is_error for call in llm.tool_calls)
	last_ok = next((call.name for call in reversed(llm.tool_calls) if not call.is_error), None)
	all_failed = bool(llm.tool_calls) and all(call.is_error for call in llm.tool_calls)
	handler_broke = any(
		call.is_error and (call.result or {}).get("error") not in MODEL_FAULT_ERRORS
		for call in llm.tool_calls
	)

	if escalated:
		answer_text = (llm.text or "").strip() or mn.MSG_ESCALATED
	elif llm.text and llm.text.strip():
		answer_text = llm.text.strip()
	elif all_failed and handler_broke:
		answer_text = mn.AGENT_ANSWER_TOOL_ERROR
	else:
		answer_text = mn.MSG_QUESTION_CANNOT

	return AnswerOutcome(
		answer=QuestionAnswer(answer_mn=answer_text, used_tool=last_ok, needs_escalation=escalated),
		llm=llm,
		injection_suspected=False,
		injection_fragment=None,
		tools_used=tools_used,
	)


__all__ = [
	"MAX_TURNS",
	"MODEL_FAULT_ERRORS",
	"PROMPT_NAME",
	"PURPOSE",
	"TOOL_ARG_MODELS",
	"TOOL_NAMES",
	"TOOL_SPECS",
	"AnswerFaqArgs",
	"AnswerFromBooksArgs",
	"AnswerOutcome",
	"BooksArgs",
	"EscalateArgs",
	"Handler",
	"answer",
	"build_user_text",
	"make_dispatcher",
]
