"""Nyabo Proposal: what the model proposed, what the accountant decided, what was posted.

The controller only keeps the record consistent; decisions happen in
``nyabo_mn.agent.post`` (a Telegram tap) and creation in ``nyabo_mn.agent.pipeline``.
JSON blobs are normalised to text so a dict handed in by code and a string read back
from the database look the same to every reader; the explanation is capped at the
field length so a long model reason never fails the insert of an otherwise good proposal.
"""

from __future__ import annotations

import json
from typing import Any

from frappe.model.document import Document

JSON_FIELDS = ("entry_json", "extracted_json", "verification_json", "confidence_json", "warnings_json")
EXPLANATION_MAX = 300


class NyaboProposal(Document):
	def validate(self) -> None:
		for fieldname in JSON_FIELDS:
			value = self.get(fieldname)
			if isinstance(value, (dict, list)):
				self.set(fieldname, json.dumps(value, ensure_ascii=False))
		if self.explanation and len(self.explanation) > EXPLANATION_MAX:
			self.explanation = self.explanation[: EXPLANATION_MAX - 1] + "…"
		if self.status == "posted" and not self.posted_name:
			# A "posted" proposal without its document is a lie the card would repeat.
			from frappe import ValidationError

			raise ValidationError(f"Nyabo Proposal {self.name or ''}: status posted needs posted_name")

	def json_field(self, fieldname: str) -> Any:
		"""Parsed JSON of one of the blob fields (None when empty)."""
		value = self.get(fieldname)
		if value in (None, ""):
			return None
		return value if isinstance(value, (dict, list)) else json.loads(value)

	def warnings(self) -> list[str]:
		return list(self.json_field("warnings_json") or [])
