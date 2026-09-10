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

import json
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


def _accept(
	bot: FakeBotApi,
	telegram_id: int,
	company: str,
	rule: str = BLOCKING,
	kind: str = verify.KIND_PATTERN,
):
	"""Tap [Манай компанид хамаарна] on a card that asked about ``company``.

	The client the card named rides on the button (``keyboards.company_token``), so the tap can
	only ever be answered for that client — which is why every call here has to say which one it
	was looking at, exactly as the real card does.
	"""
	return run(
		bot,
		callback_update(telegram_id, keyboards.rule_data(keyboards.VERIFY_ACCEPT, kind, rule, company)),
	)


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
	assert keyboards.rule_data(keyboards.VERIFY_ACCEPT, verify.KIND_PATTERN, BLOCKING, books) in (
		bot.callback_datas()
	)

	outcome = _accept(bot, ACCOUNTANT_ID, books)

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
	outcome = _accept(colleague, OTHER_ACCOUNTANT_ID, books)

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
	outcome = _accept(bot, ACCOUNTANT_ID, books)

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

	_accept(bot, OTHER_ACCOUNTANT_ID, company_v03)
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


# --- 3b. the rule may not change underneath the acceptance ---------------------------------------


def _redeploy_with_a_different_debit(rule: str = BLOCKING) -> str:
	"""What a later deploy does: the same seed row, with its debit line rewritten.

	`seed.upsert` is called exactly as `seed.sync` calls it — an unverified row is not protected
	from a rewrite, and an accepted rule *is* unverified, which is the whole of this finding.
	"""
	import copy

	from nyabo_mn.nyabo.seed import load_seed
	from nyabo_mn.rules import seed

	row = copy.deepcopy(next(r for r in load_seed("posting_patterns")["rows"] if r["pattern_id"] == rule))
	row["lines"][0]["account_class"] = "31"
	row["lines"][0]["class_name_mn"] = "Дансны өглөг"
	return seed.upsert(
		seed.POSTING_PATTERN, rule, seed.posting_pattern_values(row), force=False, child_field="lines"
	)


def test_a_deploy_that_rewrites_an_accepted_rule_stops_it_posting_again(
	books: str, monkeypatch: pytest.MonkeyPatch
):
	"""An acceptance covers content, not a name — and an accepted rule is still an unverified row.

	`seed.upsert` protects `verified = 1` from a rewrite; nothing protected the third provenance,
	so a deploy could change the debit and credit lines while the acceptance stood, and the
	company went on posting under that accountant's name on content they never saw.
	"""
	posted = _guarded_post(monkeypatch)
	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")
	guard.require_verified(BLOCKING, company=books)  # today it posts

	assert _redeploy_with_a_different_debit() == "updated"

	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING, company=books)
	assert posted == []
	# ...and it is back on the list of what will refuse this company's postings.
	assert BLOCKING in {rule.name for rule in verify.pending(company=books)}


def test_the_change_is_on_the_record_before_anybody_is_refused(books: str):
	"""«Do not silently invalidate» — the deploy that outran the acceptance writes its own row.

	Without it the acceptance simply stops working and the only trace is a refusal in a chat.
	The event names the company, the rule, who had accepted it, and both fingerprints, so an
	auditor can see what the acceptance covered and what the row says now.
	"""
	result = verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")
	before = frappe.db.get_value(verify.ACCEPTANCE, result["acceptance"], "rule_fingerprint")
	assert before, "the acceptance records the content it was given for"

	_redeploy_with_a_different_debit()

	events = frappe.get_all(
		"Nyabo Event",
		filters={"event_type": mn.EVENT_RULE_CHANGED_AFTER_ACCEPTANCE},
		fields=["name", "company", "ref_name", "payload_json"],
	)
	assert len(events) == 1
	event = events[0]
	assert event["company"] == books and event["ref_name"] == BLOCKING
	payload = (
		json.loads(event["payload_json"]) if isinstance(event["payload_json"], str) else event["payload_json"]
	)
	assert payload["accepted_by"] == "tg-5001@nyabo.local"
	assert payload["accepted_fingerprint"] == before and payload["fingerprint"] != before
	# The acceptance row itself is untouched: it is the record of what that person read.
	assert frappe.db.get_value(verify.ACCEPTANCE, result["acceptance"], "rule_fingerprint") == before


