"""An unrecognised statement is read, proved against its own balance, and offered as one card.

The founder's case (DECISIONS PRO-04): a Khan Bank export whose columns any accountant can
read was answered with «Огноо» багана юу вэ? six times. Now the keyword guess — or the model's
reading when the keywords cannot — is applied to the whole file, and only a reading the running
balance agrees with reaches the accountant, as one card with [Манай компанид хамаарна]. The
questions are still there, behind [Багана засах] and for the file nothing can read.
"""

from __future__ import annotations

import datetime as dt

import frappe
import pytest

from nyabo_mn.agent import layout
from nyabo_mn.agent.mock_client import MockLlmClient
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.telegram import keyboards
from tests.fixtures.statements import make_fixtures as fixtures
from tests.fixtures.telegram.fake_bot import FakeBotApi, callback_update, link_user, message_update, run
from tests.flows import bank_helpers as helpers

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ENGLISH_HEADERS = ["Txn Date", "Narration", "Dr", "Cr", "Bal", "Ref"]


@pytest.fixture
def books(company, frappe_hooks):
	with frappe_hooks(without_apps=("nyabo_mn",)):
		helpers.setup_banks(company)
		yield company


def _send(bot: FakeBotApi, telegram_id: int, filename: str, file_id: str = "stmt") -> dict:
	return run(
		bot,
		message_update(
			telegram_id,
			document={"file_id": file_id, "file_name": filename, "mime_type": XLSX_MIME, "file_size": 4096},
		),
	)


def english_xlsx(swap: bool = False) -> tuple[str, bytes]:
	"""Headers no keyword knows, under a title block; ``swap`` puts the money in the wrong columns."""
	balances = fixtures._running(fixtures.KHAN_LINES, fixtures.KHAN_OPENING)
	rows: list[list] = [
		["KHAN BANK — account statement"],
		[f"Account {fixtures.KHAN_ACCOUNT_NO}"],
		ENGLISH_HEADERS,
	]
	for line, balance in zip(fixtures.KHAN_LINES, balances, strict=True):
		out, inn = (line["in"], line["out"]) if swap else (line["out"], line["in"])
		rows.append(
			[line["date"].strftime("%Y-%m-%d"), line["text"], out or "", inn or "", balance, line["ref"]]
		)
	return "khan_english.xlsx", fixtures._xlsx(rows)


def _model(columns: list[tuple[int, str]], header_row: int = 2, bank: str = "Khan Bank") -> MockLlmClient:
	client = MockLlmClient()
	client.add(
		"classify",
		{
			"data": {
				"header_row": header_row,
				"bank": bank,
				"columns": [{"index": i, "role": r} for i, r in columns],
				"amount_style": "separate_debit_credit",
				"date_format": None,
				"confidence": 0.9,
				"note": None,
			}
		},
	)
	return client


def _card_head(bank: str) -> str:
	return mn.MSG_STATEMENT_LAYOUT_READ.split("\n")[0].format(bank=mn.BANK_NAMES_MN[bank])


def _accept(layout_id: str, company: str) -> str:
	return keyboards.rule_data(keyboards.VERIFY_ACCEPT, "b", layout_id, company)


KHAN_REAL_HEADERS = [
	"Гүйлгээний огноо",
	"Салбар",
	"Эхний үлдэгдэл",
	"Кредит гүйлгээ",
	"Дебит гүйлгээ",
	"Эцсийн үлдэгдэл",
	"Гүйлгээний утга",
	"Харьцсан данс",
]


def khan_real_shape_xlsx() -> tuple[str, bytes]:
	"""The shape of the founder's own Khan Bank export (2026-09-15): no bank name anywhere, an
	IBAN in the title block, the header on row 7, an opening *and* a closing balance column,
	debits as negative numbers, datetime text. The keyword guess used to take «Эхний үлдэгдэл»
	for the balance, and the accountant was asked about every column."""
	balances = fixtures._running(fixtures.KHAN_LINES, fixtures.KHAN_OPENING)
	rows: list[list] = [
		["", "", "", "", "", "", "Printed Date:", "2026-09-15"],
		["", "", "Депозит дансны дэлгэрэнгүй хуулга"],
		[],
		["Хэрэглэгч:", "", "", "ТЕСТ ХХК", "", "", "Интервал: 2026-09-01-2026-09-30"],
		[],
		["Валютын төрөл:", "", "", "MNT", "", "IBAN:", f"MN06000500{fixtures.KHAN_ACCOUNT_NO}"],
		[],
		KHAN_REAL_HEADERS,
	]
	opening = fixtures.KHAN_OPENING
	for line, balance in zip(fixtures.KHAN_LINES, balances, strict=True):
		rows.append(
			[
				line["date"].strftime("%Y-%m-%d 12:37:45"),
				"5000",
				f"{opening:.2f}",
				f"{line['in']:.2f}",
				f"{-line['out']:.2f}",
				f"{balance:.2f}",
				line["text"],
				line["ref"],
			]
		)
		opening = balance
	rows.append([])
	rows.append(["Нийт:", "", "", f"{sum(line['in'] for line in fixtures.KHAN_LINES):.2f}", "", "", "", ""])
	return "Statement_MNT.xlsx", fixtures._xlsx(rows)


