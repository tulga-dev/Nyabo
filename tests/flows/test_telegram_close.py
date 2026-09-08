"""/хаалт month-end, corrections, statement layout mapping, bank cards, quality, policy, questions."""

from __future__ import annotations

import frappe

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps
from tests.fixtures.telegram.fake_bot import (
	FakeBotApi,
	callback_update,
	link_user,
	make_proposal,
	message_update,
	run,
)


def test_close_refused_for_owner(company, monkeypatch):
	called: list = []
	monkeypatch.setattr(_deps, "checklist", lambda c, p: called.append(("checklist", c, p)) or {})
	link_user(8001, "Owner", company)
	bot = FakeBotApi()
	outcome = run(bot, message_update(8001, "/хаалт 2026-08"))
	assert outcome["result"] == {"refused": "role"}
	assert bot.last_text == mn.MSG_NO_PERMISSION
	assert called == []
	run(bot, callback_update(8001, "c:2026-08:confirm"))
	assert bot.sent("answer_callback_query")[-1]["text"] == mn.MSG_NO_PERMISSION


def test_close_usage_and_full_path(company, monkeypatch):
	monkeypatch.setattr(
		_deps,
		"checklist",
		lambda c, p: {
			"open_proposals": 0,
			"unmatched_bank_lines": 1,
			"unverified_documents": 0,
			"pending_suppliers": 0,
			"unverified_rules_used": 0,
		},
	)
	monkeypatch.setattr(
		_deps,
		"summaries",
		lambda c, p: {
			"trial_balance": {"debit": "1250000", "credit": "1250000"},
			"simplified": {"revenue": "900000", "tax": "9000", "quarter": "2026 оны 3-р улирал"},
			"pdfs": [("simplified-2026-08.pdf", b"%PDF-1.4 fake", mn.REPORT_SIMPLIFIED_SUMMARY)],
		},
	)
	locks: list = []
	monkeypatch.setattr(
		_deps, "lock_period", lambda c, p, u: locks.append((c, p, u)) or {"name": "Тест ХХК 2026-08"}
	)
	link_user(8002, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(8002, "/хаалт"))
	assert bot.last_text == mn.MSG_CLOSE_USAGE
	run(bot, message_update(8002, "/хаалт 2026-13"))
	assert bot.last_text == mn.MSG_CLOSE_USAGE

	bot.clear()
	run(bot, message_update(8002, "/хаалт 2026-08"))
	texts = bot.texts()
	assert texts[0].startswith(mn.MSG_CLOSE_HEADER.format(company=company, period="2026 оны 8-р сар"))
	assert "Тулгаагүй банкны гүйлгээ: 1" in texts[0]
	assert "Гүйлгээ баланс: дебет 1 250 000₮ · кредит 1 250 000₮" in texts[0]
	assert "1% татвар 9 000₮" in texts[0]
	doc = bot.sent("send_document")[0]
	assert doc["filename"] == "simplified-2026-08.pdf" and doc["content"].startswith(b"%PDF")
	assert doc["caption"] == mn.MSG_CLOSE_PDF_CAPTION.format(
		title=mn.REPORT_SIMPLIFIED_SUMMARY, period="2026-08"
	)
	assert bot.last_text == mn.MSG_CLOSE_CONFIRM
	assert bot.callback_datas() == ["c:2026-08:confirm", "c:2026-08:cancel"]

	run(bot, callback_update(8002, "c:2026-08:cancel", message_id=901))
	assert bot.sent("edit_message_text")[-1]["text"] == mn.MSG_CLOSE_CANCELLED
	run(bot, callback_update(8002, "c:2026-08:confirm", message_id=901))
	assert locks == [(company, "2026-08", "tg-8002@nyabo.local")]
	assert bot.sent("edit_message_text")[-1]["text"] == mn.MSG_CLOSE_DONE.format(
		period="2026 оны 8-р сар", name="Тест ХХК 2026-08"
	)


def test_close_blocked_message(company, monkeypatch):
	monkeypatch.setattr(_deps, "checklist", lambda c, p: {})
	monkeypatch.setattr(_deps, "summaries", lambda c, p: {})

	def refuse(c, p, u):
		frappe.throw(mn.MSG_PERIOD_NOT_ENDED.format(end_date="2026-09-30"))

	monkeypatch.setattr(_deps, "lock_period", refuse)
	link_user(8003, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(8003, "/хаалт 2026-09"))
	run(bot, callback_update(8003, "c:2026-09:confirm"))
	assert bot.last_text == mn.MSG_CLOSE_BLOCKED.format(
		reason=mn.MSG_PERIOD_NOT_ENDED.format(end_date="2026-09-30")
	)


