"""Receipt intake: photo → Nyabo Document + enqueue; duplicates; card send/update helpers."""

from __future__ import annotations

import hashlib

import frappe

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps
from nyabo_mn.telegram.handlers import receipt
from tests.fixtures.telegram.fake_bot import FakeBotApi, link_user, make_proposal, message_update, run

PHOTO = b"\xff\xd8\xff\xe0 fake jpeg bytes"


def _pipeline_recorder(monkeypatch):
	calls: list[str] = []
	monkeypatch.setattr(_deps, "process_receipt", lambda document_name: calls.append(document_name))
	return calls


def test_photo_creates_document_and_enqueues_pipeline(company, monkeypatch):
	calls = _pipeline_recorder(monkeypatch)
	link_user(3001, "Owner", company)
	bot = FakeBotApi(files={"f-photo-1": PHOTO})
	outcome = run(bot, message_update(3001, photo_file_id="f-photo-1", message_id=77))
	doc_name = outcome["result"]["document"]
	doc = frappe.get_doc("Nyabo Document", doc_name)
	assert doc.doc_type == "receipt" and doc.status == "received"
	assert doc.company == company
	assert doc.file_hash == hashlib.sha256(PHOTO).hexdigest()
	assert doc.size_bytes == len(PHOTO)
	assert doc.sender_telegram_id == "3001" and doc.sender_user == "tg-3001@nyabo.local"
	assert doc.telegram_file_id == "f-photo-1"
	assert doc.telegram_chat_id == "3001" and doc.telegram_message_id == "77"
	assert doc.file and doc.file.startswith("/private/files/")
	attached = frappe.get_all(
		"File", filters={"attached_to_doctype": "Nyabo Document", "attached_to_name": doc_name}
	)
	assert len(attached) == 1
	assert frappe.get_doc("File", attached[0].name).get_content() == PHOTO
	assert mn.MSG_RECEIVED_PROCESSING in bot.texts()
	job = frappe.local.enqueued[-1]
	assert job.method.endswith("process_receipt") and job.queue == "long"
	assert job.kwargs == {"document_name": doc_name}
	assert calls == [doc_name]
	# the bot picked the largest photo size and downloaded through getFile
	assert bot.sent("get_file") == [{"file_id": "f-photo-1"}]


def test_duplicate_photo_is_refused(company, monkeypatch):
	calls = _pipeline_recorder(monkeypatch)
	link_user(3002, "Accountant", company)
	bot = FakeBotApi(files={"f1": PHOTO, "f2": PHOTO})
	run(bot, message_update(3002, photo_file_id="f1"))
	bot.clear()
	outcome = run(bot, message_update(3002, photo_file_id="f2"))
	assert bot.last_text == mn.MSG_DUPLICATE_DOCUMENT
	assert outcome["result"]["duplicate"].startswith("NYD-")
	assert frappe.db.count("Nyabo Document") == 1
	assert len(calls) == 1


def test_image_document_is_a_receipt_and_spreadsheet_is_a_statement(company, monkeypatch):
	calls = _pipeline_recorder(monkeypatch)
	imported: list[str] = []
	monkeypatch.setattr(
		_deps,
		"import_statement",
		lambda name: imported.append(name) or {"status": "ok", "bank": "Khan Bank", "count": 0},
	)
	link_user(3003, "Accountant", company)
	bot = FakeBotApi(files={"img": PHOTO, "xlsx": b"PK\x03\x04 sheet"})
	run(
		bot,
		message_update(
			3003,
			document={
				"file_id": "img",
				"file_name": "receipt.png",
				"mime_type": "image/png",
				"file_size": 20,
			},
		),
	)
	assert len(calls) == 1
	run(
		bot,
		message_update(
			3003,
			document={
				"file_id": "xlsx",
				"file_name": "khan.xlsx",
				"mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
				"file_size": 10,
			},
		),
	)
	assert imported and frappe.get_doc("Nyabo Document", imported[0]).doc_type == "bank_statement"
	assert mn.MSG_STATEMENT_RECEIVED in bot.texts()
	assert "Khan Bank" in bot.last_text


