"""Card renderers: dicts in, plain text out (docs/ARCHITECTURE.md §5.1, §5.3, §5.5).

Pure functions so a snapshot test can pin the exact anatomy of a card without Frappe.
Every visible string comes from ``nyabo_mn.i18n.mn``; money goes through
``core.money.fmt_mnt`` and weekdays through ``core.dates`` so a card and a report never
format the same amount two ways. The model's only contribution is the one-line
explanation, printed inside «…» (principle 7).
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from nyabo_mn.core import dates
from nyabo_mn.core.money import fmt_mnt, quantize, to_decimal
from nyabo_mn.i18n import mn

# A Telegram bubble on a 360dp phone fits roughly 40 Cyrillic characters before it wraps;
# 60 is the width at which a wrapped line is still one visual unit rather than a paragraph.
CARD_MAX_LINE_CHARS = 60
SELLER_MAX_CHARS = 30

# Treatments that book no VAT amount and yet are not "no VAT": the supply is inside the
# VAT law, zero-rated (art. 13) or exempt (art. 14). Kept here, not in the card body, so
# the two lists in ``mn.VAT_TREATMENT_LABELS`` and here are read side by side.
VAT_ZERO_AMOUNT_TREATMENTS = ("exempt", "zero")

# --- helpers ---------------------------------------------------------------------------------------


def _json(value: Any) -> Any:
	"""JSON columns arrive as text from the DB and as dicts from a fresh document."""
	if value in (None, ""):
		return None
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return None


def _money(value: Any) -> Decimal:
	if value in (None, ""):
		return Decimal("0.00")
	try:
		return quantize(to_decimal(value))
	except (InvalidOperation, ValueError, TypeError):
		return Decimal("0.00")


def _date(value: Any) -> dt.date | None:
	if isinstance(value, dt.datetime):
		return value.date()
	if isinstance(value, dt.date):
		return value
	if isinstance(value, str) and value:
		try:
			return dt.date.fromisoformat(value[:10])
		except ValueError:
			return None
	return None


def fmt_date(value: Any) -> str:
	"""A transaction date as the user reads it: ``"03.08 (Да)"``.

	Cards show dd.mm plus the weekday (``core.dates.short_date_mn``); ISO belongs to the
	JSON columns, the report filters and the PDF filenames, which are read by machines.
	"""
	day = _date(value)
	return dates.short_date_weekday_mn(day) if day else mn.VALUE_UNKNOWN


def _clip(text: str, limit: int) -> str:
	"""Keep one card line inside a phone's width; a 60-character ХХК name must not wrap."""
	text = str(text)
	return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _vat_rate_percent(total: Decimal, vat: Decimal, explicit: Any) -> str:
	"""Display-only rate: the explicit one from the proposal, else derived from the amounts.

	Rules code never derives a rate from amounts (principle 1); the card only prints what the
	receipt implies so the accountant can eyeball it.
	"""
	if explicit not in (None, ""):
		rate = to_decimal(explicit)
		percent = rate * 100 if rate <= 1 else rate
		return str(int(percent)) if percent == int(percent) else str(percent)
	net = total - vat
	if vat > 0 and net > 0:
		percent = (vat / net * 100).quantize(Decimal("1"))
		return str(int(percent))
	return "0"


# --- receipt card ----------------------------------------------------------------------------------


def verification_text(verification: dict[str, Any] | None) -> str:
	"""ARCHITECTURE §7: never "ebarimt ✓" — three separate facts, none of them a tax-authority check.

	1. the seller: found in the public registry by ТТД/РД, or not;
	2. the receipt itself: no buyer-side verification endpoint exists, so it stays
	«Баримт шалгагдаагүй» unless a provider ever answers ``status = "verified"``;
	3. the QR: whether ``ebarimt.qr.decode`` read a ``qrData`` off the photo. Reading a QR
	proves only that a QR was on the paper — it is reported next to, never instead of,
	the unchecked-receipt wording (UX-09).

	``verification_json`` is written nested by ``agent.pipeline`` (``{"seller": …,
	"receipt": …, "qr_data": …}``); the flat shape is what older rows and the simulator
	carry, so both are read here.
	"""
	verification = verification or {}
	seller_row = verification.get("seller")
	seller_row = seller_row if isinstance(seller_row, dict) else verification
	receipt_row = verification.get("receipt")
	receipt_row = receipt_row if isinstance(receipt_row, dict) else verification
	seller_found = bool(
		seller_row.get("seller_found") or seller_row.get("vat_payer") or seller_row.get("found")
	)
	parts = [mn.VERIFICATION_SELLER_OK if seller_found else mn.VERIFICATION_SELLER_NOT_FOUND]
	if receipt_row.get("status") != "verified":
		parts.append(mn.VERIFICATION_RECEIPT_UNCHECKED)
	if "qr_data" in verification:
		parts.append(mn.VERIFICATION_QR_FOUND if verification.get("qr_data") else mn.VERIFICATION_QR_MISSING)
	return " · ".join(parts)


