"""/дүрэм: the door MSG_UNVERIFIED_RULE_BLOCKED points at, and the refusal that now names it.

Тест ХХК is not a VAT payer, so the flow is exercised on a rule an ordinary non-VAT company
really walks into and the seed really ships unverified. These tests pin the list, the evidence,
the single confirming tap (row + Nyabo Event), the two readers of the refusal, and the guard
itself, which must keep refusing until a human has actually said yes.

WHY the anchor rule is a named constant the fixture checks: which seed rows are verified is
*data*, and a legal-citation pass changes it. This module was anchored on
``purchase_expense_non_vat`` until Order 116 12.2.2 А was found for it, and the eight tests below
then failed for a reason that had nothing to do with the flow they cover. ``unverified_seed``
asserts the anchors are still unverified in the seed and says what to do when they are not, so
the next citation pass gets a sentence instead of eight red tests.
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
#: An admin created by ``/link admin <company>``: an admin of these books who appears in no
#: site config file, and whom a notice about this company's blocked work has to reach.
COMPANY_ADMIN_ID = 3001
ACCOUNTANT_ID = 2001

#: The rule these tests verify. Order 116 prints no entry that turns a customer advance into
#: revenue (docs/legal/order116.md §3, "Order 116 prints no such entry at all"), so the seed
#: ships it unverified, and a non-VAT company meets it on every delivery against an advance.
BLOCKING = "customer_prepayment_recognize_non_vat"
#: A second rule of the same group: verifying one rule must clear that one and nothing else.
STILL_BLOCKED = "bank_transfer_internal"
#: The Mongolian name and the debit and credit of ``BLOCKING`` as the seed spells them, so the
#: card assertions name the entry the admin is asked to vouch for and not merely two accounts.
BLOCKING_LABEL = "Урьдчилгааг орлогоор хүлээн зөвшөөрөх (НӨАТ төлөгч бус)"
BLOCKING_DEBIT = "Бусад өглөг, урьдчилан төлөгдсөн орлого"
BLOCKING_CREDIT = "Борлуулалт"


@pytest.fixture
def unverified_seed() -> tuple[list[str], list[str]]:
	"""The rule names the seed itself ships unverified: patterns first, then tax parameters.

	Read out of the seed rather than written down, because every citation pass moves rows off
	this list; the assertions below then measure the list instead of a number that rots.
	"""
	patterns = [
		row["pattern_id"]
		for row in load_seed("posting_patterns")["rows"]
		if not row.get("verified") and row.get("enabled", True)
	]
	parameters = [
		f"{row['key']}:{row['effective_from']}"
		for row in load_seed("tax_parameters")["rows"]
		if not row.get("verified")
	]
	for anchor in (BLOCKING, STILL_BLOCKED):
		assert anchor in patterns, (
			f"{anchor} is verified in the seed now, so it can no longer anchor this flow. Point "
			"BLOCKING / STILL_BLOCKED at another pattern the seed still ships unverified, and "
			"move the label and account names with it. Do not un-verify the seed row instead: "
			"the citations are the product, these tests are only its first reader."
		)
	return patterns, parameters


@pytest.fixture
def rules_site(seeded: dict, company: str, unverified_seed: tuple[list[str], list[str]]) -> str:
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


def test_admin_lists_the_rules_that_are_blocking_work_most_used_first(
	rules_site: str, unverified_seed: tuple[list[str], list[str]]
):
	_use_pattern(rules_site, BLOCKING, times=3)
	bot = FakeBotApi()
	outcome = run(bot, message_update(ADMIN_ID, "/дүрэм"))

	patterns, parameters = unverified_seed
	result = outcome["result"]
	assert result["shown"][0] == BLOCKING, "the pattern that blocks the most work comes first"
	# Every unverified seed row reaches the list, and the header counts them all, not the page.
	assert result["pending"] == len(patterns) + len(parameters)
	text = bot.last_text
	assert mn.MSG_RULES_TITLE.format(count=result["pending"]) in text
	# The row says what the rule is for, and how much work it is holding up.
	assert BLOCKING_LABEL in text
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
	assert BLOCKING_LABEL in text
	assert mn.CARD_RULE_SIDE_LABELS["debit"] in text and mn.CARD_RULE_SIDE_LABELS["credit"] in text
	assert BLOCKING_DEBIT in text and BLOCKING_CREDIT in text
	# The seed carries the instrument for every pattern, so «Заавар 116» alone must not read as
	# an authority: this row has no section and no quote, and the card has to say it in words.
	assert mn.CARD_RULE_NO_CITATION in text
	assert mn.CARD_RULE_RESPONSIBILITY in text
	assert bot.callback_datas() == [
		keyboards.rule_data(keyboards.VERIFY_CONFIRM, verify.KIND_PATTERN, BLOCKING),
		keyboards.rule_data(keyboards.VERIFY_LEAVE, verify.KIND_PATTERN, BLOCKING),
	]


def test_the_card_shows_the_briefing_the_seed_wrote_for_whoever_taps_the_button(rules_site: str):
	"""CORE-18: an unverifiable row's note says what an admin would be vouching for. Show it.

	The nine patterns Order 116 does not print each carry that sentence, and the card is the one
	screen where the decision is actually taken — an admin who only reads «no citation» is being
	asked to take responsibility for something nobody named to them.
	"""
	seed_note = next(
		row["notes"] for row in load_seed("posting_patterns")["rows"] if row["pattern_id"] == BLOCKING
	)
	bot = FakeBotApi()
	run(
		bot,
		callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, BLOCKING)),
	)

	text = bot.last_text
	assert mn.CARD_RULE_BRIEFING_TITLE in text
	briefing = seed_note[seed_note.index("WHAT AN ADMIN WOULD BE VOUCHING FOR") :]
	assert briefing in text, "the seed's own sentence, not a paraphrase of it"
	assert "IFRS for SMEs s.23" in text  # the other authority the tick would rest on
	# The reader provenance above that sentence stays in the repository; it is not evidence.
	assert "re-checked 2026-09-09" not in text
	assert mn.CARD_RULE_NOTE_CUT not in text, "this briefing fits whole"


def test_a_pending_tax_parameter_card_says_what_would_unblock_it(rules_site: str):
	"""CORE-19: a parameter note opens its tail with DAILY USE and then what unblocks the row."""
	name = "emd.employee_rate:2026-01-01"
	bot = FakeBotApi()
	run(
		bot,
		callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PARAMETER, name)),
	)

	text = bot.last_text
	assert mn.CARD_RULE_BRIEFING_TITLE in text
	assert "DAILY USE:" in text and "WHAT UNBLOCKS IT" in text


def test_the_briefing_says_in_mongolian_that_the_paragraph_under_it_is_english(rules_site: str):
	"""The card is Mongolian; the seed's briefing is not, and it is the sentence being vouched for.

	It is left in the English it was reviewed in on purpose (VER-10) — a re-worded Mongolian
	caveat about the law would be a new claim nobody checked. What must not happen is a
	Mongolian-speaking bookkeeper meeting an unreadable paragraph directly under the verify
	button with nothing telling them what it is or what to do instead.
	"""
	bot = FakeBotApi()
	run(
		bot,
		callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, BLOCKING)),
	)

	text = bot.last_text
	title = text.index(mn.CARD_RULE_BRIEFING_TITLE)
	language = text.index(mn.CARD_RULE_BRIEFING_LANGUAGE)
	briefing = text.index("WHAT AN ADMIN WOULD BE VOUCHING FOR")
	assert title < language < briefing, "the warning comes before the English it warns about"


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


def test_a_quote_too_long_for_the_card_is_marked_cut_and_points_at_the_full_text(rules_site: str):
	"""A sliced quote must not read as the whole provision on the screen where the tick happens.

	`purchase_expense_non_vat` carries the longest quote in the seed (431 characters against a
	400-character card limit), and it is the row an admin is most likely to be looking at. Shown
	inside guillemets with nothing else, the fragment ends mid-sentence and reads as the complete
	printed rule — which is the one thing an accountant must not be misled about.
	"""
	cited = "purchase_expense_non_vat"
	quote = next(
		row["citation"]["quote"]
		for row in load_seed("posting_patterns")["rows"]
		if row["pattern_id"] == cited
	)
	assert len(quote) > verify.QUOTE_MAX_CHARS, "pick another row: this one now fits"
	frappe.db.set_value(verify.PATTERN, cited, "verified", 0)
	bot = FakeBotApi()
	run(
		bot, callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, cited))
	)

	text = bot.last_text
	shown = quote[: verify.QUOTE_MAX_CHARS].rstrip()
	assert shown in text and quote not in text
	# Cut in the punctuation and cut in words, and the page carrying the rest is on the card.
	assert mn.CARD_RULE_QUOTE.format(quote=shown) not in text
	assert mn.CARD_RULE_QUOTE_CUT.format(quote=shown) in text
	assert mn.CARD_RULE_QUOTE_CUT_NOTE in text
	assert "https://legalinfo.mn/mn/detail?lawId=205201" in text


def test_the_scope_caveat_reaches_the_card_of_a_rule_broader_than_its_quote(rules_site: str):
	"""A quote about outside services on a pattern that books any expense: say so where it is read.

	`purchase_expense_non_vat` is verified on Заавар 116 12.2.2 А, whose sentence names fees for
	legal and other professional outside services, while the pattern is selected for every
	ordinary receipt at a non-VAT company. The reading is defensible; presenting it as if the
	instrument printed it for expenses in general is not.
	"""
	cited = "purchase_expense_non_vat"
	frappe.db.set_value(verify.PATTERN, cited, "verified", 0)
	bot = FakeBotApi()
	run(
		bot, callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, cited))
	)

	text = bot.last_text
	assert mn.CARD_RULE_BRIEFING_TITLE in text
	assert "SCOPE OF THIS CITATION" in text and "outside services" in text


def test_a_quote_that_fits_is_not_marked_cut(rules_site: str):
	"""The other half of the contract: a complete quote must not be dressed up as a fragment."""
	whole = "sale_cash_vat_payer"
	frappe.db.set_value(verify.PATTERN, whole, "verified", 0)
	bot = FakeBotApi()
	run(
		bot, callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, whole))
	)

	text = bot.last_text
	assert mn.CARD_RULE_QUOTE_CUT_NOTE not in text and "…»" not in text


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


def test_a_tax_parameter_names_its_article_once_and_says_it_is_still_pending(rules_site: str):
	"""Every seeded parameter carries its article twice — in `article` and in `source_text`.

	The citation line is «{instrument}, {section}», so the card read «…, art. 18.5, 18.5»: two
	provisions where there is one, on the screen where an admin decides whether the citation is
	real. The line above it is clipped to one card width, and every law title in the seed is
	longer than that, so «хүлээгдэж буй» — the fact that the row has no value yet — used to fall
	off the end of it.
	"""
	name = "property_tax.rate:2026-01-01"
	bot = FakeBotApi()
	run(
		bot,
		callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PARAMETER, name)),
	)

	text = bot.last_text
	assert "art. 6.1" not in text, "the article is in the tail of source_text; do not print it twice"
	assert "(2000, consolidated), 6.1" in text, "and it is still cited, once"
	assert mn.CARD_RULE_PURPOSE_LABELS["t"].format(purpose=mn.RULE_STATUS_LABELS["pending"]) in text


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
		guard.require_verified(STILL_BLOCKED)
	assert mn.MSG_RULE_VERIFIED_RETRY in bot.texts()


def test_the_accountant_who_was_blocked_is_told_the_rule_was_cleared(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""The last leg of the walk: the refusal promised this moment, and nobody was told it came.

	The accountant is told «press [Батлах] again once an admin has verified it» — their proposal
	stays `proposed` and keeps its own button, so the retry really is one tap. But the tap
	happens in the admin's chat, and the person waiting had no way to learn the rule had been
	cleared: they either re-send the receipt or the card is never answered at all.
	"""
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))
	assert mn.MSG_UNVERIFIED_RULE_ADMIN_ASKED in bot.texts()

	admin_bot = FakeBotApi()
	outcome = run(
		admin_bot,
		callback_update(
			ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_CONFIRM, verify.KIND_PATTERN, BLOCKING)
		),
	)

	assert outcome["result"]["requesters_told"] == 1
	told = [
		call["chat_id"]
		for call in admin_bot.sent("send_message")
		if call["text"] == mn.MSG_RULE_VERIFIED_FOR_REQUESTER.format(rule=BLOCKING)
	]
	assert told == [str(ACCOUNTANT_ID)], "the person who was stopped, and only them"