# --- the keyword reading --------------------------------------------------------------------------


def test_the_founders_khan_export_is_read_by_the_keywords_alone_and_proved(books, monkeypatch):
	"""The real shape: two balance columns, negative debits, no bank name — read with no model call."""

	def no_model(company):
		raise AssertionError("the keywords read this file; the model must not be asked")

	monkeypatch.setattr(layout, "default_client", no_model)
	link_user(9400, "Accountant", books)
	bot = FakeBotApi(files={"stmt": khan_real_shape_xlsx()[1]})
	_send(bot, 9400, "Statement_MNT.xlsx")

	card = bot.last_text
	assert card.startswith(_card_head("Khan Bank")), "the bank comes from the IBAN's bank code"
	assert mn.STM_READ_MAPPING_LINE.format(role=mn.COLUMN_ROLES["balance"], header="Эцсийн үлдэгдэл") in card
	assert mn.STM_READ_MAPPING_LINE.format(role=mn.COLUMN_ROLES["debit"], header="Дебит гүйлгээ") in card
	assert mn.STM_READ_MAPPING_LINE.format(role=mn.COLUMN_ROLES["reference"], header="Харьцсан данс") in card
	assert mn.COLUMN_ROLES["balance"] + " = «Эхний үлдэгдэл»" not in card
	closing = fixtures._running(fixtures.KHAN_LINES, fixtures.KHAN_OPENING)[-1]
	assert (
		mn.STM_READ_BALANCE_OK.format(opening=fmt_mnt(fixtures.KHAN_OPENING), closing=fmt_mnt(closing))
		in card
	)
	assert mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Гүйлгээний огноо") not in bot.texts()

	layout_id = frappe.get_all("Nyabo Bank Layout", filters={"verified": 0}, pluck="name")[0]
	assert layout_id.startswith("custom-khan_bank-")
	run(bot, callback_update(9400, _accept(layout_id, books)))
	assert frappe.db.count("Bank Transaction") == 5
	withdrawals = sorted(
		frappe.get_all("Bank Transaction", filters={"withdrawal": [">", 0]}, pluck="withdrawal")
	)
	assert withdrawals == [1500.0, 50000.0, 93500.0, 200000.0], "negative debits are money out"
	assert frappe.get_all("Bank Transaction", filters={"deposit": [">", 0]}, pluck="deposit") == [1250000.0]


def test_a_readable_export_is_offered_once_with_the_figures_the_file_proves(books):
	link_user(9401, "Accountant", books)
	bot = FakeBotApi(files={"stmt": fixtures.khan_xlsx()[1]})
	_send(bot, 9401, "khan.xlsx")

	card = bot.last_text
	assert card.startswith(_card_head("Khan Bank"))
	assert mn.STM_READ_MAPPING_LINE.format(role=mn.COLUMN_ROLES["debit"], header="Зарлага") in card
	assert mn.STM_READ_MAPPING_LINE.format(role=mn.COLUMN_ROLES["credit"], header="Орлого") in card
	assert mn.STM_READ_FACTS.format(count=5, first="2026-09-02", last="2026-09-06") in card
	closing = fixtures._running(fixtures.KHAN_LINES, fixtures.KHAN_OPENING)[-1]
	assert (
		mn.STM_READ_BALANCE_OK.format(opening=fmt_mnt(fixtures.KHAN_OPENING), closing=fmt_mnt(closing))
		in card
	)
	assert mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Огноо") not in bot.texts()

	document = frappe.get_last_doc("Nyabo Document").name
	row = frappe.get_all(
		"Nyabo Bank Layout", filters={"verified": 0}, fields=["name", "header_row_hint", "bank"]
	)
	assert len(row) == 1 and row[0].bank == "Khan Bank" and row[0].header_row_hint == 3
	layout_id = row[0].name
	assert bot.callback_datas() == [
		_accept(layout_id, books),
		f"l:fix:{document}",
		keyboards.rule_data(keyboards.VERIFY_LEAVE, "b", layout_id, books),
	]
	event = frappe.get_last_doc("Nyabo Event", filters={"event_type": "statement_layout_read"})
	payload = frappe.parse_json(event.payload_json)
	assert payload["source"] == layout.SOURCE_KEYWORD and payload["balance_ok"] is True
	assert frappe.db.count("Bank Transaction") == 0, "nothing is imported on a reading alone"
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "9401"}, "state") in (None, "")


