"""Linking: unlinked replies, admin /link, six-digit code consumption, scheduler expiry."""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import state as chat_state
from tests.fixtures.telegram.fake_bot import FakeBotApi, link_user, message_update, run

ADMIN_ID = 1001  # tests/fixtures/site/site_config.json admin_telegram_ids


def test_unlinked_user_gets_not_linked(site):
	bot = FakeBotApi()
	run(bot, message_update(777, "сайн уу"))
	assert bot.last_text == mn.MSG_NOT_LINKED


def test_unlinked_start_and_whoami_are_allowed(site):
	bot = FakeBotApi()
	run(bot, message_update(777, "/start"))
	assert mn.MSG_WELCOME in bot.last_text and mn.MSG_NOT_LINKED in bot.last_text
	run(bot, message_update(777, "/whoami"))
	assert bot.last_text == mn.MSG_YOUR_TELEGRAM_ID.format(telegram_id=777)


def test_invalid_code_is_refused(site):
	bot = FakeBotApi()
	run(bot, message_update(777, "123456"))
	assert bot.last_text == mn.MSG_LINK_CODE_INVALID


def test_admin_link_issues_code_and_user_consumes_it(company):
	bot = FakeBotApi()
	result = run(bot, message_update(ADMIN_ID, f"/link нягтлан {company}"))
	code = result["result"]["code"]
	assert len(code) == 6 and code.isdigit()
	assert code in bot.last_text
	link_code = frappe.get_doc("Nyabo Link Code", code)
	assert link_code.role == "Accountant" and link_code.company == company and link_code.status == "open"

	bot.clear()
	outcome = run(bot, message_update(4242, code))
	assert outcome["result"]["linked"] is True
	link = frappe.get_doc("Nyabo User Link", "4242")
	assert link.role == "Accountant" and link.status == "active"
	assert link.user == "tg-4242@nyabo.local"
	assert [row.company for row in link.companies] == [company]
	assert link.active_company == company
	user = frappe.get_doc("User", "tg-4242@nyabo.local")
	assert user.enabled == 1
	assert "Nyabo Accountant" in frappe.get_roles("tg-4242@nyabo.local")
	assert frappe.db.get_value("Nyabo Link Code", code, "status") == "used"
	assert frappe.db.get_value("Nyabo Link Code", code, "used_by_telegram_id") == "4242"
	assert mn.MSG_LINKED.format(role=mn.ROLE_LABELS["Accountant"], company=company) in bot.texts()
	# first accountant on a company without settings is sent into onboarding
	assert mn.ONB_ASK_VAT in bot.texts()
	settings_name = frappe.db.exists("Nyabo Company Settings", {"company": company})
	assert frappe.db.get_value("Nyabo Company Settings", settings_name, "accountant_telegram_id") == "4242"


def test_link_usage_and_unknown_role(company):
	bot = FakeBotApi()
	run(bot, message_update(ADMIN_ID, "/link"))
	assert bot.last_text == mn.MSG_LINK_USAGE
	run(bot, message_update(ADMIN_ID, f"/link директор {company}"))
	assert bot.last_text == mn.MSG_LINK_ROLE_UNKNOWN
	run(bot, message_update(ADMIN_ID, "/link эзэмшигч Байхгүй ХХК"))
	assert bot.last_text == mn.MSG_LINK_COMPANY_NOT_FOUND.format(company="Байхгүй ХХК")


def test_non_admin_cannot_link(company):
	link_user(5000, "Owner", company)
	bot = FakeBotApi()
	run(bot, message_update(5000, f"/link нягтлан {company}"))
	assert bot.last_text == mn.MSG_ADMIN_ONLY