def test_the_accountant_is_told_what_changed_and_accepts_the_new_version(
	books: str, monkeypatch: pytest.MonkeyPatch
):
	"""Refuse again, say plainly what changed, ask for the new version — not silence either way."""
	posted = _guarded_post(monkeypatch)
	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")
	_redeploy_with_a_different_debit()
	proposal = make_proposal(books, posting_pattern=BLOCKING)
	bot = FakeBotApi()

	refused = run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	assert refused["result"]["unverified_rule"] == BLOCKING and posted == []
	told = "\n".join(bot.texts())
	assert mn.CARD_RULE_CHANGED_TITLE in told
	assert "Дансны өглөг" in told, "the line as it reads now"
	assert "Бусад өглөг, урьдчилан төлөгдсөн орлого" in told, "and the line they had accepted"

	outcome = _accept(bot, ACCOUNTANT_ID, books)

	assert outcome["result"]["accepted"] is True and posted == ["JE-00000"]
	# Two rows, because there were two decisions: what was accepted before the change is not
	# rewritten to say the accountant read something they never saw.
	rows = verify.acceptances(BLOCKING)
	assert len(rows) == 2 and {row["company"] for row in rows} == {books}
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_ACCEPTED}) == 2


def test_a_change_the_lines_do_not_show_is_still_shown(books: str):
	"""A pattern's scope decides which documents reach those lines, so it is part of the content.

	It is also the one change a card of debit and credit lines would print identically twice —
	«the rule changed, here it is, and here it is again» is worse than saying nothing, because it
	reads as a bug and teaches the accountant to tap through the warning.
	"""
	import copy

	from nyabo_mn.nyabo.seed import load_seed
	from nyabo_mn.rules import seed

	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")
	row = copy.deepcopy(next(r for r in load_seed("posting_patterns")["rows"] if r["pattern_id"] == BLOCKING))
	assert row.get("applies_to_vat") == "non_vat"
	row["applies_to_vat"] = "any"  # the lines are untouched; what reaches them is not

	seed.upsert(
		seed.POSTING_PATTERN, BLOCKING, seed.posting_pattern_values(row), force=False, child_field="lines"
	)

	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING, company=books)
	change = verify.rule_change(books, BLOCKING, verify.PATTERN)
	assert change is not None and change.before != change.after, (
		"the card must never print the two versions identically"
	)
	assert mn.RULE_VAT_SCOPE_NON_VAT in "\n".join(change.before)
	assert mn.RULE_VAT_SCOPE_ANY in "\n".join(change.after)


def test_a_deploy_that_changes_nothing_leaves_every_acceptance_standing(books: str):
	"""The everyday migrate: `sync` runs on every deploy and must not cry wolf."""
	from nyabo_mn.rules import seed

	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")

	seed.sync()

	guard.require_verified(BLOCKING, company=books)
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_CHANGED_AFTER_ACCEPTANCE}) == 0


def test_the_acceptance_cannot_be_edited_by_the_person_it_names(books: str):
	"""A compliance record the accountant it names could rewrite is not a record (MINOR 5).

	`Nyabo Accountant` held `write` and the identifying fields were only read-only in the UI, so
	the person an acceptance names could change the rule, the company or the date afterwards with
	no matching event. Append-only, in the controller, the way Nyabo Event is — a site whose roles
	were changed in the desk must still not be able to rewrite it.
	"""
	result = verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")
	row = frappe.get_doc(verify.ACCEPTANCE, result["acceptance"])

	row.note = "second thoughts"
	with pytest.raises(frappe.ValidationError) as exc:
		row.save()

	assert mn.MSG_ACCEPTANCE_APPEND_ONLY in str(exc.value)
	assert not frappe.db.get_value(verify.ACCEPTANCE, result["acceptance"], "note")
	# ...and no role carries a write it does not need. Deletion stays: it is how an acceptance is
	# withdrawn in the desk, and the rule stops posting again the moment it is.
	meta = frappe.get_meta(verify.ACCEPTANCE)
	assert [p.role for p in meta.permissions if p.write] == []
	assert sorted(p.role for p in meta.permissions if p.delete) == ["Nyabo Admin", "System Manager"]


def test_withdrawing_an_acceptance_in_the_desk_stops_the_rule_posting_again(books: str):
	"""The correction path the module docstring promises, kept working by the append-only rule."""
	result = verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")
	guard.require_verified(BLOCKING, company=books)

	frappe.delete_doc(verify.ACCEPTANCE, result["acceptance"])

	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING, company=books)
	# The event stays: what happened, happened.
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_ACCEPTED}) == 1


# --- 4. who may take the decision -----------------------------------------------------------------