def test_accepting_the_reading_imports_the_waiting_file_and_the_next_one_needs_no_card(books):
	link_user(9402, "Accountant", books)
	bot = FakeBotApi(files={"stmt": fixtures.khan_xlsx()[1]})
	_send(bot, 9402, "khan.xlsx")
	layout_id = frappe.get_all("Nyabo Bank Layout", filters={"verified": 0}, pluck="name")[0]

	run(bot, callback_update(9402, _accept(layout_id, books)))
	assert mn.MSG_STATEMENT_LAYOUT_REIMPORTING in bot.texts()
	assert frappe.db.count("Bank Transaction") == 5
	assert bot.last_text == mn.MSG_STATEMENT_IMPORTED.format(
		bank=mn.BANK_NAMES_MN["Khan Bank"], count=5, new=5, dup=0, matched=0, unmatched=5
	)
	# The site-wide flag is still a site admin's; the acceptance is this company's.
	assert frappe.db.get_value("Nyabo Bank Layout", layout_id, "verified") == 0


# --- the model reading ------------------------------------------------------------------------------


def test_headers_no_keyword_knows_are_read_by_the_model_and_proved_by_the_balance(books, monkeypatch):
	client = _model(
		[(0, "date"), (1, "description"), (2, "debit"), (3, "credit"), (4, "balance"), (5, "reference")]
	)
	monkeypatch.setattr(layout, "default_client", lambda company: client)
	link_user(9403, "Accountant", books)
	bot = FakeBotApi(files={"stmt": english_xlsx()[1]})
	_send(bot, 9403, "khan_english.xlsx")

	card = bot.last_text
	assert card.startswith(_card_head("Khan Bank"))
	assert mn.STM_READ_MAPPING_LINE.format(role=mn.COLUMN_ROLES["debit"], header="Dr") in card
	assert mn.STM_READ_FACTS.format(count=5, first="2026-09-02", last="2026-09-06") in card
	assert mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Txn Date") not in bot.texts()
	call = client.calls[0]
	assert call.purpose == "classify" and call.prompt_version == "statement_layout.v1"
	assert 'label="statement_rows"' in call.user_text and "row 2: Txn Date | Narration" in call.user_text
	event = frappe.get_last_doc("Nyabo Event", filters={"event_type": "statement_layout_read"})
	assert frappe.parse_json(event.payload_json)["source"] == layout.SOURCE_MODEL
	row = frappe.get_all("Nyabo Bank Layout", filters={"verified": 0}, fields=["column_map_json", "bank"])
	assert row[0].bank == "Khan Bank"
	assert frappe.parse_json(row[0].column_map_json)["credit"] == "Cr"

	layout_id = frappe.get_all("Nyabo Bank Layout", filters={"verified": 0}, pluck="name")[0]
	run(bot, callback_update(9403, _accept(layout_id, books)))
	assert frappe.db.count("Bank Transaction") == 5
	deposits = frappe.get_all("Bank Transaction", filters={"deposit": [">", 0]}, pluck="deposit")
	assert deposits == [1250000.0], "money in is the Cr column, as the balance proved"


def test_a_reading_the_balance_refutes_never_reaches_the_accountant(books, monkeypatch):
	"""The model swaps Dr and Cr; the running balance disagrees on every row; the questions are asked."""
	client = _model(
		[(0, "date"), (1, "description"), (2, "credit"), (3, "debit"), (4, "balance"), (5, "reference")]
	)
	monkeypatch.setattr(layout, "default_client", lambda company: client)
	link_user(9404, "Accountant", books)
	bot = FakeBotApi(files={"stmt": english_xlsx()[1]})
	_send(bot, 9404, "khan_english.xlsx")

	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Txn Date")
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "9404"}, "state") == "layout:0"
	assert frappe.db.count("Nyabo Bank Layout", {"verified": 0}) == 0, "a refuted reading is not stored"
	assert not any(t.startswith(_card_head("Khan Bank")) for t in bot.texts())


def test_a_model_that_fails_leaves_the_questions(books, monkeypatch):
	class Broken:
		def structured(self, **kwargs):
			raise RuntimeError("no key")

	monkeypatch.setattr(layout, "default_client", lambda company: Broken())
	link_user(9405, "Accountant", books)
	bot = FakeBotApi(files={"stmt": english_xlsx()[1]})
	_send(bot, 9405, "khan_english.xlsx")
	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Txn Date")


# --- fixing a reading -------------------------------------------------------------------------------


