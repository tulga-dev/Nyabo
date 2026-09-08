"""Nyabo Inventory Intake: the opening stock list an owner sent (xlsx/csv/text).

Amounts are recomputed on every save so the confirmation card, the Items and the
opening entry all carry the same numbers; a row with a non-positive quantity or rate
cannot become an opening balance and is refused.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from nyabo_mn.i18n import mn


class NyaboInventoryIntake(Document):
	def validate(self) -> None:
		total = 0.0
		for row in self.items or []:
			row.qty = flt(row.qty, row.precision("qty"))
			row.rate = flt(row.rate, row.precision("rate"))
			if row.qty <= 0 or row.rate <= 0:
				frappe.throw(mn.MSG_INTAKE_QTY_RATE_POSITIVE.format(item=row.item_name))
			row.amount = flt(row.qty * row.rate, row.precision("amount"))
			if not row.uom:
				row.uom = mn.UOM_PIECE
			total += row.amount
		self.total_amount = flt(total, self.precision("total_amount"))
