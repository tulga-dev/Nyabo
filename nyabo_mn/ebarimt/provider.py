"""The ebarimt provider contract (docs/ARCHITECTURE.md §7) and the provider factory.

Why a Protocol: the pipeline asks one question ("is this seller a VAT payer?") and one
non-question ("can you verify this receipt?" - today never), and the answer must come
from the public registry in production, from fixtures in tests and the simulator, and
from the seller-side POS SDK only in a future on-premise deployment. The pipeline never
sees which one it got.

The dataclasses themselves (``SellerInfo``, ``ReceiptVerification``) live in
``nyabo_mn.core.models`` because the card layer and the proposal JSON need them without
importing this package; they are re-exported here so ``nyabo_mn.ebarimt`` is the one
import a provider author needs.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol, runtime_checkable

from nyabo_mn.core.models import ReceiptVerification, SellerInfo
from nyabo_mn.i18n import mn

SOURCE_REGISTRY = "registry"
SOURCE_SUPPLIER_CACHE = "supplier_cache"
SOURCE_MOCK = "mock"
SOURCE_NONE = "none"


class NotConfigured(RuntimeError):
	"""The provider needs infrastructure this deployment does not have (PosAPI, a key ...)."""


@runtime_checkable
class EbarimtProvider(Protocol):
	name: str

	def lookup_seller(self, *, tin: str | None = None, register_no: str | None = None) -> SellerInfo: ...

	def verify_receipt(self, *, qr_data: str | None, receipt_id: str | None) -> ReceiptVerification: ...


def unsupported_verification(now: dt.datetime | None = None) -> ReceiptVerification:
	"""What every provider answers until a buyer-side verification endpoint exists."""
	return ReceiptVerification(status="unsupported", reason=mn.VERIFICATION_RECEIPT_UNCHECKED, checked_at=now)


def not_found(*, tin: str | None, register_no: str | None, source: str = SOURCE_NONE) -> SellerInfo:
	"""A lookup that produced nothing; the card shows «Худалдагч бүртгэлд алга»."""
	return SellerInfo(name="", tin=tin, register_no=register_no, vat_payer=None, found=False, source=source)


def _setting(settings: Any, name: str, default: Any = None) -> Any:
	"""Read ``nyabo_mn.config.Settings`` or any mapping (tests pass plain dicts)."""
	if settings is None:
		return default
	getter = getattr(settings, "get", None)
	value = None
	if callable(getter):
		value = getter(name)
		if value in (None, ""):
			value = getter(name.lower())
	if value in (None, ""):
		return default
	return value


def _simulation_flag() -> bool:
	try:
		import frappe
	except ImportError:
		return False
	flags = getattr(frappe, "flags", None)
	try:
		return bool(flags and flags.get("nyabo_simulation"))
	except Exception:  # noqa: BLE001 - a LocalProxy outside a site raises; treat as "not simulating"
		return False


def get_provider(settings: Any = None) -> EbarimtProvider:
	"""Pick the provider: mock under ``frappe.flags.nyabo_simulation`` or ``EBARIMT_PROVIDER=mock``,
	the POS SDK when asked for (raises ``NotConfigured`` without the extra), else the registry.

	``EBARIMT_PROVIDER`` is not a documented site-config key yet (config.KEY_SPECS lists
	``EBARIMT_API_BASE`` only); it is read leniently so the simulator can force the mock
	without touching flags. Integration request filed to add it to ``KEY_SPECS``.
	"""
	choice = str(_setting(settings, "EBARIMT_PROVIDER", "") or "").strip().lower()
	if choice == "mock" or (not choice and _simulation_flag()):
		from nyabo_mn.ebarimt.mock import MockProvider

		return MockProvider()
	if choice == "pos":
		from nyabo_mn.ebarimt.pos_sdk import PosSdkProvider

		return PosSdkProvider()
	from nyabo_mn.ebarimt.registry import RegistryProvider

	base = _setting(settings, "EBARIMT_API_BASE", None)
	return RegistryProvider(base_url=str(base) if base else None)


__all__ = [
	"SOURCE_MOCK",
	"SOURCE_NONE",
	"SOURCE_REGISTRY",
	"SOURCE_SUPPLIER_CACHE",
	"EbarimtProvider",
	"NotConfigured",
	"ReceiptVerification",
	"SellerInfo",
	"get_provider",
	"not_found",
	"unsupported_verification",
]
