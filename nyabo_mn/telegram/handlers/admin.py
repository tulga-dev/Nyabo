"""Admin commands: ``/link`` issues a code, ``/status`` shows site health, ``/дүрэм`` verifies a rule.

Admins are the link role ``Admin`` or the ids in ``ADMIN_TELEGRAM_IDS``; the second lets
the founder issue the very first accountant code before any link row exists.

``/дүрэм`` (``/rules`` in the ☰ menu) is the door ``MSG_UNVERIFIED_RULE_BLOCKED`` points at.
Until it existed the refusal said an admin would compare the rule with the primary text and
mark it verified, while an admin could do exactly two things from Telegram — ``/link`` and
``/status`` — so the only real path was the ERPNext desk. The list, the evidence card and the
single confirming tap live here; the write and the audit event live in ``rules.verify``.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.config import get_settings
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.telegram import _deps, cards, keyboards
from nyabo_mn.telegram import state as chat_state
from nyabo_mn.telegram.context import Ctx

# One screen of rules: the card stays readable and every row still gets its own button. The
# count in the header is the real total, so a cut list never understates what is blocking work.
RULES_PER_CARD = 8


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


# --- rule verification (/дүрэм, ARCHITECTURE §1.2) ---------------------------------------------


def handle_rules(ctx: Ctx) -> Any:
	"""``/дүрэм`` — the unverified rules that are blocking postings, most-used first.

	An accountant is told who may verify instead of being refused: from their side the command
	is the only visible name for the thing that stopped their receipt.
	"""
	if not ctx.is_admin:
		ctx.reply(mn.MSG_RULES_ADMIN_ONLY)
		log_event("telegram.rules.refused", level="warning", telegram_id=ctx.telegram_id, role=ctx.role)
		return {"refused": "not_admin"}
	rules = list(_deps.pending_rules())
	if not rules:
		ctx.reply(mn.MSG_RULES_NONE)
		return {"pending": 0}
	shown = rules[:RULES_PER_CARD]
	ctx.reply(cards.pending_rules_card(shown, total=len(rules)), keyboards.pending_rules_keyboard(shown))
	return {"pending": len(rules), "shown": [rule.name for rule in shown]}


def handle_callback(ctx: Ctx, parts: list[str]) -> Any:
	"""``v:op|ok|no:<kind>:<rule…>`` — open one rule, verify it, or leave it unverified.

	The admin check is repeated on every tap and not only on the command: callback data is
	attacker-chosen (TG-03), so a datum copied out of an admin's chat must not verify anything.
	"""
	if len(parts) < 4:
		return None
	action, kind = parts[1], parts[2]
	rule = keyboards.rule_from_parts(parts)
	if not ctx.is_admin:
		ctx.answer(mn.MSG_RULES_ADMIN_ONLY, show_alert=True)
		ctx.reply(mn.MSG_RULES_ADMIN_ONLY)
		log_event("telegram.rules.tap_refused", level="warning", rule=rule, telegram_id=ctx.telegram_id)
		return {"refused": "not_admin", "rule": rule}
	if action == keyboards.VERIFY_OPEN:
		return show_rule(ctx, kind, rule)
	if action == keyboards.VERIFY_CONFIRM:
		if not ctx.is_site_admin:
			# The row is global (VER-08): an admin of one company must not decide it for every
			# other client on the site, and the datum is attacker-chosen, so this is re-checked
			# on the tap and not only on the keyboard that was drawn.
			ctx.answer(mn.MSG_RULES_SITE_ADMIN_ONLY, show_alert=True)
			ctx.reply(mn.MSG_RULES_SITE_ADMIN_ONLY)
			log_event(
				"telegram.rules.tap_refused",
				level="warning",
				rule=rule,
				telegram_id=ctx.telegram_id,
				reason="not_site_admin",
			)
			return {"refused": "not_site_admin", "rule": rule}
		return confirm_rule(ctx, kind, rule)
	if action == keyboards.VERIFY_LEAVE:
		ctx.answer(mn.MSG_RULE_LEFT)
		ctx.edit(ctx.callback_message_id, mn.MSG_RULE_LEFT, keyboards.empty_markup())
		return {"left": rule}
	log_event("telegram.callback.unknown", level="warning", data=ctx.callback_data[:64])
	return None


def show_rule(ctx: Ctx, kind: str, rule: str) -> Any:
	"""The evidence card: the Mongolian name, the debit and credit lines, and the citation or its absence."""
	evidence = _deps.rule_evidence(kind, rule)
	if evidence is None:
		ctx.answer(mn.MSG_RULE_NOT_FOUND.format(rule=rule), show_alert=True)
		return {"rule": rule, "found": False}
	if evidence.verified:
		ctx.answer(_already_verified(rule, evidence.verified_by, evidence.verified_at), show_alert=True)
		return {"rule": rule, "already": True, "verified_source": evidence.verified_source}
	# A new message, not an edit: the list above it is what the admin is working through, and
	# opening one rule must not take the other seven off the screen.
	offered = offer_decision(ctx, kind, evidence, may_verify=ctx.is_site_admin)
	return {"rule": rule, "has_citation": evidence.has_citation, "offered": offered}


def offer_decision(ctx: Ctx, kind: str, evidence: Any, may_verify: bool = True) -> bool:
	"""The evidence card and the buttons; False when this reader cannot answer it here.

	A rule id long enough to push the callback datum past Telegram's 64 bytes costs the buttons
	(``keyboards.rule_decision`` drops them and logs), and an admin left looking at a card with no
	way to answer it would be exactly the dead end this whole flow exists to remove — so the card
	is followed by the one instruction that still works.

	``may_verify=False`` is the other reason a card can carry no [Баталгаажуулах]: the reader is
	an admin of one company and the row belongs to the whole site (VER-08). They get the evidence,
	because it is their work that is blocked, and the sentence naming who may clear it.
	"""
	markup = keyboards.rule_decision(kind, evidence.name, may_verify=may_verify)
	ctx.reply(cards.rule_card(evidence), markup)
	if not may_verify:
		ctx.reply(mn.MSG_RULES_SITE_ADMIN_ONLY)
		return False
	if not markup.get("inline_keyboard"):
		ctx.reply(mn.MSG_RULE_VERIFY_IN_DESK.format(rule=evidence.name))
		return False
	return True


def confirm_rule(ctx: Ctx, kind: str, rule: str) -> Any:
	"""The tap that is the compliance act: the flag, the name, the time and a Nyabo Event."""
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
	# ``event`` is log_event's own first parameter; the Nyabo Event name rides under its own key.
	log_event("telegram.rules.verified", rule=rule, kind=kind, user=ctx.user, nyabo_event=result.get("event"))
	return {"verified": True, "rule": rule, "event": result.get("event")}


def _already_verified(rule: str, verified_by: Any, verified_at: Any) -> str:
	"""«Already verified» plus *by whom* — a seed citation and a person's tap are not the same."""
	return mn.MSG_RULE_ALREADY_VERIFIED.format(
		rule=rule, source=cards.rule_verified_source(verified_by, verified_at)
	)