def test_the_person_who_taps_is_not_sent_the_news_as_if_they_were_somebody_else(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""Blocked first, made a site admin afterwards — which is how the founder unblocks a colleague.

	Their own request is on record, so the notice would go to the chat that just tapped: the same
	sentence twice, the second one addressed to them as if they were still waiting on somebody.
	"""
	link_user(COMPANY_ADMIN_ID, "Admin", rules_site)
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	run(bot, callback_update(COMPANY_ADMIN_ID, f"p:{proposal.name}:ap"))
	assert verify.requesters(BLOCKING) == [str(COMPANY_ADMIN_ID)]

	monkeypatch.setitem(frappe.conf, "admin_telegram_ids", str(COMPANY_ADMIN_ID))
	promoted = FakeBotApi()
	outcome = run(
		promoted,
		callback_update(
			COMPANY_ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_CONFIRM, verify.KIND_PATTERN, BLOCKING)
		),
	)

	assert outcome["result"]["requesters_told"] == 0
	assert mn.MSG_RULE_VERIFIED_FOR_REQUESTER.format(rule=BLOCKING) not in promoted.texts()
	assert mn.MSG_RULE_VERIFIED_RETRY in promoted.texts()


def test_verifying_twice_is_not_a_second_approval(rules_site: str):
	first = verify.verify(verify.KIND_PATTERN, BLOCKING, "Administrator")
	again = verify.verify(verify.KIND_PATTERN, BLOCKING, "tg-2001@nyabo.local")
	# The second tapper is told it is done, and by whom: a first verifier's name is the answer,
	# not a detail. Nothing about the row moves.
	assert again == {
		"ok": True,
		"already": True,
		"rule": BLOCKING,
		"doctype": verify.PATTERN,
		"verified_by": "Administrator",
		"verified_at": str(first["verified_at"]),
	}
	assert frappe.db.get_value(verify.PATTERN, BLOCKING, "verified_by") == "Administrator"
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_VERIFIED}) == 1
	assert first["event"]


def _alerts(bot: FakeBotApi) -> list[str]:
	"""The pop-ups the admin actually read; the router's own closing answer carries no text."""
	return [call["text"] for call in bot.sent("answer_callback_query") if call.get("text")]


def test_a_rule_the_seed_verified_does_not_claim_a_person_verified_it(rules_site: str):
	"""35 of the 44 patterns ship verified with verified_by empty, and no Nyabo Event behind them.

	DECISIONS VER-01 says verified_by names the human who took responsibility, so an empty one
	must be read out loud as what it is — the repository's citation — and never dressed up as a
	signature. An accountant who sees «already verified» takes it that somebody stood behind it.
	"""
	seed_verified = "payable_pay"
	assert not frappe.db.get_value(verify.PATTERN, seed_verified, "verified_by")
	bot = FakeBotApi()
	outcome = run(
		bot,
		callback_update(
			ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, seed_verified)
		),
	)

	assert outcome["result"] == {
		"rule": seed_verified,
		"already": True,
		"verified_source": verify.SOURCE_SEED,
	}
	assert mn.RULE_VERIFIED_SOURCE_SEED in _alerts(bot)[-1]