def test_used_code_cannot_be_reused_and_expired_code_is_refused(company):
	code = chat_state.issue_link_code("Owner", company, issued_by="Administrator")
	chat_state.consume_link_code(code.code, {"id": 6001, "first_name": "Дорж"})
	bot = FakeBotApi()
	run(bot, message_update(6002, code.code))
	assert bot.last_text == mn.MSG_LINK_CODE_INVALID

	stale = chat_state.issue_link_code("Owner", company, issued_by="Administrator")
	stale.expires_at = add_to_date(now_datetime(), minutes=-1)
	stale.save()
	run(bot, message_update(6003, stale.code))
	assert bot.last_text == mn.MSG_LINK_CODE_INVALID
	assert frappe.db.get_value("Nyabo Link Code", stale.code, "status") == "expired"


def test_expire_link_codes_scheduler(company):
	stale = chat_state.issue_link_code("Owner", company, issued_by="Administrator")
	stale.expires_at = add_to_date(now_datetime(), minutes=-5)
	stale.save()
	fresh = chat_state.issue_link_code("Owner", company, issued_by="Administrator")
	chat_state.expire_link_codes()
	assert frappe.db.get_value("Nyabo Link Code", stale.code, "status") == "expired"
	assert frappe.db.get_value("Nyabo Link Code", fresh.code, "status") == "open"


def test_second_company_extends_existing_link(company):
	link = link_user(7000, "Accountant", company)
	assert len(link.companies) == 1
	code = chat_state.issue_link_code("Owner", None, issued_by="Administrator")
	again = chat_state.consume_link_code(code.code, {"id": 7000, "first_name": "Бат"})
	assert again.role == "Accountant"  # a lower role never downgrades an existing link
	assert len(again.companies) == 1


def test_linked_user_sees_menu_on_start(company):
	link_user(7100, "Owner", company)
	bot = FakeBotApi()
	run(bot, message_update(7100, "/start"))
	assert mn.MSG_MENU in bot.last_text
	run(bot, message_update(7100, "/меню"))
	assert mn.MSG_ACTIVE_COMPANY.format(company=company) in bot.last_text
	run(bot, message_update(7100, "/такой"))
	assert bot.last_text == mn.MSG_UNKNOWN_COMMAND


def test_link_code_guessing_is_capped_and_reported(company):
	"""Six digits is the only credential guarding a company's books (SEC-05)."""
	bot = FakeBotApi()
	for _ in range(chat_state.LINK_ATTEMPT_LIMIT - 1):
		run(bot, message_update(778, "000000"))
		assert bot.last_text == mn.MSG_LINK_CODE_INVALID
	run(bot, message_update(778, "000001"))
	assert bot.last_text == mn.MSG_LINK_CODE_TOO_MANY.format(minutes=chat_state.LINK_BLOCK_MINUTES)
	assert frappe.db.exists("Nyabo Event", {"event_type": "link_code_guessing_blocked"})
	assert any(
		kw["chat_id"] == ADMIN_ID and kw["text"] == mn.MSG_ADMIN_LINK_GUESSING.format(chat_id=778)
		for kw in bot.sent("send_message")
	)

	# a real code is refused too while the block holds
	code = chat_state.issue_link_code("Accountant", company, issued_by="Administrator").code
	run(bot, message_update(778, code))
	assert bot.last_text == mn.MSG_LINK_CODE_TOO_MANY.format(minutes=chat_state.LINK_BLOCK_MINUTES)
	assert not frappe.db.exists("Nyabo User Link", "778")

	# once the block lapses the same code still works, and success clears the counter
	frappe.db.set_value(
		"Nyabo Chat State",
		frappe.db.exists("Nyabo Chat State", {"chat_id": "778"}),
		"link_blocked_until",
		add_to_date(now_datetime(), minutes=-1),
	)
	run(bot, message_update(778, code))
	assert frappe.db.get_value("Nyabo User Link", "778", "status") == "active"
	state = frappe.db.get_value(
		"Nyabo Chat State", {"chat_id": "778"}, ["link_attempts", "link_blocked_until"], as_dict=True
	)
	assert not state.link_attempts and not state.link_blocked_until
