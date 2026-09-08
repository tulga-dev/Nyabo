"""Mongolbank official rates -> ERPNext Currency Exchange rows (rates are data, ARCHITECTURE §2 FX).

The accounting pipeline never reads this module: it asks
``erpnext.setup.utils.get_exchange_rate(from, to, transaction_date)``, which reads the
Currency Exchange table first. This module only fills that table, idempotently, from
rows the admin imports (CSV) or, behind a settings flag that is off by default, from
Mongolbank's website endpoint.

    bench --site <site> execute nyabo_mn.compliance.fx_rates.import_csv --kwargs '{"path": "rates.csv"}'
"""

from __future__ import annotations

import csv
import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe
from frappe.utils import getdate

from nyabo_mn.compliance import events
from nyabo_mn.i18n import mn

BASE_CURRENCY = "MNT"
FETCH_FLAG = "MONGOLBANK_FETCH_ENABLED"
# UNVERIFIED: undocumented endpoint (observed in the browser network log on 2026-09-08; a
# POST with no body returns JSON, a GET returns the HTML 404 page). Off unless the site
# config sets MONGOLBANK_FETCH_ENABLED; never called from tests.
MONGOLBANK_URL = "https://www.mongolbank.mn/en/currency-rates/data"
NON_CURRENCY_KEYS: frozenset[str] = frozenset({"RATE_DATE", "XAU", "XAG", "SDR"})


def _rate(value: Any) -> Decimal:
	text = str(value).replace(",", "").replace(" ", "").strip()
	try:
		return Decimal(text)
	except InvalidOperation as exc:
		raise ValueError(f"not a rate: {value!r}") from exc


def parse_mongolbank_json(payload: dict[str, Any]) -> list[dict[str, Any]]:
	"""{"success": true, "data": [{"RATE_DATE": "2026-09-01", "USD": "3,595.21", ...}]} -> rows.

	Precious metals and the SDR are skipped: they are not currencies in ERPNext's sense.
	Rates are MNT per one unit of the foreign currency, which is exactly
	``Currency Exchange.exchange_rate`` for from_currency=<cur>, to_currency=MNT.
	"""
	if not payload or not payload.get("success"):
		return []
	rows: list[dict[str, Any]] = []
	for day in payload.get("data") or []:
		date = day.get("RATE_DATE")
		if not date:
			continue
		for currency, value in day.items():
			if currency in NON_CURRENCY_KEYS or value in (None, ""):
				continue
			rows.append({"date": getdate(date), "currency": currency, "rate": _rate(value)})
	return rows


def import_rates(rows: list[dict[str, Any]], *, only_known_currencies: bool = True) -> int:
	"""Create Currency Exchange rows (from <cur> to MNT, buying and selling); returns the count created.

	Idempotent on ERPNext's own name ``<date>-<from>-<to>``; currencies missing from the
	Currency table are skipped by default because the Link would fail anyway.
	"""
	created = 0
	skipped = 0
	for row in rows:
		currency = str(row["currency"]).upper()
		date = getdate(row["date"])
		if currency == BASE_CURRENCY:
			continue
		if only_known_currencies and not frappe.db.exists("Currency", currency):
			skipped += 1
			continue
		name = f"{date.isoformat()}-{currency}-{BASE_CURRENCY}"
		if frappe.db.exists("Currency Exchange", name):
			skipped += 1
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Currency Exchange",
				"date": date,
				"from_currency": currency,
				"to_currency": BASE_CURRENCY,
				"exchange_rate": float(_rate(row["rate"])),
				"for_buying": 1,
				"for_selling": 1,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		created += 1
	if created:
		events.log(mn.EVENT_FX_RATES_IMPORTED, payload={"created": created, "skipped": skipped})
	return created


def fetch_enabled() -> bool:
	return bool(frappe.conf.get(FETCH_FLAG) or frappe.conf.get(FETCH_FLAG.lower()))


def fetch_mongolbank(start: dt.date | str, end: dt.date | str) -> list[dict[str, Any]]:
	"""Rows from Mongolbank's website for the range; refused unless the site flag is on.

	# UNVERIFIED: undocumented endpoint, see MONGOLBANK_URL. Network is only touched here.
	"""
	if not fetch_enabled():
		frappe.throw(mn.MSG_FX_FETCH_DISABLED)
	import requests

	response = requests.post(
		MONGOLBANK_URL,
		params={"startDate": getdate(start).isoformat(), "endDate": getdate(end).isoformat()},
		timeout=15,
	)
	response.raise_for_status()
	return parse_mongolbank_json(response.json())


def import_mongolbank(start: dt.date | str, end: dt.date | str) -> int:
	return import_rates(fetch_mongolbank(start, end))


def parse_csv(path: str) -> list[dict[str, Any]]:
	"""CSV with a header row containing date, currency, rate (any column order, UTF-8)."""
	rows: list[dict[str, Any]] = []
	with open(path, encoding="utf-8-sig", newline="") as handle:
		for record in csv.DictReader(handle):
			normalized = {(k or "").strip().lower(): (v or "").strip() for k, v in record.items()}
			if not normalized.get("date") or not normalized.get("currency"):
				continue
			rows.append(
				{
					"date": getdate(normalized["date"]),
					"currency": normalized["currency"].upper(),
					"rate": _rate(normalized["rate"]),
				}
			)
	return rows


def import_csv(path: str) -> int:
	"""bench execute entry point; prints and returns the number of rows created."""
	created = import_rates(parse_csv(path))
	print(mn.MSG_FX_RATES_IMPORTED.format(count=created, skipped=0))
	return created
