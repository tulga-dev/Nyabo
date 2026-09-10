"""The accountant accepts an uncited rule for their own company, and the intake goes through.

The founder's decision: «the main user is accountant, so all the intakes should just ask
accountant confirm». Until now every intake that met an unverified rule told the accountant to
wait for an admin — and only a site admin listed in ADMIN_TELEGRAM_IDS could act (VER-08), so the
person whose signature the entry carries could not move. Nine posting patterns and thirteen tax
parameters are in that state and they are ordinary work.

What is pinned here (DECISIONS ACC-01):

* the accountant meets the refusal, reads the rule, accepts it and the intake posts — one flow,
  nothing re-sent, nobody waited for;
* the acceptance is a record with a person, a company and a time, not a flag;
* it binds one company: a second client is still refused until its own accountant answers;
* an owner cannot make it, because it is a professional judgement and not an approval;
* a rule the seed ships with a citation asks nobody, then or now;
* and the three ways a rule can be cleared stay three different things on the record.
"""

from __future__ import annotations

from typing import Any

import frappe
import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.rules import guard, verify
from nyabo_mn.telegram import _deps, keyboards
from tests.fixtures.telegram.fake_bot import (
	FakeBotApi,
	callback_update,
	link_user,
	make_proposal,
	message_update,
	run,
)

#: Order 116 prints no entry that turns a customer advance into revenue (docs/legal/order116.md
#: §3), so the seed ships this unverified and a non-VAT company meets it on every delivery
#: against an advance. ``tests/flows/test_telegram_rules.py`` guards the same anchor.
BLOCKING = "customer_prepayment_recognize_non_vat"
#: A rule the citation pass verified in the repository: it must go on asking nobody anything.
CITED = "purchase_expense_non_vat"

ACCOUNTANT_ID = 5001
OTHER_ACCOUNTANT_ID = 5002
OWNER_ID = 5003
#: One accountant, two clients: the persona the founder's decision is about.
MULTI_CLIENT_ID = 5004
ADMIN_ID = 1001  # tests/fixtures/site/site_config.json admin_telegram_ids


@pytest.fixture
def books(seeded: dict, company: str) -> str:
	"""Тест ХХК with its accountant linked — the founder's own shape, one accountant, one client."""
	link_user(ACCOUNTANT_ID, "Accountant", company)
	return company


def _guarded_post(monkeypatch: pytest.MonkeyPatch, rule: str = BLOCKING) -> list[str]:
	"""``post_proposal`` standing on the real guard: it refuses until *this* company may post.

	The point of the stand-in is that the guard is not stood in for — it is called with the
	proposal's own company, exactly as ``agent.post.post_proposal`` calls it, so an acceptance
	recorded for one company and not another decides the outcome here the way it decides it live.
	``tests/flows/test_pipeline_post.py`` covers the same question against the real ledger.
	"""
	posted: list[str] = []

	def post_proposal(name: str, user: str, telegram_id: str) -> dict[str, Any]:
		proposal = frappe.get_doc("Nyabo Proposal", name)
		guard.require_verified(rule, company=proposal.company)
		proposal.db_set(
			{"status": "posted", "posted_doctype": "Journal Entry", "posted_name": f"JE-{len(posted):05d}"}
		)
		posted.append(proposal.posted_name)
		return {"posted_doctype": "Journal Entry", "posted_name": proposal.posted_name}

	monkeypatch.setattr(_deps, "post_proposal", post_proposal)
	return posted


def _accept(bot: FakeBotApi, telegram_id: int, rule: str = BLOCKING, kind: str = verify.KIND_PATTERN):
	return run(bot, callback_update(telegram_id, keyboards.rule_data(keyboards.VERIFY_ACCEPT, kind, rule)))


# --- 1. the whole point: refused, accepted, posted, in one exchange -----------------------------


