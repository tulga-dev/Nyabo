"""Decode the ebarimt QR code on a receipt photo.

The QR carries an opaque numeric ``qrData`` string (docs/ARCHITECTURE.md §2); we keep it on
the posted document (``ebarimt_qr_data``) for a future verification endpoint and show
«QR уншсан» on the card. Decoding is best effort: ``pyzbar`` (needs the zbar shared
library and Pillow) is tried first, then ``zxing-cpp``; when neither is importable the
function returns ``None`` and logs a ``qr_decoder_missing`` event once per process, so a
missing native library never turns a receipt into a failed job.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("nyabo.ebarimt")

_missing_logged = False


def _log_missing(reason: str) -> None:
	global _missing_logged
	if _missing_logged:
		return
	_missing_logged = True
	try:
		from nyabo_mn.log import log_event

		log_event("qr_decoder_missing", level="warning", reason=reason)
	except Exception:  # noqa: BLE001 - no Frappe site (unit tests, simulator): fall back to logging
		logger.warning("qr decoder missing: %s", reason)


def _open_image(image_bytes: bytes) -> Any:
	import io

	from PIL import Image

	return Image.open(io.BytesIO(image_bytes))


def _decode_pyzbar(image_bytes: bytes) -> str | None:
	from pyzbar import pyzbar

	image = _open_image(image_bytes)
	for symbol in pyzbar.decode(image):
		if getattr(symbol, "type", "QRCODE") == "QRCODE" and symbol.data:
			return symbol.data.decode("utf-8", errors="replace").strip() or None
	return None


def _decode_zxing(image_bytes: bytes) -> str | None:
	import zxingcpp

	image = _open_image(image_bytes)
	for result in zxingcpp.read_barcodes(image):
		text = getattr(result, "text", "") or ""
		if text.strip():
			return text.strip()
	return None


def decode(image_bytes: bytes) -> str | None:
	"""``qrData`` from the first QR found, or ``None``. Never raises."""
	if not image_bytes:
		return None
	missing: list[str] = []
	for label, decoder in (("pyzbar", _decode_pyzbar), ("zxingcpp", _decode_zxing)):
		try:
			value = decoder(image_bytes)
		except ImportError:
			missing.append(label)
			continue
		except Exception as exc:  # noqa: BLE001 - a corrupt image is not a pipeline failure
			logger.info("qr decode with %s failed: %s", label, type(exc).__name__)
			continue
		if value:
			return value
	if len(missing) == 2:
		_log_missing("neither pyzbar nor zxingcpp is importable")
	return None


__all__ = ["decode"]
