"""import_statement: unknown layouts, idempotent Bank Transaction creation, events."""

from __future__ import annotations

import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.matching import bank_import
from tests.fixtures.statements import make_fixtures as fixtures
from tests.flows import bank_helpers as helpers


@pytest.fixture
def books(company, frappe_hooks):
	with frappe_hooks(without_apps=("nyabo_mn",)):
		yield company


def test_unknown_layout_returns_preview_and_guess(books):
	filename, data = fixtures.khan_xlsx()
	name = helpers.statement_document(books, filename, data)
	summary = bank_import.import_statement(name)
	assert summary["unknown_layout"] is True and summary["status"] == "unknown_layout"
	assert summary["new"] == 0 and summary["transactions"] == []
	assert len(summary["preview_rows"]) == 5
	assert summary["preview_rows"][3][:2] == ["Огноо", "Гүйлгээний утга"]
	# what the column-mapping conversation reads: the header row and the rows under it
	assert summary["headers"][:2] == ["Огноо", "Гүйлгээний утга"]
	assert (
		summary["preview"][0][1] == "Эхний үлдэгдэл" and summary["preview"][1][1] == "Петровис ХХК шатахуун"
	)
	assert summary["company"] == books
	assert summary["guess"]["column_map"]["debit"] == 2 and summary["guess"]["verified"] is False
	assert summary["bank"] == "Khan Bank"
	assert "Огноо" in bank_import.summary_text(summary)
	import frappe

	assert frappe.db.get_value("Nyabo Document", name, "status") == "received"
	assert frappe.db.count("Nyabo Event", {"event_type": "statement_layout_unknown", "ref_name": name}) == 1
	assert frappe.db.count("Bank Transaction") == 0


def test_import_creates_submitted_transactions_idempotently(books):
	import frappe

	banks = helpers.setup_banks(books)
	helpers.register_layouts()
	filename, data = fixtures.khan_xlsx()
	name = helpers.statement_document(books, filename, data)
	summary = bank_import.import_statement(name, run_matching=False)
	assert summary["unknown_layout"] is False
	assert (summary["bank"], summary["layout"]) == ("Khan Bank", "test_khan_synthetic")
	assert (summary["count"], summary["new"], summary["dup"]) == (5, 5, 0)
	assert summary["bank_account"] == banks["khan"]
	rows = frappe.get_all(
		"Bank Transaction",
		fields=[
			"name",
			"docstatus",
			"status",
			"deposit",
			"withdrawal",
			"reference_number",
			"transaction_id",
			"currency",
		],
		order_by="date asc",
	)
	assert len(rows) == 5 and all(r.docstatus == 1 for r in rows)
	assert all(r.status == "Unreconciled" for r in rows)
	assert [(r.withdrawal, r.deposit) for r in rows] == [
		(93500.0, 0.0),
		(1500.0, 0.0),
		(0.0, 1250000.0),
		(200000.0, 0.0),
		(50000.0, 0.0),
	]
	assert rows[0].reference_number == "TX1001" and len(rows[0].transaction_id) == 64
	assert rows[1].reference_number == rows[1].transaction_id  # no bank reference: the row hash
	assert frappe.db.get_value("Nyabo Document", name, "status") == "extracted"
	events = frappe.get_all(
		"Nyabo Event", filters={"event_type": "statement_imported"}, fields=["payload_json"]
	)
	assert len(events) == 1
	payload = bank_import.import_event_payloads(books, banks["khan"])[0]
	assert payload["new"] == 5 and len(payload["transactions"]) == 5 and len(payload["row_hashes"]) == 5
	assert payload["closing_balance"] == "1905000.00" and payload["closing_date"] == "2026-09-06"

	# Same file again (another Nyabo Document): nothing new.
	again = helpers.statement_document(books, filename, data)
	second = bank_import.import_statement(again, run_matching=False)
	assert (second["count"], second["new"], second["dup"]) == (5, 0, 5)
	assert frappe.db.count("Bank Transaction") == 5
	assert mn.MSG_STATEMENT_IMPORTED.split("{")[0] in bank_import.summary_text(second)


def test_csv_cp1251_imports_through_its_own_layout(books):
	import frappe

	helpers.setup_banks(books)
	helpers.register_layouts()
	filename, data = fixtures.khan_csv_cp1251()
	name = helpers.statement_document(books, filename, data)
	summary = bank_import.import_statement(name, run_matching=False)
	assert summary["layout"] == "test_khan_synthetic_cp1251"
	assert (summary["count"], summary["new"]) == (5, 5)
	assert (
		frappe.db.get_value("Bank Transaction", {"withdrawal": 93500.0}, "description")
		== "Петровис ХХК шатахуун"
	)


def test_missing_bank_account_configuration_is_reported(books):
	import frappe

	helpers.register_layouts()
	filename, data = fixtures.golomt_xlsx()
	name = helpers.statement_document(books, filename, data)
	with pytest.raises(bank_import.BankImportError) as info:
		bank_import.import_statement(name)
	assert "Голомт банк" in info.value.message_mn
	assert frappe.db.get_value("Nyabo Document", name, "status") == "failed"