def test_a_rule_a_person_verified_names_that_person(rules_site: str):
	"""The other half: a real tap must be attributable, on the card and on the second tap."""
	verify.verify(verify.KIND_PATTERN, BLOCKING, "Administrator")
	bot = FakeBotApi()
	outcome = run(
		bot,
		callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, BLOCKING)),
	)

	assert outcome["result"]["verified_source"] == verify.SOURCE_PERSON
	alert = _alerts(bot)[-1]
	assert "Administrator" in alert and mn.RULE_VERIFIED_SOURCE_SEED not in alert


def test_a_verified_rule_can_still_be_read_and_asks_nothing(rules_site: str):
	"""The scope caveat on the flagship row is only readable here, and only if the card is drawn.

	`purchase_expense_non_vat` and `bank_line_expense` ship verified with a `SCOPE OF THIS
	CITATION` paragraph saying the quoted sentence is printed for outside services and is being
	applied more widely (VER-09) — and the list shows unverified rules only, so this tap is the
	one path in the chat that reaches it. An alert that disappears when it is tapped away is not
	somewhere a caveat about a legal reading can live.
	"""
	cited = "purchase_expense_non_vat"
	assert frappe.db.get_value(verify.PATTERN, cited, "verified") == 1
	bot = FakeBotApi()
	run(
		bot, callback_update(ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, cited))
	)

	text = bot.last_text
	assert "SCOPE OF THIS CITATION" in text and "12.2.2 А" in text
	# It is read, not decided: no question, no buttons, and the flag names its own provenance.
	assert mn.CARD_RULE_ASK not in text
	assert mn.CARD_RULE_BRIEFING_TITLE_VERIFIED in text and mn.CARD_RULE_BRIEFING_TITLE not in text
	assert mn.CARD_RULE_VERIFIED_BY.format(source=mn.RULE_VERIFIED_SOURCE_SEED) in text
	assert bot.callback_datas() == []


