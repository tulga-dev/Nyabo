"""Seller lookup against the public ebarimt taxpayer registry (docs/ARCHITECTURE.md §2, §7).

Two endpoints, both GET, no authentication (read 2026-09-08):

    {base}/getInfo?tin=<TIN>      -> {"status", "msg", "data": {"name", "vatPayer", "found", ...}}
    {base}/getTinInfo?regNo=<RD>  -> {"status", "msg", "data": "<TIN>"}

with ``base = https://api.ebarimt.mn/api/info/check``. Nothing else is verified: a
non-200 status, a body that is not JSON, or a body without the documented keys is
treated as "not found". The lookup never raises into the pipeline - a registry outage
must degrade to «Худалдагч бүртгэлд алга» on the card, not to a failed receipt.

Results are cached on the Supplier (``ebarimt_vat_payer``, ``ebarimt_checked_at``,
custom fields from ``setup/custom_fields.py``) for ``CACHE_DAYS`` so a supplier that
sends ten receipts a month costs one registry call.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable
from typing import Any

from nyabo_mn.core.models import ReceiptVerification, SellerInfo
from nyabo_mn.ebarimt.provider import (
	SOURCE_REGISTRY,
	SOURCE_SUPPLIER_CACHE,
	not_found,
	unsupported_verification,
)

logger = logging.getLogger("nyabo.ebarimt")

DEFAULT_BASE_URL = "https://api.ebarimt.mn/api/info/check"
TIMEOUT_S = 5.0
CACHE_DAYS = 30

# fetch(url, params) -> (status_code, parsed_json_or_None); injected in tests.
Fetch = Callable[[str, dict[str, str]], tuple[int, Any]]


def requests_fetch(url: str, params: dict[str, str], timeout: float = TIMEOUT_S) -> tuple[int, Any]:
	"""Default transport: ``requests`` with the 5 s timeout; malformed JSON becomes ``None``."""
	import requests  # Frappe ships it; imported lazily so tests never touch the network

	response = requests.get(url, params=params, timeout=timeout)
	try:
		body = response.json()
	except ValueError:
		body = None
	return response.status_code, body


def _digits(value: str | None) -> str | None:
	text = "".join(ch for ch in str(value or "") if ch.isalnum()).strip()
	return text or None


def parse_get_info(body: Any, *, tin: str, register_no: str | None) -> SellerInfo:
	"""Turn a ``getInfo`` body into ``SellerInfo``; anything off-shape is "not found"."""
	if not isinstance(body, dict):
		return not_found(tin=tin, register_no=register_no, source=SOURCE_REGISTRY)
	data = body.get("data")
	if not isinstance(data, dict):
		return not_found(tin=tin, register_no=register_no, source=SOURCE_REGISTRY)
	found = data.get("found")
	name = str(data.get("name") or "").strip()
	if found is False or (found is None and not name):
		return not_found(tin=tin, register_no=register_no, source=SOURCE_REGISTRY)
	vat_payer = data.get("vatPayer")
	if isinstance(vat_payer, str):
		vat_payer = vat_payer.strip().lower() in ("true", "1", "yes", "y")
	elif vat_payer is not None:
		vat_payer = bool(vat_payer)
	return SellerInfo(
		name=name,
		tin=tin,
		register_no=register_no,
		vat_payer=vat_payer,
		found=True,
		source=SOURCE_REGISTRY,
	)


def parse_get_tin_info(body: Any) -> str | None:
	"""``getTinInfo`` answers ``data: "<TIN>"``; anything else is "no TIN"."""
	if not isinstance(body, dict):
		return None
	data = body.get("data")
	if isinstance(data, (str, int)):
		return _digits(str(data))
	return None


class RegistryProvider:
	name = "registry"

	def __init__(
		self,
		base_url: str | None = None,
		*,
		fetch: Fetch | None = None,
		timeout_s: float = TIMEOUT_S,
		cache_days: int = CACHE_DAYS,
		now: Callable[[], dt.datetime] | None = None,
	):
		self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
		self.timeout_s = timeout_s
		self.cache_days = cache_days
		self._fetch = fetch or (lambda url, params: requests_fetch(url, params, timeout=self.timeout_s))
		self._now = now or (lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))

	# -- contract --

	def lookup_seller(self, *, tin: str | None = None, register_no: str | None = None) -> SellerInfo:
		tin = _digits(tin)
		register_no = _digits(register_no)
		if not tin and register_no:
			tin = self._tin_for_register_no(register_no)
		if not tin:
			return not_found(tin=None, register_no=register_no)
		cached = self._from_supplier_cache(tin, register_no)
		if cached is not None:
			return cached
		info = self._from_registry(tin, register_no)
		if info.found:
			self.cache_on_supplier(info)
		return info

	def verify_receipt(self, *, qr_data: str | None, receipt_id: str | None) -> ReceiptVerification:
		del qr_data, receipt_id  # no buyer-side endpoint exists (ARCHITECTURE §2)
		return unsupported_verification(self._now())

	# -- registry calls (never raise) --

	def _get(self, path: str, params: dict[str, str]) -> Any:
		url = f"{self.base_url}/{path}"
		try:
			status, body = self._fetch(url, params)
		except Exception as exc:  # noqa: BLE001 - outage, DNS, timeout: all mean "not found"
			logger.warning("ebarimt registry %s failed: %s", path, type(exc).__name__)
			return None
		if status != 200:
			logger.info("ebarimt registry %s returned %s", path, status)
			return None
		return body

	def _tin_for_register_no(self, register_no: str) -> str | None:
		return parse_get_tin_info(self._get("getTinInfo", {"regNo": register_no}))

	def _from_registry(self, tin: str, register_no: str | None) -> SellerInfo:
		body = self._get("getInfo", {"tin": tin})
		if body is None:
			return not_found(tin=tin, register_no=register_no, source=SOURCE_REGISTRY)
		return parse_get_info(body, tin=tin, register_no=register_no)

	# -- Supplier cache (custom fields) --

	def _from_supplier_cache(self, tin: str, register_no: str | None) -> SellerInfo | None:
		try:
			import frappe
		except ImportError:
			return None
		try:
			row = frappe.db.get_value(
				"Supplier",
				{"tin": tin},
				["name", "supplier_name", "register_no", "ebarimt_vat_payer", "ebarimt_checked_at"],
				as_dict=True,
			)
		except Exception as exc:  # noqa: BLE001 - a site without the custom fields yet
			logger.info("supplier cache unavailable: %s", type(exc).__name__)
			return None
		if not row or not row.get("ebarimt_checked_at"):
			return None
		checked_at = row["ebarimt_checked_at"]
		if isinstance(checked_at, str):
			checked_at = dt.datetime.fromisoformat(checked_at)
		if checked_at.tzinfo is not None:
			checked_at = checked_at.replace(tzinfo=None)
		if self._now() - checked_at > dt.timedelta(days=self.cache_days):
			return None
		return SellerInfo(
			name=str(row.get("supplier_name") or row["name"]),
			tin=tin,
			register_no=register_no or row.get("register_no"),
			vat_payer=bool(row.get("ebarimt_vat_payer")),
			found=True,
			source=SOURCE_SUPPLIER_CACHE,
		)

	def cache_on_supplier(self, info: SellerInfo, supplier_name: str | None = None) -> bool:
		"""Stamp the registry answer on the Supplier that carries this TIN (or the named one)."""
		if not info.found or not info.tin:
			return False
		try:
			import frappe
		except ImportError:
			return False
		try:
			name = supplier_name or frappe.db.get_value("Supplier", {"tin": info.tin}, "name")
			if not name:
				return False
			frappe.db.set_value(
				"Supplier",
				name,
				{
					"ebarimt_vat_payer": 1 if info.vat_payer else 0,
					"ebarimt_checked_at": self._now().replace(microsecond=0),
				},
			)
			return True
		except Exception as exc:  # noqa: BLE001 - caching is best effort
			logger.info("could not cache registry answer on Supplier: %s", type(exc).__name__)
			return False


def dumps_for_log(body: Any) -> str:
	"""Compact, non-secret representation for debug logs (the registry is public data)."""
	try:
		return json.dumps(body, ensure_ascii=False)[:500]
	except (TypeError, ValueError):
		return repr(body)[:500]


__all__ = [
	"CACHE_DAYS",
	"DEFAULT_BASE_URL",
	"TIMEOUT_S",
	"Fetch",
	"RegistryProvider",
	"parse_get_info",
	"parse_get_tin_info",
	"requests_fetch",
]
