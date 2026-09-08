"""Nyabo Correction: one changed field on a proposal, or a rejection / reversal record.

Law on Accounting art. 15 wants the reason and the person recorded; the row is that
record. After insert, an ``account_code`` correction is offered to the learning step
(``nyabo_mn.agent.post.learn_from_correction``): two agreeing corrections for the same
supplier or description create a ``Nyabo Rule`` in ``pending_confirmation``. Learning
failures are logged and never block the correction itself.
"""

from __future__ import annotations

import logging

from frappe.model.document import Document

logger = logging.getLogger("nyabo.agent")


class NyaboCorrection(Document):
	def validate(self) -> None:
		from frappe import ValidationError

		if self.field == "account_code" and not self.corrected_value:
			raise ValidationError("Nyabo Correction: an account_code correction needs corrected_value")
		if self.source == "rejection" and self.field != "rejected":
			self.field = "rejected"

	def after_insert(self) -> None:
		if self.field != "account_code":
			return
		try:
			from nyabo_mn.agent.post import learn_from_correction

			learn_from_correction(self)
		except Exception as exc:  # noqa: BLE001 - learning is best effort; the correction stands
			logger.exception("learn_from_correction failed for %s", self.name)
			try:
				from nyabo_mn.log import log_error

				log_error("correction.learn_failed", exc, correction=self.name)
			except Exception:  # noqa: BLE001
				pass