def test_fix_opens_the_questions_on_the_stored_file_and_the_answers_replace_the_reading(books):
	link_user(9406, "Accountant", books)
	bot = FakeBotApi(files={"stmt": fixtures.khan_xlsx()[1]})
	_send(bot, 9406, "khan.xlsx")
	document = frappe.get_last_doc("Nyabo Document").name
	layout_id = frappe.get_all("Nyabo Bank Layout", filters={"verified": 0}, pluck="name")[0]

	run(bot, callback_update(9406, f"l:fix:{document}"))
	assert mn.MSG_STATEMENT_LAYOUT_FIX_START in bot.texts()
	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Огноо")
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "9406"}, "state") == "layout:0"
	# The card's buttons are taken away so the reading cannot be accepted after it was doubted.
	edited = bot.sent("edit_message_reply_markup")[-1]
	assert edited["reply_markup"] == keyboards.empty_markup()

	for index, role in enumerate(["date", "description", "debit", "credit", "ignore", "reference"]):
		run(bot, callback_update(9406, f"l:{index}:{role}"))
	rows = frappe.get_all("Nyabo Bank Layout", filters={"verified": 0}, fields=["name", "column_map_json"])
	assert [r.name for r in rows] == [layout_id], "the answers land on the reading's own row"
	assert "balance" not in frappe.parse_json(rows[0].column_map_json)
	assert mn.MSG_STATEMENT_LAYOUT_SAVED.format(layout=layout_id) in bot.texts()


def test_fix_is_the_accountants_button(books):
	link_user(9407, "Owner", books)
	bot = FakeBotApi(files={"stmt": fixtures.khan_xlsx()[1]})
	_send(bot, 9407, "khan.xlsx")
	document = frappe.get_last_doc("Nyabo Document").name
	run(bot, callback_update(9407, f"l:fix:{document}"))
	assert bot.last_text == mn.MSG_NO_PERMISSION
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "9407"}, "state") in (None, "")


def test_the_check_is_the_balance_not_the_headers():
	"""Pure: a swapped debit/credit reads fine as text and fails on every row of the balance."""
	from nyabo_mn.core.statements import LayoutSpec, check_layout

	balances = fixtures._running(fixtures.KHAN_LINES, fixtures.KHAN_OPENING)
	rows: list[list] = [["title"], ["Огноо", "Утга", "Зарлага", "Орлого", "Үлдэгдэл"]]
	for line, balance in zip(fixtures.KHAN_LINES, balances, strict=True):
		rows.append([line["date"], line["text"], line["out"] or None, line["in"] or None, balance])
	right = LayoutSpec(
		layout_id="t",
		bank="Other",
		column_map={"date": 0, "description": 1, "debit": 2, "credit": 3, "balance": 4},
		header_row_hint=1,
	)
	wrong = LayoutSpec(
		layout_id="t",
		bank="Other",
		column_map={"date": 0, "description": 1, "debit": 3, "credit": 2, "balance": 4},
		header_row_hint=1,
	)
	good = check_layout(rows, right)
	assert good.ok and good.balance_checked == 4 and good.balance_agreed == 4
	assert good.opening_balance == fixtures.KHAN_OPENING and good.closing_balance == balances[-1]
	assert good.first_date == dt.date(2026, 9, 2)
	bad = check_layout(rows, wrong)
	assert not bad.ok and bad.balance_agreed == 0
	# Without a balance column the file cannot refute the reading, and the card must say so.
	blind = LayoutSpec(
		layout_id="t",
		bank="Other",
		column_map={"date": 0, "description": 1, "debit": 2, "credit": 3},
		header_row_hint=1,
	)
	assert check_layout(rows, blind).ok and check_layout(rows, blind).balance_ok is None


def test_a_statement_that_sat_unread_can_be_put_back_through_the_reader(books):
	"""``api.reread_statement``: the stored file, the same worker, the card in the same chat."""
	from nyabo_mn import api
	from nyabo_mn.telegram import api as telegram_api

	link_user(9408, "Accountant", books)
	bot = FakeBotApi(files={"stmt": khan_real_shape_xlsx()[1]})
	_send(bot, 9408, "Statement_MNT.xlsx")
	document = frappe.get_last_doc("Nyabo Document").name
	first_cards = sum(1 for t in bot.texts() if t.startswith(_card_head("Khan Bank")))

	frappe.set_user("Administrator")
	with telegram_api.use_bot(bot):
		result = api.reread_statement(document)
	assert result == {"document": document, "chat_id": "9408", "queued": True}
	# The reading's row is already stored, so the second pass is the confirmation of that row —
	# the accountant is asked once more, never a question per column, and no twin row appears.
	layout_id = frappe.get_all("Nyabo Bank Layout", filters={"verified": 0}, pluck="name")
	assert len(layout_id) == 1
	assert mn.MSG_STATEMENT_LAYOUT_UNVERIFIED.format(layout=layout_id[0]) in bot.texts()
	assert sum(1 for t in bot.texts() if t.startswith(_card_head("Khan Bank"))) == first_cards
	assert mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Гүйлгээний огноо") not in bot.texts()