def account_reason(proposal: dict[str, Any]) -> str:
	if proposal.get("rule_applied"):
		return mn.CARD_REASON_RULE.format(rule=proposal["rule_applied"])
	source = (_json(proposal.get("confidence_json")) or {}).get("source") or proposal.get("source")
	if source == "history":
		return mn.CARD_REASON_HISTORY
	return mn.CARD_REASON_MODEL


def receipt_card(proposal: dict[str, Any], warnings: list[str] | None = None) -> str:
	"""The proposal card, §5.1 anatomy:

	🧾 seller · dd.mm (weekday)
	💵 total₮ · НӨАТ vat₮ (rate%, treatment)
	🔎 verification
	📒 code account · reason
	«explanation»
	⚠️ warning (one line each)
	📜 pattern citation

	Money and verification are two lines, not one: together they ran to 88 characters and
	wrapped into an unreadable block on a phone (UX-10).
	"""
	extracted = _json(proposal.get("extracted_json")) or {}
	seller = (
		proposal.get("supplier_name")
		or proposal.get("supplier")
		or extracted.get("seller_name")
		or mn.VALUE_UNKNOWN
	)
	day = _date(proposal.get("posting_date"))
	title = mn.CARD_RECEIPT_TITLE.format(
		seller=_clip(seller, SELLER_MAX_CHARS),
		date=dates.short_date_mn(day) if day else mn.VALUE_UNKNOWN,
		weekday=dates.weekday_short_mn(day) if day else mn.VALUE_UNKNOWN,
	)
	total = _money(proposal.get("total"))
	vat = _money(proposal.get("vat_amount"))
	treatment = proposal.get("vat_treatment") or "none"
	if vat > 0 and treatment != "none":
		money_line = mn.CARD_MONEY_LINE.format(
			total=fmt_mnt(total),
			vat=fmt_mnt(vat),
			rate=_vat_rate_percent(total, vat, extracted.get("vat_rate") or proposal.get("vat_rate")),
			treatment=mn.VAT_TREATMENT_LABELS.get(treatment, treatment),
		)
	elif treatment in VAT_ZERO_AMOUNT_TREATMENTS:
		# Exempt and zero-rated receipts carry no VAT amount but are not "НӨАТ-гүй": the
		# supply is inside the VAT law and the accountant needs to see which one it is
		# (VAT law art. 13 zero-rated / art. 14 exempt). UX-06.
		money_line = mn.CARD_MONEY_LINE_TREATMENT.format(
			total=fmt_mnt(total), treatment=mn.VAT_TREATMENT_LABELS[treatment]
		)
	else:
		money_line = mn.CARD_MONEY_LINE_NO_VAT.format(total=fmt_mnt(total))
	verification_line = mn.CARD_VERIFICATION_LINE.format(
		verification=verification_text(_json(proposal.get("verification_json")))
	)
	account_line = mn.CARD_ACCOUNT_LINE.format(
		code=proposal.get("account_code") or mn.VALUE_UNKNOWN,
		account=proposal.get("account_name") or _strip_account(proposal.get("account")) or mn.VALUE_UNKNOWN,
		reason=account_reason(proposal),
	)
	lines = [title, money_line, verification_line, account_line]
	explanation = (proposal.get("explanation") or "").strip()
	if explanation:
		lines.append(mn.CARD_EXPLANATION_LINE.format(explanation=explanation))
	all_warnings = list(warnings if warnings is not None else (_json(proposal.get("warnings_json")) or []))
	if proposal.get("supplier_is_new") and mn.WARN_NEW_SUPPLIER not in all_warnings:
		all_warnings.append(mn.WARN_NEW_SUPPLIER)
	for warning in dict.fromkeys(w for w in all_warnings if w):
		lines.append(mn.CARD_WARNING_LINE.format(warning=warning))
	citation = proposal.get("citation") or proposal.get("posting_pattern")
	if citation:
		lines.append(mn.CARD_PATTERN_LINE.format(pattern=citation))
	return "\n".join(lines)


