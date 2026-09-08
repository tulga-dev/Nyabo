"""Match a receipt's seller to an ERPNext Supplier, or create one pending confirmation.

Order of evidence (docs/ARCHITECTURE.md §5.3 step 3): the TIN printed on the receipt or
returned by the registry, then the register number, then a normalised-name match at
``NAME_MATCH_MIN`` (0.9 on ``core.matching.name_similarity``: high on purpose, because a
false supplier match silently books an expense against the wrong party and only the
accountant would notice). Anything created here carries ``nyabo_pending_confirmation = 1``
so the card shows ⚠️ and the month-end checklist counts it.

Supplier is not company-scoped in ERPNext; ``company`` is only used for the event log.
"""

from __future__ import annotations

import logging
from typing import Any

from nyabo_mn.core.matching import name_similarity
from nyabo_mn.core.models import Receipt, SellerInfo
from nyabo_mn.i18n import mn

logger = logging.getLogger("nyabo.agent")

NAME_MATCH_MIN = 0.9
SUPPLIER_TYPE = "Company"


def _digits(value: str | None) -> str | None:
	text = "".join(ch for ch in str(value or "") if ch.isalnum()).strip()
	return text or None


def _by_field(field: str, value: str | None) -> str | None:
	import frappe

	if not value:
		return None
	return frappe.db.get_value("Supplier", {field: value}, "name")


def _by_name(name: str) -> str | None:
	"""Best normalised-name match at or above ``NAME_MATCH_MIN``; ties keep the first row."""
	import frappe

	if not name.strip():
		return None
	best: tuple[float, str] | None = None
	for row in frappe.get_all("Supplier", fields=["name", "supplier_name"]):
		score = name_similarity(name, row.supplier_name or row.name)
		if score >= NAME_MATCH_MIN and (best is None or score > best[0]):
			best = (score, row.name)
	return best[1] if best else None


def ensure_supplier_group(name: str = mn.SUPPLIER_GROUP_DEFAULT) -> str:
	import frappe

	if frappe.db.exists("Supplier Group", name):
		return name
	doc = frappe.get_doc({"doctype": "Supplier Group", "supplier_group_name": name})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def match(receipt: Receipt, seller_info: SellerInfo | None) -> str | None:
	"""The existing Supplier for this seller, or None."""
	tin = _digits((seller_info.tin if seller_info else None) or receipt.seller_tin)
	register_no = _digits((seller_info.register_no if seller_info else None) or receipt.seller_register_no)
	found = _by_field("tin", tin) or _by_field("tax_id", tin) or _by_field("register_no", register_no)
	if found:
		return found
	names = []
	if seller_info and seller_info.found and seller_info.name:
		names.append(seller_info.name)
	if receipt.seller_name:
		names.append(receipt.seller_name)
	for name in names:
		found = _by_name(name)
		if found:
			return found
	return None


def create(receipt: Receipt, seller_info: SellerInfo | None) -> str:
	"""Insert the Supplier with the registry name when we have it, else the printed one."""
	import frappe

	tin = _digits((seller_info.tin if seller_info else None) or receipt.seller_tin)
	register_no = _digits((seller_info.register_no if seller_info else None) or receipt.seller_register_no)
	registry_name = seller_info.name if seller_info and seller_info.found else ""
	supplier_name = (registry_name or receipt.seller_name or "").strip() or mn.SUPPLIER_NAME_UNKNOWN
	if frappe.db.exists("Supplier", supplier_name):
		# Same printed name, different identifiers: keep both parties apart with a suffix.
		supplier_name = f"{supplier_name} ({tin or register_no or frappe.generate_hash(length=4)})"
	values: dict[str, Any] = {
		"doctype": "Supplier",
		"supplier_name": supplier_name,
		"supplier_group": ensure_supplier_group(),
		"supplier_type": SUPPLIER_TYPE,
		"tax_id": tin,
		"tin": tin,
		"register_no": register_no,
		"nyabo_pending_confirmation": 1,
	}
	if seller_info and seller_info.found:
		from frappe.utils import now_datetime

		values["ebarimt_vat_payer"] = 1 if seller_info.vat_payer else 0
		values["ebarimt_checked_at"] = now_datetime()
	doc = frappe.get_doc(values)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def match_or_create(
	company: str, receipt: Receipt, seller_info: SellerInfo | None = None
) -> tuple[str, bool]:
	"""``(supplier_name, is_new)``; the pipeline warns «Шинэ харилцагч» when ``is_new``."""
	existing = match(receipt, seller_info)
	if existing:
		return existing, False
	name = create(receipt, seller_info)
	logger.info("supplier created company=%s supplier=%s", company, name)
	return name, True


__all__ = ["NAME_MATCH_MIN", "SUPPLIER_TYPE", "create", "ensure_supplier_group", "match", "match_or_create"]
