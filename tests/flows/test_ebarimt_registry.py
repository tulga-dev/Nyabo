"""RegistryProvider against a fake transport: the documented shapes, every failure mode degrading to
"not found", the register-number path, and the 30-day Supplier cache in the stub."""

from __future__ import annotations

import datetime as dt

import frappe

from nyabo_mn.core.models import SellerInfo
from nyabo_mn.ebarimt import provider as provider_mod
from nyabo_mn.ebarimt.registry import RegistryProvider, parse_get_info, parse_get_tin_info
from nyabo_mn.i18n import mn

TIN = "37200019261"
NOW = dt.datetime(2026, 9, 8, 12, 0)


class FakeFetch:
	def __init__(
		self, responses: dict[str, tuple[int, object]] | None = None, *, raise_on: str | None = None
	):
		self.responses = responses or {}
		self.raise_on = raise_on
		self.calls: list[tuple[str, dict]] = []

	def __call__(self, url: str, params: dict) -> tuple[int, object]:
		self.calls.append((url, params))
		path = url.rsplit("/", 1)[-1]
		if self.raise_on == path:
			raise TimeoutError("read timed out")
		return self.responses.get(path, (404, None))


def _found_body(name: str = "Петровис ХХК", vat_payer: bool = True) -> dict:
	return {
		"status": 200,
		"msg": "success",
		"data": {"name": name, "vatPayer": vat_payer, "found": True, "vatpayerRegisteredDate": "2010-01-01"},
	}


def test_parse_get_info_shapes():
	info = parse_get_info(_found_body(), tin=TIN, register_no="2550385")
	assert info == SellerInfo(
		name="Петровис ХХК", tin=TIN, register_no="2550385", vat_payer=True, found=True, source="registry"
	)
	assert parse_get_info({"status": 200, "data": {"found": False}}, tin=TIN, register_no=None).found is False
	assert parse_get_info({"status": 200, "data": "garbage"}, tin=TIN, register_no=None).found is False
	assert parse_get_info("<html>", tin=TIN, register_no=None).found is False
	assert parse_get_info(_found_body(vat_payer="false"), tin=TIN, register_no=None).vat_payer is False
	assert parse_get_tin_info({"status": 200, "data": TIN}) == TIN
	assert parse_get_tin_info({"status": 200, "data": {"tin": TIN}}) is None
	assert parse_get_tin_info(None) is None


def test_lookup_by_tin_then_by_register_no_and_failures_never_raise():
	fetch = FakeFetch({"getInfo": (200, _found_body()), "getTinInfo": (200, {"status": 200, "data": TIN})})
	registry = RegistryProvider("https://example.test/check/", fetch=fetch, now=lambda: NOW)
	assert registry.lookup_seller(tin=TIN).found is True
	assert fetch.calls[-1] == ("https://example.test/check/getInfo", {"tin": TIN})
	by_reg = registry.lookup_seller(register_no="2550385")
	assert by_reg.found is True and by_reg.tin == TIN and by_reg.register_no == "2550385"
	assert fetch.calls[-2] == ("https://example.test/check/getTinInfo", {"regNo": "2550385"})

	assert registry.lookup_seller().found is False
	assert RegistryProvider(fetch=FakeFetch({"getInfo": (500, None)})).lookup_seller(tin=TIN).found is False
	assert RegistryProvider(fetch=FakeFetch({"getInfo": (200, None)})).lookup_seller(tin=TIN).found is False
	assert RegistryProvider(fetch=FakeFetch(raise_on="getInfo")).lookup_seller(tin=TIN).found is False
	assert (
		RegistryProvider(fetch=FakeFetch(raise_on="getTinInfo")).lookup_seller(register_no="1").found is False
	)

	verification = registry.verify_receipt(qr_data="123", receipt_id="abc")
	assert verification.status == "unsupported" and verification.reason == mn.VERIFICATION_RECEIPT_UNCHECKED
	assert verification.checked_at == NOW


def test_registry_answer_is_cached_on_the_supplier_for_30_days(site):
	frappe.get_doc({"doctype": "Supplier", "supplier_name": "Петровис ХХК", "tin": TIN}).insert(
		ignore_permissions=True
	)
	fetch = FakeFetch({"getInfo": (200, _found_body())})
	clock = {"now": NOW}
	registry = RegistryProvider(fetch=fetch, now=lambda: clock["now"])
	first = registry.lookup_seller(tin=TIN)
	assert first.source == "registry" and len(fetch.calls) == 1
	assert frappe.db.get_value("Supplier", "Петровис ХХК", "ebarimt_vat_payer") == 1
	assert frappe.db.get_value("Supplier", "Петровис ХХК", "ebarimt_checked_at") == NOW

	second = registry.lookup_seller(tin=TIN)
	assert second.source == "supplier_cache" and second.vat_payer is True and second.name == "Петровис ХХК"
	assert len(fetch.calls) == 1  # no network call

	clock["now"] = NOW + dt.timedelta(days=31)
	third = registry.lookup_seller(tin=TIN)
	assert third.source == "registry" and len(fetch.calls) == 2


def test_get_provider_factory(site, frappe_flags):
	from nyabo_mn.ebarimt.mock import MockProvider
	from nyabo_mn.ebarimt.pos_sdk import PosSdkProvider

	assert isinstance(provider_mod.get_provider({}), RegistryProvider)
	assert (
		provider_mod.get_provider({"EBARIMT_API_BASE": "https://x.test/api/"}).base_url
		== "https://x.test/api"
	)
	assert isinstance(provider_mod.get_provider({"EBARIMT_PROVIDER": "mock"}), MockProvider)
	with frappe_flags(nyabo_simulation=True):
		assert isinstance(provider_mod.get_provider({}), MockProvider)
	try:
		provider_mod.get_provider({"EBARIMT_PROVIDER": "pos"})
	except provider_mod.NotConfigured as exc:
		assert "PosAPI" in str(exc)
	else:  # pragma: no cover - only when the optional extra is installed locally
		assert PosSdkProvider is not None
