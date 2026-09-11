"""A transaction typed in words: the model reads it, code drafts it, the accountant confirms it.

The founder's own case — «орлого бүртгэ» answered with «асуултыг админд дамжууллаа» — is
what these pin: a typed sale or expense is a proposal card with [Батлах], never an
escalation, and nothing reaches the ledger before the tap.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import frappe

from nyabo_mn.agent import pipeline, post, typed
from nyabo_mn.agent.mock_client import MockLlmClient
from nyabo_mn.core.money import fmt_mnt
from nyabo_mn.i18n import mn
from nyabo_mn.reports import dashboard as data
from nyabo_mn.telegram import _deps
from tests.fixtures.telegram.fake_bot import FakeBotApi, callback_update, link_user, message_update, run
from tests.flows.conftest import ACCOUNTANT, seed_patterns

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
TYPED_PATTERNS = (typed.PATTERN_INCOME_VAT, typed.PATTERN_INCOME_NON_VAT, typed.PATTERN_EXPENSE)


def _client(text: str, **args) -> MockLlmClient:
	client = MockLlmClient()
	call = {"name": "record_transaction", "arguments": args}
	client.add("question", {"text": text, "tool_calls": [call]})
	return client


def _args(**overrides) -> dict:
	base = {
		"direction": "income",
		"amount_mnt": 2000000,
		"party": "Ганзориг ХХК",
		"description": "борлуулалт",
		"paid_via": "bank",
		"date": None,
		"account_code": None,
	}
	base.update(overrides)
	return base


def test_a_typed_sale_becomes_a_proposal_the_accountant_posts(books):
	seed_patterns(verified=True, only=TYPED_PATTERNS)
	reply = pipeline.answer_question(
		ACCOUNTANT,
		books,
		"Ганзориг ХХК-аас 2 сая орлого орлоо",
		client=_client("Бэлтгэлээ.", **_args()),
		now=NOW,
		source={"chat_id": 9701, "message_id": 5, "sender": {"id": 9701, "first_name": "Бат"}},
	)
	assert reply.proposal and reply.follow_ups == ()
	assert reply.text == mn.MSG_TYPED_PROPOSED.format(
		kind=mn.TYPED_INCOME_LABEL, amount=fmt_mnt(2000000), date="2026-09-11"
	)

	proposal = frappe.get_doc("Nyabo Proposal", reply.proposal)
	assert proposal.status == "proposed" and proposal.kind == typed.KIND and proposal.needs_accountant == 1
	assert proposal.total == 2000000 and proposal.posting_date.isoformat() == "2026-09-11"
	# VAT payer in 2026: the output VAT is carved out of the gross by code, at the verified rate.
	entry = json.loads(proposal.entry_json)
	credits = {line["account_code"]: line["credit"] for line in entry["lines"] if float(line["credit"]) > 0}
	debits = {line["account_code"]: line["debit"] for line in entry["lines"] if float(line["debit"]) > 0}
	assert list(debits.values()) == ["2000000.00"] and len(credits) == 2
	assert set(credits.values()) == {"1818181.82", "181818.18"}
	assert entry["pattern_id"] == typed.PATTERN_INCOME_VAT
	# The typed message is the primary document behind the entry (art. 13.7).
	document = frappe.get_doc("Nyabo Document", proposal.document)
	assert document.doc_type == typed.KIND and document.telegram_chat_id == "9701"
	assert frappe.db.count("GL Entry", {"company": books, "is_cancelled": 0}) == 0, "nothing posted yet"

	posted = post.post_proposal(proposal.name, ACCOUNTANT)
	assert posted["posted_doctype"] == "Journal Entry"
	je = frappe.get_doc("Journal Entry", posted["posted_name"])
	assert je.docstatus == 1 and je.source_document == proposal.document
	assert data.month_totals(books, "2026-09")["revenue"] == Decimal("1818181.82")


def test_a_typed_cash_expense_uses_the_named_account_or_the_default(books):
	reply = pipeline.answer_question(
		ACCOUNTANT,
		books,
		"Шатахуунд 85 000 төгрөг бэлнээр төлсөн",
		client=_client(
			"Бэлтгэлээ.",
			**_args(
				direction="expense", amount_mnt=85000, party="Петровис", paid_via="cash", account_code="6210"
			),
		),
		now=NOW,
	)
	entry = json.loads(frappe.get_doc("Nyabo Proposal", reply.proposal).entry_json)
	assert [(line["account_code"], line["debit"], line["credit"]) for line in entry["lines"]] == [
		("6210", "85000.00", "0.00"),
		("1110", "0.00", "85000.00"),
	]
	assert entry["pattern_id"] == typed.PATTERN_EXPENSE

	reply = pipeline.answer_question(
		ACCOUNTANT,
		books,
		"Юнителд 89 000 төлсөн",
		client=_client(
			"Бэлтгэлээ.", **_args(direction="expense", amount_mnt=89000, party="Юнител", account_code="9999")
		),
		now=NOW,
	)
	proposal = frappe.get_doc("Nyabo Proposal", reply.proposal)
	assert proposal.account_code == "6910", "an unknown code falls back to the company's default expense"
	assert mn.WARN_TYPED_NO_DOCUMENT in json.loads(proposal.warnings_json)


def test_a_sentence_without_an_amount_is_refused_by_code_not_guessed(books):
	before = frappe.db.count("Nyabo Proposal", {"company": books})
	reply = pipeline.answer_question(
		ACCOUNTANT,
		books,
		"Орлого орлоо",
		client=_client("Дүнг хэлнэ үү.", **_args(amount_mnt=0)),
		now=NOW,
	)
	assert reply.proposal is None and reply.text == "Дүнг хэлнэ үү."
	assert frappe.db.count("Nyabo Proposal", {"company": books}) == before


def test_in_telegram_the_card_carries_the_accountants_buttons_and_a_tap_posts(books, monkeypatch):
	from nyabo_mn.agent import questions

	seed_patterns(verified=True, only=TYPED_PATTERNS)
	link_user(9702, "Accountant", books)
	bot = FakeBotApi()

	def _answer(user, comp, text, memory=None, on_turn=None, on_step=None, source=None):
		on_step("record_transaction", _args())
		result = typed.propose(comp, user, _args(), text=text, source=source, today=NOW.date())
		return questions.Reply(text=result["text"], proposal=result["proposal"])

	monkeypatch.setattr(_deps, "answer_question", _answer)
	run(bot, message_update(9702, "Ганзориг ХХК-аас 2 сая орлого орлоо"))
	name = frappe.get_all("Nyabo Proposal", filters={"company": books}, pluck="name")[-1]
	assert bot.last_text.startswith(mn.MSG_TYPED_PROPOSED.split("{")[0])
	assert "Ганзориг ХХК" in bot.last_text and fmt_mnt(2000000) in bot.last_text
	assert bot.callback_datas() == [f"p:{name}:ap", f"p:{name}:ch", f"p:{name}:rj"]
	assert (
		bot.sent("send_rich_draft")[-1]["html"] == f"<tg-thinking>{mn.CARD_THINKING_DRAFTING}</tg-thinking>"
	)

	run(bot, callback_update(9702, f"p:{name}:ap"))
	assert frappe.db.get_value("Nyabo Proposal", name, "status") == "posted"
	assert mn.MSG_ESCALATED not in bot.texts()
