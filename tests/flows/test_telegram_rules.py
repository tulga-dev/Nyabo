"""/дүрэм: the door MSG_UNVERIFIED_RULE_BLOCKED points at, and the refusal that now names it.

The founder's live session is the case under test: Тест ХХК is not a VAT payer, so an ordinary
receipt maps to ``purchase_expense_non_vat``, which ships unverified — the tap was refused with a
sentence about an admin who had no command to run. These tests pin the list, the evidence, the
single confirming tap (row + Nyabo Event), the two readers of the refusal, and the guard itself,
which must keep refusing until a human has actually said yes.
"""

from __future__ import annotations

from typing import Any

import frappe
import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.nyabo.seed import load_seed
from nyabo_mn.rules import guard, verify
from nyabo_mn.telegram import _deps, keyboards
from nyabo_mn.telegram.api import MAX_CALLBACK_DATA_BYTES
from tests.fixtures.telegram.fake_bot import (
	FakeBotApi,
	callback_update,
	link_user,
	make_proposal,
	message_update,
	run,
)

ADMIN_ID = 1001  # tests/fixtures/site/site_config.json admin_telegram_ids
ACCOUNTANT_ID = 2001
BLOCKING = "purchase_expense_non_vat"


@pytest.fixture
def rules_site(seeded: dict, company: str) -> str:
	"""The seeded rule rows on a provisioned company, with the founder linked as accountant.

	``ADMIN_ID`` is an admin through ADMIN_TELEGRAM_IDS, which is how the founder is one before
	any Admin link row exists — the exact setup of the live bot.
	"""
	link_user(ADMIN_ID, "Accountant", company)
	link_user(ACCOUNTANT_ID, "Accountant", company)
	return company


def _use_pattern(company: str, pattern_id: str, times: int = 2) -> None:
	"""Proposals built on a pattern are the usage trail the list orders by."""
	for _ in range(times):
		make_proposal(company, posting_pattern=pattern_id)


def _rule_datas(bot: FakeBotApi) -> list[str]:
	return [data for data in bot.callback_datas() if data.startswith(keyboards.PREFIX_VERIFY)]


# --- 1. an admin can see what is pending ------------------------------------------------------


def test_admin_lists_the_rules_that_are_blocking_work_most_used_first(rules_site: str):
	_use_pattern(rules_site, BLOCKING, times=3)
	bot = FakeBotApi()
	outcome = run(bot, message_update(ADMIN_ID, "/дүрэм"))

	result = outcome["result"]
	assert result["shown"][0] == BLOCKING, "the pattern that blocks the most work comes first"
	assert result["pending"] >= 16  # 16 unverified posting patterns + 13 tax parameters in the seed
	text = bot.last_text
	assert mn.MSG_RULES_TITLE.format(count=result["pending"]) in text
	# The row says what the rule is for, and how much work it is holding up.
	assert "Зардлын худалдан авалт (НӨАТ төлөгч бус)" in text
	assert "3 удаа хэрэглэсэн" in text
	assert _rule_datas(bot)[0] == keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, BLOCKING)


def test_the_latin_alias_reaches_the_same_command(rules_site: str):
	bot = FakeBotApi()
	assert run(bot, message_update(ADMIN_ID, "/rules"))["result"]["pending"] > 0
	from nyabo_mn.telegram import commands

	assert "rules" in commands.MENU_COMMANDS and mn.BOT_COMMAND_DESCRIPTIONS["rules"]


def test_nothing_pending_says_so(rules_site: str):
	for doctype in (verify.PATTERN, verify.PARAMETER):
		for name in frappe.get_all(doctype, filters={"verified": 0}, pluck="name"):
			frappe.db.set_value(doctype, name, "verified", 1)
	bot = FakeBotApi()
	assert run(bot, message_update(ADMIN_ID, "/дүрэм"))["result"] == {"pending": 0}
	assert bot.last_text == mn.MSG_RULES_NONE


# --- 2. an admin can read the evidence --------------------------------------------------------


def test_the_rule_card_shows_the_entry_and_says_plainly_that_there_is_no_citation(rules_site: str):
	bot = FakeBotApi()
	data = keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, BLOCKING)
	outcome = run(bot, callback_update(ADMIN_ID, data))

	assert outcome["result"] == {"rule": BLOCKING, "has_citation": False, "offered": True}
	text = bot.last_text
	assert "Зардлын худалдан авалт (НӨАТ төлөгч бус)" in text
	assert mn.CARD_RULE_SIDE_LABELS["debit"] in text and mn.CARD_RULE_SIDE_LABELS["credit"] in text
	assert "Удирдлагын зардал" in text and "Дансны өглөг" in text
	# The seed carries the instrument for every pattern, so «Заавар 116» alone must not read as
	# an authority: this row has no section and no quote, and the card has to say it in words.
	assert mn.CARD_RULE_NO_CITATION in text
	assert mn.CARD_RULE_RESPONSIBILITY in text
	assert bot.callback_datas() == [
		keyboards.rule_data(keyboards.VERIFY_CONFIRM, verify.KIND_PATTERN, BLOCKING),
		keyboards.rule_data(keyboards.VERIFY_LEAVE, verify.KIND_PATTERN, BLOCKING),
	]


