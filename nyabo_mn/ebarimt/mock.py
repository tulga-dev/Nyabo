"""Fixture-driven ebarimt provider for tests and the simulator (no network).

Sellers come from ``tests/fixtures/receipts/sellers.json`` (``{"<tin>": {"name", "vat_payer",
"register_no"}}``) plus anything added with ``add``. Unknown TINs answer "not found", so a
test can exercise the «Худалдагч бүртгэлд алга» path without a fixture.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from nyabo_mn.core.models import ReceiptVerification, SellerInfo
from nyabo_mn.ebarimt.provider import SOURCE_MOCK, not_found, unsupported_verification

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "receipts" / "sellers.json"

# Built-in sellers so the simulator works even without the fixture file.
BUILTIN_SELLERS: dict[str, dict[str, Any]] = {
	"37200019261": {"name": "Петровис ХХК", "vat_payer": True, "register_no": "2550385"},
	"12345678901": {"name": "Ганбат ганцаарчилсан үйлдвэр", "vat_payer": False, "register_no": "9988776"},
}


class MockProvider:
	name = "mock"

	def __init__(
		self, fixture: Path | str | None = DEFAULT_FIXTURE, *, sellers: dict[str, Any] | None = None
	):
		self.sellers: dict[str, dict[str, Any]] = {k: dict(v) for k, v in BUILTIN_SELLERS.items()}
		if fixture and Path(fixture).is_file():
			with Path(fixture).open(encoding="utf-8") as fh:
				loaded = json.load(fh)
			self.sellers.update({str(k): dict(v) for k, v in loaded.items() if not str(k).startswith("_")})
		if sellers:
			self.sellers.update({str(k): dict(v) for k, v in sellers.items()})
		self.calls: list[dict[str, Any]] = []

	def add(self, tin: str, name: str, vat_payer: bool | None, register_no: str | None = None) -> None:
		self.sellers[str(tin)] = {"name": name, "vat_payer": vat_payer, "register_no": register_no}

	def lookup_seller(self, *, tin: str | None = None, register_no: str | None = None) -> SellerInfo:
		self.calls.append({"tin": tin, "register_no": register_no})
		row = self.sellers.get(str(tin)) if tin else None
		if row is None and register_no:
			for candidate_tin, candidate in self.sellers.items():
				if str(candidate.get("register_no") or "") == str(register_no):
					tin, row = candidate_tin, candidate
					break
		if row is None:
			return not_found(tin=tin, register_no=register_no, source=SOURCE_MOCK)
		return SellerInfo(
			name=str(row.get("name") or ""),
			tin=str(tin),
			register_no=row.get("register_no") or register_no,
			vat_payer=row.get("vat_payer"),
			found=True,
			source=SOURCE_MOCK,
		)

	def verify_receipt(self, *, qr_data: str | None, receipt_id: str | None) -> ReceiptVerification:
		del qr_data, receipt_id
		return unsupported_verification(dt.datetime(2026, 9, 8, 12, 0))


__all__ = ["BUILTIN_SELLERS", "DEFAULT_FIXTURE", "MockProvider"]