def _strip_account(account: Any) -> str:
	"""``"6210 - Шатахуун - TST"`` -> ``"Шатахуун"`` (ERPNext account names carry code and abbr)."""
	if not account:
		return ""
	parts = str(account).split(" - ")
	if len(parts) >= 3:
		return " - ".join(parts[1:-1])
	if len(parts) == 2:
		return parts[1] if parts[0].replace(".", "").isdigit() else parts[0]
	return str(account)


def posted_card(proposal: dict[str, Any], doc_name: str, approver: str) -> str:
	return (
		receipt_card(proposal) + "\n" + mn.MSG_POSTED_CARD_FOOTER.format(doc_name=doc_name, approver=approver)
	)


def rejected_card(proposal: dict[str, Any], reason: str) -> str:
	return receipt_card(proposal) + "\n" + mn.MSG_REJECTED_CARD_FOOTER.format(reason=reason)


# --- bank line card --------------------------------------------------------------------------------


def bank_line_card(txn: dict[str, Any], proposal: dict[str, Any] | None = None) -> str:
	"""§5.4 unmatched line: bank · date · signed amount · «description», plus the auto-proposal."""
	deposit = _money(txn.get("deposit"))
	withdrawal = _money(txn.get("withdrawal"))
	amount = deposit - withdrawal if (deposit or withdrawal) else _money(txn.get("amount"))
	lines = [
		mn.CARD_BANK_LINE.format(
			bank=txn.get("bank") or txn.get("bank_account") or mn.VALUE_UNKNOWN,
			date=fmt_date(txn.get("date")),
			amount=fmt_mnt(amount),
			description=(txn.get("description") or "")[:120],
		)
	]
	if txn.get("matched_voucher"):
		lines.append(mn.CARD_BANK_MATCHED.format(voucher=txn["matched_voucher"]))
	if proposal:
		lines.append(
			mn.CARD_BANK_PROPOSAL.format(
				code=proposal.get("account_code") or mn.VALUE_UNKNOWN,
				account=proposal.get("account_name")
				or _strip_account(proposal.get("account"))
				or mn.VALUE_UNKNOWN,
				reason=account_reason(proposal),
			)
		)
	return "\n".join(lines)


def bank_candidates_text(candidates: list[dict[str, Any]]) -> str:
	if not candidates:
		return mn.MSG_BANK_FIND_NONE
	lines = [mn.MSG_BANK_FIND_CANDIDATES]
	for index, cand in enumerate(candidates, start=1):
		lines.append(
			mn.CARD_BANK_CANDIDATE.format(
				index=index,
				voucher=cand.get("voucher_name") or cand.get("name") or mn.VALUE_UNKNOWN,
				date=fmt_date(cand.get("date") or cand.get("posting_date")),
				amount=fmt_mnt(_money(cand.get("amount"))),
				party=cand.get("party") or mn.VALUE_UNKNOWN,
			)
		)
	return "\n".join(lines)


# --- month-end card --------------------------------------------------------------------------------


