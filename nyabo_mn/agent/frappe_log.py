"""Write one ``Nyabo LLM Call`` per model call (docs/ARCHITECTURE.md §6: "every call writes").

The only module in ``nyabo_mn.agent`` that touches Frappe, and it imports it lazily so
the rest of the package stays importable in tests and the simulator. Metadata only: no
prompt, no image, no answer ever reaches the database through this path.

Usage::

    client = get_client(settings, record_call=frappe_log.recorder(company=company))
"""

from __future__ import annotations

import logging
from typing import Any

from nyabo_mn.agent.cost import estimate_tokens
from nyabo_mn.agent.llm_client import CallRecord, RecordCall

logger = logging.getLogger("nyabo.agent")

DOCTYPE = "Nyabo LLM Call"


def as_doc(record: CallRecord, *, company: str | None = None, proposal: str | None = None) -> dict[str, Any]:
	"""The dict handed to ``frappe.get_doc``; fields match nyabo_llm_call.json."""
	cost = record.cost_usd
	if cost is None:
		cost = estimate_tokens(record.model, record.tokens_in, record.tokens_out)
	return {
		"doctype": DOCTYPE,
		"purpose": record.purpose
		if record.purpose in ("extract", "classify", "question", "eval")
		else "other",
		"provider": record.provider,
		"model": record.model,
		"prompt_version": record.prompt_version,
		"ok": 1 if record.ok else 0,
		"error_class": record.error_class,
		"tokens_in": int(record.tokens_in),
		"tokens_out": int(record.tokens_out),
		"latency_ms": int(record.latency_ms),
		"cost_usd": float(cost),
		"company": company or record.company,
		"proposal": proposal or record.proposal,
	}


def record(call: CallRecord, *, company: str | None = None, proposal: str | None = None) -> str | None:
	"""Insert the log row; returns its name, or None when Frappe is unavailable or refuses.

	Failures are swallowed on purpose: a broken log table must not stop a receipt from
	being processed, but they are reported through ``nyabo_mn.log`` so they are visible.
	"""
	try:
		import frappe
	except ImportError:
		logger.info("frappe not importable; LLM call not persisted: %s", call)
		return None
	try:
		doc = frappe.get_doc(as_doc(call, company=company, proposal=proposal))
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception as exc:  # noqa: BLE001 - see docstring
		try:
			from nyabo_mn.log import log_error

			log_error("llm_call.log_failed", exc, purpose=call.purpose, provider=call.provider)
		except Exception:  # noqa: BLE001 - logging about logging; last resort is the module logger
			logger.exception("could not persist %s", DOCTYPE)
		return None


def recorder(*, company: str | None = None, proposal: str | None = None) -> RecordCall:
	"""A ``record_call`` callback bound to a company/proposal for ``get_client``."""

	def _record(call: CallRecord) -> None:
		record(call, company=company, proposal=proposal)

	return _record


__all__ = ["DOCTYPE", "as_doc", "record", "recorder"]
