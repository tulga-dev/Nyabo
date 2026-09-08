"""``/компани``: the chooser, the switch, persistence and the cross-company guard (SEC-06).

An accountant with several clients drives the whole app from one chat, so the active
company is what decides where the next receipt is filed. These tests go through the
router (not the handler) because the guard that matters lives in two places: the handler
refuses a company the link does not carry, and ``state.set_active_company`` refuses it
again for anything that calls it directly.
"""

from __future__ import annotations

import frappe
import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps
from nyabo_mn.telegram import state as chat_state
from tests.fixtures.telegram.fake_bot import FakeBotApi, callback_update, link_user, message_update, run

OTHER_COMPANY = "Хоёр дахь ХХК"
OTHER_ABBR = "HOY"
PHOTO = b"\xff\xd8\xff\xe0 second company receipt"


def _other_company() -> str:
	from nyabo_mn.setup.provision_company import provision_company

	if not frappe.db.exists("Company", OTHER_COMPANY):
		provision_company(OTHER_COMPANY, OTHER_ABBR, vat_registered=0)
	return OTHER_COMPANY


def _link_two(telegram_id: int, company: str) -> str:
	"""One Telegram user linked to two companies, the way two link codes would do it."""
	other = _other_company()
	link_user(telegram_id, "Accountant", company)
	link_user(telegram_id, "Accountant", other)
	return other


def _active(telegram_id: int) -> str | None:
	return frappe.db.get_value("Nyabo User Link", str(telegram_id), "active_company")


def test_a_single_company_answers_without_a_chooser(company):
	link_user(9101, "Owner", company)
	bot = FakeBotApi()
	run(bot, message_update(9101, "/компани"))
	assert bot.last_text == mn.MSG_ACTIVE_COMPANY.format(company=company)
	assert bot.last_markup() is None


def test_a_link_without_a_company_is_sent_to_the_admin(company):
	link_user(9102, "Owner", None)
	bot = FakeBotApi()
	run(bot, message_update(9102, "/компани"))
	assert bot.last_text == mn.MSG_NO_COMPANY


def test_two_companies_show_a_chooser_and_the_tap_switches(company):
	other = _link_two(9103, company)
	bot = FakeBotApi()
	run(bot, message_update(9103, "/компани"))
	assert bot.last_text == mn.MSG_CHOOSE_COMPANY
	assert bot.callback_datas() == ["k:0", "k:1"]
	buttons = [b["text"] for row in bot.last_markup()["inline_keyboard"] for b in row]
	assert buttons == [company[:40], other[:40]]
	assert _active(9103) == company

	bot.clear()
	outcome = run(bot, callback_update(9103, "k:1", message_id=55))
	assert outcome["result"] == {"company": other}
	edit = bot.sent("edit_message_text")[-1]
	assert edit["message_id"] == 55
	assert edit["text"] == mn.MSG_ACTIVE_COMPANY.format(company=other)
	assert edit["reply_markup"] == {"inline_keyboard": []}  # the chooser is spent
	assert _active(9103) == other

	# The choice survives the next update: /компани now reports the second company.
	bot.clear()
	run(bot, message_update(9103, "/компани"))
	assert bot.last_text == mn.MSG_CHOOSE_COMPANY  # two companies still offer the chooser
	run(bot, callback_update(9103, "k:0", message_id=56))
	assert _active(9103) == company


def test_switching_by_name_needs_the_company_on_the_link(company):
	other = _link_two(9104, company)
	bot = FakeBotApi()
	run(bot, message_update(9104, f"/компани {other}"))
	assert bot.last_text == mn.MSG_ACTIVE_COMPANY.format(company=other)
	assert _active(9104) == other


def test_another_clients_company_is_refused_and_nothing_moves(company):
	"""SEC-06: the accountant of Тест ХХК may not switch into a company they are not linked to."""
	stranger = _other_company()
	link_user(9105, "Accountant", company)
	bot = FakeBotApi()
	outcome = run(bot, message_update(9105, f"/компани {stranger}"))
	assert outcome["result"] is None
	assert bot.last_text == mn.MSG_NO_PERMISSION
	assert _active(9105) == company
	# and the state helper refuses it too, for any caller that skips the handler
	link = chat_state.get_link(9105)
	with pytest.raises(frappe.PermissionError):
		chat_state.set_active_company(link, stranger)
	assert _active(9105) == company


def test_an_index_outside_the_users_own_list_is_refused(company):
	_link_two(9106, company)
	bot = FakeBotApi()
	run(bot, callback_update(9106, "k:9", message_id=57))
	assert bot.last_text == mn.MSG_NO_COMPANY
	assert _active(9106) == company
	bot.clear()
	run(bot, callback_update(9106, "k:x", message_id=58))
	assert bot.last_text == mn.MSG_NO_COMPANY
	assert _active(9106) == company


def test_a_revoked_company_stops_being_active(company):
	"""Access must not outlive the link: the stale ``active_company`` is ignored, not obeyed."""
	other = _link_two(9108, company)
	bot = FakeBotApi()
	run(bot, callback_update(9108, "k:1", message_id=60))
	assert _active(9108) == other

	link = frappe.get_doc("Nyabo User Link", "9108")
	link.companies = [row for row in link.companies if row.company != other]
	link.flags.ignore_permissions = True
	link.save()

	bot.clear()
	run(bot, message_update(9108, "/компани"))
	assert bot.last_text == mn.MSG_ACTIVE_COMPANY.format(company=company)
	assert chat_state.active_company(chat_state.get_link(9108)) == company


def test_the_next_receipt_is_filed_under_the_company_just_chosen(company, monkeypatch):
	documents: list[str] = []
	monkeypatch.setattr(_deps, "process_receipt", lambda document_name: documents.append(document_name))
	other = _link_two(9107, company)
	bot = FakeBotApi(files={"photo-1": PHOTO})
	run(bot, callback_update(9107, "k:1", message_id=59))
	run(bot, message_update(9107, photo_file_id="photo-1"))
	assert documents, bot.texts()
	assert frappe.db.get_value("Nyabo Document", documents[-1], "company") == other