def test_the_accountant_is_refused_accepts_the_rule_and_the_intake_posts(
	books: str, monkeypatch: pytest.MonkeyPatch
):
	"""One flow, no waiting: the two taps are [Батлах] and [Манай компанид хамаарна].

	The receipt is never re-sent and no second [Батлах] is asked for — the accountant's own tap,
	refused minutes earlier and recorded as a Nyabo Event, is what the acceptance completes.
	"""
	posted = _guarded_post(monkeypatch)
	proposal = make_proposal(books, posting_pattern=BLOCKING)
	bot = FakeBotApi()

	refused = run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))
	assert refused["result"]["unverified_rule"] == BLOCKING
	assert posted == [] and frappe.db.get_value("Nyabo Proposal", proposal.name, "status") == "proposed"
	# The way out is on the screen they are already looking at, with the evidence above it.
	assert mn.MSG_UNVERIFIED_RULE_ACCOUNTANT_CAN_ACCEPT.format(company=books) in bot.texts()
	assert keyboards.rule_data(keyboards.VERIFY_ACCEPT, verify.KIND_PATTERN, BLOCKING) in (
		bot.callback_datas()
	)

	outcome = _accept(bot, ACCOUNTANT_ID)

	assert outcome["result"]["accepted"] is True
	assert outcome["result"]["posted"] == "JE-00000"
	assert posted == ["JE-00000"], "the refused tap was finished, not asked for again"
	assert frappe.db.get_value("Nyabo Proposal", proposal.name, "status") == "posted"
	assert mn.MSG_RULE_ACCEPTED_POSTING in bot.texts()
	assert mn.MSG_POSTED.format(doc_name="JE-00000") in bot.texts()
	# Nothing was re-sent: one document, one proposal, from start to finish.
	assert frappe.db.count("Nyabo Proposal") == 1


def test_a_stale_acceptance_asks_for_the_one_tap_instead_of_posting_somebody_elses_document(
	books: str, monkeypatch: pytest.MonkeyPatch
):
	"""VER-04's objection, honoured: only this chat's own refused tap is ever finished.

	A rule card sitting in a shared chat must not let one person's acceptance post another
	person's receipt. When there is no refusal of this person's own to finish, the accountant is
	told the one tap that is left — which is still no waiting and still no re-sending.
	"""
	posted = _guarded_post(monkeypatch)
	link_user(OTHER_ACCOUNTANT_ID, "Accountant", books)
	proposal = make_proposal(books, posting_pattern=BLOCKING)
	blocked = FakeBotApi()
	run(blocked, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	colleague = FakeBotApi()
	outcome = _accept(colleague, OTHER_ACCOUNTANT_ID)

	assert outcome["result"]["accepted"] is True and outcome["result"]["posted"] is None
	assert posted == [] and frappe.db.get_value("Nyabo Proposal", proposal.name, "status") == "proposed"
	assert mn.MSG_RULE_ACCEPTED_RETRY in colleague.texts()
	# The person who was actually stopped is told the rule is cleared, and for which company.
	told = [
		call["chat_id"]
		for call in colleague.sent("send_message")
		if call["text"] == mn.MSG_RULE_ACCEPTED_FOR_REQUESTER.format(rule=BLOCKING, company=books)
	]
	assert told == [str(ACCOUNTANT_ID)]


def test_three_taps_on_the_same_refused_card_write_one_block_row(books: str, monkeypatch: pytest.MonkeyPatch):
	"""Tapping [Батлах] again is what a person does when nothing seems to happen.

	The block row is what lets the acceptance finish that tap, so it has to be written on the
	first refusal — and it must not be written again on the second and third, because a Nyabo
	Event is append-only and nobody can tidy the duplicates away afterwards.
	"""
	_guarded_post(monkeypatch)
	proposal = make_proposal(books, posting_pattern=BLOCKING)
	bot = FakeBotApi()

	for _ in range(3):
		run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_BLOCKED}) == 1
	# Every tap is still answered, and the refused approval can still be finished.
	assert bot.texts().count(mn.MSG_UNVERIFIED_RULE_BLOCKED.format(rule=BLOCKING)) == 3
	assert verify.blocked_proposal(BLOCKING, books, ACCOUNTANT_ID) == proposal.name


# --- 1b. the warning on the card the founder actually looks at ----------------------------------


def test_the_card_stops_warning_the_company_that_accepted_and_goes_on_warning_the_others(
	books: str, company_v03: str
):
	"""The founder's own complaint: «⚠️ Дүрэм баталгаажаагүй» after he had already accepted.

	The warning used to read ``pattern.verified`` and nothing else, so it knew about the seed's
	citation and the site admin's tick and not about the third provenance — the one this whole
	flow added. It has to ask the guard's two questions, in the guard's own order, for the
	company the entry is being built for.
	"""
	from nyabo_mn.agent import pipeline
	from nyabo_mn.core import rules_engine
	from nyabo_mn.rules import patterns

	pattern = patterns.load(BLOCKING)
	assert pattern.verified is False, "the seed ships this one uncited; that is the whole premise"

	def card_warnings(company: str) -> tuple[str, ...]:
		"""The warnings the receipt card would carry, built the way ``agent.pipeline`` builds them."""
		entry = rules_engine.instantiate(
			pattern,
			{"gross": "100000"},
			lambda selector: "1110",
			company=company,
			cleared=pipeline.rule_cleared(pattern, company),
		)
		return entry.warnings

	assert mn.WARN_UNVERIFIED_RULE in card_warnings(books)

	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")

	assert mn.WARN_UNVERIFIED_RULE not in card_warnings(books), (
		"the accountant accepted this rule for these books; the card may not go on calling it "
		"unverified, which is the complaint that started this work"
	)
	# ...and it binds one company, on the card exactly as in the guard.
	assert mn.WARN_UNVERIFIED_RULE in card_warnings(company_v03)


