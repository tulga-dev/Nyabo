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
from nyabo_mn.telegram import _deps, keyboards
from nyabo_mn.telegram._deps import DependencyMissing
from tests.fixtures.statements import make_fixtures as fixtures
from tests.fixtures.telegram.fake_bot import (
	FakeBotApi,
	callback_update,
	link_user,
	message_update,
	run,
)
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
	# UX-05: this line goes through mn.BANK_NAMES_MN like every other bank name the
	# accountant reads, so it says «Хаан банк», not the layout key.
	assert bot.last_text == mn.MSG_STATEMENT_IMPORTED.format(
		bank=mn.BANK_NAMES_MN["Khan Bank"], count=5, new=5, dup=0, matched=0, unmatched=5
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


def test_a_layout_nobody_confirmed_imports_nothing_and_asks_the_accountant(books):
	"""CORE-08 with ACC-02: the mapping is not re-asked, and the confirmation is the reader's own.

	The sentence used to end «Админд мэдэгдлээ» while this branch notified nobody — the accountant
	was promised something that did not happen, about a person who could not have read their file
	anyway. Now the mapping is shown to the person who has it and the button is theirs.
	"""
	helpers.setup_banks(books)
	helpers.register_layouts()
	frappe.db.set_value("Nyabo Bank Layout", "test_khan_synthetic", "verified", 0)
	filename, data = fixtures.khan_xlsx()
	link_user(9303, "Accountant", books)
	bot = FakeBotApi(files={"stmt": data})
	_send(bot, 9303, filename)
	assert mn.MSG_STATEMENT_LAYOUT_UNVERIFIED.format(layout="test_khan_synthetic") in bot.texts()
	assert bot.callback_datas() == [
		keyboards.rule_data(keyboards.VERIFY_ACCEPT, "b", "test_khan_synthetic"),
		keyboards.rule_data(keyboards.VERIFY_LEAVE, "b", "test_khan_synthetic"),
	]
	assert frappe.db.count("Bank Transaction") == 0
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "9303"}, "state") in (None, "")
	document = frappe.get_last_doc("Nyabo Document")
	assert document.status == "received"  # nothing was extracted from it
	# Nothing waits on an admin, so nothing is sent to one from this branch either.
	assert [kw for kw in bot.sent("send_message") if kw["chat_id"] == 1001] == []


def test_a_refused_layout_records_the_person_who_sent_it_not_the_chat(books):
	"""MINOR 7: the telegram_id on a block row is a *person*, and in a group that is not the chat.

	``run_import`` runs on the worker with only a chat id, and put that number in the field
	``save_layout`` fills with ``ctx.telegram_id``. In a one-to-one chat the two are equal, so it
	worked — and it would be wrong about who did what the moment a company keeps its books in a
	group, which is where a shared bookkeeping chat ends up. The row is read back to finish that
	person's own upload (``verify.blocked_document``), so a chat id there also hands one person's
	stored file to whoever else taps the card.
	"""
	helpers.setup_banks(books)
	helpers.register_layouts()
	frappe.db.set_value("Nyabo Bank Layout", "test_khan_synthetic", "verified", 0)
	filename, data = fixtures.khan_xlsx()
	link_user(9310, "Accountant", books)
	bot = FakeBotApi(files={"stmt": data})

	run(
		bot,
		message_update(
			9310,
			chat_id=-1002000000,
			document={"file_id": "stmt", "file_name": filename, "mime_type": XLSX_MIME, "file_size": 4096},
		),
	)

	blocks = frappe.get_all(
		"Nyabo Event",
		filters={"event_type": mn.EVENT_RULE_BLOCKED},
		fields=["actor_telegram_id", "company", "ref_name"],
	)
	assert [row["actor_telegram_id"] for row in blocks] == ["9310"]
	assert blocks[0]["company"] == books
	# ...and the file that person is waiting on is still found by their own id.
	from nyabo_mn.rules import verify

	assert verify.blocked_document("test_khan_synthetic", books, 9310) == blocks[0]["ref_name"]
	assert verify.blocked_document("test_khan_synthetic", books, -1002000000) is None


