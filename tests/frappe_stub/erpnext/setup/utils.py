"""erpnext.setup.utils.get_exchange_rate (version-16) over the stub's Currency Exchange rows.

Same lookup: ``date <= transaction_date``, ``from_currency``/``to_currency``, optional
``for_buying`` / ``for_selling`` filter, newest first; stale rates are refused when
``Accounts Settings.allow_stale`` is 0 (``stale_days``). Without a row the external
provider would be called; the stub returns 0.0 when ``Currency Exchange Settings.disabled``
is set and otherwise raises ``NotImplementedError`` (no network in tests).
"""

from __future__ import annotations

from typing import Any

from frappe.utils.data import add_days, cint, flt, get_datetime_str, nowdate


def get_exchange_rate(
	from_currency: str, to_currency: str, transaction_date: Any = None, args: Any = None
) -> Any:
	import frappe

	if not (from_currency and to_currency):
		return None
	if from_currency == to_currency:
		return 1
	if not transaction_date:
		transaction_date = nowdate()

	allow_stale = frappe.get_single_value("Accounts Settings", "allow_stale")
	allow_stale_rates = 1 if allow_stale is None else cint(allow_stale)  # ERPNext's field default is 1

	filters: list[list[Any]] = [
		["date", "<=", get_datetime_str(transaction_date)],
		["from_currency", "=", from_currency],
		["to_currency", "=", to_currency],
	]
	if args == "for_buying":
		filters.append(["for_buying", "=", "1"])
	elif args == "for_selling":
		filters.append(["for_selling", "=", "1"])
	if not allow_stale_rates:
		stale_days = cint(frappe.get_single_value("Accounts Settings", "stale_days"))
		checkpoint_date = add_days(transaction_date, -stale_days)
		filters.append(["date", ">", get_datetime_str(checkpoint_date)])

	entries = frappe.get_all(
		"Currency Exchange", fields=["exchange_rate"], filters=filters, order_by="date desc", limit=1
	)
	if entries:
		return flt(entries[0].exchange_rate)
	if frappe.get_single_value("Currency Exchange Settings", "disabled"):
		return 0.00
	raise NotImplementedError(
		f"frappe stub: no Currency Exchange row for {from_currency}->{to_currency} on {transaction_date} and the "
		"external rate provider is not available; insert a Currency Exchange or disable Currency Exchange Settings"
	)


def before_tests() -> None:
	return None