def test_an_owner_cannot_accept_a_rule(books: str):
	"""An owner may approve a simple document; deciding that a rule applies to the books is not theirs."""
	link_user(OWNER_ID, "Owner", books)
	bot = FakeBotApi()

	outcome = _accept(bot, OWNER_ID, books)

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

	_accept(bot, OTHER_ACCOUNTANT_ID, company_v03)

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

	accepted = _accept(bot, MULTI_CLIENT_ID, company_v03)

	# ...and the acceptance is written for the client the document belongs to, which is the only
	# company it unblocks — the active one is untouched.
	assert accepted["result"]["company"] == company_v03
	assert accepted["result"]["posted"] == "JE-00000" and posted == ["JE-00000"]
	assert [row["company"] for row in verify.acceptances(BLOCKING)] == [company_v03]
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING, company=books)


def _the_card_goes_cold() -> None:
	"""Age every refusal past ``REQUEST_DEDUPE_MINUTES``: the accountant walked away and came back.

	The inline button on the card stays live for ever, and this is the state it is tapped in far
	more often than not — a client rings, twenty minutes go by, and the card is still on screen.
	"""
	from frappe.utils import add_to_date, now_datetime

	long_ago = add_to_date(now_datetime(), minutes=-(verify.REQUEST_DEDUPE_MINUTES + 5))
	for row in frappe.get_all("Nyabo Event", filters={"event_type": mn.EVENT_RULE_BLOCKED}, pluck="name"):
		frappe.db.set_value("Nyabo Event", row, "creation", long_ago, update_modified=False)


def _drawn_accept_datum(bot: FakeBotApi) -> str:
	"""The [Манай компанид хамаарна] datum the card really drew — never one rebuilt by the test."""
	prefix = f"{keyboards.PREFIX_VERIFY}:{keyboards.VERIFY_ACCEPT}:"
	return next(data for data in bot.callback_datas() if data.startswith(prefix))


def test_a_tap_twenty_minutes_late_is_recorded_for_the_client_the_card_asked_about(
	books: str, company_v03: str, monkeypatch: pytest.MonkeyPatch
):
	"""BLOCKER 1: a compliance record must never be able to say something that did not happen.

	The company an acceptance was written for used to be resolved on the tap from this chat's
	recent refusals, which only look back ``REQUEST_DEDUPE_MINUTES``; the button on the card
	never expires. So an accountant with two clients, stopped on client B's receipt, who walked
	away for twenty minutes and then tapped got the acceptance written for client A — whichever
	company happened to be active. The card asked about B, the record said A, A's books were
	unblocked on a rule nobody had decided about for A, and B stayed stuck.

	The company now rides on the card's own button as a digest of the name and is resolved
	against this reader's own linked companies (TG-03), so the answer is the same however long
	the card sat there. Finishing the *posting* is deliberately not: that stays inside the retry
	window (VER-04), so the accountant is told the one tap that is left rather than having a
	receipt posted for them out of a card of unknown age.
	"""
	posted = _guarded_post(monkeypatch)
	link_user(MULTI_CLIENT_ID, "Accountant", books)
	link_user(MULTI_CLIENT_ID, "Accountant", company_v03)
	assert frappe.db.get_value("Nyabo User Link", str(MULTI_CLIENT_ID), "active_company") == books

	other = make_proposal(company_v03, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	run(bot, callback_update(MULTI_CLIENT_ID, f"p:{other.name}:ap"))
	tap = _drawn_accept_datum(bot)

	_the_card_goes_cold()
	bot.clear()
	accepted = run(bot, callback_update(MULTI_CLIENT_ID, tap))

	assert accepted["result"]["company"] == company_v03, "the card asked about B; so does the record"
	assert [row["company"] for row in verify.acceptances(BLOCKING)] == [company_v03]
	# A was never asked about and is not cleared — the whole point of the per-company record.
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING, company=books)
	guard.require_verified(BLOCKING, company=company_v03)
	# ...and the confirmation on screen names the same client the row does.
	assert any(company_v03 in text for text in bot.texts())
	# The refused tap is too old to finish for them, so they are told the one tap that is left.
	assert posted == [] and mn.MSG_RULE_ACCEPTED_RETRY in bot.texts()