def test_the_verified_counts_split_the_seed_flag_from_a_human_tap(rules_site: str):
	"""The number an audit view prints: how many rows may post, and how many a person vouched for."""
	before = verify.verified_counts(verify.PATTERN)
	assert before["by_person"] == 0 and before["by_seed"] == before["verified"] > 0

	verify.verify(verify.KIND_PATTERN, BLOCKING, "Administrator")

	after = verify.verified_counts(verify.PATTERN)
	assert after["verified"] == before["verified"] + 1
	assert after["by_person"] == 1 and after["by_seed"] == before["by_seed"]


def test_a_write_that_cannot_go_through_is_a_shaped_failure_not_a_traceback(rules_site: str):
	"""`verified_by` is a Link to User, so the save raises for a session user with no User row.

	That is a real state: a Telegram admin linked before `ensure_frappe_user` existed has no
	User row, and their tap would have raised inside the handler — the accountant sees the
	router's apology and the rule stays unverified with nobody able to say why.
	"""
	assert not frappe.db.exists("User", "ghost@nyabo.local")

	result = verify.verify(verify.KIND_PATTERN, BLOCKING, "ghost@nyabo.local")

	assert result == {
		"ok": False,
		"reason": "save_failed",
		"rule": BLOCKING,
		"doctype": verify.PATTERN,
	}
	assert frappe.db.get_value(verify.PATTERN, BLOCKING, "verified") == 0
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_VERIFIED}) == 0


