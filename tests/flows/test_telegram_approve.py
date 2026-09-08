"""Approve / change account / reject taps with the role gate of §5.3."""

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


def _fake_pipeline(monkeypatch):
	calls: dict[str, list] = {"post": [], "change": [], "reject": []}

	def post_proposal(name, user, telegram_id):
		calls["post"].append((name, user, telegram_id))
		doc = frappe.get_doc("Nyabo Proposal", name)
		doc.db_set(
			{
				"status": "posted",
				"posted_doctype": "Journal Entry",
				"posted_name": "ACC-JV-2026-00009",
				"approved_by": user,
				"approved_telegram_id": telegram_id,
			}
		)
		return {"posted_doctype": "Journal Entry", "posted_name": "ACC-JV-2026-00009"}

	def change_account(name, code, user):
		calls["change"].append((name, code, user))
		doc = frappe.get_doc("Nyabo Proposal", name)
		doc.db_set({"account_code": code})
		return doc

	def reject(name, reason_code, user, reason_text=None):
		calls["reject"].append((name, reason_code, user, reason_text))
		reason = reason_text or mn.REJECT_REASONS.get(reason_code, mn.REJECT_OTHER)
		frappe.get_doc("Nyabo Proposal", name).db_set({"status": "rejected", "rejection_reason": reason})

	monkeypatch.setattr(_deps, "post_proposal", post_proposal)
	monkeypatch.setattr(_deps, "change_account", change_account)
	monkeypatch.setattr(_deps, "reject", reject)
	monkeypatch.setattr(
		_deps, "top_accounts", lambda company, n=6: [("6210", "Шатахуун"), ("6910", "Бусад зардал")][:n]
	)
	monkeypatch.setattr(
		_deps, "search_accounts", lambda company, q: [("6220", "Тээвэр")] if "тээ" in q.lower() else []
	)
	return calls


def test_owner_cannot_approve_needs_accountant(company, monkeypatch):
	calls = _fake_pipeline(monkeypatch)
	link_user(2001, "Owner", company)
	proposal = make_proposal(company, needs_accountant=1)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(2001, f"p:{proposal.name}:ap"))
	assert outcome["result"] == {"approved": False}
	assert bot.last_text == mn.MSG_ACCOUNTANT_ONLY
	assert calls["post"] == []
	assert frappe.db.get_value("Nyabo Proposal", proposal.name, "status") == "proposed"
	# the callback query is always answered
	assert bot.sent("answer_callback_query")


def test_owner_refused_without_auto_approve_policy(company, monkeypatch):
	calls = _fake_pipeline(monkeypatch)
	link_user(2002, "Owner", company)
	proposal = make_proposal(company, needs_accountant=0)
	bot = FakeBotApi()
	run(bot, callback_update(2002, f"p:{proposal.name}:ap"))
	assert bot.last_text == mn.MSG_ACCOUNTANT_ONLY and calls["post"] == []


def test_owner_allowed_by_owner_simple_policy(company, monkeypatch):
	calls = _fake_pipeline(monkeypatch)
	link_user(2003, "Owner", company)
	name = frappe.db.exists("Nyabo Company Settings", {"company": company})
	frappe.db.set_value(
		"Nyabo Company Settings",
		name,
		{
			"auto_approve_policy": "owner_simple",
			"auto_approve_max_amount": 100000,
			"auto_approve_accounts": "6210, 6220",
		},
	)
	proposal = make_proposal(company, needs_accountant=0, total=85000, account_code="6210")
	bot = FakeBotApi()
	outcome = run(bot, callback_update(2003, f"p:{proposal.name}:ap"))
	assert outcome["result"]["approved"] is True
	assert calls["post"] == [(proposal.name, "tg-2003@nyabo.local", "2003")]

	over_cap = make_proposal(company, needs_accountant=0, total=150000, account_code="6210")
	run(bot, callback_update(2003, f"p:{over_cap.name}:ap"))
	assert bot.last_text == mn.MSG_ACCOUNTANT_ONLY
	other_account = make_proposal(company, needs_accountant=0, total=1000, account_code="6910")
	run(bot, callback_update(2003, f"p:{other_account.name}:ap"))
	assert bot.last_text == mn.MSG_ACCOUNTANT_ONLY
	assert len(calls["post"]) == 1