def test_a_verified_citation_is_quoted_instead(rules_site: str):
	verified_pattern = "sale_cash_vat_payer"
	frappe.db.set_value(verify.PATTERN, verified_pattern, "verified", 0)
	bot = FakeBotApi()
	run(
		bot,
		callback_update(
			ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, verified_pattern)
		),
	)
	text = bot.last_text
	assert mn.CARD_RULE_NO_CITATION not in text
	assert "11.2.1" in text and "«" in text


def test_a_tax_parameter_shows_its_value_and_the_article(rules_site: str):
	name = "si.employee_rate:2026-01-01"
	bot = FakeBotApi()
	run(
		bot,
		callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PARAMETER, name)),
	)
	text = bot.last_text
	assert "si.employee_rate" in text
	assert mn.CARD_RULE_VALUE.split("{")[0] in text  # «Утга: …»
	assert "18.1" in text


# --- 3. verification is recorded like a compliance act ----------------------------------------


def test_verifying_writes_the_row_the_event_and_stops_the_guard_refusing(rules_site: str):
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING)

	bot = FakeBotApi()
	data = keyboards.rule_data(keyboards.VERIFY_CONFIRM, verify.KIND_PATTERN, BLOCKING)
	outcome = run(bot, callback_update(ADMIN_ID, data))
	assert outcome["result"]["verified"] is True

	row = frappe.get_doc(verify.PATTERN, BLOCKING)
	assert row.verified == 1
	assert row.verified_by == "tg-1001@nyabo.local" and row.verified_at
	event = frappe.get_doc("Nyabo Event", outcome["result"]["event"])
	assert event.event_type == mn.EVENT_RULE_VERIFIED
	assert event.ref_doctype == verify.PATTERN and event.ref_name == BLOCKING
	assert event.actor_user == "tg-1001@nyabo.local" and event.actor_telegram_id == str(ADMIN_ID)

	# The guard is what actually gates a posting, and it is now satisfied — without being weakened.
	guard.require_verified(BLOCKING)
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified("payable_pay")
	assert mn.MSG_RULE_VERIFIED_RETRY in bot.texts()


def test_verifying_twice_is_not_a_second_approval(rules_site: str):
	first = verify.verify(verify.KIND_PATTERN, BLOCKING, "Administrator")
	again = verify.verify(verify.KIND_PATTERN, BLOCKING, "tg-2001@nyabo.local")
	assert again == {"ok": True, "already": True, "rule": BLOCKING, "doctype": verify.PATTERN}
	assert frappe.db.get_value(verify.PATTERN, BLOCKING, "verified_by") == "Administrator"
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_VERIFIED}) == 1
	assert first["event"]


def test_leaving_a_rule_changes_nothing(rules_site: str):
	bot = FakeBotApi()
	run(
		bot,
		callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_LEAVE, verify.KIND_PATTERN, BLOCKING)),
	)
	assert bot.last_text == mn.MSG_RULE_LEFT
	assert frappe.db.get_value(verify.PATTERN, BLOCKING, "verified") == 0


# --- 4. only an admin -------------------------------------------------------------------------


def test_a_non_admin_is_told_who_can_verify_not_silently_refused(rules_site: str):
	bot = FakeBotApi()
	outcome = run(bot, message_update(ACCOUNTANT_ID, "/дүрэм"))
	assert outcome["result"] == {"refused": "not_admin"}
	assert bot.last_text == mn.MSG_RULES_ADMIN_ONLY


def test_a_forged_tap_from_a_non_admin_verifies_nothing(rules_site: str):
	bot = FakeBotApi()
	data = keyboards.rule_data(keyboards.VERIFY_CONFIRM, verify.KIND_PATTERN, BLOCKING)
	outcome = run(bot, callback_update(ACCOUNTANT_ID, data))
	assert outcome["result"] == {"refused": "not_admin", "rule": BLOCKING}
	assert frappe.db.get_value(verify.PATTERN, BLOCKING, "verified") == 0
	assert bot.last_text == mn.MSG_RULES_ADMIN_ONLY


# --- 5. the refusal the accountant hits -------------------------------------------------------


def _refuse_posting(monkeypatch: pytest.MonkeyPatch, rule: str = BLOCKING) -> None:
	"""``agent.post.post_proposal`` raises exactly this when the pattern is unverified."""

	def post_proposal(name: str, user: str, telegram_id: str) -> dict[str, Any]:
		raise guard.UnverifiedRuleError(rule)

	monkeypatch.setattr(_deps, "post_proposal", post_proposal)