def test_a_card_whose_client_this_reader_no_longer_keeps_is_refused_not_guessed_at(
	books: str, company_v03: str, monkeypatch: pytest.MonkeyPatch
):
	"""The datum names a client, and it is never trusted on its own (TG-03).

	The digest can only *select* among the companies the tapper is linked to and keeps the books
	of. When it selects none of them — the accountant was unlinked from that client, or the datum
	was copied out of somebody else's chat — there is nothing the acceptance could truthfully
	say, so nothing is written and the card says so. Falling back to the active company here is
	exactly the guess that put one client's name on another client's decision.
	"""
	_guarded_post(monkeypatch)
	link_user(ACCOUNTANT_ID, "Accountant", books)
	bot = FakeBotApi()

	outcome = _accept(bot, ACCOUNTANT_ID, company_v03)

	assert outcome["result"] == {"accepted": False, "reason": "unknown_company", "rule": BLOCKING}
	assert frappe.db.count(verify.ACCEPTANCE) == 0
	assert frappe.db.count("Nyabo Event", {"event_type": mn.EVENT_RULE_ACCEPTED}) == 0
	assert bot.last_text == mn.MSG_RULE_ACCEPT_COMPANY_UNKNOWN
	# ...and their own client is not quietly cleared instead.
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING, company=books)


def test_after_clearing_one_client_the_accountant_can_clear_the_next(
	books: str, company_v03: str, monkeypatch: pytest.MonkeyPatch
):
	"""The other half of the multi-client day: turning from the client you just cleared to the next.

	``blocked_company`` answers «the client whose document is waiting», and it went on answering
	after that client had been answered for. So the accountant cleared the rule for client B, ran
	``/дүрэм`` on client A — a list drawn for A, with this rule on it because A's work is still
	refused — opened it, and read «already accepted for B» over a card with no buttons. There was
	nothing left to tap and A stayed blocked: a dead end reached by the most ordinary sequence
	there is.
	"""
	posted = _guarded_post(monkeypatch)
	link_user(MULTI_CLIENT_ID, "Accountant", books)
	link_user(MULTI_CLIENT_ID, "Accountant", company_v03)
	other = make_proposal(company_v03, posting_pattern=BLOCKING)
	bot = FakeBotApi()
	run(bot, callback_update(MULTI_CLIENT_ID, f"p:{other.name}:ap"))
	_accept(bot, MULTI_CLIENT_ID, company_v03)
	assert [row["company"] for row in verify.acceptances(BLOCKING)] == [company_v03] and posted

	# Same accountant, same quarter of an hour, now on their own active client's list.
	bot.clear()
	opened = run(
		bot,
		callback_update(
			MULTI_CLIENT_ID, keyboards.rule_data(keyboards.VERIFY_OPEN, verify.KIND_PATTERN, BLOCKING)
		),
	)

	assert opened["result"].get("already") is not True, "A has answered nothing; the card must ask"
	assert bot.callback_datas(), "a card the accountant cannot answer is the dead end itself"
	assert any(mn.CARD_RULE_ACCEPT_ASK.format(company=books) in text for text in bot.texts())

	accepted = _accept(bot, MULTI_CLIENT_ID, books)

	assert accepted["result"]["company"] == books
	assert sorted(row["company"] for row in verify.acceptances(BLOCKING)) == sorted([books, company_v03])
	guard.require_verified(BLOCKING, company=books)  # A may post now, and so may B


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


def test_a_name_no_guarded_doctype_knows_is_never_cleared_by_an_acceptance(
	books: str, monkeypatch: pytest.MonkeyPatch
):
	"""MINOR 8: ``guard._ref`` returns no DocType for a bare name none of them has, and the
	acceptance lookup went ahead anyway — with ``doctype=None``, so any acceptance of that name
	for that company would have cleared it.

	Unknown means unverified. That is ``require_verified``'s own rule and it is what the guard
	says everywhere else; here it was being decided by accident, which is a different thing from
	being decided.
	"""
	asked: list[tuple[Any, ...]] = []
	real = verify.acceptance

	def spy(company: Any, rule: str, doctype: str | None = None) -> Any:
		asked.append((company, rule, doctype))
		return real(company, rule, doctype)

	monkeypatch.setattr(verify, "acceptance", spy)

	assert guard.accepted_for("no_such_rule_anywhere", books) is False

	# The reachable shape of the same thing: the rule row is deleted and its acceptance is left
	# behind. A rule Nyabo cannot look up has no content anybody can have read.
	monkeypatch.undo()
	verify.accept(verify.KIND_PATTERN, BLOCKING, books, "tg-5001@nyabo.local")
	guard.require_verified(BLOCKING, company=books)
	frappe.delete_doc(verify.PATTERN, BLOCKING)

	assert guard.accepted_for(BLOCKING, books) is False
	assert guard.is_verified(BLOCKING, company=books) is False
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(BLOCKING, company=books)
	# The acceptance row stays: it is a record of what somebody read, never a permission.
	assert [row["company"] for row in verify.acceptances(BLOCKING)] == [books]
	assert asked == [], "nothing is asked about a name that is in none of the guarded DocTypes"


