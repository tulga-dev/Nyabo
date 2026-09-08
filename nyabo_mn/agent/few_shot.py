"""Few-shot examples for the classification call: the company's last approved entries.

The classifier is told "here is how this company booked its last 20 receipts" (docs/
ARCHITECTURE.md §5.3 step 4). Examples come from approved / posted ``Nyabo Proposal``
rows - never from raw model output - so a wrong proposal the accountant changed is
learned from its corrected account, and a rejected one is never an example.

Bundles are cached in ``frappe.cache`` per company because the classification call runs
on the ``long`` queue for every receipt; the nightly ``refresh_all`` job rebuilds every
company's bundle and stamps ``few_shot_refreshed_at``. Posting or correcting a proposal
calls ``invalidate`` so the next receipt sees the change without waiting for the night.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("nyabo.agent")

DEFAULT_N = 20
CACHE_PREFIX = "nyabo:few_shot:"
EXAMPLE_STATUSES = ("approved", "posted")


def _cache_key(company: str) -> str:
	return f"{CACHE_PREFIX}{company}"


def _loads(value: Any) -> Any:
	if value in (None, ""):
		return None
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return None


def example_from_proposal(row: Any) -> dict[str, Any] | None:
	"""One example: seller, first line description, account code, VAT treatment."""
	code = row.get("account_code")
	if not code:
		return None
	extracted = _loads(row.get("extracted_json")) or {}
	lines = extracted.get("lines") or []
	description = ""
	if lines and isinstance(lines[0], dict):
		description = str(lines[0].get("description") or "")
	seller = row.get("supplier") or extracted.get("seller_name") or ""
	return {
		"seller": str(seller),
		"description": description,
		"account_code": str(code),
		"vat_treatment": str(row.get("vat_treatment") or "none"),
	}


def build(company: str, n: int = DEFAULT_N) -> list[dict[str, Any]]:
	"""Read the last ``n`` approved proposals of the company (no cache)."""
	import frappe

	rows = frappe.get_all(
		"Nyabo Proposal",
		filters={"company": company, "status": ["in", list(EXAMPLE_STATUSES)], "kind": ["!=", "bank_line"]},
		fields=["supplier", "account_code", "vat_treatment", "extracted_json", "modified"],
		order_by="modified desc",
		limit=n,
	)
	examples = [example for example in (example_from_proposal(r) for r in rows) if example]
	return examples[:n]


def bundle(company: str, n: int = DEFAULT_N) -> list[dict[str, Any]]:
	"""Cached examples for the classifier; falls back to a fresh build when the cache is empty."""
	import frappe

	cached = None
	try:
		cached = frappe.cache.get_value(_cache_key(company))
	except Exception as exc:  # noqa: BLE001 - Redis down must not stop a receipt
		logger.info("few-shot cache read failed: %s", type(exc).__name__)
	if isinstance(cached, list):
		return [dict(e) for e in cached[:n]]
	examples = build(company, n)
	_store(company, examples)
	return examples


def _store(company: str, examples: list[dict[str, Any]]) -> None:
	import frappe

	try:
		frappe.cache.set_value(_cache_key(company), examples)
	except Exception as exc:  # noqa: BLE001
		logger.info("few-shot cache write failed: %s", type(exc).__name__)


def invalidate(company: str) -> None:
	import frappe

	try:
		frappe.cache.delete_value(_cache_key(company))
	except Exception as exc:  # noqa: BLE001
		logger.info("few-shot cache delete failed: %s", type(exc).__name__)


def refresh(company: str, n: int = DEFAULT_N) -> list[dict[str, Any]]:
	"""Rebuild one company's bundle and stamp the settings row."""
	import frappe
	from frappe.utils import now_datetime

	examples = build(company, n)
	_store(company, examples)
	name = frappe.db.get_value("Nyabo Company Settings", {"company": company}, "name")
	if name:
		frappe.db.set_value("Nyabo Company Settings", name, "few_shot_refreshed_at", now_datetime())
	return examples


def refresh_all() -> dict[str, int]:
	"""Scheduler entry (hooks.py ``daily``): refresh every company that has settings."""
	import frappe

	counts: dict[str, int] = {}
	for company in frappe.get_all("Nyabo Company Settings", pluck="company"):
		try:
			counts[company] = len(refresh(company))
		except Exception as exc:  # noqa: BLE001 - one broken company must not stop the others
			logger.exception("few-shot refresh failed for %s", company)
			try:
				from nyabo_mn.log import log_error

				log_error("few_shot.refresh_failed", exc, company=company)
			except Exception:  # noqa: BLE001
				pass
	return counts


__all__ = [
	"CACHE_PREFIX",
	"DEFAULT_N",
	"EXAMPLE_STATUSES",
	"build",
	"bundle",
	"example_from_proposal",
	"invalidate",
	"refresh",
	"refresh_all",
]