# --- corrections -------------------------------------------------------------------------------------


def _posted_je(company: str) -> str:
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"company": company,
			"posting_date": "2026-08-14",
			"voucher_type": "Journal Entry",
			"nyabo_primary_document_ref": "Кассын зарлагын баримт №14 (тест)",
			"accounts": [
				{
					"account": frappe.db.get_value(
						"Account", {"account_number": "6210", "company": company}, "name"
					),
					"debit_in_account_currency": 85000,
				},
				{
					"account": frappe.db.get_value(
						"Account", {"account_number": "1110", "company": company}, "name"
					),
					"credit_in_account_currency": 85000,
				},
			],
		}
	)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name


def test_correction_flow_reverses_and_reproposes(company, monkeypatch):
	reversals: list = []
	monkeypatch.setattr(
		_deps,
		"reverse",
		lambda dt, n, code, text, u: (
			reversals.append((dt, n, code, text, u))
			or {"reversal_name": "ACC-JV-2026-00002", "period_closed": True, "original_period": "2026-08"}
		),
	)
	proposals: list = []

	def make_correction_proposal(dt, n, reason, u):
		proposals.append((dt, n, reason, u))
		doc = frappe.get_doc(
			{
				"doctype": "Nyabo Document",
				"company": company,
				"doc_type": "receipt",
				"telegram_chat_id": "8010",
				"file": "/private/files/x.jpg",
			}
		)
		doc.insert(ignore_permissions=True)
		return make_proposal(company, document=doc.name, kind="correction").name

	monkeypatch.setattr(_deps, "make_correction_proposal", make_correction_proposal)
	link_user(8010, "Accountant", company, first_name="Сараа")
	je = _posted_je(company)
	bot = FakeBotApi()
	run(bot, callback_update(8010, f"x:je:{je}:rev"))
	assert mn.MSG_CORRECTION_ASK_REASON in bot.last_text
	assert f"x:{je}:reason:account" in bot.callback_datas()
	run(bot, callback_update(8010, f"x:{je}:reason:account", message_id=31))
	assert reversals == [("Journal Entry", je, "account", mn.CORRECT_WRONG_ACCOUNT, "tg-8010@nyabo.local")]
	texts = bot.texts()
	assert (
		mn.MSG_CORRECTION_DONE.format(
			reversal="ACC-JV-2026-00002", reason=mn.CORRECT_WRONG_ACCOUNT, approver="Сараа"
		)
		in texts
	)
	assert mn.MSG_CORRECTION_PERIOD_CLOSED.format(period="2026-08") in texts
	assert mn.MSG_CORRECTION_NEW_ENTRY_HINT in texts
	assert proposals and proposals[0][0] == "Journal Entry"
	assert bot.last_text.startswith("🧾")  # the new proposal card
	assert bot.callback_datas()[0].endswith(":ap")


def test_correction_duplicate_reason_and_free_text(company, monkeypatch):
	reversals: list = []
	monkeypatch.setattr(
		_deps,
		"reverse",
		lambda dt, n, code, text, u: reversals.append((code, text)) or {"reversal_name": "ACC-JV-2026-00003"},
	)
	made: list = []
	monkeypatch.setattr(_deps, "make_correction_proposal", lambda *a: made.append(a) or None)
	link_user(8011, "Accountant", company)
	je = _posted_je(company)
	bot = FakeBotApi()
	run(bot, callback_update(8011, f"x:je:{je}:rev"))
	run(bot, callback_update(8011, f"x:{je}:reason:dup"))
	assert reversals == [("dup", mn.CORRECT_DUPLICATE)] and made == []
	assert mn.MSG_CORRECTION_NEW_ENTRY_HINT not in bot.texts()

	run(bot, callback_update(8011, f"x:je:{je}:rev"))
	run(bot, callback_update(8011, f"x:{je}:reason:other"))
	assert bot.last_text == mn.MSG_CORRECTION_ASK_TEXT
	run(bot, message_update(8011, "Огноо буруу байсан"))
	assert reversals[-1] == ("other", "Огноо буруу байсан")
	assert len(made) == 1


