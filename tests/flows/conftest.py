"""Shared fixtures for the flow tests.

Rules/setup: a synced seed and a v0.3 company with two banks (``seeded``, ``company_v03``).
Receipt pipeline: a company with regimes, verified patterns, a mock LLM and a mock ebarimt
provider, and a helper that stores a receipt photo as a Nyabo Document (``books``,
``store_receipt``, ``mock_llm``, ``mock_provider``, ``run_receipt``).
Evals: ``test_evals_*`` / ``test_simulator_*`` modules run under ``frappe.flags.nyabo_simulation``
(mock clients, verified-rule guard bypassed); other flow modules keep the real guard.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path
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


RECEIPTS = Path(__file__).resolve().parents[1] / "fixtures" / "receipts"
ACCOUNTANT = "acc@example.com"
OWNER = "owner@example.com"
NOBODY = "nobody@example.com"
# 1x1 transparent PNG; the mock client never looks at the pixels, only hashes the bytes.
PNG_1PX = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
PURCHASE_PATTERNS = (
	"purchase_expense_vat_payer",
	"purchase_expense_non_vat",
	"purchase_inventory_vat_payer",
	"purchase_inventory_non_vat",
	"fixed_asset_acquire_vat_payer",
	"fixed_asset_acquire_non_vat",
)


def receipt_payload(name: str) -> dict[str, Any]:
	with (RECEIPTS / f"{name}.json").open(encoding="utf-8") as fh:
		return json.load(fh)


def seed_patterns(verified: bool = True, only: tuple[str, ...] = PURCHASE_PATTERNS) -> list[str]:
	"""Insert the seed posting patterns as DocType rows (the admin's ``verified`` flag lives there)."""
	import frappe

	from nyabo_mn.nyabo.seed import load_seed

	names = []
	for row in load_seed("posting_patterns")["rows"]:
		if row["pattern_id"] not in only or frappe.db.exists("Nyabo Posting Pattern", row["pattern_id"]):
			continue
		citation = row.get("citation") or {}
		doc = frappe.get_doc(
			{
				"doctype": "Nyabo Posting Pattern",
				"pattern_id": row["pattern_id"],
				"name_mn": row["name_mn"],
				"family": row["family"],
				"reference_bullet": row.get("reference_bullet"),
				"document_types": ", ".join(row["document_types"]),
				"applies_to_vat": row.get("applies_to_vat", "any"),
				"applies_to_cit": row.get("applies_to_cit", "any"),
				"conditions": row.get("conditions"),
				"verified": 1 if verified else 0,
				"enabled": 1 if row.get("enabled", True) else 0,
				"primary_document_mn": row.get("primary_document_mn"),
				"citation_instrument": citation.get("instrument"),
				"citation_instrument_full": citation.get("instrument_full"),
				"citation_section": citation.get("section"),
				"citation_quote": citation.get("quote"),
				"citation_url": citation.get("url"),
				"notes": row.get("notes"),
				"lines": [
					{
						"side": line["side"],
						"account_class": line["account_class"],
						"class_name_mn": line.get("class_name_mn"),
						"sub_account_mn": line.get("sub_account_mn"),
						"amount_kind": line["amount_kind"],
						"role": line.get("role"),
						"optional": 1 if line.get("optional") else 0,
						"alternatives_json": json.dumps(line.get("alternatives") or [], ensure_ascii=False),
						"v1_code_hint": line.get("v1_code_hint"),
						"v1_code_range": ",".join(line.get("v1_code_range") or []),
						"class_assumed": 1 if line.get("class_assumed") else 0,
					}
					for line in row["lines"]
				],
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		names.append(doc.name)
	return names


def _ensure_user(email: str, roles: tuple[str, ...] = ()) -> str:
	import frappe

	if not frappe.db.exists("User", email):
		doc = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0]})
		doc.flags.ignore_permissions = True
		doc.insert()
	if roles:
		user = frappe.get_doc("User", email)
		user.flags.ignore_permissions = True
		user.add_roles(*roles)
	return email