def test_the_tap_answers_a_failed_write_with_something_a_person_can_act_on(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""«Rule not found» would be a lie, and a silent tap is what this flow exists to remove."""

	def verify_rule(kind: str, rule: str, user: str, telegram_id: Any = None) -> dict[str, Any]:
		return {"ok": False, "reason": "save_failed", "rule": rule, "doctype": verify.PATTERN}

	monkeypatch.setattr(_deps, "verify_rule", verify_rule)
	bot = FakeBotApi()
	data = keyboards.rule_data(keyboards.VERIFY_CONFIRM, verify.KIND_PATTERN, BLOCKING)
	outcome = run(bot, callback_update(ADMIN_ID, data))

	assert outcome["result"]["ok"] is False
	failed = mn.MSG_RULE_VERIFY_FAILED.format(rule=BLOCKING)
	assert failed in bot.texts(), "the admin is left with the desk, not with nothing"
	assert failed in _alerts(bot)[-1]
	assert mn.MSG_RULE_NOT_FOUND.format(rule=BLOCKING) not in bot.texts()


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


def test_an_admin_of_one_company_cannot_verify_a_rule_that_applies_to_every_client(rules_site: str):
	"""Nyabo Posting Pattern is one row for the whole site; the Admin role is granted per company.

	`/link admin <company>` makes somebody an admin of *those* books. Letting that person tick a
	global rule would have one client's admin decide, for every other client on the site, that a
	posting is backed by the law — with their name on the audit row.
	"""
	link_user(COMPANY_ADMIN_ID, "Admin", rules_site)
	bot = FakeBotApi()
	data = keyboards.rule_data(keyboards.VERIFY_CONFIRM, verify.KIND_PATTERN, BLOCKING)
	outcome = run(bot, callback_update(COMPANY_ADMIN_ID, data))

	assert outcome["result"] == {"refused": "not_site_admin", "rule": BLOCKING}
	assert frappe.db.get_value(verify.PATTERN, BLOCKING, "verified") == 0
	assert bot.last_text == mn.MSG_RULES_SITE_ADMIN_ONLY


def test_a_company_admin_still_reads_the_evidence_and_is_told_who_may_clear_it(rules_site: str):
	"""It is their work that is blocked, so they get the card — with no button that would refuse."""
	link_user(COMPANY_ADMIN_ID, "Admin", rules_site)
	bot = FakeBotApi()
	data = keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, BLOCKING)
	outcome = run(bot, callback_update(COMPANY_ADMIN_ID, data))

	assert outcome["result"] == {"rule": BLOCKING, "has_citation": False, "offered": False}
	assert BLOCKING_LABEL in bot.texts()[0]  # the evidence card came first
	assert bot.callback_datas() == [
		keyboards.rule_data(keyboards.VERIFY_LEAVE, verify.KIND_PATTERN, BLOCKING)
	]
	assert bot.last_text == mn.MSG_RULES_SITE_ADMIN_ONLY


def test_a_blocked_company_admin_takes_the_accountants_path_not_the_verify_button(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""A refusal must not hand a per-company admin a tap they are not allowed to make."""
	link_user(COMPANY_ADMIN_ID, "Admin", rules_site)
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(COMPANY_ADMIN_ID, f"p:{proposal.name}:ap"))

	assert outcome["result"]["offered"] is False and outcome["result"]["notified"] is True
	assert _rule_datas(bot) == []
	assert mn.MSG_UNVERIFIED_RULE_ADMIN_ASKED in bot.texts()


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


