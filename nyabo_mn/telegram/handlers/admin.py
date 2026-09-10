"""Admin commands: ``/link`` issues a code, ``/status`` shows site health, ``/дүрэм`` verifies a rule.

Admins are the link role ``Admin`` or the ids in ``ADMIN_TELEGRAM_IDS``; the second lets
the founder issue the very first accountant code before any link row exists.

``/дүрэм`` (``/rules`` in the ☰ menu) is the door ``MSG_UNVERIFIED_RULE_BLOCKED`` points at, and
it is the **accountant's** command, which is why it lives beside the admin ones rather than among
them. The refusal used to tell the accountant to wait for an admin, and only a site admin could
act — so the person whose signature the entry carries could not move. Now the accountant reads
the rule and accepts it for their own company (DECISIONS ACC-01), and the site admin keeps the
global verification for when a citation turns up (VER-08). Both taps, and the two very different
sentences they produce, live here; the writes and the audit events live in ``rules.verify``.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.config import get_settings
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram import _deps, cards, keyboards
from nyabo_mn.telegram import state as chat_state
from nyabo_mn.telegram.context import ACCOUNTANT_ROLES, Ctx

# One screen of rules: the card stays readable and every row still gets its own button. The
# count in the header is the real total, so a cut list never understates what is blocking work.
RULES_PER_CARD = 8
#: ``rules.verify.KIND_LAYOUT``. A bank layout is accepted through this same handler, and the
#: sentence after it differs: a layout stops a *file*, not a card with a [Батлах] on it (ACC-02).
LAYOUT_KIND = "b"


def noop() -> None:
	return None


def handle_link(ctx: Ctx) -> Any:
	if not ctx.is_admin:
		ctx.reply(mn.MSG_ADMIN_ONLY)
		return None
	parts = ctx.args.split(maxsplit=1)
	if len(parts) < 2:
		ctx.reply(mn.MSG_LINK_USAGE)
		return None
	role = chat_state.ROLE_WORDS.get(parts[0].strip().lower())
	if role is None:
		ctx.reply(mn.MSG_LINK_ROLE_UNKNOWN)
		return None
	company = parts[1].strip()
	if not frappe.db.exists("Company", company):
		ctx.reply(mn.MSG_LINK_COMPANY_NOT_FOUND.format(company=company))
		return None
	code = chat_state.issue_link_code(role, company, issued_by=ctx.user)
	ctx.reply(
		mn.MSG_LINK_CODE_ISSUED.format(
			code=code.code,
			role=mn.ROLE_LABELS.get(role, role),
			company=company,
			minutes=chat_state.LINK_CODE_MINUTES,
		)
	)
	return {"code": code.code, "role": role, "company": company}


def handle_status(ctx: Ctx) -> Any:
	if not ctx.is_admin:
		ctx.reply(mn.MSG_ADMIN_ONLY)
		return None
	settings = get_settings()
	missing = [key for keys in settings.report().values() for key in keys]
	config = (
		mn.MSG_STATUS_CONFIG_OK
		if not missing
		else mn.MSG_STATUS_CONFIG_MISSING.format(keys=", ".join(sorted(set(missing))))
	)
	unmatched = frappe.db.count("Bank Transaction", {"status": ["in", ["Pending", "Unreconciled"]]})
	ctx.reply(
		mn.MSG_STATUS.format(
			companies=frappe.db.count("Company"),
			users=frappe.db.count("Nyabo User Link", {"status": "active"}),
			proposals=frappe.db.count("Nyabo Proposal", {"status": "proposed"}),
			unmatched=unmatched,
			config=config,
		)
	)
	return {"missing": missing}


# --- rule verification and acceptance (/дүрэм, ARCHITECTURE §1.2, DECISIONS ACC-01) -----------


def _keeps_books(ctx: Ctx, company: str | None) -> bool:
	"""Is this reader the accountant of *that* company's books — not of whichever one is active?

	``ctx.is_accountant`` answers for the active company, and ``approve.can_approve`` deliberately
	does not: an accountant may tap [Батлах] on a proposal for any client they are linked to.
	Reading the role off the active company told the multi-client accountant, on their own
	client's receipt, that somebody else decides — and then sent that somebody-else notice to
	their own chat. The role lives on the ``Nyabo User Company`` row, so it is asked there.
	"""
	if not company or ctx.link is None:
		return False
	return chat_state.role_for(ctx.link, company) in ACCOUNTANT_ROLES


def _keeps_any_books(ctx: Ctx) -> bool:
	"""True when this reader is the accountant of at least one of the companies they are linked to."""
	return ctx.is_accountant or any(_keeps_books(ctx, company) for company in ctx.companies)


def _may_read_rules(ctx: Ctx) -> bool:
	"""Who may open the list and the evidence cards: an accountant of some books, or a site admin.

	Two people, two different answers on the same card, and each of them must be able to reach
	it. ``is_accountant`` is per company (TG-04) and a site admin is site-wide (VER-08), so
	neither check implies the other — asking only the first is how the founder, an Owner of his
	own company, lost ``/дүрэм`` and with it the only door to the global verification.
	"""
	return _keeps_any_books(ctx) or ctx.is_site_admin


def _accepting_company(ctx: Ctx, rule: str = "") -> str | None:
	"""The books an acceptance from *this* reader would be for — ``None`` when there are none.

	Normally the active company. But when this very chat was refused this very rule for another
	of their clients inside the retry window, that client is what the card asks about and what
	the acceptance is written for: it is the company whose document is waiting, and accepting for
	the active one instead would clear a rule nobody was blocked on (``verify.blocked_company``).

	A site admin who keeps nobody's books gets ``None``, so their evidence card is drawn for no
	company: it then asks the site-wide question (``CARD_RULE_ASK``) instead of «does this apply
	to {company}?», which is a question they have no button to answer.
	"""
	blocked = _deps.blocked_company(rule, ctx.telegram_id) if rule else None
	if blocked and blocked != ctx.company and _keeps_books(ctx, blocked):
		return blocked
	return ctx.company if _keeps_books(ctx, ctx.company) else None


def _refuse_tap(ctx: Ctx, kind: str, rule: str, message: str, reason: str) -> dict[str, Any]:
	"""Answer a tap this reader may not make, in the words of the thing they tapped."""
	# A layout is not in `/дүрэм`, so it does not get the sentence that points there (ACC-02).
	if kind == LAYOUT_KIND and message == mn.MSG_RULES_ACCOUNTANT_ONLY:
		message = mn.MSG_STATEMENT_LAYOUT_ACCOUNTANT_ONLY
	ctx.answer(message, show_alert=True)
	ctx.reply(message)
	log_event(
		"telegram.rules.tap_refused",
		level="warning",
		rule=rule,
		telegram_id=ctx.telegram_id,
		reason=reason,
	)
	return {"refused": reason, "rule": rule}


def handle_rules(ctx: Ctx) -> Any:
	"""``/дүрэм`` — the unverified rules that are blocking this company's postings, most-used first.

	The accountant's command, not the admin's. They are the person the refusal stops, and they
	are the person whose signature the entry carries, so they are the person who decides whether
	an uncited rule applies to the books they keep. A site admin sees the same list and may also
	verify the global row when a citation turns up.

	Both, therefore, and not one instead of the other: ``is_accountant`` is the link role on the
	*active* company, so gating on it alone shut out the site admin whose role on their own
	company is Owner — the one person VER-08 reserves the global verification for, and the only
	way into it is this command.
	"""
	if not _may_read_rules(ctx):
		ctx.reply(mn.MSG_RULES_ACCOUNTANT_ONLY)
		log_event("telegram.rules.refused", level="warning", telegram_id=ctx.telegram_id, role=ctx.role)
		return {"refused": "not_accountant"}
	rules = list(_deps.pending_rules(company=ctx.company))
	if not rules:
		ctx.reply(mn.MSG_RULES_NONE)
		return {"pending": 0}
	shown = rules[:RULES_PER_CARD]
	ctx.reply(cards.pending_rules_card(shown, total=len(rules)), keyboards.pending_rules_keyboard(shown))
	return {"pending": len(rules), "shown": [rule.name for rule in shown]}


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``v:op|ac|ok|no:<kind>:<rule…>`` — open one rule, accept it here, verify it, or leave it.

	The permission is re-checked on every tap and not only on the command: callback data is
	attacker-chosen (TG-03), so a datum copied out of somebody else's chat must clear nothing.
	And it is re-checked *per action*, because the two acts on this card belong to two different
	people: reading is open to both, [Манай компанид хамаарна] is the accountant's alone, and
	[Сайт даяар баталгаажуулах] is the site admin's alone (ACC-01, VER-08).
	"""
	if len(parts) < 4:
		return None
	action, kind = parts[1], parts[2]
	rule = keyboards.rule_from_parts(parts)
	if not _may_read_rules(ctx):
		return _refuse_tap(ctx, kind, rule, mn.MSG_RULES_ACCOUNTANT_ONLY, "not_accountant")
	if action == keyboards.VERIFY_OPEN:
		return show_rule(ctx, kind, rule)
	if action == keyboards.VERIFY_ACCEPT:
		if not _keeps_any_books(ctx):
			# A site admin reading the list is not the professional who keeps these books, and
			# acceptance is that professional's judgement — the global tick below is theirs.
			return _refuse_tap(ctx, kind, rule, mn.MSG_RULES_ACCOUNTANT_ONLY, "not_accountant")
		return accept_rule(ctx, kind, rule)
	if action == keyboards.VERIFY_CONFIRM:
		if not ctx.is_site_admin:
			# The row is global (VER-08): an admin of one company must not decide it for every
			# other client on the site, and the datum is attacker-chosen, so this is re-checked
			# on the tap and not only on the keyboard that was drawn. The accountant's own answer
			# — [Манай компанид хамаарна] — is on the same card and is not refused.
			return _refuse_tap(ctx, kind, rule, mn.MSG_RULES_SITE_ADMIN_ONLY, "not_site_admin")
		return confirm_rule(ctx, kind, rule)
	if action == keyboards.VERIFY_LEAVE:
		# «This rule will go on refusing postings» is not what an unconfirmed *layout* does — it
		# refuses statements, and the accountant is entitled to the sentence that says so.
		left = mn.MSG_STATEMENT_LAYOUT_LEFT if kind == LAYOUT_KIND else mn.MSG_RULE_LEFT
		ctx.answer(left)
		ctx.edit(ctx.callback_message_id, left, keyboards.empty_markup())
		return {"left": rule}
	log_event("telegram.callback.unknown", level="warning", data=ctx.callback_data[:64])
	return None