def test_the_accountant_confirms_the_layout_and_the_next_statement_imports(books):
	"""ACC-02: the person who read the file confirms the mapping, and the file then goes in.

	The confirmation is per company for the same reason a rule's acceptance is (ACC-01): one
	client's Khan Bank export is not proof about another client's, so the site-wide flag on the
	row stays a site admin's to set. What changes is that nobody has to be found first.
	"""
	from nyabo_mn.rules import verify

	helpers.setup_banks(books)
	helpers.register_layouts()
	frappe.db.set_value("Nyabo Bank Layout", "test_khan_synthetic", "verified", 0)
	filename, data = fixtures.khan_xlsx()
	link_user(9305, "Accountant", books)
	bot = FakeBotApi(files={"first": data})
	_send(bot, 9305, filename, file_id="first")
	assert frappe.db.count("Bank Transaction") == 0

	confirmed = run(
		bot,
		callback_update(9305, keyboards.rule_data(keyboards.VERIFY_ACCEPT, "b", "test_khan_synthetic")),
	)

	assert confirmed["result"]["accepted"] is True
	row = frappe.get_doc(verify.ACCEPTANCE, confirmed["result"]["acceptance"])
	assert row.company == books and row.rule_doctype == "Nyabo Bank Layout"
	assert row.accepted_by == "tg-9305@nyabo.local" and row.accepted_at
	# The global row is untouched: this says «right for my client», not «right for the site».
	assert frappe.db.get_value("Nyabo Bank Layout", "test_khan_synthetic", "verified") == 0
	# The file it stopped is already stored, so it is read on the spot: re-sending it would meet
	# the sha256 dedup and be answered «this document is already here» (§5.3).
	assert mn.MSG_STATEMENT_LAYOUT_REIMPORTING in bot.texts()
	assert frappe.db.count("Bank Transaction") == 5
	assert (
		mn.MSG_STATEMENT_IMPORTED.format(
			bank=mn.BANK_NAMES_MN["Khan Bank"], count=5, new=5, dup=0, matched=0, unmatched=5
		)
		in bot.texts()
	)


def test_the_confirmation_says_what_happens_next_and_not_what_used_to(books):
	"""MINOR 11: «the next statement will be read when you send it again» is not what happens.

	The flow re-imports the file it already has on the spot. An accountant who reads that
	sentence and sends the statement again meets the sha256 dedup and «this document is already
	here» (§5.3) — the message asked them for the one thing Nyabo would refuse.
	"""
	helpers.setup_banks(books)
	helpers.register_layouts()
	frappe.db.set_value("Nyabo Bank Layout", "test_khan_synthetic", "verified", 0)
	filename, data = fixtures.khan_xlsx()
	link_user(9307, "Accountant", books)
	bot = FakeBotApi(files={"first": data})
	_send(bot, 9307, filename, file_id="first")

	run(
		bot,
		callback_update(9307, keyboards.rule_data(keyboards.VERIFY_ACCEPT, "b", "test_khan_synthetic")),
	)

	texts = bot.texts()
	assert mn.MSG_STATEMENT_LAYOUT_ACCEPTED.format(layout="test_khan_synthetic") in texts
	assert mn.MSG_STATEMENT_LAYOUT_REIMPORTING in texts
	assert "дахин илгээ" not in mn.MSG_STATEMENT_LAYOUT_ACCEPTED, (
		"the confirmation must not ask for the file the flow is already re-reading; the sentence "
		"that does ask for it is MSG_STATEMENT_LAYOUT_ACCEPTED_RESEND, on the branch where there "
		"is no stored file to re-read"
	)
	assert "дахин илгээ" in mn.MSG_STATEMENT_LAYOUT_ACCEPTED_RESEND


def test_a_confirmation_the_accountant_came_back_to_still_reads_the_waiting_file(books):
	"""The accountant is called away, confirms twenty minutes later, and the statement still goes in.

	``blocked_document`` is kept to this chat and to REQUEST_DEDUPE_MINUTES because it finishes a
	posting (VER-04). A layout confirmation posts nothing — it re-reads a spreadsheet — and being
	held to the same window meant the card, tapped a little late, answered «send this statement
	again», which the sha256 dedup then refused: a sentence that did not do what it said, with
	nothing after it. The file is found by the books it is waiting for instead.
	"""
	helpers.setup_banks(books)
	helpers.register_layouts()
	frappe.db.set_value("Nyabo Bank Layout", "test_khan_synthetic", "verified", 0)
	filename, data = fixtures.khan_xlsx()
	link_user(9309, "Accountant", books)
	bot = FakeBotApi(files={"first": data})
	_send(bot, 9309, filename, file_id="first")
	assert frappe.db.count("Bank Transaction") == 0
	for row in frappe.get_all("Nyabo Event", filters={"event_type": mn.EVENT_RULE_BLOCKED}, fields=["name"]):
		frappe.db.set_value(
			"Nyabo Event", row["name"], "creation", "2020-01-01 00:00:00", update_modified=False
		)

	run(bot, callback_update(9309, keyboards.rule_data(keyboards.VERIFY_ACCEPT, "b", "test_khan_synthetic")))

	texts = bot.texts()
	assert mn.MSG_STATEMENT_LAYOUT_REIMPORTING in texts
	assert mn.MSG_STATEMENT_LAYOUT_ACCEPTED_RESEND not in texts, (
		"the file is stored, so asking for it again would meet the dedup and end the flow there"
	)
	assert frappe.db.count("Bank Transaction") == 5


