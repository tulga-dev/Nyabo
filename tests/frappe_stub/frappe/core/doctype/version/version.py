"""Version controller (frappe/core/doctype/version/version.py): ``get_data`` and ``get_diff``."""

from __future__ import annotations

import json
from typing import Any

from frappe._stub.version import get_diff
from frappe.model.document import Document


class Version(Document):
	def get_data(self) -> Any:
		return json.loads(self.data or "{}")

	def set_diff(self, old: Any, new: Any) -> bool:
		import frappe

		diff = get_diff(old, new)
		if diff:
			self.ref_doctype = new.doctype
			self.docname = new.name
			self.data = frappe.as_json(diff, indent=None, separators=(",", ":"), ensure_ascii=False)
			return True
		return False


__all__ = ["Version", "get_diff"]