def test_accountant_approve_posts_and_edits_card(company, monkeypatch):
	calls = _fake_pipeline(monkeypatch)
	link_user(2004, "Accountant", company, first_name="Сараа")
	proposal = make_proposal(company, needs_accountant=1)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(2004, f"p:{proposal.name}:ap", message_id=501))
	assert outcome["result"] == {
		"approved": True,
		"posted_doctype": "Journal Entry",
		"posted_name": "ACC-JV-2026-00009",
	}
	assert calls["post"] == [(proposal.name, "tg-2004@nyabo.local", "2004")]
	edits = bot.sent("edit_message_text")
	assert edits[0]["message_id"] == 501 and mn.MSG_APPROVED_POSTING in edits[0]["text"]
	final = edits[-1]
	assert final["text"].endswith(
		mn.MSG_POSTED_CARD_FOOTER.format(doc_name="ACC-JV-2026-00009", approver="Сараа")
	)
	assert final["text"].startswith("🧾 Петровис ХХК")
	assert final["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "x:je:ACC-JV-2026-00009:rev"
	assert bot.sent("answer_callback_query")[-1]["text"] == mn.MSG_POSTED.format(doc_name="ACC-JV-2026-00009")

	# a second tap on the same card is refused as already decided
	bot.clear()
	run(bot, callback_update(2004, f"p:{proposal.name}:ap", message_id=501))
	assert calls["post"] and len(calls["post"]) == 1
	assert mn.MSG_PROPOSAL_ALREADY_DECIDED.format(status="posted") in [
		kw["text"] for kw in bot.sent("answer_callback_query")
	]


def test_change_account_flow(company, monkeypatch):
	calls = _fake_pipeline(monkeypatch)
	link_user(2005, "Accountant", company)
	proposal = make_proposal(company)
	bot = FakeBotApi()
	run(bot, callback_update(2005, f"p:{proposal.name}:ch", message_id=601))
	markup = bot.sent("edit_message_reply_markup")[-1]["reply_markup"]
	datas = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
	assert f"p:{proposal.name}:acc:6210" in datas and f"p:{proposal.name}:acc:more" in datas
	assert f"p:{proposal.name}:back" in datas

	run(bot, callback_update(2005, f"p:{proposal.name}:acc:6910", message_id=601))
	assert calls["change"] == [(proposal.name, "6910", "tg-2005@nyabo.local")]
	edit = bot.sent("edit_message_text")[-1]
	assert "📒 6910" in edit["text"] and edit["message_id"] == 601
	assert edit["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"p:{proposal.name}:ap"

	# "Өөр данс…" opens a text search
	bot.clear()
	run(bot, callback_update(2005, f"p:{proposal.name}:acc:more", message_id=601))
	assert bot.last_text == mn.MSG_SEARCH_ACCOUNT
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "2005"}, "state") == "acc_search"
	run(bot, message_update(2005, "тээвэр"))
	assert f"p:{proposal.name}:acc:6220" in bot.callback_datas()
	assert frappe.db.get_value("Nyabo Chat State", {"chat_id": "2005"}, "state") in (None, "")
	run(bot, callback_update(2005, f"p:{proposal.name}:acc:more", message_id=601))
	run(bot, message_update(2005, "юу ч байхгүй"))
	assert bot.last_text == mn.MSG_ACCOUNT_NOT_FOUND.format(query="юу ч байхгүй")


def test_reject_reason_flow(company, monkeypatch):
	calls = _fake_pipeline(monkeypatch)
	link_user(2006, "Accountant", company)
	proposal = make_proposal(company)
	bot = FakeBotApi()
	run(bot, callback_update(2006, f"p:{proposal.name}:rj", message_id=701))
	markup = bot.sent("edit_message_reply_markup")[-1]["reply_markup"]
	datas = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
	assert f"p:{proposal.name}:rr:personal" in datas and f"p:{proposal.name}:rr:other" in datas
	run(bot, callback_update(2006, f"p:{proposal.name}:rr:personal", message_id=701))
	# the tapped code travels, not its Mongolian label (the corrections job keys off the code)
	assert calls["reject"] == [(proposal.name, "personal", "tg-2006@nyabo.local", None)]
	edit = bot.sent("edit_message_text")[-1]
	assert edit["text"].endswith(mn.MSG_REJECTED_CARD_FOOTER.format(reason=mn.REJECT_PERSONAL))
	assert edit["reply_markup"] == {"inline_keyboard": []}

	other = make_proposal(company)
	bot.clear()
	run(bot, callback_update(2006, f"p:{other.name}:rr:other", message_id=702))
	assert bot.last_text == mn.MSG_REJECT_TEXT_ASK
	run(bot, message_update(2006, "Энэ бол ажилтны хувийн зардал"))
	assert calls["reject"][-1] == (
		other.name,
		"other",
		"tg-2006@nyabo.local",
		"Энэ бол ажилтны хувийн зардал",
	)
	assert bot.sent("edit_message_text")[-1]["message_id"] == 702


