"""Quarterly 1% summary for a company on the simplified regime.

Revenue is the quarter's net credit on every Income-root ledger account; the rate is the
``simplified.rate`` tax parameter in force on the quarter's last day. An unverified rate
row is refused for a statutory figure (``UnverifiedRuleError``) unless ``simulation`` is
set, mirroring the posting guard: a number nobody checked must not reach a tax return.

The regime's own conditions are looked up the same way, before anything is computed:
``simplified.requires_not_vat_registered`` (CIT art. 29.3.1) and
``simplified.revenue_threshold`` (art. 29.1). Their rows end where the law becomes
uncertain — the 2027 rows are ``status: pending`` on purpose — so a lookup that lands
there raises ``PendingRuleError`` (Mongolian) instead of printing 1% of the quarter for a
company nobody knows is still in the regime.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import frappe
from frappe.utils import getdate

from nyabo_mn.core.dates import month_bounds, period_of, quarter_bounds
from nyabo_mn.core.money import fmt_mnt, quantize
from nyabo_mn.core.rules_engine import MissingRuleError, ParameterRow
from nyabo_mn.i18n import mn
from nyabo_mn.reports import accounts, gl, rules_bridge

RATE_KEY = "simplified.rate"
NOT_VAT_REGISTERED_KEY = "simplified.requires_not_vat_registered"
REVENUE_THRESHOLD_KEY = "simplified.revenue_threshold"
ELIGIBILITY_KEYS: tuple[str, ...] = (NOT_VAT_REGISTERED_KEY, REVENUE_THRESHOLD_KEY)


def parse_quarter(quarter: str) -> tuple[int, int]:
	start, end = gl.range_of(quarter if "Q" in quarter.upper() else quarter)
	return start.year, (start.month - 1) // 3 + 1


def _revenue(company: str, start: dt.date, end: dt.date) -> Decimal:
	income_accounts = accounts.accounts_by_root_type(company, ("Income",))
	return quantize(gl.net_credit(gl.rows(company, start, end, accounts=income_accounts)))


def _threshold(row: ParameterRow) -> tuple[Decimal | None, str]:
	"""(amount, comparator) of ``simplified.revenue_threshold``; the value is a rule object."""
	value = row.value if isinstance(row.value, dict) else {}
	amount = value.get("amount")
	return (
		Decimal(str(amount)) if amount is not None else None,
		str(value.get("comparator") or "lt"),
	)


def eligibility(company: str, end: dt.date, *, simulation: bool = False) -> dict[str, Any]:
	"""The regime's conditions on the quarter's last day (CIT art. 29.1, 29.3.1).

	Both parameters are resolved and guarded before any figure is computed, so a period whose
	rows are still ``pending`` refuses instead of reporting 1% of the revenue. A company that
	is a VAT withholding payer on that date is outside the regime (29.3.1) and is refused;
	the prior-year revenue is only compared against the threshold — the law's basis is the
	confirmed prior-year return, which Nyabo does not hold, so the company's own books can
	raise the question for the accountant but never answer it.
	"""
	rows = {}
	for key in ELIGIBILITY_KEYS:
		row = rules_bridge.parameter_on(key, end)
		rules_bridge.require_verified(row, simulation=simulation)
		rows[key] = row
	try:
		vat_payer: bool | None = _regime_is_vat_payer(company, end)
	except MissingRuleError:
		vat_payer = None
	if rows[NOT_VAT_REGISTERED_KEY].value and vat_payer:
		frappe.throw(mn.MSG_SIMPLIFIED_NOT_ELIGIBLE_VAT)
	amount, comparator = _threshold(rows[REVENUE_THRESHOLD_KEY])
	prior_start, prior_end = dt.date(end.year - 1, 1, 1), dt.date(end.year - 1, 12, 31)
	prior_revenue = _revenue(company, prior_start, prior_end)
	over_threshold: bool | None = None
	warnings: list[str] = []
	if amount is not None and prior_revenue > 0:
		over_threshold = prior_revenue >= amount if comparator == "lt" else prior_revenue > amount
		if over_threshold:
			warnings.append(
				mn.WARN_SIMPLIFIED_OVER_THRESHOLD.format(
					revenue=fmt_mnt(prior_revenue), threshold=fmt_mnt(amount)
				)
			)
	return {
		"rows": {key: rules_bridge.row_summary(row) for key, row in rows.items()},
		"is_vat_payer": vat_payer,
		"threshold": amount,
		"comparator": comparator,
		"prior_year": period_of(prior_start)[:4],
		"prior_year_revenue": prior_revenue,
		"over_threshold": over_threshold,
		"warnings": warnings,
	}


def _regime_is_vat_payer(company: str, on_date: dt.date) -> bool:
	from nyabo_mn.rules import regime

	return regime.is_vat_payer(company, on_date)


def compute(company: str, quarter: str, *, simulation: bool = False) -> dict[str, Any]:
	"""{revenue, tax_1pct, rate_row, eligibility, warnings, months, from/to_date, quarter, simulation}."""
	year, q = parse_quarter(quarter)
	start, end = quarter_bounds(year, q)
	eligible = eligibility(company, end, simulation=simulation)
	rate_row = rules_bridge.parameter_on(RATE_KEY, end)
	rules_bridge.require_verified(rate_row, simulation=simulation)
	rate = rate_row.as_decimal()
	income_accounts = accounts.accounts_by_root_type(company, ("Income",))
	rows = gl.rows(company, start, end, accounts=income_accounts)
	months: list[dict[str, Any]] = []
	for offset in range(3):
		m_start, m_end = month_bounds(year, start.month + offset)
		month_rows = [r for r in rows if m_start <= getdate(r.posting_date) <= m_end]
		months.append({"period": period_of(m_start), "revenue": gl.net_credit(month_rows)})
	revenue = quantize(sum((m["revenue"] for m in months), Decimal("0")))
	return {
		"revenue": revenue,
		"tax_1pct": quantize(revenue * rate),
		"rate": rate,
		"rate_row": rules_bridge.row_summary(rate_row),
		"eligibility": eligible,
		"needs_accountant": bool(eligible["over_threshold"]),
		"warnings": eligible["warnings"],
		"months": months,
		"from_date": start,
		"to_date": end,
		"quarter": f"{year}-Q{q}",
		"simulation": simulation,
	}
