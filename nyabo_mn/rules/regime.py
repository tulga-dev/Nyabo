"""Tax regime history of a company (docs/ARCHITECTURE.md §1.6).

This module and `core.rules_engine.regime_on` are the only places that know the regime
names. Everything else calls `posting_context(company, on_date)` and reads
`is_vat_payer`, `input_vat_recoverable` and `summary_kind` from the RegimeContext.

History lives in `Nyabo Company Settings.regimes` (Nyabo Tax Regime Period rows). A
regime change closes the previous period the day before the new one starts, so the
history stays contiguous and the settings controller can validate it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import frappe
from frappe.utils import add_days, getdate

from nyabo_mn.core.models import Regime, RegimeContext
from nyabo_mn.core.rules_engine import regime_on
from nyabo_mn.i18n import mn

SETTINGS_DOCTYPE = "Nyabo Company Settings"

REGIME_VAT_PAYER = Regime.VAT_PAYER.value
REGIME_SIMPLIFIED = Regime.SIMPLIFIED_1PCT.value
REGIME_NAMES: tuple[str, ...] = tuple(r.value for r in Regime)

HistoryRow = tuple[str, dt.date | None, dt.date | None]


def initial_regime(vat_registered: bool) -> str:
	"""Onboarding step 2 (§5.2): a VAT payer files monthly, everyone else starts on the 1% regime."""
	return REGIME_VAT_PAYER if vat_registered else REGIME_SIMPLIFIED


def validate_regime_name(regime: str) -> str:
	if regime not in REGIME_NAMES:
		frappe.throw(mn.MSG_REGIME_UNKNOWN.format(regime=regime))
	return regime


def settings_name(company: str) -> str | None:
	return frappe.db.get_value(SETTINGS_DOCTYPE, {"company": company}, "name")


def history(company: str) -> list[HistoryRow]:
	"""(regime, effective_from, effective_to) rows, oldest first; empty when onboarding is not done."""
	name = settings_name(company)
	if not name:
		return []
	rows = frappe.get_all(
		"Nyabo Tax Regime Period",
		filters={"parent": name, "parenttype": SETTINGS_DOCTYPE, "parentfield": "regimes"},
		fields=["regime", "effective_from", "effective_to", "idx"],
		order_by="idx asc",
	)
	out = [(str(r.regime), _date(r.effective_from), _date(r.effective_to)) for r in rows]
	out.sort(key=lambda r: r[1] or dt.date.min)
	return out


def posting_context(company: str, on_date: dt.date | str) -> RegimeContext:
	"""RegimeContext for the transaction date; raises MissingRuleError when no period covers it."""
	return regime_on(history(company), getdate(on_date))


def is_vat_payer(company: str, on_date: dt.date | str) -> bool:
	return posting_context(company, on_date).is_vat_payer


def set_regime(company: str, regime: str, effective_from: dt.date | str, *, note: str | None = None) -> Any:
	"""Append a regime period from `effective_from`, closing the open previous period the day before.

	Idempotent: a row with the same regime and start date is left alone. Creates the
	company settings when they do not exist yet (provisioning calls this first).
	"""
	validate_regime_name(regime)
	start = getdate(effective_from)
	name = settings_name(company)
	doc = (
		frappe.get_doc(SETTINGS_DOCTYPE, name)
		if name
		else frappe.get_doc({"doctype": SETTINGS_DOCTYPE, "company": company})
	)
	doc.flags.ignore_permissions = True
	for row in doc.regimes or []:
		if row.regime == regime and _date(row.effective_from) == start:
			return doc
	for row in doc.regimes or []:
		row_start = _date(row.effective_from)
		if row.effective_to in (None, "") and row_start is not None and row_start < start:
			row.effective_to = add_days(start, -1)
	doc.append("regimes", {"regime": regime, "effective_from": start, "effective_to": None, "note": note})
	doc.save()
	return doc


def _date(value: Any) -> dt.date | None:
	return getdate(value) if value not in (None, "") else None
