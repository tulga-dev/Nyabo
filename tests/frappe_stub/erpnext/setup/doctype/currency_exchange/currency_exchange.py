"""Currency Exchange: ``<yyyy-MM-dd>-<from>-<to>[-Buying|-Selling]``, rate > 0, from != to."""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document
from frappe.utils.data import cint, flt, formatdate


class CurrencyExchange(Document):
	def autoname(self) -> None:
		purpose = ""
		if not cint(self.for_buying) == cint(self.for_selling):
			purpose = "-Buying" if cint(self.for_buying) else "-Selling"
		self.name = "{}-{}-{}{}".format(formatdate(self.date, "yyyy-MM-dd"), self.from_currency, self.to_currency, purpose)

	def validate(self) -> None:
		if flt(self.exchange_rate) <= 0:
			raise ValidationError("Exchange Rate must be greater than 0")
		if self.from_currency == self.to_currency:
			raise ValidationError("From Currency and To Currency cannot be same")
		if not cint(self.for_buying) and not cint(self.for_selling):
			raise ValidationError("Currency Exchange must be applicable for Buying or for Selling.")