# --- 2. the record ------------------------------------------------------------------------------


def test_the_acceptance_records_the_rule_the_company_the_person_and_the_time(books: str):
	bot = FakeBotApi()
	outcome = _accept(bot, ACCOUNTANT_ID)

	row = frappe.get_doc(verify.ACCEPTANCE, outcome["result"]["acceptance"])
	assert row.company == books and row.rule == BLOCKING and row.rule_kind == verify.KIND_PATTERN
	assert row.rule_doctype == verify.PATTERN
	assert row.accepted_by == "tg-5001@nyabo.local"
	assert row.accepted_telegram_id == str(ACCOUNTANT_ID) and row.accepted_at
	# What the accountant was looking at when they took it on: this rule has no citation, and an
	# acceptance of bare mechanics is not the same act as accepting a cited reading.
	assert row.had_citation == 0
	assert row.rule_label == "Урьдчилгааг орлогоор хүлээн зөвшөөрөх (НӨАТ төлөгч бус)"

	event = frappe.get_doc("Nyabo Event", outcome["result"]["event"])
	assert event.event_type == mn.EVENT_RULE_ACCEPTED
	assert event.company == books and event.ref_doctype == verify.PATTERN and event.ref_name == BLOCKING
	assert event.actor_user == "tg-5001@nyabo.local" and event.actor_telegram_id == str(ACCOUNTANT_ID)


def test_accepting_twice_is_not_a_second_decision(books: str):
	first = verify.accept(verify.KIND_PATTERN, BLOCKING, books, "Administrator")
	again = verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")

	assert again["already"] is True and again["accepted_by"] == "Administrator"
	assert frappe.db.count(verify.ACCEPTANCE) == 1
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_ACCEPTED}) == 1
	assert first["event"]


def test_the_global_row_is_never_touched_by_an_acceptance(books: str):
	"""A posting pattern is one row for the whole site; accepting it for one client is not a tick."""
	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")

	row = frappe.get_doc(verify.PATTERN, BLOCKING)
	assert row.verified == 0 and not row.verified_by and not row.verified_at
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_VERIFIED}) == 0


# --- 3. it binds one company ---------------------------------------------------------------------


def test_a_second_company_is_still_refused_until_its_own_accountant_accepts(
	books: str, company_v03: str, monkeypatch: pytest.MonkeyPatch
):
	"""The reason acceptance is per company and not a widening of VER-08, in one test.

	One accountant's reading of an uncited rule is a judgement about the books they keep. Making
	it a global tick would have it decide, for every other client on the site, that a posting is
	backed — with a name on the audit row that never looked at those books.
	"""
	posted = _guarded_post(monkeypatch)
	link_user(OTHER_ACCOUNTANT_ID, "Accountant", company_v03)
	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")

	guard.require_verified(BLOCKING, company=books)
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING, company=company_v03)
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING)  # and no company at all is still the old, strict answer

	# ...and the second company's own intake is refused, in its own chat, with its own way out.
	other = make_proposal(company_v03, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	refused = run(bot, callback_update(OTHER_ACCOUNTANT_ID, f"p:{other.name}:ap"))
	assert refused["result"]["unverified_rule"] == BLOCKING and posted == []

	_accept(bot, OTHER_ACCOUNTANT_ID)
	assert posted == ["JE-00000"]
	assert {row["company"] for row in verify.acceptances(BLOCKING)} == {books, company_v03}


def test_the_list_drops_what_this_company_has_already_accepted(books: str, company_v03: str):
	"""`/дүрэм` answers «what will refuse my postings», and an accepted rule will not."""
	link_user(OTHER_ACCOUNTANT_ID, "Accountant", company_v03)
	before = {rule.name for rule in verify.pending(company=books)}
	assert BLOCKING in before

	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")

	assert BLOCKING not in {rule.name for rule in verify.pending(company=books)}
	assert BLOCKING in {rule.name for rule in verify.pending(company=company_v03)}
	assert BLOCKING in {rule.name for rule in verify.pending()}


# --- 4. who may take the decision -----------------------------------------------------------------


def test_an_owner_cannot_accept_a_rule(books: str):
	"""An owner may approve a simple document; deciding that a rule applies to the books is not theirs."""
	link_user(OWNER_ID, "Owner", books)
	bot = FakeBotApi()

	outcome = _accept(bot, OWNER_ID)

	assert outcome["result"] == {"refused": "not_accountant", "rule": BLOCKING}
	assert frappe.db.count(verify.ACCEPTANCE) == 0
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_ACCEPTED}) == 0
	# ...and they are told which person decides, not sent looking for an admin.
	assert bot.last_text == mn.MSG_RULES_ACCOUNTANT_ONLY
	assert "нягтлан" in bot.last_text