def show_rule(ctx: Ctx, kind: str, rule: str) -> Any:
	"""The evidence card: the Mongolian name, the debit and credit lines, and the citation or its absence."""
	evidence = _deps.rule_evidence(kind, rule, _accepting_company(ctx, rule))
	if evidence is None:
		ctx.answer(mn.MSG_RULE_NOT_FOUND.format(rule=rule), show_alert=True)
		return {"rule": rule, "found": False}
	if evidence.verified:
		ctx.answer(_already_verified(rule, evidence.verified_by, evidence.verified_at), show_alert=True)
		# The card too, with no buttons on it. The alert is gone the moment it is tapped away, and
		# this is the only path in the chat that reaches a *verified* rule — so it is the only
		# place an accountant can read the citation behind a rule that is already posting, and the
		# scope caveat under it (VER-09). Nothing is asked; the last line says who vouched.
		ctx.reply(cards.rule_card(evidence), keyboards.empty_markup())
		return {"rule": rule, "already": True, "verified_source": evidence.source}
	if evidence.accepted:
		# Already accepted for these books: nothing is asked, and the card names the colleague
		# who took the responsibility rather than inviting a second, contradicting tap.
		ctx.answer(_already_accepted(ctx, rule, evidence), show_alert=True)
		ctx.reply(cards.rule_card(evidence), keyboards.empty_markup())
		return {"rule": rule, "already": True, "verified_source": evidence.source}
	# A new message, not an edit: the list above it is what the accountant is working through, and
	# opening one rule must not take the other seven off the screen.
	offered = offer_decision(ctx, kind, evidence)
	return {"rule": rule, "has_citation": evidence.has_citation, "offered": offered}