def test_owner_cannot_correct(company, monkeypatch):
	link_user(8012, "Owner", company)
	je = _posted_je(company)
	bot = FakeBotApi()
	run(bot, callback_update(8012, f"x:je:{je}:rev"))
	assert bot.sent("answer_callback_query")[0]["text"] == mn.MSG_NO_PERMISSION
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "8012"}, "state") in (None, "")


# --- statements and bank cards -----------------------------------------------------------------------


def test_unknown_layout_mapping_conversation(company):
	"""Real bank_import summary (unknown_layout + preview_rows + guess), not an invented shape."""
	from tests.fixtures.statements import make_fixtures as fixtures

	filename, data = fixtures.khan_xlsx()
	link_user(8020, "Accountant", company)
	bot = FakeBotApi(files={"x": data})
	run(
		bot,
		message_update(
			8020,
			document={
				"file_id": "x",
				"file_name": filename,
				"mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
			},
		),
	)
	texts = "\n".join(bot.texts())
	# the accountant is never told an empty import succeeded
	assert (
		mn.MSG_STATEMENT_IMPORTED.format(bank="Хаан банк", count=0, new=0, dup=0, matched=0, unmatched=0)
		not in texts
	)
	assert any(t.startswith(mn.MSG_STATEMENT_LAYOUT_UNKNOWN.split("\n")[0]) for t in bot.texts())
	# the header sits under a title block: the preview shows the header row and what follows it
	assert "Огноо | Гүйлгээний утга | Зарлага | Орлого | Үлдэгдэл | Лавлах" in texts
	assert "2026.09.01 | Эхний үлдэгдэл" in texts
	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Огноо")
	assert "l:0:date" in bot.callback_datas() and "l:0:ignore" in bot.callback_datas()
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "8020"}, "state") == "layout:0"

	run(bot, callback_update(8020, "l:0:date"))
	run(bot, message_update(8020, "юу?"))  # text repeats the current question
	assert bot.last_text == mn.MSG_STATEMENT_LAYOUT_ASK_COLUMN.format(header="Гүйлгээний утга")
	run(bot, callback_update(8020, "l:1:description"))
	run(bot, callback_update(8020, "l:2:debit"))
	run(bot, callback_update(8020, "l:3:credit"))
	run(bot, callback_update(8020, "l:4:balance"))
	run(bot, callback_update(8020, "l:5:reference"))
	layouts = frappe.get_all(
		"Nyabo Bank Layout",
		filters={"bank": "Khan Bank", "verified": 0},
		fields=["name", "column_map_json", "header_signature_json", "amount_style"],
	)
	assert len(layouts) == 1
	assert frappe.parse_json(layouts[0].column_map_json) == {
		"date": "Огноо",
		"description": "Гүйлгээний утга",
		"debit": "Зарлага",
		"credit": "Орлого",
		"balance": "Үлдэгдэл",
		"reference": "Лавлах",
	}
	assert frappe.parse_json(layouts[0].header_signature_json) == [
		"Огноо",
		"Гүйлгээний утга",
		"Зарлага",
		"Орлого",
		"Үлдэгдэл",
		"Лавлах",
	]
	assert layouts[0].amount_style == "separate_debit_credit"
	assert mn.MSG_STATEMENT_LAYOUT_SAVED.format(layout=layouts[0].name) in bot.texts()
	assert any(kw["chat_id"] == 1001 and layouts[0].name in kw["text"] for kw in bot.sent("send_message"))
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "8020"}, "state") in (None, "")


def test_import_refusal_shows_the_importers_mongolian_text(company):
	"""A recognised layout with no configured bank account must not become "admin notified"."""
	from tests.fixtures.statements import make_fixtures as fixtures
	from tests.flows import bank_helpers

	bank_helpers.register_layouts()
	filename, data = fixtures.khan_xlsx()
	link_user(8021, "Accountant", company)
	bot = FakeBotApi(files={"x": data})
	run(
		bot,
		message_update(
			8021,
			document={
				"file_id": "x",
				"file_name": filename,
				"mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
			},
		),
	)
	assert mn.MSG_STATEMENT_NO_BANK_ACCOUNT.format(bank="Хаан банк") in bot.texts()
	assert mn.MSG_ERROR_ADMIN_NOTIFIED not in bot.texts()


