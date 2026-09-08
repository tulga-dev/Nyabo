"""``frappe.utils.pdf.get_pdf`` without wkhtmltopdf: the bytes are the HTML itself.

Signature from frappe/utils/pdf.py (version-16):
``get_pdf(html, options=None, output=None, smart_shrinking=False)``. Tests assert on the
HTML the report produced, not on PDF bytes, so returning the encoded HTML keeps the call
site identical while staying honest about what was rendered.
"""

from __future__ import annotations

from typing import Any


def get_pdf(
	html: str, options: dict[str, Any] | None = None, output: Any = None, smart_shrinking: bool = False
) -> bytes:
	import frappe

	frappe._stub.record_call(
		"get_pdf", html=html, options=dict(options or {}), smart_shrinking=smart_shrinking
	)
	if output is not None:
		raise NotImplementedError("frappe stub: get_pdf(output=PdfWriter) merging is not implemented")
	return html.encode("utf-8")


def prepare_options(html: str, options: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
	return html, dict(options or {})


def cleanup(fname: str, options: dict[str, Any]) -> None:
	return None