@pytest.fixture
def books(company: str) -> str:
	"""Тест ХХК with a V1 chart, VAT payer in 2026, simplified 1% from 2027, verified purchase patterns."""
	import frappe

	settings = frappe.get_doc("Nyabo Company Settings", company)
	settings.chart_scheme = "v1"
	settings.default_expense_code = "6910"
	settings.accountant_user = _ensure_user(ACCOUNTANT)
	settings.append(
		"regimes", {"regime": "vat_payer", "effective_from": "2026-01-01", "effective_to": "2026-12-31"}
	)
	settings.append("regimes", {"regime": "simplified_1pct", "effective_from": "2027-01-01"})
	settings.flags.ignore_permissions = True
	settings.save()
	_ensure_user(OWNER)
	_ensure_user(NOBODY)
	frappe.get_doc(
		{
			"doctype": "Nyabo User Link",
			"telegram_id": "700001",
			"user": OWNER,
			"role": "Owner",
			"status": "active",
			"companies": [{"company": company}],
		}
	).insert(ignore_permissions=True)
	if not frappe.db.exists("Fiscal Year", "2027"):
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": "2027",
				"year_start_date": "2027-01-01",
				"year_end_date": "2027-12-31",
			}
		).insert(ignore_permissions=True)
	seed_patterns(verified=True)
	return company


@pytest.fixture
def store_receipt(books: str) -> Callable[..., str]:
	"""``store_receipt(image_bytes=PNG_1PX)`` -> Nyabo Document name (status received)."""
	import frappe

	counter = {"n": 0}

	def _store(image_bytes: bytes = PNG_1PX, *, company: str = books, mime: str = "image/png") -> str:
		counter["n"] += 1
		# Distinct bytes per call so the sha256 dedup of the Telegram layer would not collapse them.
		payload = image_bytes + counter["n"].to_bytes(2, "big")
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"receipt_{counter['n']}.png",
				"content": payload,
				"is_private": 1,
			}
		)
		file_doc.flags.ignore_permissions = True
		file_doc.insert()
		doc = frappe.get_doc(
			{
				"doctype": "Nyabo Document",
				"company": company,
				"doc_type": "receipt",
				"status": "received",
				"file": file_doc.file_url,
				"file_hash": hashlib.sha256(payload).hexdigest(),
				"mime_type": mime,
				"size_bytes": len(payload),
				"sender_user": ACCOUNTANT,
				"sender_telegram_id": "700002",
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc.name

	return _store


@pytest.fixture
def mock_llm() -> Callable[..., Any]:
	"""``mock_llm("petrovis_fuel", classify={...})`` -> MockLlmClient answering with that receipt."""
	from nyabo_mn.agent.mock_client import MockLlmClient

	def _make(
		receipt: str = "petrovis_fuel", *, classify: dict[str, Any] | None = None, **overrides: Any
	) -> Any:
		client = MockLlmClient()
		payload = receipt_payload(receipt)
		payload["data"].update(overrides)
		client.add("extract", payload)
		if classify is not None:
			client.add("classify", {"data": classify})
		return client

	return _make


@pytest.fixture
def mock_provider() -> Any:
	from nyabo_mn.ebarimt.mock import MockProvider

	return MockProvider()


@pytest.fixture
def run_receipt(
	store_receipt: Callable[..., str], mock_llm: Callable[..., Any], mock_provider: Any
) -> Callable[..., Any]:
	"""``run_receipt("petrovis_fuel", date="2027-01-15")`` -> the Nyabo Proposal document."""
	import frappe

	from nyabo_mn.agent import pipeline

	def _run(
		receipt: str = "petrovis_fuel", *, classify: dict[str, Any] | None = None, **overrides: Any
	) -> Any:
		document = store_receipt()
		client = mock_llm(receipt, classify=classify, **overrides)
		name = pipeline.process_receipt(document, client=client, provider=mock_provider, send=None)
		return frappe.get_doc("Nyabo Proposal", name)

	return _run


@pytest.fixture(autouse=True)
def _simulation_flag(request: pytest.FixtureRequest) -> Iterator[None]:
	"""Only the evals/simulator modules run under the simulation flag (module docstring)."""
	if not request.module.__name__.rsplit(".", 1)[-1].startswith(("test_evals", "test_simulator")):
		yield
		return
	try:
		import frappe
	except ImportError:  # pure-Python run without the stub on the path
		yield
		return
	previous = frappe.local.flags.get("nyabo_simulation")
	frappe.local.flags.nyabo_simulation = True
	try:
		yield
	finally:
		if previous is None:
			frappe.local.flags.pop("nyabo_simulation", None)
		else:
			frappe.local.flags.nyabo_simulation = previous