def offer_decision(ctx: Ctx, kind: str, evidence: Any) -> bool:
	"""The evidence card and the answers this reader may give; False when they can give none here.

	A rule id long enough to push the callback datum past Telegram's 64 bytes costs the buttons
	(``keyboards.rule_decision`` drops them and logs), and a reader left looking at a card with no
	way to answer it would be exactly the dead end this whole flow exists to remove — so the card
	is followed by the one instruction that still works.

	Who gets which button: the accountant of an active company gets [Манай компанид хамаарна],
	which binds that company only; a site admin also gets [Сайт даяар баталгаажуулах], which binds
	every company on the site (VER-08). With no active company there is nothing to accept *for*,
	and the card says so rather than drawing a button that would refuse.

	A reader who is a site admin but not an accountant of these books gets the global tick and
	nothing else — neither the button nor the question, which is why the company reaches the
	card through ``_accepting_company`` rather than straight off ``ctx``. The card's own company
	is what decides: it is the client the acceptance would be written for, which for an
	accountant acting on a second client is not the active one.
	"""
	company = str(getattr(evidence, "company", "") or "")
	may_accept = _keeps_books(ctx, company)
	markup = keyboards.rule_decision(kind, evidence.name, may_verify=ctx.is_site_admin, may_accept=may_accept)
	ctx.reply(cards.rule_card(evidence), markup)
	if not markup.get("inline_keyboard"):
		ctx.reply(mn.MSG_RULE_VERIFY_IN_DESK.format(rule=evidence.name))
		return False
	if _keeps_any_books(ctx) and not may_accept:
		ctx.reply(mn.MSG_RULE_ACCEPT_NO_COMPANY)
	return may_accept or ctx.is_site_admin


