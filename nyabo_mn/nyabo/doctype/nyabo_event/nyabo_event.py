"""Nyabo Event controller: append-only even when the hooks are not installed.

The doc_events in hooks.py enforce the same rule; the controller repeats it so a site
where hooks were switched off (or a test running ``without_apps=("nyabo_mn",)``) still
cannot rewrite history. Reads stay unrestricted.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from nyabo_mn.i18n import mn


class NyaboEvent(Document):
	def validate(self) -> None:
		if not self.is_new():
			frappe.throw(mn.MSG_EVENT_APPEND_ONLY)

	def on_trash(self) -> None:
		frappe.throw(mn.MSG_EVENT_APPEND_ONLY)