def _bank_transaction(company: str) -> str:
	if not frappe.db.exists("Bank", "Khan Bank"):
		frappe.get_doc({"doctype": "Bank", "bank_name": "Khan Bank"}).insert(ignore_permissions=True)
	gl_account = frappe.db.get_value("Account", {"account_number": "1120", "company": company}, "name")
	bank_account = frappe.get_doc(
		{
			"doctype": "Bank Account",
			"account_name": "Хаан MNT",
			"bank": "Khan Bank",
			"company": company,
			"is_company_account": 1,
			"account": gl_account,
		}
	)
	bank_account.insert(ignore_permissions=True)
	txn = frappe.get_doc(
		{
			"doctype": "Bank Transaction",
			"date": "2026-08-03",
			"bank_account": bank_account.name,
			"company": company,
			"withdrawal": 120000,
			"deposit": 0,
			"description": "Түлш",
			"currency": "MNT",
		}
	)
	txn.flags.ignore_permissions = True
	txn.insert()
	txn.submit()
	return txn.name


def test_bank_card_find_and_reconcile(company, monkeypatch):
	monkeypatch.setattr(
		_deps,
		"find_candidates",
		lambda txn, q: (
			[
				{
					"voucher_doctype": "Journal Entry",
					"voucher_name": "ACC-JV-2026-00001",
					"date": "2026-08-03",
					"amount": 120000,
					"party": "Петровис",
				}
			]
			if q
			else []
		),
	)
	reconciled: list = []
	monkeypatch.setattr(_deps, "reconcile", lambda *a: reconciled.append(a))
	link_user(8030, "Accountant", company)
	txn = _bank_transaction(company)
	bot = FakeBotApi()
	from nyabo_mn.telegram.handlers import bank

	bank.send_bank_card(bot, 8030, txn)
	assert bot.last_text.startswith("🏦 Хаан банк · 2026-08-03 · -120 000₮ · «Түлш»")
	assert bot.callback_datas() == [f"b:{txn}:find", f"b:{txn}:exp", f"b:{txn}:later"]
	run(bot, callback_update(8030, f"b:{txn}:find", message_id=41))
	assert bot.last_text == mn.MSG_BANK_FIND_ASK
	run(bot, message_update(8030, "Петровис"))
	assert "1. ACC-JV-2026-00001 · 2026-08-03 · 120 000₮ · Петровис" in bot.last_text
	assert bot.callback_datas()[0] == f"b:{txn}:m:0"
	run(bot, callback_update(8030, f"b:{txn}:m:0", message_id=42))
	assert reconciled == [(txn, "Journal Entry", "ACC-JV-2026-00001", "tg-8030@nyabo.local")]
	assert bot.sent("edit_message_text")[-1]["text"] == mn.MSG_BANK_MATCHED.format(
		voucher="ACC-JV-2026-00001"
	)
	run(bot, callback_update(8030, f"b:{txn}:later", message_id=41))
	assert bot.sent("answer_callback_query")[-1]["text"] == mn.MSG_BANK_LATER


# --- misc commands -----------------------------------------------------------------------------------


def test_quality_policy_question_and_status(company, monkeypatch):
	monkeypatch.setattr(
		_deps,
		"quality_summary",
		lambda c, days=30: {
			"documents": 12,
			"extraction_accuracy": 0.92,
			"classification_accuracy": 0.8,
			"vat_accuracy": 1.0,
			"automatch_rate": 0.7,
			"false_match_rate": 0.0,
			"latency_s": 9.5,
			"cost_usd_per_document": 0.03,
		},
	)
	monkeypatch.setattr(_deps, "policy_pdf", lambda c: b"%PDF policy")
	monkeypatch.setattr(
		_deps, "answer_question", lambda user, company, text: f"{company}: 1110 данс 500 000₮"
	)
	link_user(8040, "Admin", company)
	bot = FakeBotApi()
	run(bot, message_update(8040, "/чанар"))
	assert "Танилт (дүн/огноо/НӨАТ): 92%" in bot.last_text and "$0.03" in bot.last_text
	run(bot, message_update(8040, "/бодлого"))
	doc = bot.sent("send_document")[0]
	assert (
		doc["content"] == b"%PDF policy"
		and doc["filename"].endswith(".pdf")
		and doc["caption"] == mn.MSG_POLICY_GENERATED
	)
	run(bot, message_update(8040, "кассын үлдэгдэл хэд вэ?"))
	assert bot.last_text == f"{company}: 1110 данс 500 000₮"
	run(bot, message_update(8040, "/status"))
	assert bot.last_text.startswith("🛠")
	run(bot, message_update(8040, "/данс"))
	assert bot.last_text == mn.MSG_RECON_NONE
	run(bot, message_update(8040, "/тусламж"))
	assert mn.MSG_ADMIN_HELP in bot.last_text
