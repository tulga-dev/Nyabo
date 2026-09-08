"""Nyabo Eval Case: one input/expected pair the evals run (golden, synthetic, or from a correction).

The controller only guards the shape: both JSON columns must hold objects, and the kinds
that branch on the regime must name one, because ``evals.loader.EvalCase.from_doc`` would
otherwise refuse the row at run time, far from whoever typed it into the desk.
"""

from __future__ import annotations

import json

import frappe
from frappe.model.document import Document

from nyabo_mn.i18n import mn

REGIME_KINDS = ("classification", "vat", "correction", "rules", "injection")


class NyaboEvalCase(Document):
	def validate(self) -> None:
		for fieldname in ("input_json", "expected_json"):
			self._validate_json_object(fieldname)
		if self.kind in REGIME_KINDS and not self.regime:
			frappe.throw(mn.MSG_EVAL_CASE_REGIME_REQUIRED.format(kind=self.kind))

	def _validate_json_object(self, fieldname: str) -> None:
		value = self.get(fieldname)
		if value in (None, ""):
			return
		if isinstance(value, (dict, list)):
			self.set(fieldname, json.dumps(value, ensure_ascii=False))
			value = self.get(fieldname)
		try:
			parsed = json.loads(value)
		except (TypeError, ValueError) as exc:
			frappe.throw(mn.MSG_EVAL_CASE_BAD_JSON.format(field=fieldname, error=str(exc)))
			return
		if not isinstance(parsed, dict):
			frappe.throw(mn.MSG_EVAL_CASE_BAD_JSON.format(field=fieldname, error="object expected"))