def close_card(company: str, period: str, checklist: dict[str, Any], summaries: dict[str, Any]) -> str:
	"""§5.5: header, open items, December inventory line, trial balance, then the regime summary."""
	lines = [
		mn.MSG_CLOSE_HEADER.format(company=company, period=dates.period_label(period)),
		mn.MSG_CLOSE_OPEN_ITEMS.format(
			proposals=checklist.get("open_proposals", checklist.get("proposals", 0)),
			unmatched=checklist.get("unmatched_bank_lines", checklist.get("unmatched", 0)),
			unverified_docs=checklist.get("unverified_documents", checklist.get("unverified_docs", 0)),
			pending_suppliers=checklist.get("pending_suppliers", 0),
			unverified_rules=checklist.get("unverified_rules_used", checklist.get("unverified_rules", 0)),
		),
	]
	_year, month = dates.parse_period(period)
	if month == 12 or checklist.get("inventory_count_required"):
		lines.append(mn.MSG_CLOSE_INVENTORY_COUNT)
	trial = summaries.get("trial_balance") or {}
	if trial:
		lines.append(
			mn.MSG_CLOSE_TRIAL_BALANCE.format(
				debit=fmt_mnt(_money(trial.get("debit"))), credit=fmt_mnt(_money(trial.get("credit")))
			)
		)
	vat = summaries.get("vat")
	if vat:
		lines.append(
			mn.MSG_CLOSE_VAT_SUMMARY.format(
				output=fmt_mnt(_money(vat.get("output"))),
				input=fmt_mnt(_money(vat.get("input"))),
				net=fmt_mnt(_money(vat.get("net"))),
			)
		)
	simplified = summaries.get("simplified")
	if simplified:
		lines.append(
			mn.MSG_CLOSE_SIMPLIFIED_SUMMARY.format(
				revenue=fmt_mnt(_money(simplified.get("revenue"))),
				tax=fmt_mnt(_money(simplified.get("tax"))),
				quarter=simplified.get("quarter") or "",
			)
		)
	return "\n".join(lines)


# --- onboarding cards ------------------------------------------------------------------------------


def onboarding_summary(payload: dict[str, Any], company: str) -> str:
	regime = mn.ONB_SUMMARY_REGIME_VAT if payload.get("vat_registered") else mn.ONB_SUMMARY_REGIME_SIMPLIFIED
	banks = payload.get("banks") or []
	bank_text = (
		", ".join(f"{b['bank']} ({'/'.join(b.get('currencies') or ['MNT'])})" for b in banks)
		if banks
		else mn.ONB_SUMMARY_BANKS_NONE
	)
	if payload.get("posted_intake"):
		# Asked first, because the ledger outranks every answer given after it. Буцах from the
		# accountant's name lands on the stock question again, and Тийм → «алгасах» there skips
		# the *next* list — but the skipped note reads «not entered, register it later», which
		# for a company whose opening entry is already posted invites filing it a second time.
		# ``posted_count`` is the count as filed, kept because a later draft that is read and
		# then dropped takes ``inventory_count`` with it (``_forget_inventory_list``).
		inventory = mn.ONB_SUMMARY_INVENTORY_COUNT.format(
			count=payload.get("posted_count", payload.get("inventory_count", 0))
		)
	elif payload.get("inventory_skipped"):
		# Asked before ``has_inventory``: a skipped list keeps the Тийм answer (the company does
		# hold stock, so provisioning still opens the inventory accounts), and a count printed
		# from a payload with no list in it would report a stock count that never happened.
		inventory = mn.ONB_SUMMARY_INVENTORY_SKIPPED
	elif payload.get("has_inventory"):
		inventory = mn.ONB_SUMMARY_INVENTORY_COUNT.format(count=payload.get("inventory_count", 0))
	else:
		inventory = mn.ONB_SUMMARY_INVENTORY_NONE
	accountant = payload.get("accountant_name") or mn.ONB_SUMMARY_ACCOUNTANT_NONE
	if payload.get("micpa"):
		accountant = f"{accountant} ({payload['micpa']})"
	return mn.ONB_DONE.format(
		company=company, regime=regime, banks=bank_text, inventory=inventory, accountant=accountant
	)


def inventory_total(items: list[dict[str, Any]]) -> Decimal:
	"""Line amount when the parser gave one, else qty × rate; Decimal all the way."""
	total = Decimal("0.00")
	for item in items:
		amount = item.get("amount")
		if amount in (None, ""):
			amount = _money(item.get("qty")) * _money(item.get("rate"))
		total += _money(amount)
	return total


def inventory_preview(items: list[dict[str, Any]]) -> str:
	return mn.ONB_INVENTORY_PARSED.format(count=len(items), total=fmt_mnt(inventory_total(items)))