def test_unsupported_document_and_too_large_file(company, monkeypatch):
	_pipeline_recorder(monkeypatch)
	link_user(3004, "Accountant", company)
	bot = FakeBotApi(files={"zip": b"zip"})
	run(
		bot,
		message_update(
			3004, document={"file_id": "zip", "file_name": "a.zip", "mime_type": "application/zip"}
		),
	)
	assert bot.last_text == mn.MSG_UNSUPPORTED_FILE
	run(
		bot,
		message_update(
			3004,
			document={
				"file_id": "zip",
				"file_name": "a.csv",
				"mime_type": "text/csv",
				"file_size": 30 * 1024 * 1024,
			},
		),
	)
	assert bot.last_text == mn.MSG_FILE_TOO_LARGE.format(mb=20)


def test_missing_pipeline_module_tells_user_and_admin(company, monkeypatch):
	"""The pipeline exists now; simulate its absence the way _deps reports it."""

	def _missing(document_name: str) -> None:
		raise _deps.DependencyMissing("nyabo_mn.agent.pipeline.process_receipt is not available: dependency")

	monkeypatch.setattr(_deps, "process_receipt", _missing)
	link_user(3005, "Owner", company)
	bot = FakeBotApi(files={"f": PHOTO})
	outcome = run(bot, message_update(3005, photo_file_id="f"))
	assert outcome["error"] == "dependency_missing"
	assert bot.last_text == mn.MSG_FEATURE_UNAVAILABLE or any(
		t == mn.MSG_FEATURE_UNAVAILABLE for t in bot.texts()
	)
	admin_msgs = [kw for kw in bot.sent("send_message") if kw["chat_id"] == 1001]
	assert admin_msgs and "dependency" in admin_msgs[0]["text"]


def test_send_and_update_card(company):
	link_user(3006, "Accountant", company)
	doc = frappe.get_doc(
		{
			"doctype": "Nyabo Document",
			"company": company,
			"doc_type": "receipt",
			"telegram_chat_id": "3006",
			"file": "/private/files/x.jpg",
		}
	)
	doc.insert(ignore_permissions=True)
	proposal = make_proposal(company, document=doc.name)
	bot = FakeBotApi()
	result = receipt.send_proposal_card(proposal.name, bot=bot)
	assert result["sent"] is True and result["chat_id"] == "3006"
	sent = bot.sent("send_message")[0]
	assert sent["text"].startswith("🧾 Петровис ХХК · 2026-08-14 (Ба)")
	assert sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"p:{proposal.name}:ap"
	proposal.reload()
	assert proposal.card_chat_id == "3006" and proposal.card_message_id == str(result["message_id"])

	proposal.db_set(
		{"status": "posted", "posted_doctype": "Journal Entry", "posted_name": "ACC-JV-2026-00001"}
	)
	receipt.update_card(proposal.name, bot=bot)
	edit = bot.sent("edit_message_text")[0]
	assert edit["message_id"] == result["message_id"]
	assert "✅ Бүртгэлээ: ACC-JV-2026-00001" in edit["text"]
	assert edit["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "x:je:ACC-JV-2026-00001:rev"


def test_unhandled_exception_is_reported_not_raised(company, monkeypatch):
	link_user(3007, "Owner", company)

	def boom(*_args, **_kwargs):
		raise RuntimeError("boom")

	monkeypatch.setattr(_deps, "answer_question", boom)
	bot = FakeBotApi()
	outcome = run(bot, message_update(3007, "хэдэн төгрөг үлдсэн бэ?"))
	assert "boom" in outcome["error"]
	assert mn.MSG_ERROR_ADMIN_NOTIFIED in bot.texts()
	assert frappe.local.error_log and frappe.local.error_log[-1].title == "nyabo: telegram.handler_failed"
	assert any(kw["chat_id"] == 1001 for kw in bot.sent("send_message"))
	assert frappe.session.user == "Administrator"  # the session user is restored after the job


def test_card_of_a_real_pipeline_run_reports_the_seller_as_found(run_receipt):
	"""End to end: a MockProvider registry hit must show «Худалдагч ✓ (ТТД)» on the card."""
	proposal = run_receipt("petrovis_fuel")
	assert frappe.parse_json(proposal.verification_json)["seller"]["found"] is True
	bot = FakeBotApi()
	receipt.send_proposal_card(proposal.name, chat_id=3101, bot=bot)
	assert mn.VERIFICATION_SELLER_OK in bot.last_text
	assert mn.VERIFICATION_SELLER_NOT_FOUND not in bot.last_text
