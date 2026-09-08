"""MockProvider fixtures, the QR decoder's never-raise contract, the POS SDK stub, and the supplier
matcher's identifier-then-name order."""

from __future__ import annotations

import pytest

from nyabo_mn.core.models import Receipt
from nyabo_mn.ebarimt import NotConfigured, qr
from nyabo_mn.ebarimt.mock import MockProvider
from nyabo_mn.ebarimt.pos_sdk import PosSdkProvider
from nyabo_mn.i18n import mn


def test_mock_provider_answers_from_fixtures_and_extras():
	provider = MockProvider()
	petrovis = provider.lookup_seller(tin="37200019261")
	assert petrovis.found and petrovis.vat_payer is True and petrovis.name == "Петровис ХХК"
	assert petrovis.source == "mock"
	by_reg = provider.lookup_seller(register_no="9988776")
	assert by_reg.found and by_reg.vat_payer is False and by_reg.tin == "12345678901"
	assert provider.lookup_seller(tin="000").found is False
	provider.add("77777777777", "Шинэ ХХК", None)
	assert provider.lookup_seller(tin="77777777777").vat_payer is None
	assert provider.verify_receipt(qr_data=None, receipt_id=None).status == "unsupported"
	assert provider.calls[0] == {"tin": "37200019261", "register_no": None}
	assert (
		MockProvider(fixture=None, sellers={"1": {"name": "X", "vat_payer": True}})
		.lookup_seller(tin="1")
		.name
		== "X"
	)


def test_qr_decode_never_raises():
	assert qr.decode(b"") is None
	assert qr.decode(b"not an image at all") is None
	qr._missing_logged = False
	assert qr.decode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32) is None


def test_pos_sdk_provider_is_not_configured_without_the_extra():
	with pytest.raises(NotConfigured, match="PosAPI 3.0"):
		PosSdkProvider()
	with pytest.raises(NotConfigured):
		PosSdkProvider(service_url="http://localhost:7080")


def test_supplier_match_prefers_identifiers_over_similar_names(site):
	import frappe

	from nyabo_mn.agent import supplier
	from nyabo_mn.core.models import SellerInfo

	frappe.get_doc({"doctype": "Supplier", "supplier_name": "Петровис ХХК", "tin": "111"}).insert(
		ignore_permissions=True
	)
	frappe.get_doc({"doctype": "Supplier", "supplier_name": "Петровис Ойл ХХК", "register_no": "222"}).insert(
		ignore_permissions=True
	)
	receipt = Receipt(
		seller_name="ПЕТРОВИС",
		seller_tin=None,
		seller_register_no="222",
		date=None,
		total=None,
		vat_amount=None,
	)
	assert supplier.match(receipt, None) == "Петровис Ойл ХХК"  # register number beats the name
	name_only = Receipt(
		seller_name="Петровис",
		seller_tin=None,
		seller_register_no=None,
		date=None,
		total=None,
		vat_amount=None,
	)
	assert supplier.match(name_only, None) == "Петровис ХХК"
	nothing = Receipt(
		seller_name="Гэрэл ХХК",
		seller_tin=None,
		seller_register_no=None,
		date=None,
		total=None,
		vat_amount=None,
	)
	assert supplier.match(nothing, None) is None
	info = SellerInfo(
		name="Гэрэл Гэгээ ХХК", tin="999", register_no="333", vat_payer=False, found=True, source="mock"
	)
	created, is_new = supplier.match_or_create("Тест ХХК", nothing, info)
	assert is_new and created == "Гэрэл Гэгээ ХХК"
	row = frappe.db.get_value(
		"Supplier",
		created,
		[
			"tin",
			"tax_id",
			"register_no",
			"supplier_group",
			"supplier_type",
			"nyabo_pending_confirmation",
			"ebarimt_vat_payer",
		],
		as_dict=True,
	)
	assert row.tin == "999" and row.tax_id == "999" and row.register_no == "333"
	assert row.supplier_group == mn.SUPPLIER_GROUP_DEFAULT and row.supplier_type == "Company"
	assert row.nyabo_pending_confirmation == 1 and row.ebarimt_vat_payer == 0
	again, is_new = supplier.match_or_create("Тест ХХК", nothing, info)
	assert again == created and not is_new
	unnamed = Receipt(
		seller_name="", seller_tin=None, seller_register_no=None, date=None, total=None, vat_amount=None
	)
	assert supplier.match_or_create("Тест ХХК", unnamed, None) == (mn.SUPPLIER_NAME_UNKNOWN, True)