def test_a_statement_already_in_the_ledger_is_never_read_a_second_time(books):
	"""``waiting_statement`` is widened by the books, so ``status`` is what keeps it honest."""
	from nyabo_mn.rules import verify

	helpers.setup_banks(books)
	helpers.register_layouts()
	filename, data = fixtures.khan_xlsx()
	link_user(9310, "Accountant", books)
	bot = FakeBotApi(files={"first": data})
	_send(bot, 9310, filename, file_id="first")
	assert frappe.db.count("Bank Transaction") == 5
	document = frappe.get_last_doc("Nyabo Document")
	assert document.status == "extracted"
	# A block row naming a document that has since been read must not resurrect it.
	verify.record_block(
		"test_khan_synthetic", company=books, telegram_id=9310, document=document.name, user="tg-9310"
	)

	assert verify.waiting_statement("test_khan_synthetic", books) is None


def test_a_layout_another_company_confirmed_is_still_refused_here(books, company_v03):
	"""One accountant's reading of a spreadsheet is not evidence about another client's file."""
	from nyabo_mn.rules import verify

	helpers.setup_banks(books)
	helpers.register_layouts()
	frappe.db.set_value("Nyabo Bank Layout", "test_khan_synthetic", "verified", 0)
	verify.accept(verify.KIND_LAYOUT, "test_khan_synthetic", company_v03, "Administrator")
	filename, data = fixtures.khan_xlsx()
	link_user(9306, "Accountant", books)
	bot = FakeBotApi(files={"stmt": data})

	_send(bot, 9306, filename)

	assert frappe.db.count("Bank Transaction") == 0
	assert mn.MSG_STATEMENT_LAYOUT_UNVERIFIED.format(layout="test_khan_synthetic") in bot.texts()


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
	# The worker has no keyboard to draw and notifies nobody, so it promises neither (UX-13).
	assert bot.last_text == mn.MSG_ERROR_NO_BUTTON
	assert not [kw for kw in bot.sent("send_message") if kw.get("reply_markup")]
	assert "psycopg2" not in "\n".join(bot.texts())  # no stack trace, no driver noise
	assert frappe.local.error_log[-1].title == "nyabo: telegram.statement.import_failed"


def test_a_missing_matching_module_tells_the_user_the_feature_is_off(books, monkeypatch):
	def missing(document_name: str):
		raise DependencyMissing("nyabo_mn.matching.bank_import.import_statement is not available")

	monkeypatch.setattr(_deps, "import_statement", missing)
	link_user(9306, "Accountant", books)
	bot = FakeBotApi(files={"stmt": b"PK\x03\x04 sheet"})
	_send(bot, 9306, "khan.xlsx")
	assert bot.last_text == mn.MSG_FEATURE_UNAVAILABLE_NO_BUTTON
	assert not [kw for kw in bot.sent("send_message") if kw.get("reply_markup")]


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


def _one_column_xlsx() -> bytes:
	"""A workbook with a single column: a date, and nothing an amount could be read from."""
	import io as _io

	from openpyxl import Workbook

	wb = Workbook()
	ws = wb.active
	ws.title = "Statement"
	for row in (["Огноо"], ["2026.09.01"], ["2026.09.02"], ["2026.09.03"]):
		ws.append(row)
	buf = _io.BytesIO()
	wb.save(buf)
	return buf.getvalue()


def test_a_statement_with_one_column_is_refused_not_walked_into_a_loop(books):
	"""MINOR: every role answer produced the same refusal, naming a button that is not drawn.

	``missing_for_import`` wants a date column *and* one of amount/debit/credit, and a column
	carries one role, so a single column can never satisfy it. ``_ask_column`` draws Буцах only
	from the second column on, and the refusal names Буцах as the way out — so the accountant
	was asked a question whose every answer came back to a message pointing at a button that
	was not there. The file is refused where it is read instead.
	"""
	link_user(9308, "Accountant", books)
	bot = FakeBotApi(files={"stmt": _one_column_xlsx()})
	_send(bot, 9308, "нэг_багана.xlsx")

	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_TOO_FEW_COLUMNS
	# Not «this file type is unsupported»: xlsx is read fine, it simply has no columns to map.
	assert mn.MSG_UNSUPPORTED_FILE not in bot.texts()
	assert mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Огноо") not in bot.texts()
	assert not bot.callback_datas()  # no question, so no roles to answer it with
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "9308"}, "state") in (None, "")
	assert not frappe.get_all("Nyabo Bank Layout", filters={"layout_id": ["like", "custom-%"]})


def test_a_single_header_never_starts_the_mapping_conversation(books):
	"""The same guard where the headers arrive already picked out, not read off the rows."""
	from nyabo_mn.telegram.handlers import statement

	link_user(9309, "Accountant", books)
	bot = FakeBotApi()
	statement.start_layout_mapping(
		bot,
		9309,
		"NYD-00009",
		{"headers": ["Огноо", "", ""], "preview": [["2026-08-01"]], "preview_rows": [["Огноо"]]},
	)
	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_TOO_FEW_COLUMNS
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "9309"}, "state") in (None, "")