def test_statement_account_number_selects_the_settings_row(books):
	banks = helpers.setup_banks(books)
	filename, data = fixtures.khan_xlsx()
	from nyabo_mn.parsers import excel

	rows = excel.read_rows(data, filename)
	row = bank_import.resolve_bank_row(books, "TDB", "MNT", rows, header_index=3)
	assert (
		row is not None and row["erpnext_bank_account"] == banks["khan"]
	)  # the title block names Khan's account
	# Data rows are never searched: the transfer narrative names the other account.
	assert (
		bank_import.resolve_bank_row(books, "TDB", "MNT", rows[4:], header_index=0)["erpnext_bank_account"]
		== banks["tdb"]
	)
	assert (
		bank_import.resolve_bank_row(books, "TDB", "MNT", [["no numbers here"]])["erpnext_bank_account"]
		== banks["tdb"]
	)
	assert bank_import.resolve_bank_row(books, "XacBank", "MNT", [[]]) is None


def test_learned_layout_blocks_real_import_but_works_under_simulation(books, frappe_flags):
	import frappe

	from nyabo_mn.parsers import excel, layouts

	helpers.setup_banks(books)
	filename, data = fixtures.tdb_xlsx()
	rows = excel.read_rows(data, filename)
	layouts.save_learned_layout(
		"TDB",
		rows[0],
		{
			"0": "date",
			"1": "reference",
			"2": "debit",
			"3": "credit",
			"4": "currency",
			"5": "description",
			"6": "balance",
		},
		books,
		None,
		date_formats=["%Y-%m-%d %H:%M:%S"],
	)
	name = helpers.statement_document(books, filename, data)
	summary = bank_import.import_statement(name)
	assert summary["unknown_layout"] is True and frappe.db.count("Bank Transaction") == 0
	# The mapping question was already answered: the admin verifies the row, nobody re-maps it.
	assert summary["status"] == "unverified_layout" and summary["layout"].startswith("learned_tdb_")
	with frappe_flags(nyabo_simulation=True):
		summary = bank_import.import_statement(name, run_matching=False)
	assert summary["unknown_layout"] is False and summary["new"] == 3
	assert summary["layout"].startswith("learned_tdb_")


def test_xls_upload_fails_the_document_with_a_message(books):
	import frappe

	name = helpers.statement_document(books, "old.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32)
	with pytest.raises(bank_import.BankImportError) as info:
		bank_import.import_statement(name)
	assert info.value.message_mn == mn.MSG_STATEMENT_FILE_XLS_UNSUPPORTED
	assert frappe.db.get_value("Nyabo Document", name, "status") == "failed"


# --- the contract the Telegram worker reads ------------------------------------------------------


def _run_import(document: str, chat_id: int) -> tuple[object, object]:
	"""statement.run_import against the real importer, with a recording bot."""
	from nyabo_mn.telegram import api
	from nyabo_mn.telegram.handlers import statement
	from tests.fixtures.telegram.fake_bot import FakeBotApi

	bot = FakeBotApi()
	with api.use_bot(bot):
		return statement.run_import(document, chat_id), bot


def test_run_import_starts_the_column_mapping_for_an_unknown_layout(books):
	import frappe

	helpers.setup_banks(books)  # no layout registered: the export is unrecognised
	name = helpers.statement_document(books, *fixtures.khan_xlsx())
	result, bot = _run_import(name, 3101)
	assert result == {"ok": True, "mapping": True}
	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Огноо")
	assert any("Огноо | Гүйлгээний утга" in text for text in bot.texts())
	assert not any(text.startswith(mn.MSG_STATEMENT_IMPORTED[:2]) for text in bot.texts())
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "3101"}, "state") == "layout:0"


def test_run_import_asks_the_admin_to_verify_a_learned_layout(books):
	import frappe

	helpers.setup_banks(books)
	layout = helpers.register_layouts(only=["test_khan_synthetic"])[0]
	frappe.db.set_value("Nyabo Bank Layout", layout, "verified", 0)
	name = helpers.statement_document(books, *fixtures.khan_xlsx())
	result, bot = _run_import(name, 3102)
	assert result == {"ok": True, "unverified": True}
	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_UNVERIFIED
	assert frappe.db.count("Bank Transaction") == 0
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "3102"}, "state") in (None, "")


def test_run_import_reports_a_missing_bank_account_in_mongolian(books):
	helpers.register_layouts()  # the Golomt layout is known; no Golomt account is configured
	name = helpers.statement_document(books, *fixtures.golomt_xlsx())
	result, bot = _run_import(name, 3103)
	# The refusal text travels back with the result so the caller can log why, and the
	# accountant sees the Mongolian reason rather than the generic error.
	assert result["ok"] is False and "Голомт банк" in result["refused"]
	assert bot.last_text != mn.MSG_ERROR_ADMIN_NOTIFIED and "Голомт банк" in bot.last_text


def test_run_import_reports_the_imported_statement(books):
	helpers.setup_banks(books)
	helpers.register_layouts()
	name = helpers.statement_document(books, *fixtures.khan_xlsx())
	result, bot = _run_import(name, 3104)
	assert result["ok"] is True and result["summary"]["status"] == "imported"
	assert result["summary"]["new"] == 5
	assert bot.sent("send_message")[-1]["text"].startswith(mn.MSG_STATEMENT_IMPORTED[:2])