def test_the_refusal_names_the_rule_and_keeps_the_card_tappable(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	assert outcome["result"]["unverified_rule"] == BLOCKING
	assert mn.MSG_UNVERIFIED_RULE_BLOCKED.format(rule=BLOCKING) in bot.texts()
	assert mn.MSG_UNVERIFIED_RULE_ADMIN_ASKED in bot.texts()
	# The proposal is untouched and its card still carries [Батлах]: the retry is one tap, and the
	# accountant never re-sends the photo.
	assert frappe.db.get_value("Nyabo Proposal", proposal.name, "status") == "proposed"
	assert f"p:{proposal.name}:ap" in [
		button["callback_data"]
		for call in bot.sent("edit_message_text")
		for row in (call.get("reply_markup") or {}).get("inline_keyboard", [])
		for button in row
	]


def test_a_blocked_accountant_has_the_request_recorded_and_the_admins_notified(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	requested = frappe.get_all(
		"Nyabo Event", filters={"event_type": mn.EVENT_RULE_VERIFY_REQUESTED}, fields=["reason", "company"]
	)
	assert [(row["reason"], row["company"]) for row in requested] == [(BLOCKING, rules_site)]
	notice = mn.MSG_ADMIN_RULE_VERIFY_REQUEST.format(company=rules_site, rule=BLOCKING)
	assert [call["chat_id"] for call in bot.sent("send_message") if call["text"] == notice] == [ADMIN_ID]


def test_a_rule_id_too_long_for_a_button_sends_the_admin_to_the_desk(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""The other side of the 64-byte cap: no button, but never a card with no answer on it."""
	long_id = "purchase_expense_non_vat_" + "x" * 40
	row = frappe.copy_doc(frappe.get_doc(verify.PATTERN, BLOCKING))
	row.pattern_id = long_id
	row.flags.ignore_permissions = True
	row.insert()
	_refuse_posting(monkeypatch, rule=long_id)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(ADMIN_ID, f"p:{proposal.name}:ap"))

	assert outcome["result"]["offered"] is False
	assert mn.MSG_RULE_VERIFY_IN_DESK.format(rule=long_id) in bot.texts()
	assert _rule_datas(bot) == []


def test_a_blocked_admin_is_offered_the_verify_button_there_and_then(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(ADMIN_ID, f"p:{proposal.name}:ap"))

	assert outcome["result"]["offered"] is True and outcome["result"]["notified"] is False
	assert mn.MSG_UNVERIFIED_RULE_ADMIN_CAN_VERIFY in bot.texts()
	assert keyboards.rule_data(keyboards.VERIFY_CONFIRM, verify.KIND_PATTERN, BLOCKING) in _rule_datas(bot)
	assert mn.CARD_RULE_NO_CITATION in bot.last_text


# --- 6. the datum fits ------------------------------------------------------------------------


def test_callback_data_fits_64_bytes_for_the_longest_seeded_rule_names():
	"""Telegram caps callback_data at 64 bytes, and a tax parameter is named ``key:effective_from``."""
	longest_pattern = max((row["pattern_id"] for row in load_seed("posting_patterns")["rows"]), key=len)
	longest_parameter = max(
		(f"{row['key']}:{row['effective_from']}" for row in load_seed("tax_parameters")["rows"]), key=len
	)
	for kind, rule in ((verify.KIND_PATTERN, longest_pattern), (verify.KIND_PARAMETER, longest_parameter)):
		for action in (keyboards.VERIFY_OPEN, keyboards.VERIFY_CONFIRM, keyboards.VERIFY_LEAVE):
			data = keyboards.rule_data(action, kind, rule)
			assert len(data.encode("utf-8")) <= MAX_CALLBACK_DATA_BYTES, data
			parts = keyboards.decode(data)
			assert parts[1] == action and parts[2] == kind
			assert keyboards.rule_from_parts(parts) == rule


def test_a_rule_too_long_for_a_button_costs_the_button_not_the_card():
	long_rule = "x" * 80
	rules = [
		verify.PendingRule(
			kind=verify.KIND_PATTERN,
			doctype=verify.PATTERN,
			name=long_rule,
			label="Урт нэртэй дүрэм",
			purpose="—",
		)
	]
	assert keyboards.pending_rules_keyboard(rules) == {"inline_keyboard": []}
	assert keyboards.rule_decision(verify.KIND_PATTERN, long_rule) == {"inline_keyboard": []}
	with pytest.raises(keyboards.CallbackDataTooLong):
		keyboards.rule_data(keyboards.VERIFY_CONFIRM, verify.KIND_PATTERN, long_rule)
