"""The inventory intake chain end to end, through ``_deps`` against the real functions.

Why this file exists: the onboarding flow tests monkeypatch every ``_deps`` shim, so the seam
between the chat layer and ``setup.inventory_intake`` was never executed by any test, and it
shipped wired wrong in two ways at once - the spreadsheet path called ``parse_table`` with a
file, and ``create_intake`` was called in the chat's argument order, which sent the Telegram
user id ("tg-...@nyabo.local") into ``posting_date`` and crashed on the live site.

``tests/unit/test_telegram_deps.py`` now binds every shim's arguments to its target, which
catches the wrong *number* of arguments. It cannot catch the wrong *order* between two strings,
so these tests do what the accountant does: send a list, tap Батлах, and look at what was
written. Nothing here is monkeypatched below the bot API.
"""

from __future__ import annotations

import io

import frappe
import pytest
from frappe.utils import getdate, today

from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.setup import inventory_intake as intake
from nyabo_mn.telegram import _deps, keyboards
from tests.fixtures.telegram.fake_bot import FakeBotApi, callback_update, link_user, message_update, run

TEXT_LIST = "Хор, 5, 45 000\nЦаас А4, 10, 12 500"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(rows: list[list[object]]) -> bytes:
	"""A real .xlsx upload, so ``read_rows`` does the work it does for an owner's file."""
	from openpyxl import Workbook

	workbook = Workbook()
	sheet = workbook.active
	for row in rows:
		sheet.append(row)
	buffer = io.BytesIO()
	workbook.save(buffer)
	return buffer.getvalue()


def _to_inventory_step(uid: int, company: str) -> FakeBotApi:
	"""Walk the wizard to the inventory question; the conversation itself is another agent's."""
	link_user(uid, "Accountant", company)
	bot = FakeBotApi()
	run(bot, message_update(uid, "/эхлэх"))
	run(bot, callback_update(uid, "o:vat:no"))
	run(bot, callback_update(uid, "o:400m:yes"))
	run(bot, callback_update(uid, "o:banks:done"))
	run(bot, callback_update(uid, "o:inv:yes"))
	bot.clear()
	return bot


# --- the shims, called the way the handler calls them --------------------------------------------


def test_deps_turns_a_typed_list_into_a_draft_intake(company_v03):
	items = _deps.inventory_parse_text(TEXT_LIST)
	assert items == [
		{"item_name": "Хор", "qty": 5.0, "uom": "ш", "rate": 45000.0, "amount": 225000.0},
		{"item_name": "Цаас А4", "qty": 10.0, "uom": "ш", "rate": 12500.0, "amount": 125000.0},
	]

	name = _deps.inventory_create_intake(company_v03, items, "text", "tg-6609746064@nyabo.local")

	# A name, not a Document: the handler puts this straight into callback data.
	assert isinstance(name, str) and name.startswith("NYI-")
	doc = frappe.get_doc(intake.DOCTYPE, name)
	assert (doc.company, doc.source, doc.status) == (company_v03, "text", "draft")
	# The user id used to land here and blow up as an isoformat string.
	assert getdate(doc.posting_date) == getdate(today())
	assert doc.total_amount == 350000.0
	assert [(r.item_name, r.qty, r.rate, r.uom) for r in doc.items] == [
		("Хор", 5.0, 45000.0, "ш"),
		("Цаас А4", 10.0, 12500.0, "ш"),
	]


def test_deps_reads_a_spreadsheet_upload_and_files_it(company_v03):
	content = _xlsx([["Нэр", "Тоо", "Нэгж үнэ"], ["Хор", 5, 45000], ["Цаас А4", 10, 12500]])
	items = _deps.inventory_parse_table(content, "бараа.xlsx")
	assert [(i["item_name"], i["qty"], i["rate"]) for i in items] == [
		("Хор", 5.0, 45000.0),
		("Цаас А4", 10.0, 12500.0),
	]

	name = _deps.inventory_create_intake(
		company_v03, items, "excel", "Administrator", file_url="/private/files/бараа.xlsx"
	)
	doc = frappe.get_doc(intake.DOCTYPE, name)
	assert (doc.source, doc.file) == ("excel", "/private/files/бараа.xlsx")
	assert doc.total_amount == 350000.0