def test_unknown_proposal_is_answered_with_alert(company, monkeypatch):
	calls = _fake_pipeline(monkeypatch)
	link_user(2007, "Accountant", company)
	bot = FakeBotApi()
	run(bot, callback_update(2007, "p:NYP-99999:ap"))
	assert bot.sent("answer_callback_query")[0]["text"] == mn.MSG_PROPOSAL_NOT_FOUND
	assert calls["post"] == [] and bot.sent("send_message") == []


def test_callback_without_link_is_ignored(site):
	bot = FakeBotApi()
	outcome = run(bot, callback_update(2999, "p:NYP-00001:ap"))
	assert outcome["result"] is None
	assert bot.sent("send_message") == []
	assert bot.sent("answer_callback_query")


def test_account_chooser_uses_the_real_deps_shim(company):
	"""No monkeypatch: the tap must resolve ``_deps.top_accounts`` at its real dotted path."""
	link_user(2101, "Accountant", company)
	proposal = make_proposal(company)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(2101, f"p:{proposal.name}:ch"))
	assert outcome.get("error") is None
	assert outcome["result"]["accounts"], "top_accounts returned nothing through the real shim"
	assert mn.MSG_FEATURE_UNAVAILABLE not in bot.texts()


def test_rejection_stores_the_tapped_code_not_its_label(company):
	"""Real ``_deps.reject``: Nyabo Correction.reason must stay machine-readable (§5.6)."""
	link_user(2102, "Accountant", company)
	proposal = make_proposal(company)
	bot = FakeBotApi()
	run(bot, callback_update(2102, f"p:{proposal.name}:rr:dup", message_id=801))
	row = frappe.get_all(
		"Nyabo Correction",
		filters={"proposal": proposal.name},
		fields=["field", "source", "reason", "reason_text"],
	)[0]
	assert (row.field, row.source, row.reason, row.reason_text) == (
		"rejected",
		"rejection",
		"dup",
		mn.REJECT_REASONS["dup"],
	)
	assert (
		frappe.db.get_value("Nyabo Proposal", proposal.name, "rejection_reason") == (mn.REJECT_REASONS["dup"])
	)

	other = make_proposal(company)
	bot.clear()
	run(bot, callback_update(2102, f"p:{other.name}:rr:other", message_id=802))
	run(bot, message_update(2102, "Энэ бол ажилтны хувийн зардал"))
	row = frappe.get_all(
		"Nyabo Correction", filters={"proposal": other.name}, fields=["reason", "reason_text"]
	)[0]
	assert (row.reason, row.reason_text) == ("other", "Энэ бол ажилтны хувийн зардал")
	assert frappe.db.get_value("Nyabo Proposal", other.name, "rejection_reason") == (
		"Энэ бол ажилтны хувийн зардал"
	)


def _second_company() -> str:
	from nyabo_mn.setup.provision_company import provision_company

	provision_company("Хоёр ХХК", "HOY", vat_registered=0)
	return "Хоёр ХХК"


def test_accountant_code_for_one_company_does_not_promote_the_other(company, monkeypatch):
	"""An owner who keeps another company's books stays an owner in their own (SEC-04)."""
	from nyabo_mn.agent import post as agent_post
	from nyabo_mn.telegram import state as chat_state

	calls = _fake_pipeline(monkeypatch)
	link_user(2201, "Owner", company)
	other = _second_company()
	link_user(2201, "Accountant", other)  # a code issued by the other company's admin

	link = frappe.get_doc("Nyabo User Link", "2201")
	assert sorted((row.company, row.role) for row in link.companies) == [
		(company, "Owner"),
		(other, "Accountant"),
	]
	assert chat_state.role_for(link, company) == "Owner"
	assert chat_state.role_for(link, other) == "Accountant"
	assert agent_post.approver_kind(company, "tg-2201@nyabo.local") == "owner"
	assert agent_post.approver_kind(other, "tg-2201@nyabo.local") == "accountant"

	# the Telegram tap on his own company's accountant-only proposal is still refused
	proposal = make_proposal(company, needs_accountant=1)
	bot = FakeBotApi()
	outcome = run(bot, callback_update(2201, f"p:{proposal.name}:ap"))
	assert outcome["result"] == {"approved": False}
	assert bot.last_text == mn.MSG_ACCOUNTANT_ONLY
	assert calls["post"] == []
	assert frappe.db.get_value("Nyabo Proposal", proposal.name, "status") == "proposed"

	# and it goes through for the company he really is the accountant of
	run(bot, message_update(2201, f"/компани {other}"))
	theirs = make_proposal(other, needs_accountant=1)
	run(bot, callback_update(2201, f"p:{theirs.name}:ap"))
	assert frappe.db.get_value("Nyabo Proposal", theirs.name, "status") == "posted"
