"""Ebarimt (и-баримт) providers: seller registry lookup, receipt verification, QR decoding.

See docs/ARCHITECTURE.md §7. The only public data source today is the taxpayer registry;
buyer-side receipt verification is not offered, so every provider answers
``ReceiptVerification(status="unsupported")`` and the card says «Баримт шалгагдаагүй».
"""

from nyabo_mn.ebarimt.provider import (
	EbarimtProvider,
	NotConfigured,
	ReceiptVerification,
	SellerInfo,
	get_provider,
	unsupported_verification,
)

__all__ = [
	"EbarimtProvider",
	"NotConfigured",
	"ReceiptVerification",
	"SellerInfo",
	"get_provider",
	"unsupported_verification",
]