def test_deps_post_confirms_the_intake_the_tap_approved(company_v03):
	items = _deps.inventory_parse_text(TEXT_LIST)
	name = _deps.inventory_create_intake(company_v03, items, "text", "Administrator")

	created = _deps.inventory_post_intake(name, "Administrator")

	# post_intake refuses a draft, so the shim must record the tap as the confirmation first.
	assert created["items"] == ["Хор", "Цаас А4"]
	assert created["journal_entry"].startswith("ACC-JV-")
	doc = frappe.get_doc(intake.DOCTYPE, name)
	assert (doc.status, doc.confirmed_by) == ("posted", "Administrator")
	with pytest.raises(frappe.ValidationError, match="аль хэдийн"):
		_deps.inventory_post_intake(name, "Administrator")


def _state(chat_id: int) -> str | None:
	return frappe.db.get_value("Nyabo Chat State", {"chat_id": str(chat_id)}, "state")


def _at_the_confirmation_card(uid: int, company: str) -> tuple[FakeBotApi, str]:
	"""A real draft intake, waiting for [Батлах]: what every way out of that step meets."""
	bot = _to_inventory_step(uid, company)
	run(bot, message_update(uid, TEXT_LIST))
	name = bot.callback_datas()[0].split(":")[1]
	assert frappe.db.get_value(intake.DOCTYPE, name, "status") == "draft"
	return bot, name


@pytest.mark.parametrize("way_out", ["алгасах", "цуцлах", "буцах", "tapped_cancel_button"])
def test_leaving_the_confirmation_card_cancels_the_draft_it_leaves_behind(company_v03, way_out):
	"""MINOR: the draft was inserted when the card was drawn and nothing ever closed it.

	It could not reach the ledger — ``post_intake`` refuses anything but a confirmed intake —
	but the rows piled up in the desk with no explanation. Cancelling is a status, not a
	delete: this app corrects by reversal and keeps its trail.
	"""
	uid = 9310 + len(way_out)
	bot, name = _at_the_confirmation_card(uid, company_v03)

	if way_out == "tapped_cancel_button":
		run(bot, callback_update(uid, f"i:{name}:cancel"))
	else:
		run(bot, message_update(uid, way_out))

	assert frappe.db.get_value(intake.DOCTYPE, name, "status") == "cancelled"
	# The row is still there to read, with its rows and its total: cancelled, not deleted.
	assert frappe.get_doc(intake.DOCTYPE, name).total_amount == 350000.0
	# …and a cancelled intake can never be talked into the ledger afterwards.
	with pytest.raises(frappe.ValidationError):
		intake.confirm_intake(name, "Administrator")
	with pytest.raises(frappe.ValidationError):
		intake.post_intake(name, "Administrator")


def test_leaving_the_wizard_after_the_post_cancels_nothing(company_v03, caplog):
	"""MINOR: the ordinary «confirm the stock, then leave» handed a posted intake to cancel.

	``handle_intake_callback`` sets ``inventory_posted`` but leaves ``payload["intake"]``, and
	``_forget_inventory_list`` popped the key and cancelled whatever it found. The opening entry
	is in the ledger and only a reversal takes it back (principle 5), so the refusal was correct
	and the call was the mistake — an error line in the log on the happy path.
	"""
	import logging

	uid = 9309
	bot, name = _at_the_confirmation_card(uid, company_v03)
	run(bot, callback_update(uid, f"i:{name}:confirm"))
	assert frappe.db.get_value(intake.DOCTYPE, name, "status") == "posted"
	assert _state(uid) == "onb:acc_name"

	with caplog.at_level(logging.ERROR, logger="frappe.nyabo"):
		run(bot, message_update(uid, "цуцлах"))

	assert _state(uid) in (None, "")
	assert frappe.db.get_value(intake.DOCTYPE, name, "status") == "posted"
	assert "intake_cancel_failed" not in caplog.text, "a filed list has no draft to cancel"