# --- account chooser -------------------------------------------------------------------------------


def account_chooser_text(accounts: list[tuple[str, str]], query: str | None = None) -> str:
	header = mn.MSG_ACCOUNT_SEARCH_RESULTS if query else mn.MSG_CHOOSE_ACCOUNT
	if query and not accounts:
		return mn.MSG_ACCOUNT_NOT_FOUND.format(query=query)
	return header


# --- reconciliation status (/данс) ----------------------------------------------------------------


def recon_status(company: str, rows: list[dict[str, Any]]) -> str:
	if not rows:
		return mn.MSG_RECON_NONE
	lines = [mn.MSG_RECON_STATUS_HEADER.format(company=company)]
	for row in rows:
		statement = _money(row.get("statement"))
		ledger = _money(row.get("ledger"))
		lines.append(
			mn.MSG_RECON_STATUS_LINE.format(
				bank=row.get("bank") or mn.VALUE_UNKNOWN,
				currency=row.get("currency") or "MNT",
				statement=fmt_mnt(statement),
				ledger=fmt_mnt(ledger),
				diff=fmt_mnt(statement - ledger),
				unmatched=row.get("unmatched", 0),
			)
		)
	return "\n".join(lines)


# --- questions (§5.7) ------------------------------------------------------------------------------


def question_card(answer: str, subject: str = "") -> str:
	"""The answer, then the one line naming what was actually read.

	The subject line is the safety valve on conversation memory: «мөн өнгөрсөн сард?» resolves
	against a remembered account and month, and the only way an accountant can catch the bot
	having carried the wrong one forward is to see «6210 · 2026 оны 7-р сар» under the
	sentence. It is built by code from the handler's resolved arguments, never by the model.
	"""
	# The empty-answer default is the WHOLE dead end, next step included. Both callers already
	# pass ``MSG_QUESTION_CANNOT_FULL`` for the failures they know about, so this line only ever
	# fires on one they did not — and a card that says "I could not answer" and stops there is
	# exactly the bare refusal the typed path was just fixed for. Three sites, one string.
	text = (answer or "").strip() or mn.MSG_QUESTION_CANNOT_FULL
	if not subject:
		return text
	return f"{text}\n{mn.MSG_QUESTION_SUBJECT.format(subject=_clip(subject, CARD_MAX_LINE_CHARS))}"


# --- quality (/чанар) ------------------------------------------------------------------------------


def quality_card(company: str, days: int, metrics: dict[str, Any]) -> str:
	if not metrics or not metrics.get("documents"):
		return mn.MSG_QUALITY_NO_DATA

	def pct(key: str) -> str:
		value = metrics.get(key)
		return (
			mn.VALUE_UNKNOWN
			if value is None
			else str(int(round(float(value) * (100 if float(value) <= 1 else 1))))
		)

	body = mn.MSG_QUALITY_BODY.format(
		extraction=pct("extraction_accuracy"),
		classification=pct("classification_accuracy"),
		vat=pct("vat_accuracy"),
		automatch=pct("automatch_rate"),
		false_match=pct("false_match_rate"),
		latency=metrics.get("latency_s", mn.VALUE_UNKNOWN),
		cost=metrics.get("cost_usd_per_document", mn.VALUE_UNKNOWN),
	)
	return mn.MSG_QUALITY_HEADER.format(company=company, days=days) + "\n" + body


# --- rule verification (/дүрэм, §1.2) ---------------------------------------------------------------


def pending_rules_card(rules: Any, total: int | None = None) -> str:
	"""The list an admin sees: what is blocking work, most-used first, and what each rule is for.

	``total`` is the number of unverified rules there really are, when the list was cut short:
	saying "16" and showing eight is honest, showing eight and saying nothing is not.
	"""
	rules = list(rules)
	if not rules:
		return mn.MSG_RULES_NONE
	shown = total or len(rules)
	lines = [mn.MSG_RULES_TITLE.format(count=shown), mn.MSG_RULES_INTRO, ""]
	for index, rule in enumerate(rules, start=1):
		row = mn.CARD_RULE_ROW_USES if rule.uses else mn.CARD_RULE_ROW
		lines.append(
			row.format(
				index=index,
				label=_clip(rule.label, CARD_MAX_LINE_CHARS),
				purpose=rule.purpose,
				uses=rule.uses,
			)
		)
	if total and total > len(rules):
		lines.append(mn.MSG_RULES_MORE.format(count=total - len(rules)))
	return "\n".join(lines)