def accept_rule(ctx: Ctx, kind: str, rule: str) -> Any:
	"""The accountant's tap: this rule applies to *this company's* books, and the record of it.

	The company is resolved here rather than carried in the datum: 64 bytes do not stretch to a
	company name beside a rule name (VER-03), and a company copied out of somebody else's chat
	must never decide anything for those books. Usually it is the tapper's active company —
	unless this very chat's refusal of this very rule, minutes ago, was another client of theirs
	(``_accepting_company``), because that is the client whose document is waiting.

	It never touches ``verified``. The global row is one row for the whole site, and one
	accountant's reading of an uncited rule must not bind another accountant's client — which is
	the whole reason acceptance is per company and not a widening of VER-08.
	"""
	company = _accepting_company(ctx, rule)
	if not company:
		ctx.answer(mn.MSG_RULE_ACCEPT_NO_COMPANY, show_alert=True)
		ctx.reply(mn.MSG_RULE_ACCEPT_NO_COMPANY)
		return {"accepted": False, "reason": "no_company", "rule": rule}
	result = _deps.accept_rule(kind, rule, company, ctx.user, telegram_id=ctx.telegram_id)
	if not result.get("ok"):
		# A rule that is not there and a write that would not go through are different problems,
		# and only one of them has a next step. Both leave the rule unaccepted, so say which.
		if result.get("reason") in ("not_found", "unknown_kind"):
			ctx.answer(mn.MSG_RULE_NOT_FOUND.format(rule=rule), show_alert=True)
		else:
			ctx.answer(mn.MSG_RULE_ACCEPT_FAILED.format(rule=rule), show_alert=True)
			ctx.reply(mn.MSG_RULE_ACCEPT_FAILED.format(rule=rule))
		return result
	if result.get("already"):
		ctx.answer(
			mn.MSG_RULE_ALREADY_ACCEPTED.format(
				rule=rule,
				company=company,
				user=result.get("accepted_by") or mn.VALUE_UNKNOWN,
				when=str(result.get("accepted_at") or "")[:16],
			),
			show_alert=True,
		)
		return result
	ctx.edit(
		ctx.callback_message_id,
		mn.MSG_STATEMENT_LAYOUT_ACCEPTED.format(layout=rule)
		if kind == LAYOUT_KIND
		else mn.MSG_RULE_ACCEPTED.format(
			rule=rule,
			company=company,
			user=_actor_name(ctx),
			when=str(result.get("accepted_at") or "")[:16],
		),
		keyboards.empty_markup(),
	)
	told = _tell_whoever_this_rule_stopped(ctx, rule, company=company)
	continued = _finish_the_blocked_tap(ctx, kind, rule, company)
	log_event(
		"telegram.rules.accepted",
		rule=rule,
		kind=kind,
		company=company,
		user=ctx.user,
		nyabo_event=result.get("event"),
		acceptance=result.get("acceptance"),
		continued=continued,
		requesters_told=told,
	)
	return {
		"accepted": True,
		"rule": rule,
		"company": company,
		"acceptance": result.get("acceptance"),
		"event": result.get("event"),
		"posted": continued,
		"requesters_told": told,
	}