def test_an_accountant_of_another_company_accepts_nothing_here(books: str, company_v03: str):
	"""The link role is per company (TG-04), and so is the answer it entitles you to give."""
	link_user(OTHER_ACCOUNTANT_ID, "Accountant", company_v03)
	bot = FakeBotApi()

	_accept(bot, OTHER_ACCOUNTANT_ID)

	# The tap accepted the rule for *their* company, the active one, and for no other.
	assert [row["company"] for row in verify.acceptances(BLOCKING)] == [company_v03]
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING, company=books)


def test_the_multi_client_accountant_is_offered_their_own_clients_rule_not_told_to_wait(
	books: str, company_v03: str, monkeypatch: pytest.MonkeyPatch
):
	"""One accountant across several clients — the persona this whole change exists for.

	``approve.can_approve`` lets them tap [Батлах] on a proposal for any client they are linked
	to, but the rule block resolved their role against the ACTIVE company. Acting on client B
	while client A was active they were read as not-an-accountant: told which person decides,
	and sent that «ask your accountant» notice in their own chat.
	"""
	posted = _guarded_post(monkeypatch)
	link_user(MULTI_CLIENT_ID, "Accountant", books)
	link_user(MULTI_CLIENT_ID, "Accountant", company_v03)
	assert frappe.db.get_value("Nyabo User Link", str(MULTI_CLIENT_ID), "active_company") == books

	other = make_proposal(company_v03, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	refused = run(bot, callback_update(MULTI_CLIENT_ID, f"p:{other.name}:ap"))

	assert refused["result"]["unverified_rule"] == BLOCKING
	assert refused["result"]["offered"] is True and refused["result"]["notified"] is False
	# The client whose receipt it is, named in the sentence and in the question on the card.
	assert mn.MSG_UNVERIFIED_RULE_ACCOUNTANT_CAN_ACCEPT.format(company=company_v03) in bot.texts()
	assert mn.MSG_UNVERIFIED_RULE_ACCOUNTANT_ASKED not in bot.texts()
	assert (
		mn.MSG_ACCOUNTANT_RULE_ACCEPT_REQUEST.format(company=company_v03, rule=BLOCKING) not in bot.texts()
	), "nobody is told to go and ask themselves"

	accepted = _accept(bot, MULTI_CLIENT_ID)

	# ...and the acceptance is written for the client the document belongs to, which is the only
	# company it unblocks — the active one is untouched.
	assert accepted["result"]["company"] == company_v03
	assert accepted["result"]["posted"] == "JE-00000" and posted == ["JE-00000"]
	assert [row["company"] for row in verify.acceptances(BLOCKING)] == [company_v03]
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING, company=books)


def test_nobody_is_rung_about_a_block_of_their_own(books: str, monkeypatch: pytest.MonkeyPatch):
	"""A rule name that is no row at all falls through to «who can clear this» — and the people
	who can are this company's accountants, one of whom is the person who was just stopped.

	Telling somebody that their request has been passed to an accountant, and then sending that
	request to their own chat, is the shape of «somebody else will do it» that this work removes.
	"""

	def post_proposal(name: str, user: str, telegram_id: str) -> dict[str, Any]:
		raise guard.UnverifiedRuleError("no_such_rule", company=books)

	monkeypatch.setattr(_deps, "post_proposal", post_proposal)
	proposal = make_proposal(books, posting_pattern=BLOCKING)
	bot = FakeBotApi()

	outcome = run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	assert outcome["result"]["offered"] is False
	# The site admin is a different person and is still told; the accountant who was stopped is
	# not sent a copy of their own request.
	assert outcome["result"]["admins_notified"] == 1
	assert mn.MSG_ACCOUNTANT_RULE_ACCEPT_REQUEST.format(company=books, rule="no_such_rule") not in bot.texts()
	# The request is still on record, whoever could or could not be reached.
	assert frappe.db.exists("Nyabo Event", {"event_type": mn.EVENT_RULE_VERIFY_REQUESTED})


