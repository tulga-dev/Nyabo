"""Nyabo Link Code: a six-digit, time-limited code an admin hands to a person.

The controller only guards the shape: the code is six digits (what a person can type
into Telegram from a phone call) and an expiry is always set, because
``telegram.state.consume_link_code`` treats a missing expiry as expired.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from nyabo_mn.i18n import mn


class NyaboLinkCode(Document):
	def validate(self) -> None:
		code = (self.code or "").strip()
		if len(code) != 6 or not code.isdigit():
			frappe.throw(mn.MSG_LINK_CODE_INVALID)
		self.code = code
		if not self.expires_at:
			frappe.throw(mn.MSG_LINK_CODE_INVALID)
		if not self.status:
			self.status = "open"