def _finish_the_blocked_tap(ctx: Ctx, kind: str, rule: str, company: str) -> str | None:
	"""Continue the approval this same person asked for minutes ago, or tell them what is left.

	This is the point of the whole flow: the accountant tapped [Батлах] on a receipt, the guard
	refused because of this rule, and they have just removed that refusal. Asking them to press
	the identical button a second time is the waiting the founder's decision is about.

	It is deliberately narrow (VER-04's objection, honoured rather than dropped): only a proposal
	whose refused tap this very chat made, for this company and this rule, inside the retry
	window, and only when it is still ``proposed``. Anything else — a card in a shared chat, a
	colleague's document, a stale refusal — falls back to the sentence that names the one tap.

	A bank layout stops no card: the statement was refused before any proposal existed, and the
	file itself is what has to come back, so that is what the accountant is asked for (ACC-02).
	"""
	if kind == LAYOUT_KIND:
		document = _deps.blocked_document(rule, company, ctx.telegram_id)
		if not document:
			ctx.reply(mn.MSG_STATEMENT_LAYOUT_ACCEPTED_RESEND)
			return None
		from nyabo_mn.telegram.handlers import statement

		ctx.reply(mn.MSG_STATEMENT_LAYOUT_REIMPORTING)
		frappe.enqueue(
			statement.IMPORT_METHOD,
			queue="long",
			timeout=900,
			document_name=document,
			chat_id=ctx.chat_id,
			enqueue_after_commit=True,
		)
		# Nothing is posted by re-reading a statement — the lines become cards of their own — so
		# this returns nothing rather than putting a document name in a field called «posted».
		return None
	proposal = _deps.blocked_proposal(rule, company, ctx.telegram_id)
	if not proposal:
		ctx.reply(mn.MSG_RULE_ACCEPTED_RETRY)
		return None
	from nyabo_mn.telegram.handlers import approve

	ctx.reply(mn.MSG_RULE_ACCEPTED_POSTING)
	return approve.post_after_rule_cleared(ctx, proposal)


def confirm_rule(ctx: Ctx, kind: str, rule: str) -> Any:
	"""The site admin's tap: the flag, the name, the time and a Nyabo Event, for every company."""
	result = _deps.verify_rule(kind, rule, ctx.user, telegram_id=ctx.telegram_id)
	if not result.get("ok"):
		# A rule that is not there and a write that would not go through are different problems,
		# and only one of them has a next step. Both leave the row unverified, so say which.
		if result.get("reason") in ("not_found", "unknown_kind"):
			ctx.answer(mn.MSG_RULE_NOT_FOUND.format(rule=rule), show_alert=True)
		else:
			ctx.answer(mn.MSG_RULE_VERIFY_FAILED.format(rule=rule), show_alert=True)
			ctx.reply(mn.MSG_RULE_VERIFY_FAILED.format(rule=rule))
		return result
	if result.get("already"):
		ctx.answer(
			_already_verified(rule, result.get("verified_by"), result.get("verified_at")), show_alert=True
		)
		return result
	ctx.edit(
		ctx.callback_message_id,
		mn.MSG_RULE_VERIFIED.format(
			rule=rule, user=_actor_name(ctx), when=str(result.get("verified_at") or "")[:16]
		),
		keyboards.empty_markup(),
	)
	# Nothing was re-sent and nothing was lost: the proposal that was refused is still `proposed`
	# and still wearing its own [Батлах] (telegram.handlers.approve), so this is the whole retry.
	ctx.reply(mn.MSG_RULE_VERIFIED_RETRY)
	told = _tell_whoever_this_rule_stopped(ctx, rule)
	# ``event`` is log_event's own first parameter; the Nyabo Event name rides under its own key.
	log_event(
		"telegram.rules.verified",
		rule=rule,
		kind=kind,
		user=ctx.user,
		nyabo_event=result.get("event"),
		requesters_told=told,
	)
	return {"verified": True, "rule": rule, "event": result.get("event"), "requesters_told": told}


