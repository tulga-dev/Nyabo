"""Nyabo Chat State: the conversation step, its payload and the last update id per chat.

``payload_json`` is written by ``telegram.state`` as a JSON string; the controller
normalises a dict handed in from the desk so the column never holds a Python repr.
"""

from __future__ import annotations

import json

from frappe.model.document import Document


class NyaboChatState(Document):
	def validate(self) -> None:
		self.chat_id = str(self.chat_id or "").strip()
		if isinstance(self.payload_json, (dict, list)):
			self.payload_json = json.dumps(self.payload_json, ensure_ascii=False, default=str)
