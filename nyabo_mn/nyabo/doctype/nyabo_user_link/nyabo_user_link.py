"""Nyabo User Link: one row per Telegram account, keyed by the numeric Telegram id.

The id is stored as text (Telegram ids exceed 32 bits) but must be digits, so a link
created by hand in the desk cannot silently point at nobody. The active company is
always one of the linked companies; an admin removing a company row resets it.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class NyaboUserLink(Document):
	def validate(self) -> None:
		telegram_id = str(self.telegram_id or "").strip()
		if not telegram_id.lstrip("-").isdigit():
			frappe.throw(f"Telegram ID must be numeric: {telegram_id!r}")
		self.telegram_id = telegram_id
		companies = [row.company for row in (self.get("companies") or []) if row.company]
		if self.active_company and self.active_company not in companies:
			self.active_company = companies[0] if companies else None
		if not self.active_company and companies:
			self.active_company = companies[0]
		if not self.status:
			self.status = "active"