#: The employee social-insurance rate: an uncited tax parameter that stops an ordinary payroll,
#: and the one shape ``guard._ref``'s docstring warns about — a core ``ParameterRow`` carries
#: ``key`` and ``effective_from`` separately, while the row it came from is named ``key:date``.
SI_RATE_KEY = "si.employee_rate"
SI_RATE_ROW = "si.employee_rate:2026-01-01"


def test_a_tax_parameter_acceptance_clears_the_guard_through_a_parameter_row(books: str, company_v03: str):
	"""MINOR 6: the failure ``guard._ref`` names in its own docstring, covered.

	``rules.params.get`` hands the guard a ``ParameterRow``, not a name. If the guard asked about
	``si.employee_rate`` instead of ``si.employee_rate:2026-01-01`` it would never find the
	acceptance recorded a moment earlier, and would go on refusing a rule the accountant had just
	accepted — which is the one failure this whole flow exists to remove. Nothing else on the tax
	side exercises that mapping.
	"""
	import datetime as dt

	from nyabo_mn.rules import params

	on_date = dt.date(2026, 6, 15)
	assert frappe.db.get_value(verify.PARAMETER, SI_RATE_ROW, "verified") == 0

	with pytest.raises(guard.UnverifiedRuleError) as refused:
		params.get(SI_RATE_KEY, on_date, company=books)
	assert refused.value.rule == SI_RATE_ROW, "the refusal names the row, not the bare key"

	verify.accept(verify.KIND_PARAMETER, SI_RATE_ROW, books, "tg-5001@nyabo.local")

	row = params.get(SI_RATE_KEY, on_date, company=books)
	assert str(row.key) == SI_RATE_KEY and row.verified is False, "cleared by acceptance, not by a flag"
	# The guard was asked about the ParameterRow itself, and found the acceptance under the
	# document name the row is stored as.
	assert guard.accepted_for(row, books) is True
	assert guard.is_verified(row, company=books) is True
	# ...and it binds one company, on this side of the guard exactly as on the pattern side.
	assert guard.accepted_for(row, company_v03) is False
	with pytest.raises(guard.UnverifiedRuleError):
		params.get(SI_RATE_KEY, on_date, company=company_v03)


def test_a_tax_parameter_refusal_reaches_the_accountants_card_by_the_name_it_names(
	books: str, monkeypatch: pytest.MonkeyPatch
):
	"""The other half of the same mapping: the refusal has to name a row somebody can open.

	``handlers.admin.rule_blocked`` looks the rule up by the name in the message. A refusal that
	said ``si.employee_rate`` named nothing — the row is ``si.employee_rate:2026-01-01`` — so the
	accountant got no evidence card and was told which person decides, on the tax-parameter path
	the whole flow is supposed to cover.
	"""

	def post_proposal(name: str, user: str, telegram_id: str) -> dict[str, Any]:
		import datetime as dt

		from nyabo_mn.rules import params

		proposal = frappe.get_doc("Nyabo Proposal", name)
		params.get(SI_RATE_KEY, dt.date(2026, 6, 15), company=proposal.company)
		raise AssertionError("the guard was supposed to refuse")

	monkeypatch.setattr(_deps, "post_proposal", post_proposal)
	proposal = make_proposal(books, posting_pattern=CITED)
	bot = FakeBotApi()

	outcome = run(bot, callback_update(ACCOUNTANT_ID, f"p:{proposal.name}:ap"))

	assert outcome["result"]["unverified_rule"] == SI_RATE_ROW
	assert outcome["result"]["offered"] is True
	assert mn.MSG_UNVERIFIED_RULE_ACCOUNTANT_CAN_ACCEPT.format(company=books) in bot.texts()
	assert keyboards.rule_data(keyboards.VERIFY_ACCEPT, verify.KIND_PARAMETER, SI_RATE_ROW, books) in (
		bot.callback_datas()
	)


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
	# The two the first sweep missed (MINOR 9). Onboarding is the first intake there is, and a
	# refused question is the accountant asking about their own books; neither of them has an
	# admin to send anybody to, and one of them promised a notification nothing sends.
	"MSG_ONBOARDING_APPLY_PENDING",
	"AGENT_ANSWER_INJECTION_REFUSED",
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