@pytest.mark.parametrize("way_home", ["цэс", "/меню"])
def test_going_home_cancels_the_draft_the_step_leaves_behind(company_v03, way_home):
	"""MINOR: [Цэс] and every slash command threw the conversation away without asking the flow.

	Алгасах, Цуцлах, Буцах and the card's own [Цуцлах] all run the flow's clean-up. ``_go_home``
	(the [Цэс] button and the typed «цэс»/«меню») called ``clear_state`` straight, and the router
	cleared the state for any slash command before handing off — so both left the draft Nyabo
	Inventory Intake behind the confirmation card sitting on the desk with nothing to explain it.
	"""
	uid = 9340 + len(way_home)
	bot, name = _at_the_confirmation_card(uid, company_v03)

	run(bot, message_update(uid, way_home))

	assert _state(uid) in (None, "")
	assert frappe.db.get_value(intake.DOCTYPE, name, "status") == "cancelled"


def test_a_posted_intake_is_never_cancelled(company_v03):
	"""The opening stock is in the ledger; only a reversal takes it out (principle 5)."""
	items = _deps.inventory_parse_text(TEXT_LIST)
	name = _deps.inventory_create_intake(company_v03, items, "text", "Administrator")
	_deps.inventory_post_intake(name, "Administrator")

	with pytest.raises(frappe.ValidationError, match="аль хэдийн"):
		intake.cancel_intake(name, "Administrator")
	assert frappe.db.get_value(intake.DOCTYPE, name, "status") == "posted"


def test_cancelling_twice_is_not_an_error(company_v03):
	"""Буцах then Цуцлах reaches the same draft twice; the second time there is nothing to do."""
	items = _deps.inventory_parse_text(TEXT_LIST)
	name = _deps.inventory_create_intake(company_v03, items, "text", "Administrator")

	intake.cancel_intake(name, "Administrator")
	intake.cancel_intake(name, "Administrator")

	assert frappe.db.get_value(intake.DOCTYPE, name, "status") == "cancelled"


def test_a_bad_line_still_raises_the_mongolian_parse_error(company_v03):
	"""The handler turns this into ONB_INVENTORY_PARSE_FAILED; it must not become a TypeError."""
	with pytest.raises(intake.IntakeParseError):
		_deps.inventory_parse_text("хор, зургаа, их")
	with pytest.raises(intake.IntakeParseError):
		_deps.inventory_parse_table(_xlsx([["a", "b", "c"], ["x", "y", "z"]]), "бараа.xlsx")
	# Dicts that came back from the chat are re-read, not trusted, so a broken one is refused
	# with the same message rather than becoming a 0 ₮ opening balance.
	with pytest.raises(intake.IntakeParseError):
		intake.create_intake(company_v03, "text", [{"item_name": "Хор", "qty": "их", "rate": 5}], today())


# --- the same chain from the chat, with nothing below the bot replaced ----------------------------


def test_owner_types_a_list_and_taps_confirm(company_v03):
	uid = 9301
	bot = _to_inventory_step(uid, company_v03)

	run(bot, message_update(uid, TEXT_LIST))

	assert bot.last_text == mn.ONB_INVENTORY_PARSED.format(count=2, total=fmt_mnt(350000))
	# The card also carries the wizard's escape row, so match the intake's own pair rather
	# than counting buttons: this test is about the chain underneath, not the keyboard.
	data = [d for d in bot.callback_datas() if d.startswith(f"{keyboards.PREFIX_INTAKE}:")]
	assert [d.rsplit(":", 1)[1] for d in data] == ["confirm", "cancel"]
	name = data[0].split(":")[1]
	assert frappe.db.get_value(intake.DOCTYPE, name, "status") == "draft"

	run(bot, callback_update(uid, data[0]))

	created = frappe.parse_json(frappe.db.get_value(intake.DOCTYPE, name, "created_docs_json"))
	journal_entry = created["journal_entry"]
	assert journal_entry in "\n".join(bot.texts())
	je = frappe.get_doc("Journal Entry", journal_entry)
	assert je.docstatus == 1 and je.nyabo_primary_document_ref == name
	assert [(a.debit, a.credit) for a in je.accounts] == [(350000.0, 0.0), (0.0, 350000.0)]
	# …and the wizard moved on to the accountant question, as it did before the plumbing worked.
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": str(uid)}, "state") == "onb:acc_name"


