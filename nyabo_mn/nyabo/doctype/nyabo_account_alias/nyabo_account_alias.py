"""Nyabo Account Alias: `alias_code` (V1 / accountant / MoF template code) -> `target_code` in the chart.

The target must exist in the company's chart once the chart is installed; before that
(provisioning inserts aliases right after the accounts, but an admin may prepare rows
for a company without accounts) the check is skipped. `target_account` is filled from
the code so reports can link to the ledger.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from nyabo_mn.i18n import mn


class NyaboAccountAlias(Document):
	def validate(self) -> None:
		self.alias_code = (self.alias_code or "").strip()
		self.target_code = (self.target_code or "").strip()
		if not frappe.db.exists("Account", {"company": self.company}):
			return
		account = frappe.db.get_value(
			"Account", {"company": self.company, "account_number": self.target_code}, "name"
		)
		if not account:
			frappe.throw(mn.MSG_ALIAS_TARGET_MISSING.format(code=self.target_code, company=self.company))
		self.target_account = account
