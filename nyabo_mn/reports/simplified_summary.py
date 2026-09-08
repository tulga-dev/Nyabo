"""Quarterly 1% summary for a company on the simplified regime.

Revenue is the quarter's net credit on every Income-root ledger account; the rate is the
``simplified.rate`` tax parameter in force on the quarter's last day. An unverified rate
row is refused for a statutory figure (``UnverifiedRuleError``) unless ``simulation`` is
set, mirroring the posting guard: a number nobody checked must not reach a tax return.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from frappe.utils import getdate

from nyabo_mn.core.dates import month_bounds, period_of, quarter_bounds
from nyabo_mn.core.money import quantize
from nyabo_mn.reports import accounts, gl, rules_bridge

RATE_KEY = "simplified.rate"


def parse_quarter(quarter: str) -> tuple[int, int]:
	start, end = gl.range_of(quarter if "Q" in quarter.upper() else quarter)
	return start.year, (start.month - 1) // 3 + 1


def compute(company: str, quarter: str, *, simulation: bool = False) -> dict[str, Any]:
	"""{revenue, tax_1pct, rate_row, months, from_date, to_date, quarter, simulation}."""
	year, q = parse_quarter(quarter)
	start, end = quarter_bounds(year, q)
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
		"months": months,
		"from_date": start,
		"to_date": end,
		"quarter": f"{year}-Q{q}",
		"simulation": simulation,
	}