def rule_card(rule: Any) -> str:
	"""One rule with its mechanics and its citation — or with the plain statement that it has none.

	The «no citation» line is the whole point of the card: the nine seeded patterns Order 116 does
	not print carry the instrument «Заавар 116 (2000)» and nothing else, and an admin who is not
	told that is being invited to tap a button that looks like it is backed by a legal text. The
	briefing under it is what the seed says they would be vouching for instead.
	"""
	kind_label = mn.RULE_KIND_LABELS.get(rule.kind, mn.VALUE_UNKNOWN)
	lines = [
		mn.CARD_RULE_TITLE.format(label=rule.label),
		mn.CARD_RULE_CODE.format(rule=rule.name, kind=kind_label),
		mn.CARD_RULE_PURPOSE.format(purpose=rule.purpose),
	]
	if rule.uses:
		lines.append(mn.CARD_RULE_USES.format(uses=rule.uses))
	if rule.lines:
		lines.append("")
		lines.append(mn.CARD_RULE_ENTRY_TITLE)
		lines += [_rule_line(line) for line in rule.lines]
	if rule.value:
		lines.append("")
		lines.append(mn.CARD_RULE_VALUE.format(value=rule.value, unit=rule.unit or mn.VALUE_UNKNOWN))
		lines.append(
			mn.CARD_RULE_EFFECTIVE.format(
				effective_from=rule.effective_from or mn.VALUE_UNKNOWN,
				effective_to=rule.effective_to or mn.CARD_RULE_OPEN_ENDED,
			)
		)
	lines.append("")
	lines += _rule_citation(rule)
	lines += _rule_briefing(rule)
	lines.append("")
	lines.append(mn.CARD_RULE_RESPONSIBILITY)
	lines.append(mn.CARD_RULE_ASK)
	return "\n".join(lines)


def _rule_line(line: Any) -> str:
	"""``"Дт 70 Удирдлагын зардал (6210, 6910) · нийт дүн"``."""
	side = mn.CARD_RULE_SIDE_LABELS.get(line.side, line.side or mn.VALUE_UNKNOWN)
	amount = mn.CARD_RULE_AMOUNT_LABELS.get(line.amount_kind, mn.CARD_RULE_AMOUNT_LABELS[""])
	if line.optional:
		amount = f"{amount} ({mn.CARD_RULE_LINE_OPTIONAL})"
	return mn.CARD_RULE_ENTRY_LINE.format(side=side, account=line.account, amount=amount)


def _rule_briefing(rule: Any) -> list[str]:
	"""The seed's «what you would be vouching for» sentence, on the screen where it is decided.

	Without it the nine patterns Order 116 does not print, and the pending tax parameters, offer
	a verify button with nothing but «no citation» beside it — while the seed has a sentence
	naming the other instrument, or saying that the entry is plain double-entry mechanics.
	"""
	note = getattr(rule, "note", "")
	if not note:
		return []
	lines = ["", mn.CARD_RULE_BRIEFING_TITLE, note]
	if getattr(rule, "note_truncated", False):
		lines.append(mn.CARD_RULE_TEXT_CUT)
	return lines


def _rule_citation(rule: Any) -> list[str]:
	if not rule.has_citation:
		return [mn.CARD_RULE_NO_CITATION]
	head = (
		mn.CARD_RULE_CITATION.format(instrument=rule.instrument, section=rule.section)
		if rule.section
		else mn.CARD_RULE_CITATION_NO_SECTION.format(instrument=rule.instrument)
	)
	lines = [head]
	if rule.quote:
		lines.append(mn.CARD_RULE_QUOTE.format(quote=rule.quote))
	if rule.url:
		lines.append(mn.CARD_RULE_SOURCE_URL.format(url=rule.url))
	return lines


__all__ = [name for name in dir() if not name.startswith("_")]