def _tell_whoever_this_rule_stopped(ctx: Ctx, rule: str, company: str | None = None) -> int:
	"""Close the loop the refusal opened: whoever was blocked hears that it is cleared.

	The refusal tells them «press [Батлах] again once the rule is cleared» — and nothing ever
	told them that moment had come. Their proposal is still `proposed` and still wearing its own
	button, so the news is the whole difference between one tap and a receipt nobody comes back
	to. The person who just tapped is skipped: they have the reply above, and in the acceptance
	case Nyabo has already finished their document for them.

	``company`` is passed for an acceptance, which clears the rule for one company only: telling
	another company's accountant that the rule is cleared would be a promise their next tap breaks.
	"""
	from nyabo_mn.telegram.router import notify_chats

	chats = [
		chat for chat in _deps.rule_requesters(rule, company=company) if str(chat) != str(ctx.telegram_id)
	]
	message = (
		mn.MSG_RULE_ACCEPTED_FOR_REQUESTER.format(rule=rule, company=company)
		if company
		else mn.MSG_RULE_VERIFIED_FOR_REQUESTER.format(rule=rule)
	)
	return notify_chats(ctx.bot, chats, message)


def _already_verified(rule: str, verified_by: Any, verified_at: Any) -> str:
	"""«Already verified» plus *by whom* — a seed citation and a person's tap are not the same."""
	return mn.MSG_RULE_ALREADY_VERIFIED.format(
		rule=rule, source=cards.rule_verified_source(verified_by, verified_at)
	)


def _already_accepted(ctx: Ctx, rule: str, evidence: Any) -> str:
	"""«Already accepted, for this company, by this colleague» — never «verified»: it is not."""
	return mn.MSG_RULE_ALREADY_ACCEPTED.format(
		rule=rule,
		company=evidence.company or ctx.company or mn.VALUE_UNKNOWN,
		user=evidence.accepted_by or mn.VALUE_UNKNOWN,
		when=str(evidence.accepted_at or "")[:16],
	)


def rule_blocked(
	ctx: Ctx, rule: str, company: str | None = None, proposal: str | None = None
) -> dict[str, Any]:
	"""Turn the refusal somebody just hit into the next step, whoever is reading it.

	The accountant of the company the document belongs to is asked, right here, whether the rule
	applies to their books: the evidence card, the briefing the seed wrote for exactly this
	screen, and [Манай компанид хамаарна]. That is the founder's decision made real — the person
	whose signature the entry carries decides, and nothing waits on anybody else. «The company
	the document belongs to» is the point: the role is resolved against *that* company, the way
	``approve.can_approve`` resolves the right to tap [Батлах], and not against whichever
	company happens to be active in this chat.

	A site admin is additionally offered the global verification. Anyone else — an owner tapping
	[Батлах] under an auto-approve policy — is told which person decides, and that sentence is
	made true here rather than hoped for: a Nyabo Event records the request and the company's
	accountants are notified. If there is nobody at all, they are told that plainly, with the
	step that still works; the request is on record either way.
	"""
	company = company or ctx.company
	# Written for every reader and before anything else: it is the trail an acceptance reads to
	# finish this person's own tap, and the honest answer to «which rules are holding up work».
	_deps.record_rule_block(
		rule, company=company, proposal=proposal, telegram_id=ctx.telegram_id, user=ctx.user
	)
	if _keeps_books(ctx, company):
		found = _rule_evidence_by_name(rule, company)
		if found is not None:
			kind, evidence = found
			ctx.reply(mn.MSG_UNVERIFIED_RULE_ACCOUNTANT_CAN_ACCEPT.format(company=company))
			if ctx.is_site_admin:
				ctx.reply(mn.MSG_UNVERIFIED_RULE_ADMIN_CAN_VERIFY)
			return {"rule": rule, "offered": offer_decision(ctx, kind, evidence), "notified": False}
	if ctx.is_site_admin:
		# Not an accountant of these books, but they may still clear the row for the whole site.
		found = _rule_evidence_by_name(rule, company)
		if found is not None:
			kind, evidence = found
			ctx.reply(mn.MSG_UNVERIFIED_RULE_ADMIN_CAN_VERIFY)
			return {"rule": rule, "offered": offer_decision(ctx, kind, evidence), "notified": False}
	# An owner, or a rule name that is not a row at all (the guard counts an unknown name as
	# unverified, and that is a configuration fault somebody has to see).
	recent = _deps.recent_rule_request(rule, company)
	if recent is not None:
		# The same rule, the same company, minutes ago: tapping [Батлах] again is what a person
		# does when nothing seems to happen, and it must not add a row to an append-only log or
		# ring everybody a second time. The answer is the one the first tap earned.
		reached = int(recent.get("admins_notified") or 0)
		ctx.reply(_request_reply(rule, reached))
		# ``event`` is log_event's own first parameter; the Nyabo Event name rides under its own key.
		log_event(
			"telegram.rules.request_deduped",
			rule=rule,
			company=company,
			nyabo_event=recent.get("event"),
		)
		return {
			"rule": rule,
			"offered": False,
			"notified": bool(reached),
			"admins_notified": reached,
			"deduped": True,
		}
	reached = _tell_who_can_clear_it(ctx, rule, company)
	# Recorded after the notice so the row carries what really happened, which is what a repeat
	# within REQUEST_DEDUPE_MINUTES is answered from.
	_deps.request_rule_verification(
		rule,
		company=company,
		user=ctx.user,
		telegram_id=ctx.telegram_id,
		admins_notified=reached,
		proposal=proposal,
	)
	ctx.reply(_request_reply(rule, reached))
	log_event(
		"telegram.rules.requested",
		level="info" if reached else "warning",
		rule=rule,
		company=company,
		user=ctx.user,
		admins_notified=reached,
	)
	return {
		"rule": rule,
		"offered": False,
		"notified": bool(reached),
		"admins_notified": reached,
		"deduped": False,
	}