# --- 5. a cited rule asks nobody -------------------------------------------------------------------


def test_a_rule_the_seed_ships_cited_asks_nobody_and_posts_for_every_company(
	books: str, company_v03: str, monkeypatch: pytest.MonkeyPatch
):
	"""35 patterns and 46 parameters are verified by evidence in the repository; that stays (VER-07)."""
	assert frappe.db.get_value(verify.PATTERN, CITED, "verified") == 1
	assert not frappe.db.get_value(verify.PATTERN, CITED, "verified_by"), "no person is named for it"

	posted = _guarded_post(monkeypatch, rule=CITED)
	guard.require_verified(CITED, company=books)
	guard.require_verified(CITED, company=company_v03)

	proposal = make_proposal(books, posting_pattern=CITED)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	assert outcome["result"]["approved"] is True and posted == ["JE-00000"]
	assert frappe.db.count(verify.ACCEPTANCE) == 0, "nobody was asked for anything"
	assert CITED not in {rule.name for rule in verify.pending(company=books)}


# --- 6. three kinds of clearance, three different records -------------------------------------------


def test_the_audit_trail_tells_the_three_kinds_apart(books: str):
	"""A citation, a site admin's signature and this company's accountant are three claims.

	They may not be counted together, printed as one another, or read off a single flag: the
	repository vouched for the first, a named person vouched site-wide for the second, and a
	named person vouched for one company's books in the third (VER-07, ACC-01).
	"""
	seeded_row = verify.evidence(verify.KIND_PATTERN, CITED, books)
	assert seeded_row.source == verify.SOURCE_SEED and not seeded_row.verified_by

	verify.verify(verify.KIND_PATTERN, "bank_transfer_internal", "Administrator")
	by_person = verify.evidence(verify.KIND_PATTERN, "bank_transfer_internal", books)
	assert by_person.source == verify.SOURCE_PERSON and by_person.verified_by == "Administrator"

	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")
	by_company = verify.evidence(verify.KIND_PATTERN, BLOCKING, books)
	assert by_company.source == verify.SOURCE_COMPANY
	assert by_company.verified is False, "an acceptance is not a verification"
	assert by_company.accepted_by == "tg-5001@nyabo.local" and by_company.company == books

	# The counts a certification reader sees keep them apart too.
	counts = verify.verified_counts(verify.PATTERN)
	accepted = verify.accepted_counts(verify.PATTERN)
	assert counts["by_person"] == 1 and counts["by_seed"] == counts["verified"] - 1
	assert accepted == {"rules": 1, "companies": 1, "acceptances": 1}

	# ...and so do the events: one type per claim, never one type with a flag inside it.
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_VERIFIED}) == 1
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_ACCEPTED}) == 1


def test_an_accepted_rule_card_names_the_company_and_the_person_not_a_citation(books: str):
	"""«Verified» on a card an accountant reads means somebody stood behind the law. Here nobody did."""
	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")
	bot = FakeBotApi()
	run(
		bot,
		callback_update(
			ACCOUNTANT_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, BLOCKING)
		),
	)

	text = bot.last_text
	assert mn.CARD_RULE_ACCEPTED_BY.split("{")[0] in text
	assert books in text and "tg-5001@nyabo.local" in text
	assert mn.CARD_RULE_VERIFIED_BY.split("{")[0] not in text
	assert mn.RULE_VERIFIED_SOURCE_SEED not in text
	# Nothing is asked a second time, and there is no button to answer it with.
	assert mn.CARD_RULE_ACCEPT_ASK.format(company=books) not in text
	assert bot.callback_datas() == []


# --- 7. the language on the intake path -------------------------------------------------------------