def test_three_taps_on_the_same_blocked_card_write_one_row_and_send_one_notice(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""Tapping [Батлах] again is what a person does when nothing seems to happen.

	Each tap used to write a row into an append-only log — which is the one log nobody can tidy
	up afterwards — and ring every admin again. The accountant still gets an answer every time.
	"""
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	outcomes = [run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap")) for _ in range(3)]

	assert [o["result"]["deduped"] for o in outcomes] == [False, True, True]
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_VERIFY_REQUESTED}) == 1
	notice = mn.MSG_ADMIN_RULE_VERIFY_REQUEST.format(company=rules_site, rule=BLOCKING)
	assert len([c for c in bot.sent("send_message") if c["text"] == notice]) == 1
	# Every tap is still answered, and with the same sentence: silence is what the retry means.
	assert bot.texts().count(mn.MSG_UNVERIFIED_RULE_ADMIN_ASKED) == 3


def test_a_repeat_does_not_start_claiming_admins_were_told_when_none_were(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""The deduped answer is the first tap's answer, so it cannot become truer by repetition."""
	monkeypatch.setitem(frappe.conf, "admin_telegram_ids", "")
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	first = run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))
	second = run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	assert first["result"]["deduped"] is False and second["result"]["deduped"] is True
	assert second["result"]["notified"] is False
	assert bot.texts().count(mn.MSG_UNVERIFIED_RULE_NO_ADMIN.format(rule=BLOCKING)) == 2
	assert mn.MSG_UNVERIFIED_RULE_ADMIN_ASKED not in bot.texts()


def test_a_different_rule_is_not_swallowed_by_the_dedupe(rules_site: str, monkeypatch: pytest.MonkeyPatch):
	"""The window is per rule and company: a second rule blocking work is its own request."""
	_refuse_posting(monkeypatch)
	first = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	run(bot, callback_update(ACCOUNTANT_ID, f"p:{first.name}:ap"))
	_refuse_posting(monkeypatch, rule=STILL_BLOCKED)
	second = make_proposal(rules_site, posting_pattern=STILL_BLOCKED)
	outcome = run(bot, callback_update(ACCOUNTANT_ID, f"p:{second.name}:ap"))

	assert outcome["result"]["deduped"] is False
	rules = frappe.get_all(
		"Nyabo Event", filters={"event_type": mn.EVENT_RULE_VERIFY_REQUESTED}, pluck="reason"
	)
	assert sorted(rules) == sorted([BLOCKING, STILL_BLOCKED])


