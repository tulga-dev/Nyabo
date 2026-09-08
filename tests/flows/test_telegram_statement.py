"""Bank statement intake over the router: what the accountant is told on every branch.

``handle_document`` stores the file and enqueues ``run_import``; the worker then either
reports the import, starts the column-mapping conversation, refuses an unverified layout,
or replies with the Mongolian message of whatever the importer raised. The mapping
conversation itself is covered in ``test_telegram_close.py``; the branches here are the
ones a real accountant hits first — the same file sent twice, a layout nobody verified,
and a bank that is not in the company's settings.
"""

from __future__ import annotations

import frappe
import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps
from nyabo_mn.telegram._deps import DependencyMissing
from tests.fixtures.statements import make_fixtures as fixtures
from tests.fixtures.telegram.fake_bot import FakeBotApi, link_user, message_update, run
from tests.flows import bank_helpers as helpers

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def books(company, frappe_hooks):
	"""Тест ХХК without the nyabo doc_events, like the other bank flow tests."""
	with frappe_hooks(without_apps=("nyabo_mn",)):
		yield company


def _send(bot: FakeBotApi, telegram_id: int, filename: str, file_id: str = "stmt") -> dict:
	return run(
		bot,
		message_update(
			telegram_id,
			document={"file_id": file_id, "file_name": filename, "mime_type": XLSX_MIME, "file_size": 4096},
		),
	)


def test_a_verified_layout_imports_and_reports_the_counts(books):
	helpers.setup_banks(books)
	helpers.register_layouts()
	filename, data = fixtures.khan_xlsx()
	link_user(9301, "Accountant", books)
	bot = FakeBotApi(files={"stmt": data})
	_send(bot, 9301, filename)
	assert mn.MSG_STATEMENT_RECEIVED in bot.texts()
	# Current behaviour, pinned: the reply prints the raw layout key. Everything else the
	# accountant reads (the no-bank-account message below, /данс) goes through
	# mn.BANK_NAMES_MN and says «Хаан банк»; handing this line the same map is the fix, and
	# then the expected string here becomes "🏦 Хаан банк · 5 гүйлгээ …".
	assert bot.last_text == mn.MSG_STATEMENT_IMPORTED.format(
		bank="Khan Bank", count=5, new=5, dup=0, matched=0, unmatched=5
	)
	assert frappe.db.count("Bank Transaction") == 5


def test_the_same_file_twice_is_refused_before_it_is_imported(books):
	helpers.setup_banks(books)
	helpers.register_layouts()
	filename, data = fixtures.khan_xlsx()
	link_user(9302, "Accountant", books)
	bot = FakeBotApi(files={"first": data, "second": data})
	_send(bot, 9302, filename, file_id="first")
	before = frappe.db.count("Bank Transaction")
	bot.clear()

	outcome = _send(bot, 9302, filename, file_id="second")
	assert bot.last_text == mn.MSG_DUPLICATE_DOCUMENT
	assert outcome["result"]["duplicate"].startswith("NYD-")
	assert frappe.db.count("Nyabo Document", {"doc_type": "bank_statement"}) == 1
	assert frappe.db.count("Bank Transaction") == before  # the lines were not doubled
	assert mn.MSG_STATEMENT_RECEIVED not in bot.texts()


def test_a_layout_nobody_verified_imports_nothing(books):
	"""D-008: a mapping that was never verified must not be re-asked and must not post."""
	helpers.setup_banks(books)
	helpers.register_layouts()
	frappe.db.set_value("Nyabo Bank Layout", "test_khan_synthetic", "verified", 0)
	filename, data = fixtures.khan_xlsx()
	link_user(9303, "Accountant", books)
	bot = FakeBotApi(files={"stmt": data})
	_send(bot, 9303, filename)
	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_UNVERIFIED
	assert frappe.db.count("Bank Transaction") == 0
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "9303"}, "state") in (None, "")
	document = frappe.get_last_doc("Nyabo Document")
	assert document.status == "received"  # nothing was extracted from it
	# Current behaviour, pinned: MSG_STATEMENT_LAYOUT_UNVERIFIED ends «Админд мэдэгдлээ», but
	# this branch sends no admin notice (only the newly saved-layout branch does). Either the
	# branch notifies (notify_admins with the layout id, as save_layout does) or the sentence
	# goes; until then the accountant is promised something that did not happen.
	assert [kw for kw in bot.sent("send_message") if kw["chat_id"] == 1001] == []


def test_a_bank_that_is_not_in_the_settings_says_which_one(books):
	helpers.register_layouts()  # a verified Khan layout, but no bank account configured
	filename, data = fixtures.khan_xlsx()
	link_user(9304, "Accountant", books)
	bot = FakeBotApi(files={"stmt": data})
	_send(bot, 9304, filename)
	assert bot.last_text == mn.MSG_STATEMENT_NO_BANK_ACCOUNT.format(bank="Хаан банк")
	assert frappe.db.count("Bank Transaction") == 0
	document = frappe.get_last_doc("Nyabo Document")
	assert document.status == "failed"
	assert document.error == bot.last_text  # the accountant and the log say the same thing


def test_an_unexpected_failure_is_not_leaked_to_the_chat(books, monkeypatch):
	def boom(document_name: str):
		raise RuntimeError("psycopg2: connection reset")

	monkeypatch.setattr(_deps, "import_statement", boom)
	link_user(9305, "Accountant", books)
	bot = FakeBotApi(files={"stmt": b"PK\x03\x04 sheet"})
	_send(bot, 9305, "khan.xlsx")
	assert bot.last_text == mn.MSG_ERROR_ADMIN_NOTIFIED
	assert "psycopg2" not in "\n".join(bot.texts())  # no stack trace, no driver noise
	assert frappe.local.error_log[-1].title == "nyabo: telegram.statement.import_failed"


def test_a_missing_matching_module_tells_the_user_the_feature_is_off(books, monkeypatch):
	def missing(document_name: str):
		raise DependencyMissing("nyabo_mn.matching.bank_import.import_statement is not available")

	monkeypatch.setattr(_deps, "import_statement", missing)
	link_user(9306, "Accountant", books)
	bot = FakeBotApi(files={"stmt": b"PK\x03\x04 sheet"})
	_send(bot, 9306, "khan.xlsx")
	assert bot.last_text == mn.MSG_FEATURE_UNAVAILABLE


def test_an_unknown_layout_without_a_header_row_cannot_be_mapped(books, monkeypatch):
	monkeypatch.setattr(
		_deps,
		"import_statement",
		lambda name: {"status": "unknown_layout", "bank": "Other", "headers": [], "preview": []},
	)
	link_user(9307, "Accountant", books)
	bot = FakeBotApi(files={"stmt": b"PK\x03\x04 sheet"})
	_send(bot, 9307, "mystery.xlsx")
	assert bot.last_text == mn.MSG_UNSUPPORTED_FILE
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "9307"}, "state") in (None, "")
