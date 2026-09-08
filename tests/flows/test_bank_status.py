"""/данс: statement balance vs ledger balance per bank account."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.matching import bank_import, status
from tests.fixtures.statements import make_fixtures as fixtures
from tests.flows import bank_helpers as helpers


@pytest.fixture
def books(company, frappe_hooks):
	with frappe_hooks(without_apps=("nyabo_mn",)):
		yield company


def test_status_without_configuration(books):
	assert status.summary(books) == []
	assert status.render(books) == mn.MSG_RECON_NONE


def test_status_math_after_an_import(books):
	banks = helpers.setup_banks(books)
	helpers.register_layouts()
	before = status.summary(books, today=dt.date(2026, 9, 30))
	assert [row["bank"] for row in before] == ["Khan Bank", "TDB"]
	assert all(
		row["statement_balance"] == 0 and row["ledger_balance"] == 0 and row["unmatched"] == 0
		for row in before
	)
	assert before[0]["statement_source"] == "transactions"

	pi = helpers.paid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01", banks["khan_gl"])
	filename, data = fixtures.khan_xlsx()
	bank_import.import_statement(helpers.statement_document(books, filename, data))
	rows = status.summary(books, today=dt.date(2026, 9, 30))
	khan, tdb = rows
	assert khan["statement_source"] == "statement" and khan["as_of"] == dt.date(2026, 9, 6)
	assert khan["statement_balance"] == Decimal("1905000.00")  # closing balance column of the file
	assert khan["ledger_balance"] == Decimal("-93500.00")  # only the paid invoice hit the ledger
	assert khan["diff"] == Decimal("1998500.00")
	assert khan["unmatched"] == 4  # five lines, one reconciled against the invoice
	assert tdb["statement_balance"] == 0 and tdb["unmatched"] == 0
	text = status.render(books, today=dt.date(2026, 9, 30))
	assert (
		"Хаан банк MNT" in text
		and fmt_mnt(1905000) in text
		and fmt_mnt(-93500) in text
		and "2026-09-30" in text
	)
	assert pi.name  # keeps the reference alive for readers of the assertion above


def test_status_falls_back_to_transaction_sum_without_a_balance_column(books):
	import frappe

	helpers.setup_banks(books)
	helpers.register_layouts()
	filename, data = fixtures.transbank_xlsx()
	# Trans Bank is not configured; point its layout at TDB's account through settings instead.
	settings = frappe.get_doc("Nyabo Company Settings", books)
	settings.bank_accounts[1].bank = "Trans Bank"
	settings.flags.ignore_permissions = True
	settings.save()
	summary = bank_import.import_statement(
		helpers.statement_document(books, filename, data), run_matching=False
	)
	assert summary["new"] == 2
	rows = status.summary(books, today=dt.date(2026, 9, 30))
	trans = rows[1]
	assert trans["statement_source"] == "transactions"
	assert trans["statement_balance"] == Decimal("250000.00")  # 1 000 000 in − 750 000 out
	assert trans["unmatched"] == 2