def rule_blocked(ctx: Ctx, rule: str, company: str | None = None) -> dict[str, Any]:
	"""Turn the refusal an accountant just hit into the next step, whoever is reading it.

	An admin gets the rule's evidence and the two buttons in the same breath as the refusal. Anyone
	else is told an admin must do it — and that sentence is made true here rather than hoped for:
	a Nyabo Event records the request and ``router.notify_admins`` puts it in the admins' chats.

	«The admins have been told» is only said when somebody was actually told, which is why the
	notice goes out *before* the reply and its count decides the wording. The recipients are the
	site's ``ADMIN_TELEGRAM_IDS`` **and** the Admins linked to this company, who are admins of
	these books and are in no site config file — and the two groups are told different things,
	because only one of them can clear the row from the chat (``_tell_the_admins``). If there is
	no one at all, the accountant is told that plainly, with the step that still works — the
	request is on record either way.
	"""
	company = company or ctx.company
	# Only a site admin is offered the tap here: the row applies to every company on the site
	# (VER-08). A company admin takes the same path as the accountant — the request is recorded
	# and the site admins are told — and reads the evidence through /дүрэм.
	if ctx.is_site_admin:
		found = _rule_evidence_by_name(rule)
		if found is not None:
			kind, evidence = found
			ctx.reply(mn.MSG_UNVERIFIED_RULE_ADMIN_CAN_VERIFY)
			return {
				"rule": rule,
				"offered": offer_decision(ctx, kind, evidence),
				"notified": False,
			}
	# Not an admin, or a rule name that is not a row at all (the guard counts an unknown name as
	# unverified, and that is a configuration fault an admin has to see).
	recent = _deps.recent_rule_request(rule, company)
	if recent is not None:
		# The same rule, the same company, minutes ago: tapping [Батлах] again is what a person
		# does when nothing seems to happen, and it must not add a row to an append-only log or
		# ring every admin a second time. The answer is the one the first tap earned.
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
	reached = _tell_the_admins(ctx, rule, company)
	# Recorded after the notice so the row carries what really happened, which is what a repeat
	# within REQUEST_DEDUPE_MINUTES is answered from.
	_deps.request_rule_verification(
		rule, company=company, user=ctx.user, telegram_id=ctx.telegram_id, admins_notified=reached
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


def _tell_the_admins(ctx: Ctx, rule: str, company: str | None) -> int:
	"""Notify both kinds of admin, each with something they can actually do; returns how many heard.

	A rule row is global, so only a site admin can clear it from the chat (VER-08). Sending every
	admin «/дүрэм командаар баталгаажуулна уу» told the admin of one company to press a button
	that would then refuse them — the same empty promise as telling the accountant the admins were
	notified when nobody was, one seat further along. A company admin is still told, because the
	rule is blocking their books and the ERPNext desk is open to them; they are told that.
	"""
	from nyabo_mn.telegram.router import company_admin_ids, notify_chats, site_admin_ids

	label = company or mn.VALUE_UNKNOWN
	site_ids = site_admin_ids(ctx.settings)
	# A site admin who is also linked to this company hears once, in the wording that lets them act.
	company_ids = (company_admin_ids(company) - site_ids) if company else set()
	reached = notify_chats(
		ctx.bot, sorted(site_ids), mn.MSG_ADMIN_RULE_VERIFY_REQUEST.format(company=label, rule=rule)
	)
	reached += notify_chats(
		ctx.bot,
		sorted(company_ids),
		mn.MSG_ADMIN_RULE_VERIFY_REQUEST_COMPANY.format(company=label, rule=rule),
	)
	return reached


def _request_reply(rule: str, admins_notified: int) -> str:
	"""What the blocked accountant is told: only ever what actually happened (MAJOR 6)."""
	if admins_notified:
		return mn.MSG_UNVERIFIED_RULE_ADMIN_ASKED
	return mn.MSG_UNVERIFIED_RULE_NO_ADMIN.format(rule=rule)


def _rule_evidence_by_name(rule: str) -> tuple[str, Any] | None:
	"""``UnverifiedRuleError`` carries a bare name; the kinds are tried in ``rules.verify`` order."""
	for kind in _deps.rule_kinds():
		evidence = _deps.rule_evidence(kind, rule)
		if evidence is not None and not evidence.verified:
			return kind, evidence
	return None


def _actor_name(ctx: Ctx) -> str:
	"""The name the admin was linked under, so the confirmation names a person, not an email."""
	from nyabo_mn.telegram.handlers import approve

	return approve.approver_name(ctx)
