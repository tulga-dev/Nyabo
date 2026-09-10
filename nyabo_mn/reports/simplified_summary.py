"""Quarterly 1% summary for a company on the simplified regime.

Revenue is the quarter's net credit on the company's revenue-role accounts; the rate is
the ``simplified.rate`` tax parameter in force on the quarter's last day. An unverified
rate row is refused for a statutory figure (``UnverifiedRuleError``), mirroring the
posting guard: a number nobody checked must not reach a tax return. The one bypass is
``frappe.flags.nyabo_simulation`` (the simulator and the tests); there is deliberately no
argument and no report filter for it (F-11), only the ``simulation`` label in the output.

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
# The roles that carry sales revenue and its contra rows (classes 51 and 52 on the v0.3
# chart, 41 on V1). Nothing else belongs in the 1% base - see ``revenue_accounts``.
REVENUE_ROLES: tuple[str, ...] = ("revenue_sales", "revenue_services", "sales_discount", "sales_return")


def parse_quarter(quarter: str) -> tuple[int, int]:
	start, end = gl.range_of(quarter if "Q" in quarter.upper() else quarter)
	return start.year, (start.month - 1) // 3 + 1


def revenue_accounts(company: str) -> tuple[list[str], list[str], bool]:
	"""(accounts in the 1% base, Income-root accounts outside it, roles resolved?) — CIT art. 29.1, 29.9.

	WHY not every Income-root account (F-10): art. 29.9 taxes at 1% «энэ хуулийн 29.1-д
	заасны дагуу тодорхойлсон албан татвар ногдуулах орлого», and 29.1 determines that
	income from «үйл ажиллагааны орлогын нийт дүн» — the total of the taxpayer's *operating*
	revenue. Class 84 (үндсэн бус үйл ажиллагааны орлого, олз: FX gains, disposal gains,
	investment income) sits under the Income root but is not operating revenue, so sweeping
	it in overstates the tax. The base is therefore the revenue roles; whatever is left on
	the Income root is returned so the caller can show it and ask the accountant.

	A company whose chart resolves none of the roles (an accountant's own chart with no
	aliases yet) gets the wider base back, with the third element ``False`` — the caller
	marks the figure ``needs_accountant`` rather than silently under-reporting revenue.
	"""
	income = accounts.accounts_by_root_type(company, ("Income",))
	base: list[str] = []
	for role in REVENUE_ROLES:
		account = accounts.role_account_or_none(company, role)
		if account and account in income and account not in base:
			base.append(account)
	if not base:
		return income, [], False
	return base, [account for account in income if account not in base], True


def _revenue(company: str, start: dt.date, end: dt.date, ledger_accounts: list[str]) -> Decimal:
	if not ledger_accounts:
		return quantize(Decimal("0"))
	return quantize(gl.net_credit(gl.rows(company, start, end, accounts=ledger_accounts)))


def _threshold(row: ParameterRow) -> tuple[Decimal | None, str]:
	"""(amount, comparator) of ``simplified.revenue_threshold``; the value is a rule object."""
	value = row.value if isinstance(row.value, dict) else {}
	amount = value.get("amount")
	return (
		Decimal(str(amount)) if amount is not None else None,
		str(value.get("comparator") or "lt"),
	)


def eligibility(company: str, end: dt.date) -> dict[str, Any]:
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
		rules_bridge.require_verified(row, company=company)
		rows[key] = row
	try:
		vat_payer: bool | None = _regime_is_vat_payer(company, end)
	except MissingRuleError:
		vat_payer = None
	if rows[NOT_VAT_REGISTERED_KEY].value and vat_payer:
		frappe.throw(mn.MSG_SIMPLIFIED_NOT_ELIGIBLE_VAT)
	amount, comparator = _threshold(rows[REVENUE_THRESHOLD_KEY])
	prior_start, prior_end = dt.date(end.year - 1, 1, 1), dt.date(end.year - 1, 12, 31)
	# Art. 29.1 measures «борлуулалтын нийт орлого» — the same sales-revenue base as the tax.
	prior_revenue = _revenue(company, prior_start, prior_end, revenue_accounts(company)[0])
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
		"rows": {key: rules_bridge.row_summary(row, company) for key, row in rows.items()},
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


def compute(company: str, quarter: str) -> dict[str, Any]:
	"""{revenue, tax_1pct, rate_row, eligibility, warnings, months, from/to_date, quarter, simulation}.

	The 1% base is the quarter's net credit on the revenue-role accounts (CIT art. 29.1 read
	with 29.9: the tax is on «үйл ажиллагааны орлогын нийт дүн», total operating revenue).
	Income-root movement outside those roles — class 84 non-operating gains, or a revenue
	account no role points at — is reported as ``excluded_revenue`` with a warning and marks
	the row ``needs_accountant``: Nyabo may not decide on its own that a figure belongs in a
	tax base, but it must not hide that it left one out either.
	"""
	year, q = parse_quarter(quarter)
	start, end = quarter_bounds(year, q)
	simulation = rules_bridge.is_simulation()
	eligible = eligibility(company, end)
	rate_row = rules_bridge.parameter_on(RATE_KEY, end)
	rules_bridge.require_verified(rate_row, company=company)
	rate = rate_row.as_decimal()
	base_accounts, other_income_accounts, roles_resolved = revenue_accounts(company)
	rows = gl.rows(company, start, end, accounts=base_accounts) if base_accounts else []
	months: list[dict[str, Any]] = []
	for offset in range(3):
		m_start, m_end = month_bounds(year, start.month + offset)
		month_rows = [r for r in rows if m_start <= getdate(r.posting_date) <= m_end]
		months.append({"period": period_of(m_start), "revenue": gl.net_credit(month_rows)})
	revenue = quantize(sum((m["revenue"] for m in months), Decimal("0")))
	excluded = _revenue(company, start, end, other_income_accounts)
	warnings = list(eligible["warnings"])
	if not roles_resolved:
		warnings.append(mn.WARN_SIMPLIFIED_REVENUE_ROLES_UNKNOWN)
	elif excluded:
		warnings.append(mn.WARN_SIMPLIFIED_NON_OPERATING_EXCLUDED.format(amount=fmt_mnt(excluded)))
	return {
		"revenue": revenue,
		"tax_1pct": quantize(revenue * rate),
		"rate": rate,
		"rate_row": rules_bridge.row_summary(rate_row, company),
		"eligibility": eligible,
		"revenue_accounts": base_accounts,
		"excluded_revenue": excluded,
		"needs_accountant": bool(eligible["over_threshold"]) or not roles_resolved or bool(excluded),
		"warnings": warnings,
		"months": months,
		"from_date": start,
		"to_date": end,
		"quarter": f"{year}-Q{q}",
		"simulation": simulation,
	}
