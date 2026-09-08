"""Nightly job: yesterday's accountant corrections become eval cases (ARCHITECTURE §8, hooks.py daily).

Why: every ``Nyabo Correction`` is a labelled example the model got wrong (or the rule
got wrong). Turning it into a ``Nyabo Eval Case`` with ``source = correction`` means the
next prompt or model change is measured against what this company's accountant actually
wanted, not only against the synthetic golden set. Rows are keyed on the correction name
inside ``notes`` so a re-run of the job (or a crash halfway) never creates a case twice.

Learned rules are proposed through ``nyabo_mn.agent.pipeline.propose_learned_rules`` when
that function exists (the pipeline is owned by another agent); otherwise the count is 0
and the event says so. The job never posts anything and never touches the books.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
from collections.abc import Mapping
from typing import Any

from nyabo_mn.core import rules_engine as re_
from nyabo_mn.i18n import mn

EVENT_TYPE = "evals_nightly"
DEDUP_PREFIX = "correction:"
FIELD_TO_KIND: dict[str, str] = {"account_code": "classification", "vat_treatment": "vat"}


def _json(value: Any) -> dict[str, Any]:
	if value in (None, ""):
		return {}
	if isinstance(value, Mapping):
		return dict(value)
	try:
		parsed = json.loads(value)
	except (TypeError, ValueError):
		return {}
	return parsed if isinstance(parsed, dict) else {}


def _day_bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
	start = dt.datetime.combine(day, dt.time.min)
	return start, start + dt.timedelta(days=1)


def regime_for(company: str, on_date: dt.date | None) -> str:
	"""The regime name in force for the company on the date, from ``Nyabo Company Settings``.

	Uses ``nyabo_mn.rules.regime.posting_context`` when that module is present (it is the
	one place allowed to know regime names, ARCHITECTURE §1.6); the fallback reads the
	same ``regimes`` child rows through the core engine. Empty when onboarding is not done.
	"""
	import frappe

	day = on_date or dt.date.today()
	try:
		regime_mod = importlib.import_module("nyabo_mn.rules.regime")
		ctx = regime_mod.posting_context(company, day)
		return str(
			getattr(ctx, "regime", "").value if hasattr(getattr(ctx, "regime", None), "value") else ctx.regime
		)
	except (ImportError, AttributeError):
		pass
	except re_.RuleError:
		return ""
	if not frappe.db.exists("Nyabo Company Settings", company):
		return ""
	settings = frappe.get_doc("Nyabo Company Settings", company)
	history = [(row.regime, row.effective_from, row.effective_to) for row in settings.get("regimes") or []]
	try:
		return re_.regime_on(history, day).regime.value
	except re_.RuleError:
		return ""


def case_exists(correction_name: str) -> bool:
	import frappe

	return bool(
		frappe.db.exists(
			"Nyabo Eval Case",
			{"source": "correction", "notes": ["like", f"%{DEDUP_PREFIX}{correction_name}%"]},
		)
	)


def build_case(correction: Mapping[str, Any], proposal: Any | None) -> dict[str, Any] | None:
	"""The Eval Case dict for one correction row, or None when the field is not evaluable."""
	field = str(correction.get("field") or "")
	kind = FIELD_TO_KIND.get(field)
	if kind is None:
		return None
	extracted = _json(proposal.get("extracted_json")) if proposal is not None else {}
	posting_date = proposal.get("posting_date") if proposal is not None else None
	if isinstance(posting_date, dt.datetime):
		posting_date = posting_date.date()
	company = str(
		correction.get("company") or (proposal.get("company") if proposal is not None else "") or ""
	)
	regime = regime_for(company, posting_date) if company else ""
	context = {
		"company": company,
		"regime": regime,
		"supplier": (proposal.get("supplier") if proposal is not None else None)
		or correction.get("supplier"),
		"posting_date": posting_date.isoformat() if posting_date else None,
		"proposed_value": correction.get("proposed_value"),
		"reason": correction.get("reason"),
		"proposal": correction.get("proposal"),
		"vat_treatment": proposal.get("vat_treatment") if proposal is not None else None,
		"account_code": proposal.get("account_code") if proposal is not None else None,
	}
	expected = {field: correction.get("corrected_value")}
	notes = "\n".join(
		[
			f"{DEDUP_PREFIX}{correction['name']}",
			f"case_id:corr_{correction['name']}",
			str(correction.get("reason_text") or ""),
		]
	).strip()
	return {
		"doctype": "Nyabo Eval Case",
		"kind": kind,
		"source": "correction",
		"company": company or None,
		"regime": regime,
		"on_date": posting_date.isoformat() if posting_date else None,
		"input_document": proposal.get("document") if proposal is not None else None,
		"input_json": json.dumps({"receipt": extracted, "context": context}, ensure_ascii=False, default=str),
		"expected_json": json.dumps(expected, ensure_ascii=False, default=str),
		"notes": notes,
	}


def propose_learned_rules(corrections: list[dict[str, Any]]) -> int:
	"""Hand the day's corrections to the pipeline's rule learner when it exists; else 0."""
	try:
		pipeline = importlib.import_module("nyabo_mn.agent.pipeline")
	except ImportError:
		return 0
	fn = getattr(pipeline, "propose_learned_rules", None)
	if not callable(fn):
		return 0
	result = fn(corrections)
	if isinstance(result, int):
		return result
	try:
		return len(result)
	except TypeError:
		return 0


def run_nightly(day: dt.date | str | None = None) -> dict[str, Any]:
	"""Scheduler entry point (hooks.py ``daily``): cases for yesterday's corrections + an event."""
	import frappe

	if day is None:
		target = dt.date.today() - dt.timedelta(days=1)
	elif isinstance(day, dt.date):
		target = day
	else:
		target = dt.date.fromisoformat(str(day))
	start, end = _day_bounds(target)
	corrections = frappe.get_all(
		"Nyabo Correction",
		filters=[["creation", ">=", start], ["creation", "<", end]],
		fields=[
			"name",
			"proposal",
			"company",
			"field",
			"proposed_value",
			"corrected_value",
			"reason",
			"reason_text",
			"source",
			"supplier",
		],
		order_by="creation asc",
	)
	counts = {
		"day": target.isoformat(),
		"corrections": len(corrections),
		"created": 0,
		"skipped": 0,
		"unsupported": 0,
		"rules_proposed": 0,
		"errors": 0,
	}
	created: list[str] = []
	for row in corrections:
		if case_exists(row["name"]):
			counts["skipped"] += 1
			continue
		proposal = None
		if row.get("proposal") and frappe.db.exists("Nyabo Proposal", row["proposal"]):
			proposal = frappe.get_doc("Nyabo Proposal", row["proposal"])
		payload = build_case(row, proposal)
		if payload is None:
			counts["unsupported"] += 1
			continue
		try:
			doc = frappe.get_doc(payload)
			doc.insert(ignore_permissions=True)
			created.append(doc.name)
			counts["created"] += 1
		except Exception as exc:  # noqa: BLE001 - one bad row must not stop the night
			counts["errors"] += 1
			try:
				from nyabo_mn.log import log_error

				log_error("evals.nightly.case_failed", exc, correction=row["name"])
			except Exception:  # noqa: BLE001 - logging about logging
				pass
	try:
		counts["rules_proposed"] = propose_learned_rules([dict(r) for r in corrections])
	except Exception as exc:  # noqa: BLE001 - the learner is another module's; report, do not crash
		counts["errors"] += 1
		try:
			from nyabo_mn.log import log_error

			log_error("evals.nightly.rules_failed", exc)
		except Exception:  # noqa: BLE001
			pass
	event = frappe.get_doc(
		{
			"doctype": "Nyabo Event",
			"event_type": EVENT_TYPE,
			"reason": mn.EVAL_NIGHTLY_REASON.format(day=target.isoformat(), created=counts["created"]),
			"payload_json": json.dumps({**counts, "cases": created}, ensure_ascii=False),
		}
	)
	event.insert(ignore_permissions=True)
	counts["event"] = event.name
	counts["cases"] = created
	return counts


__all__ = ["EVENT_TYPE", "build_case", "case_exists", "propose_learned_rules", "regime_for", "run_nightly"]