def test_the_request_reaches_the_admin_linked_to_the_company_not_only_the_site_config(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""«A notification has gone to the admins» must mean every admin who can act on these books.

	`/link admin <company>` is how a client's own admin is created, and that person is in no
	site config file. Notifying only ADMIN_TELEGRAM_IDS told the accountant something that was
	not true for the person actually responsible for their company.
	"""
	link_user(COMPANY_ADMIN_ID, "Admin", rules_site)
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	assert outcome["result"]["notified"] is True and outcome["result"]["admins_notified"] == 2
	notice = mn.MSG_ADMIN_RULE_VERIFY_REQUEST.format(company=rules_site, rule=BLOCKING)
	told = [call["chat_id"] for call in bot.sent("send_message") if call["text"] == notice]
	assert told == [ADMIN_ID]
	# The company's own admin hears about it too, in the wording that is true for them: the row
	# is global, so the chat's verify button is not theirs (VER-08) and the desk is.
	company_notice = mn.MSG_ADMIN_RULE_VERIFY_REQUEST_COMPANY.format(company=rules_site, rule=BLOCKING)
	told_company = [call["chat_id"] for call in bot.sent("send_message") if call["text"] == company_notice]
	assert told_company == [COMPANY_ADMIN_ID]
	assert mn.MSG_UNVERIFIED_RULE_ADMIN_ASKED in bot.texts()


def test_a_company_admin_is_never_told_to_use_a_button_that_will_refuse_them(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""The notice must not send its reader to a card that answers «you may not» (VER-08).

	A posting pattern is one row for every company on the site, so `/дүрэм` draws the verify
	button only for a site admin. Telling a per-company admin «/дүрэм командаар баталгаажуулна
	уу» is the same empty promise as telling the accountant the admins were notified when nobody
	was — one seat further along the same flow.
	"""
	link_user(COMPANY_ADMIN_ID, "Admin", rules_site)
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	to_company_admin = [
		call["text"] for call in bot.sent("send_message") if call["chat_id"] == COMPANY_ADMIN_ID
	]
	assert to_company_admin == [
		mn.MSG_ADMIN_RULE_VERIFY_REQUEST_COMPANY.format(company=rules_site, rule=BLOCKING)
	]
	# ...and the flow it points at is the one they really get: the evidence, and who may clear it.
	tap = FakeBotApi()
	run(tap, callback_update(COMPANY_ADMIN_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, "p", BLOCKING)))
	assert tap.last_text == mn.MSG_RULES_SITE_ADMIN_ONLY


def test_an_admin_of_another_company_is_not_told_about_this_one(
	rules_site: str, company_v03: str, monkeypatch: pytest.MonkeyPatch
):
	"""The Admin role is per company (TG-04), so the notice is too."""
	link_user(COMPANY_ADMIN_ID, "Admin", company_v03)
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	notice = mn.MSG_ADMIN_RULE_VERIFY_REQUEST.format(company=rules_site, rule=BLOCKING)
	assert [call["chat_id"] for call in bot.sent("send_message") if call["text"] == notice] == [ADMIN_ID]


def test_with_nobody_to_tell_the_accountant_is_told_that_and_what_to_do(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""An empty ADMIN_TELEGRAM_IDS and no linked Admin: the promise cannot be kept, so it is not made.

	The old reply said the request had been recorded *and a notification sent to the admins*
	while `notify_admins` had sent nothing at all — the accountant would have waited for a
	person who was never going to hear about it.
	"""
	monkeypatch.setitem(frappe.conf, "admin_telegram_ids", "")
	_refuse_posting(monkeypatch)
	proposal = make_proposal(rules_site, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	assert outcome["result"]["notified"] is False and outcome["result"]["admins_notified"] == 0
	assert mn.MSG_UNVERIFIED_RULE_NO_ADMIN.format(rule=BLOCKING) in bot.texts()
	assert mn.MSG_UNVERIFIED_RULE_ADMIN_ASKED not in bot.texts()
	assert bot.sent("send_message"), "the accountant still hears something"
	# The request is on record either way: that is what makes the sentence above true.
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_VERIFY_REQUESTED}) == 1


def test_a_rule_id_too_long_for_a_button_sends_the_admin_to_the_desk(
	rules_site: str, monkeypatch: pytest.MonkeyPatch
):
	"""The other side of the 64-byte cap: no button, but never a card with no answer on it."""
	long_id = f"{BLOCKING}_" + "x" * 40
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
