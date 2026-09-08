"""Seller-side PosAPI 3.0 provider through ``ebarimt-pos-sdk`` (optional extra ``nyabo_mn[pos]``).

Why this exists but does nothing on Frappe Cloud: PosAPI 3.0 is the *merchant* API. It
talks to a PosAPI service installed on a machine inside the Mongolian network (the
Tax Authority distributes it), which Frappe Cloud's Singapore servers cannot reach.
``ebarimt-pos-sdk`` 0.4.1 (PyPI, MIT; httpx + pydantic v2 + authlib) wraps that local
service. It has no buyer-side "verify this receipt" call either, so even on-premise it
would only serve a future feature (issuing Nyabo's own sales receipts).

The import is lazy: ``PosSdkProvider()`` raises ``NotConfigured`` when the extra is not
installed or when the local service URL is not configured, and every lookup raises the
same so the pipeline's ``get_provider`` never hands it out by default.
"""

from __future__ import annotations

import importlib
from typing import Any

from nyabo_mn.core.models import ReceiptVerification, SellerInfo
from nyabo_mn.ebarimt.provider import NotConfigured

SDK_MODULE = "ebarimt_pos_sdk"
NOT_CONFIGURED_MESSAGE = (
	"PosSdkProvider needs the optional extra `nyabo_mn[pos]` (ebarimt-pos-sdk) and a PosAPI 3.0 "
	"service reachable on the local Mongolian network; it cannot run from Frappe Cloud. "
	"Use RegistryProvider (default) or MockProvider."
)


class PosSdkProvider:
	name = "pos_sdk"

	def __init__(self, service_url: str | None = None):
		try:
			self._sdk: Any = importlib.import_module(SDK_MODULE)
		except ImportError as exc:
			raise NotConfigured(NOT_CONFIGURED_MESSAGE) from exc
		if not service_url:
			raise NotConfigured(NOT_CONFIGURED_MESSAGE)
		self.service_url = service_url

	def lookup_seller(self, *, tin: str | None = None, register_no: str | None = None) -> SellerInfo:
		# UNVERIFIED: ebarimt-pos-sdk 0.4.1 exposes merchant-side calls only; no seller lookup
		# was found in its documentation, so this stays unsupported rather than guessed.
		raise NotConfigured(NOT_CONFIGURED_MESSAGE)

	def verify_receipt(self, *, qr_data: str | None, receipt_id: str | None) -> ReceiptVerification:
		raise NotConfigured(NOT_CONFIGURED_MESSAGE)


__all__ = ["NOT_CONFIGURED_MESSAGE", "SDK_MODULE", "PosSdkProvider"]
