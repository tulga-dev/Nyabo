"""Nyabo Company Settings: per-company policy, regime history and bank rows.

The regime history must be contiguous and non-overlapping: `regime_on` tolerates
overlaps (latest start wins, CORE-04) but a gap would refuse every posting dated inside
it, and an overlap hides which regime the accountant meant. `default_expense_code`
must resolve to an account of the installed chart, because the classifier falls back
to it on every receipt it cannot place.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, getdate

from nyabo_mn.i18n import mn


class NyaboCompanySettings(Document):
	def validate(self) -> None:
		self.validate_regimes()
		self.validate_default_expense_code()

	def validate_regimes(self) -> None:
		from nyabo_mn.rules import regime as regime_mod

		rows = sorted(self.regimes or [], key=lambda r: getdate(r.effective_from))
		for row in rows:
			regime_mod.validate_regime_name(row.regime)
		for previous, current in zip(rows, rows[1:], strict=False):
			if not previous.effective_to:
				frappe.throw(
					mn.MSG_REGIME_OPEN_NOT_LAST.format(
						regime=previous.regime, effective_from=previous.effective_from
					)
				)
			previous_end = getdate(previous.effective_to)
			current_start = getdate(current.effective_from)
			if current_start <= previous_end:
				frappe.throw(
					mn.MSG_REGIME_OVERLAP.format(
						first=f"{previous.regime} {previous.effective_from}",
						second=f"{current.regime} {current.effective_from}",
					)
				)
			if current_start != getdate(add_days(previous_end, 1)):
				frappe.throw(mn.MSG_REGIME_GAP.format(previous_end=previous_end, next_start=current_start))
		for row in rows:
			if row.effective_to and getdate(row.effective_to) < getdate(row.effective_from):
				frappe.throw(
					mn.MSG_TAX_PARAM_DATES.format(
						effective_to=row.effective_to, effective_from=row.effective_from
					)
				)

	def validate_default_expense_code(self) -> None:
		"""Resolvable through aliases/roles; checked only once the company has a chart."""
		from nyabo_mn.rules import aliases

		code = (self.default_expense_code or "").strip()
		self.default_expense_code = code
		if not code or not frappe.db.exists("Account", {"company": self.company}):
			return
		resolved = aliases.resolve_code(self.company, code)
		if not frappe.db.exists("Account", {"company": self.company, "account_number": resolved}):
			frappe.throw(mn.MSG_DEFAULT_EXPENSE_CODE_MISSING.format(code=code))