def _tell_who_can_clear_it(ctx: Ctx, rule: str, company: str | None) -> int:
	"""Notify the people who can actually clear this rule; returns how many heard.

	Two groups, and they are told different things because they can do different things
	(DECISIONS ACC-01): this company's accountants, who may accept the rule for these books,
	and the site admins, who may verify the global row when a citation is found. An owner is
	never sent to a button that would refuse them, and neither is anybody else.

	The person who was just stopped is dropped from both lists. They are reading the answer to
	their own tap on the screen in front of them, and «your request has been passed to your
	accountant», delivered to their own chat, is somebody-else-will-do-it addressed to nobody.
	It is reachable whenever the reader is themselves one of the people who could clear it —
	a rule name that is no row at all takes an accountant down this path.
	"""
	from nyabo_mn.telegram.router import company_accountant_ids, notify_chats, site_admin_ids

	label = company or mn.VALUE_UNKNOWN
	self_id = {int(ctx.telegram_id)} if str(ctx.telegram_id).lstrip("-").isdigit() else set()
	site_ids = site_admin_ids(ctx.settings) - self_id
	accountant_ids = (company_accountant_ids(company) - site_ids - self_id) if company else set()
	reached = notify_chats(
		ctx.bot,
		sorted(accountant_ids),
		mn.MSG_ACCOUNTANT_RULE_ACCEPT_REQUEST.format(company=label, rule=rule),
	)
	reached += notify_chats(
		ctx.bot, sorted(site_ids), mn.MSG_ADMIN_RULE_VERIFY_REQUEST.format(company=label, rule=rule)
	)
	return reached


def _request_reply(rule: str, notified: int) -> str:
	"""What the blocked owner is told: only ever what actually happened (MAJOR 6)."""
	if notified:
		return mn.MSG_UNVERIFIED_RULE_ACCOUNTANT_ASKED
	return mn.MSG_UNVERIFIED_RULE_NO_ACCOUNTANT.format(rule=rule)


def _rule_evidence_by_name(rule: str, company: str | None = None) -> tuple[str, Any] | None:
	"""``UnverifiedRuleError`` carries a bare name; the kinds are tried in ``rules.verify`` order."""
	for kind in _deps.rule_kinds():
		evidence = _deps.rule_evidence(kind, rule, company)
		if evidence is not None and not evidence.verified and not evidence.accepted:
			return kind, evidence
	return None


def _actor_name(ctx: Ctx) -> str:
	"""The name the person was linked under, so the confirmation names a person, not an email."""
	from nyabo_mn.telegram.handlers import approve

	return approve.approver_name(ctx)