#: Every string an intake can put in front of the accountant when a rule or a layout stops it.
#: None of them may tell the accountant to wait for somebody else, because none of them has to
#: any more. The ones that do name an admin are the site admin's own screens, listed apart below.
INTAKE_PATH_STRINGS = (
	"WARN_UNVERIFIED_RULE",
	"MSG_UNVERIFIED_RULE_BLOCKED",
	"MSG_UNVERIFIED_RULE_ACCOUNTANT_CAN_ACCEPT",
	"MSG_RULE_ACCEPTED",
	"MSG_RULE_ACCEPTED_RETRY",
	"MSG_RULE_ACCEPTED_POSTING",
	"MSG_RULE_ACCEPTED_FOR_REQUESTER",
	"MSG_RULE_ALREADY_ACCEPTED",
	"MSG_PERIOD_UNVERIFIED_RULES",
	"MSG_STATEMENT_LAYOUT_SAVED",
	"MSG_STATEMENT_LAYOUT_UNVERIFIED",
	"MSG_STATEMENT_LAYOUT_CONFIRM_ASK",
	"MSG_STATEMENT_LAYOUT_ACCEPTED",
	"MSG_STATEMENT_LAYOUT_ACCEPTED_RESEND",
	"MSG_RULES_INTRO",
	"MSG_RULES_TITLE",
	"MSG_RULES_NONE",
	"CARD_RULE_ACCEPT_ASK",
	"CARD_RULE_ACCEPT_RESPONSIBILITY",
	"CARD_RULE_NO_CITATION",
	"CARD_RULE_LAYOUT_SOURCE",
	"BTN_RULE_ACCEPT",
	"MSG_STATEMENT_LAYOUT_REIMPORTING",
	"MSG_NO_COMPANY",
	"MSG_BANK_SETTLE_NO_BANK_ACCOUNT",
	"MSG_RULE_MISSING",
	"MSG_RULE_PENDING",
	"MSG_MENU",
	"BOT_COMMAND_DESCRIPTIONS",
)

#: The other half of the sweep: the places on an intake path where somebody else really is
#: needed. They may name that person, and they must then name the door — a command to type or a
#: named screen — because «хандана уу» on its own is the dead end this work exists to remove.
STILL_NEEDS_SOMEBODY_ELSE = {
	"MSG_NO_COMPANY": "/link",
	"MSG_BANK_SETTLE_NO_BANK_ACCOUNT": "/эхлэх",
	"MSG_BANK_SETTLE_ERPNEXT_PERMISSION": "холболтын код",
	"MSG_RULE_AMBIGUOUS": "ERPNext",
	"MSG_RULES_SITE_ADMIN_ONLY": "сайтын админ",
}


@pytest.mark.parametrize("name", INTAKE_PATH_STRINGS)
def test_no_intake_path_string_tells_the_accountant_to_wait_for_an_admin(name: str):
	"""The founder's complaint, made into a test: «it is backwards and it is why it felt unusable».

	A string on this list may not contain the word «админ» at all. Where an admin genuinely is
	needed — the global row, the site config — the string belongs to the site admin's own screens
	and is not on this list; those are checked below to name *which* admin and how to reach them.
	"""
	value = getattr(mn, name)
	text = " ".join(value.values()) if isinstance(value, dict) else value
	assert "админ" not in text.lower(), (
		f"{name} is on an intake path and names an admin. The accountant is the main user and "
		"decides this themselves (DECISIONS ACC-01); reword it or move the string off the path."
	)


@pytest.mark.parametrize("name,door", sorted(STILL_NEEDS_SOMEBODY_ELSE.items()))
def test_where_somebody_else_really_is_needed_the_string_names_the_door(name: str, door: str):
	"""An honest «you cannot» must still name a door that opens, not a role to go and look for."""
	assert door in getattr(mn, name), (
		f"{name} sends the reader to another person without naming what that person does. "
		"Name the command or the screen, the way MSG_NO_COMPANY names /link."
	)


def test_the_two_acts_on_a_rule_card_are_never_worded_as_one():
	"""The accountant's answer binds their company; the site admin's binds every client (VER-08)."""
	assert mn.BTN_RULE_VERIFY_SITE != mn.BTN_RULE_ACCEPT
	assert "айт" in mn.BTN_RULE_VERIFY_SITE and "компани" in mn.BTN_RULE_ACCEPT


def test_the_menu_and_the_command_list_offer_the_rules_command_to_everyone(books: str):
	"""VER-05 kept `/дүрэм` in the menu with «админ баталгаажуулна» beside it. It is not true now."""
	from nyabo_mn.telegram import commands

	assert "rules" in commands.MENU_COMMANDS
	bot = FakeBotApi()
	run(bot, message_update(ACCOUNTANT_ID, "/меню"))
	assert "/дүрэм" in bot.last_text