def test_owner_uploads_a_spreadsheet(company_v03):
	uid = 9302
	content = _xlsx(
		[["Нэр", "Тоо", "Нэгж үнэ", "Нэгж"], ["Хор", 5, 45000, "ш"], ["Цаас А4", 10, 12500, None]]
	)
	bot = _to_inventory_step(uid, company_v03)
	bot.files["inv-file-1"] = content

	run(
		bot,
		message_update(
			uid,
			document={"file_id": "inv-file-1", "file_name": "бараа.xlsx", "mime_type": XLSX_MIME},
		),
	)

	assert bot.last_text == mn.ONB_INVENTORY_PARSED.format(count=2, total=fmt_mnt(350000))
	name = bot.callback_datas()[0].split(":")[1]
	doc = frappe.get_doc(intake.DOCTYPE, name)
	assert (doc.source, doc.company, doc.total_amount) == ("excel", company_v03, 350000.0)
	assert getdate(doc.posting_date) == getdate(today())

	# The workbook itself is kept, and the intake points at it: the opening entry this list
	# becomes has to carry the document it came from (Law on Accounting art. 13.7, principle 4).
	uploaded = frappe.get_last_doc("Nyabo Document")
	assert uploaded.doc_type == "inventory" and uploaded.company == company_v03
	assert uploaded.retain_until, "the retention hook must have dated it"
	assert doc.file and doc.file == uploaded.file
	attached = frappe.db.get_value(
		"File", {"attached_to_doctype": "Nyabo Document", "attached_to_name": uploaded.name}, "name"
	)
	assert attached, "the bytes are the record, not just the row"

	run(bot, callback_update(uid, bot.callback_datas()[0]))
	created = frappe.parse_json(frappe.db.get_value(intake.DOCTYPE, name, "created_docs_json"))
	je = frappe.get_doc("Journal Entry", created["journal_entry"])
	# The trail the auditor walks: entry -> intake -> the file the owner sent.
	assert je.nyabo_primary_document_ref == name
	assert frappe.db.get_value(intake.DOCTYPE, name, "file") == uploaded.file


def test_the_same_workbook_sent_twice_is_not_stored_twice(company_v03):
	"""Буцах and send it again: the first Nyabo Document is the record the intake points at."""
	content = _xlsx([["Нэр", "Тоо", "Нэгж үнэ"], ["Хор", 5, 45000]])
	uid = 9303
	bot = _to_inventory_step(uid, company_v03)
	bot.files["inv-file-2"] = content
	upload = message_update(
		uid, document={"file_id": "inv-file-2", "file_name": "бараа.xlsx", "mime_type": XLSX_MIME}
	)
	run(bot, upload)
	first = frappe.get_last_doc("Nyabo Document")

	run(bot, callback_update(uid, "e:onb:back:inv_confirm"))
	run(
		bot,
		message_update(
			uid, document={"file_id": "inv-file-2", "file_name": "бараа.xlsx", "mime_type": XLSX_MIME}
		),
	)

	assert frappe.db.count("Nyabo Document", {"doc_type": "inventory"}) == 1
	name = bot.callback_datas()[0].split(":")[1]
	assert frappe.db.get_value(intake.DOCTYPE, name, "file") == first.file


def test_a_typed_list_files_no_document_and_says_so(company_v03):
	"""There is no file to keep; the intake's own rows are the primary record."""
	uid = 9304
	bot = _to_inventory_step(uid, company_v03)

	run(bot, message_update(uid, TEXT_LIST))

	name = bot.callback_datas()[0].split(":")[1]
	assert not frappe.db.get_value(intake.DOCTYPE, name, "file")
	assert frappe.db.count("Nyabo Document", {"doc_type": "inventory"}) == 0
