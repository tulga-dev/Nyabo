"""Fixtures for the rules/setup flow tests: a synced seed and a v0.3 company with two banks."""

from __future__ import annotations

from typing import Any

import pytest

V03_COMPANY = "Гурав ХХК"
V03_ABBR = "GUR"
BANK_ROWS = [
	{"bank": "Khan Bank", "currency": "MNT", "account_number": "5001234567"},
	{"bank": "Golomt Bank", "currency": "USD"},
]


@pytest.fixture
def seeded(site: Any) -> dict:
	"""The JSON seed synced into the rules DocTypes (what after_install does)."""
	from nyabo_mn.rules import seed

	return seed.sync()


@pytest.fixture
def company_v03(seeded: dict) -> str:
	"""A VAT-registered company on the v0.3 chart with two bank accounts and inventory."""
	from nyabo_mn.setup.provision_company import provision_company

	report = provision_company(
		V03_COMPANY, V03_ABBR, vat_registered=1, chart_scheme="v03", bank_accounts=BANK_ROWS, has_inventory=1
	)
	assert report["verify"]["ok"], report["verify"]["problems"]
	return V03_COMPANY
