"""The verification write path: what is blocking work, the evidence behind one rule, and the tap.

WHY this module exists: §1.2 refuses a Nyabo Posting Pattern or a Nyabo Tax Parameter with
``verified = 0`` for a real posting. The citation pass verified the everyday path —
``purchase_expense_non_vat`` and the rest of an ordinary non-VAT day post without anybody being
asked — but nine posting patterns and thirteen tax parameters still wait for a human, and every one
of them stops somebody's work when it is reached: a customer advance recognised as revenue, a
transfer between a company's own bank accounts, the simplified 1% accrual, the employee social
insurance withholding.

Who that human is, is the founder's decision (DECISIONS ACC-01): the accountant, who is the main
user and the person whose signature the entry carries, accepts an uncited rule for their **own
company's** books; a site admin verifies the **global row** when a citation turns up.

Neither is a workflow. Each is one human saying "I have read this and I take responsibility": a
row, who, when, and a Nyabo Event — no states, no second approver, and no undoing from the chat
(a mistake is corrected in the desk, where the edit or deletion is itself traceable, and the rule
stops posting again the moment it is).

A rule may now be cleared in three different ways, and an auditor must be able to tell them apart
(DECISIONS VER-07, ACC-01):

1. **The seed's citation.** ``verified = 1`` with an empty ``verified_by``: the repository's own
   evidence — two readers, a reconciler and a verbatim quote in ``docs/legal`` — and nobody on
   this site named for it. 35 posting patterns and 46 tax parameters ship this way.
2. **A site admin's tap.** ``verified = 1`` with ``verified_by`` / ``verified_at`` and a
   ``rule_verified`` Nyabo Event: one named person saying they read the primary text, for every
   company on the site (VER-08 is why it is the *site* admin).
3. **This company's accountant accepting it.** A ``Nyabo Rule Acceptance`` row and a
   ``rule_accepted_for_company`` Nyabo Event. The global row stays unverified; the guard lets
   *that company* post on it and refuses every other company until its own accountant accepts.
   The accountant is the professional who signs these books, so this is theirs to decide — and it
   is deliberately not a global verification, because one accountant's reading of an uncited rule
   must not bind another accountant's client.

``SOURCE_SEED`` / ``SOURCE_PERSON`` / ``SOURCE_COMPANY``, ``verified_counts`` and
``accepted_counts`` exist so no screen ever prints one of the three as if it were another.

Bank layouts are guarded by the same rule but are not listed by ``pending()``: a layout is a
column mapping learned from one accountant's upload, its evidence is that spreadsheet rather than
a legal text, and the accountant who mapped it confirms it for their own company in
``telegram.handlers.statement``. They are a kind here (``KIND_LAYOUT``) so that acceptance,
evidence and the guard speak about them in the same words as the other two.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import frappe

from nyabo_mn.compliance import events
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.rules import regime

PATTERN = "Nyabo Posting Pattern"
PARAMETER = "Nyabo Tax Parameter"
LAYOUT = "Nyabo Bank Layout"
PROPOSAL = "Nyabo Proposal"
DOCUMENT = "Nyabo Document"
ACCEPTANCE = "Nyabo Rule Acceptance"

# One-letter kinds because they ride in Telegram callback data, which is capped at 64 bytes and
# already has to carry a rule name of up to 49 characters (``key:effective_from``).
KIND_PATTERN = "p"
KIND_PARAMETER = "t"
KIND_LAYOUT = "b"
DOCTYPES: dict[str, str] = {KIND_PATTERN: PATTERN, KIND_PARAMETER: PARAMETER, KIND_LAYOUT: LAYOUT}

#: Who vouched for a verified row. ``verified_by`` is empty exactly when nobody on this site did
#: and the flag came from the seed, whose evidence is the citation on the row itself.
SOURCE_SEED = "seed"
SOURCE_PERSON = "person"
#: The third provenance (DECISIONS ACC-01): nobody verified the global row, and this company's
#: accountant accepted it for their own books. It never sets ``verified`` and never speaks for
#: another company; it is a ``Nyabo Rule Acceptance`` row plus a Nyabo Event.
SOURCE_COMPANY = "company"

#: How much of a legal reference is worth reading in a chat bubble before it stops being a label.
PURPOSE_MAX_CHARS = 70
QUOTE_MAX_CHARS = 400
#: The briefing is longer than a label on purpose — it is the whole reason the row is unverified,
#: or the scope its citation does not reach. 1000 leaves room above the longest the seed carries
#: today (797 characters, ``purchase_expense_non_vat``); past it the card says it was cut.
NOTE_MAX_CHARS = 1000

#: How long one accountant's request about one rule speaks for the ones that follow it. Tapping
#: [Батлах] again is what a person does when nothing seems to happen, and each tap used to write
#: a row into an append-only log and wake every admin again. Long enough to cover the retries of
#: one sitting, short enough that a real second attempt an hour later is heard.
REQUEST_DEDUPE_MINUTES = 15

#: How long after being stopped by a rule somebody is still told that it was verified. A receipt
#: refused on Friday is still ``proposed`` on Monday, wearing its own [Батлах], so the news is
#: still worth having; past a week the person has moved on and the card has been dealt with.
REQUEST_NOTICE_DAYS = 7

#: Where the part of a seed note written *for the person at the verify button* begins. The
#: citation pass appends it to `Nyabo Posting Pattern.notes` / `Nyabo Tax Parameter.note`
#: (DECISIONS CORE-18, CORE-19); everything before the first marker is reader provenance, which
#: belongs in the repository and not in a chat bubble.
BRIEFING_MARKERS: tuple[str, ...] = (
	"DAILY USE:",
	"SCOPE OF THIS CITATION",
	"WHAT AN ADMIN WOULD BE VOUCHING FOR",
	"WHAT UNBLOCKS IT",
)

#: ``Nyabo Posting Pattern.applies_to_vat`` -> the Mongolian scope on the card. The VAT-payer key
#: is the regime name, so it comes from ``rules.regime`` rather than being spelled again (F-12).
SCOPE_ANY = "any"
SCOPE_NON_VAT = "non_vat"
SCOPE_LABELS: dict[str, str] = {
	SCOPE_ANY: mn.RULE_VAT_SCOPE_ANY,
	regime.REGIME_VAT_PAYER: mn.RULE_VAT_SCOPE_VAT_PAYER,
	SCOPE_NON_VAT: mn.RULE_VAT_SCOPE_NON_VAT,
}


@dataclasses.dataclass(frozen=True)
class PendingRule:
	"""One unverified rule as the list card shows it: what it is, and how much work it blocks."""

	kind: str
	doctype: str
	name: str
	label: str
	purpose: str
	#: Proposals already built on this rule; ``None`` when the row leaves no such trail
	#: (a tax parameter is read during a calculation and nothing records which one was used).
	uses: int | None = None

	@property
	def sort_key(self) -> tuple[int, int, str]:
		"""Most-used first, patterns before parameters, then by name so the order is stable."""
		return (0 if self.kind == KIND_PATTERN else 1, -(self.uses or 0), self.name)


@dataclasses.dataclass(frozen=True)
class RuleLine:
	"""One debit or credit of a posting pattern, in the words the DocType stores."""

	side: str
	account: str
	amount_kind: str
	optional: bool = False


@dataclasses.dataclass(frozen=True)
class RuleEvidence:
	"""Everything the admin is asked to decide on, and nothing the card would have to guess."""

	kind: str
	doctype: str
	name: str
	label: str
	purpose: str
	verified: bool
	uses: int | None = None
	lines: tuple[RuleLine, ...] = ()
	value: str = ""
	unit: str = ""
	effective_from: str = ""
	effective_to: str = ""
	verified_by: str = ""
	verified_at: str = ""
	instrument: str = ""
	section: str = ""
	quote: str = ""
	#: True when ``quote`` is a fragment of the sentence in the row. The card MUST say so: an
	#: admin decides on what is on their screen, and «…» around half a provision reads as a
	#: whole one.
	quote_truncated: bool = False
	url: str = ""
	#: What the seed says an admin would be taking responsibility for; see `_briefing`.
	note: str = ""
	note_truncated: bool = False
	#: The company this card was drawn for, and that company's acceptance if it has one. Empty on
	#: a card drawn for no particular company (``/дүрэм`` lists the site's rules, not one client's).
	company: str = ""
	accepted_by: str = ""
	accepted_at: str = ""

	@property
	def verified_source(self) -> str:
		"""``SOURCE_PERSON`` when a named human ticked this row, else ``SOURCE_SEED``."""
		return SOURCE_PERSON if self.verified_by else SOURCE_SEED

	@property
	def accepted(self) -> bool:
		"""True when ``company``'s own accountant accepted this rule for their books."""
		return bool(self.accepted_by)

	@property
	def source(self) -> str:
		"""Which of the three provenances lets this rule post for ``company`` — or ``""``.

		Verification outranks acceptance because it is the stronger claim: a globally verified row
		posts for every company and needs no acceptance at all. An empty string means nothing
		clears it yet, which is what the card is asking about.
		"""
		if self.verified:
			return self.verified_source
		return SOURCE_COMPANY if self.accepted else ""

	@property
	def has_citation(self) -> bool:
		"""A section or a verbatim quote. The instrument alone is not evidence.

		Every seeded posting pattern carries «Заавар 116 (2000)» whether or not anyone has found
		the entry in it, so treating the instrument as a citation would show the admin an
		authority for 16 rules that have none and quietly invite a tap on all of them.
		"""
		return bool(self.section or self.quote)


def verified_counts(doctype: str) -> dict[str, int]:
	"""``{"verified", "by_person", "by_seed"}`` for one guarded DocType — the audit split.

	A single "35 rows verified" conflates two very different claims, and DECISIONS VER-01 says
	``verified_by`` names the human who took responsibility. Both can be true only if the rows
	with no ``verified_by`` are counted, and shown, as what they are: verified by the citation
	the repository ships, reviewed before release, with nobody on this site named for them.
	"""
	if not frappe.db.exists("DocType", doctype):
		return {"verified": 0, "by_person": 0, "by_seed": 0}
	rows = frappe.get_all(doctype, filters={"verified": 1}, fields=["name", "verified_by"])
	by_person = sum(1 for row in rows if (row.get("verified_by") or "").strip())
	return {"verified": len(rows), "by_person": by_person, "by_seed": len(rows) - by_person}


def accepted_counts(doctype: str) -> dict[str, int]:
	"""``{"rules", "companies", "acceptances"}`` for one guarded DocType — the third provenance.

	Counted separately from ``verified_counts`` and never added to it: an acceptance says «this
	company's accountant applies this rule to these books», which is a different claim from «the
	law prints this entry», and a certification reader who saw one number would read the weaker
	claim as the stronger one for every row in it.
	"""
	empty = {"rules": 0, "companies": 0, "acceptances": 0}
	if not frappe.db.exists("DocType", ACCEPTANCE):
		return empty
	rows = frappe.get_all(ACCEPTANCE, filters={"rule_doctype": doctype}, fields=["rule", "company"])
	if not rows:
		return empty
	return {
		"rules": len({row["rule"] for row in rows}),
		"companies": len({row["company"] for row in rows}),
		"acceptances": len(rows),
	}


def kinds() -> tuple[str, ...]:
	"""The verifiable kinds, in the order a bare rule name is looked up (patterns are the common case)."""
	return tuple(DOCTYPES)


def doctype_for(kind: str) -> str | None:
	return DOCTYPES.get(kind)


# --- the accountant's acceptance, per company ---------------------------------------------------


def acceptance(company: str | None, rule: str, doctype: str | None = None) -> dict[str, Any] | None:
	"""``company``'s acceptance of ``rule``, or ``None``. The question ``rules.guard`` asks.

	``doctype`` narrows the lookup when the caller knows which kind of rule it holds; without it
	any acceptance of that name for that company counts, which is right because a pattern id, a
	layout id and a ``key:effective_from`` never collide.
	"""
	if not company or not rule or not frappe.db.exists("DocType", ACCEPTANCE):
		return None
	filters: dict[str, Any] = {"company": company, "rule": rule}
	if doctype:
		filters["rule_doctype"] = doctype
	rows = frappe.get_all(
		ACCEPTANCE,
		filters=filters,
		fields=["name", "company", "rule", "rule_doctype", "accepted_by", "accepted_at", "had_citation"],
		order_by="creation asc",
		limit=1,
	)
	return dict(rows[0]) if rows else None


def acceptances(rule: str) -> list[dict[str, Any]]:
	"""Every company that has accepted this rule, oldest first — the audit view of one rule."""
	if not frappe.db.exists("DocType", ACCEPTANCE):
		return []
	return [
		dict(row)
		for row in frappe.get_all(
			ACCEPTANCE,
			filters={"rule": rule},
			fields=["name", "company", "rule_doctype", "accepted_by", "accepted_at"],
			order_by="creation asc",
		)
	]


def accept(
	kind: str, name: str, company: str, user: str, telegram_id: str | int | None = None
) -> dict[str, Any]:
	"""Record that ``company``'s accountant accepts this rule for that company's books. Idempotent.

	This is the compliance act the founder's decision puts in the accountant's hands: the person
	whose signature the entry will carry says the rule applies to the books they keep. It writes a
	``Nyabo Rule Acceptance`` row (who, which rule, which company, when, and whether the rule had a
	citation at the time) and a ``rule_accepted_for_company`` Nyabo Event — and it deliberately
	does **not** touch ``verified``: the global row is one row for the whole site, and this
	accountant speaks only for their own client (DECISIONS ACC-01).

	Returns ``{"ok", "already", ...}`` rather than raising, exactly like ``verify``: every caller
	is a tap that needs a sentence either way.
	"""
	doctype = doctype_for(kind)
	if not doctype:
		return {"ok": False, "reason": "unknown_kind", "rule": name}
	if not company:
		return {"ok": False, "reason": "no_company", "rule": name}
	if not frappe.db.exists(doctype, name):
		return {"ok": False, "reason": "not_found", "rule": name}
	existing = acceptance(company, name, doctype)
	if existing is not None:
		# A second tap on a card somebody scrolled back to must not overwrite the first
		# accountant's name — the same rule as ``verify``, for the same reason.
		return {
			"ok": True,
			"already": True,
			"rule": name,
			"doctype": doctype,
			"company": company,
			"accepted_by": str(existing.get("accepted_by") or ""),
			"accepted_at": str(existing.get("accepted_at") or ""),
		}
	from frappe.utils import now_datetime

	found = evidence(kind, name)
	accepted_at = now_datetime()
	doc = frappe.get_doc(
		{
			"doctype": ACCEPTANCE,
			"company": company,
			"rule_kind": kind,
			"rule": name,
			"rule_doctype": doctype,
			"rule_label": found.label if found is not None else name,
			"had_citation": 1 if (found is not None and found.has_citation) else 0,
			"accepted_by": user,
			"accepted_telegram_id": str(telegram_id) if telegram_id is not None else None,
			"accepted_at": accepted_at,
		}
	)
	doc.flags.ignore_permissions = True
	try:
		doc.insert()
	except Exception as exc:  # noqa: BLE001 - every failure here has the same answer for the tapper
		# ``accepted_by`` is a Link to User, so this raises for a session user with no User row —
		# the same real state ``verify`` guards against. Nothing was written and nothing may post.
		log_event(
			"rules.verify.accept_failed",
			level="error",
			doctype=doctype,
			rule=name,
			company=company,
			user=user,
			error=type(exc).__name__,
		)
		return {"ok": False, "reason": "save_failed", "rule": name, "doctype": doctype, "company": company}
	event = events.log(
		mn.EVENT_RULE_ACCEPTED,
		company=company,
		ref_doctype=doctype,
		ref_name=name,
		reason=str(doc.rule_label or name),
		payload={
			"doctype": doctype,
			"rule": name,
			"company": company,
			"accepted_by": user,
			"had_citation": bool(doc.had_citation),
			"acceptance": doc.name,
		},
		actor_telegram_id=telegram_id,
	)
	log_event("rules.verify.accepted", doctype=doctype, rule=name, company=company, user=user)
	return {
		"ok": True,
		"already": False,
		"rule": name,
		"doctype": doctype,
		"company": company,
		"acceptance": doc.name,
		"event": event,
		"accepted_by": user,
		"accepted_at": accepted_at,
	}


# --- what is blocking work ----------------------------------------------------------------------


def pending(limit: int | None = None, company: str | None = None) -> list[PendingRule]:
	"""Unverified posting patterns and tax parameters, most-used first (see ``PendingRule.sort_key``).

	A disabled pattern is left out: it blocks nothing, because it is never selected. With a
	``company``, so is a rule that company's accountant has already accepted — the list is meant
	to answer «what will refuse my postings», and a rule this company may already post on is not
	on that list even though the global row is still unverified.
	"""
	rules = [*_pending_patterns(), *_pending_parameters()]
	if company:
		accepted = {row["rule"] for row in _accepted_rules(company)}
		rules = [rule for rule in rules if rule.name not in accepted]
	rules.sort(key=lambda rule: rule.sort_key)
	return rules[:limit] if limit else rules


def _accepted_rules(company: str) -> list[dict[str, Any]]:
	if not frappe.db.exists("DocType", ACCEPTANCE):
		return []
	return [dict(row) for row in frappe.get_all(ACCEPTANCE, filters={"company": company}, fields=["rule"])]


def _pending_patterns() -> list[PendingRule]:
	if not frappe.db.exists("DocType", PATTERN):
		return []
	rows = frappe.get_all(
		PATTERN,
		filters={"verified": 0, "enabled": 1},
		fields=["name", "name_mn", "family", "primary_document_mn", "applies_to_vat"],
	)
	return [
		PendingRule(
			kind=KIND_PATTERN,
			doctype=PATTERN,
			name=row["name"],
			label=row.get("name_mn") or row["name"],
			purpose=_pattern_purpose(row),
			uses=_pattern_uses(row["name"]),
		)
		for row in rows
	]


def _pending_parameters() -> list[PendingRule]:
	if not frappe.db.exists("DocType", PARAMETER):
		return []
	rows = frappe.get_all(
		PARAMETER,
		filters={"verified": 0},
		fields=["name", "key", "source_text", "article", "status", "effective_from"],
	)
	return [
		PendingRule(
			kind=KIND_PARAMETER,
			doctype=PARAMETER,
			name=row["name"],
			label=row["name"],
			purpose=_parameter_purpose(row),
			uses=None,
		)
		for row in rows
	]


def _pattern_purpose(row: dict[str, Any]) -> str:
	document = str(row.get("primary_document_mn") or "").strip() or str(row.get("family") or "")
	scope = SCOPE_LABELS.get(str(row.get("applies_to_vat") or SCOPE_ANY), SCOPE_LABELS[SCOPE_ANY])
	return _clip(mn.RULE_PURPOSE_PATTERN.format(document=document or mn.VALUE_UNKNOWN, scope=scope))


def _parameter_purpose(row: dict[str, Any]) -> str:
	# The same de-duplication as the citation line below: the article rides in the tail of
	# source_text, and this line is clipped, so repeating it costs the reader the law's own name.
	instrument, section = _parameter_source(row.get("source_text"), row.get("article"))
	source = instrument or section
	default_status = mn.RULE_STATUS_LABELS["active"]
	status = mn.RULE_STATUS_LABELS.get(str(row.get("status") or "active"), default_status)
	return _clip(mn.RULE_PURPOSE_PARAMETER.format(source=source or mn.VALUE_UNKNOWN, status=status))


def _pattern_uses(pattern_id: str) -> int | None:
	"""Proposals built on this pattern — the only usage trail Nyabo keeps (§1.4)."""
	if not frappe.db.exists("DocType", PROPOSAL):
		return None
	try:
		return int(frappe.db.count(PROPOSAL, {"posting_pattern": pattern_id}))
	except Exception as exc:  # noqa: BLE001 - a count must never take the list down
		log_event("rules.verify.uses_failed", level="warning", pattern=pattern_id, error=repr(exc))
		return None


def _clip(text: str, limit: int = PURPOSE_MAX_CHARS) -> str:
	text = " ".join(str(text).split())
	return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _cut(text: str, limit: int) -> tuple[str, bool]:
	"""``(text as it will be shown, was it cut?)`` — the caller has to say so on the card.

	Silently shortening a legal quote or a briefing is the dangerous case this returns a flag
	for: the admin decides on what is on the screen, so a fragment must not read as the whole.
	"""
	text = str(text or "").strip()
	if len(text) <= limit:
		return text, False
	return text[:limit].rstrip(), True


def _briefing(note: Any) -> tuple[str, bool]:
	"""The part of a seed note addressed to whoever is asked to tick the box, and whether it was cut.

	An unverifiable row's note ends with the sentence CORE-18 / CORE-19 require — what an admin
	would be vouching for, or what would unblock the row. That sentence was written for this exact
	screen, so the card shows it; the research provenance above it (which reader, which fetch) is
	for the repository. A note with no marker at all yields nothing rather than a paragraph of
	notes-to-self, and `tests/unit/test_seed_citations.py` is what keeps the markers there.
	"""
	text = " ".join(str(note or "").split())
	starts = [text.find(marker) for marker in BRIEFING_MARKERS]
	found = [start for start in starts if start >= 0]
	if not found:
		return "", False
	return _cut(text[min(found) :], NOTE_MAX_CHARS)


# --- the evidence behind one rule ---------------------------------------------------------------


def evidence(kind: str, name: str, company: str | None = None) -> RuleEvidence | None:
	"""What the reader decides on; ``None`` when the row is not there any more.

	``company`` adds that company's own acceptance to the card, so an accountant is never asked
	to accept a rule their company has already accepted, and the card can say which of the three
	provenances is holding this rule up for these particular books.
	"""
	doctype = doctype_for(kind)
	if not doctype or not frappe.db.exists(doctype, name):
		return None
	doc = frappe.get_doc(doctype, name)
	if doctype == PATTERN:
		found = _pattern_evidence(doc)
	elif doctype == LAYOUT:
		found = _layout_evidence(doc)
	else:
		found = _parameter_evidence(doc)
	return _with_acceptance(found, company)


def _with_acceptance(found: RuleEvidence, company: str | None) -> RuleEvidence:
	row = acceptance(company, found.name, found.doctype)
	return dataclasses.replace(
		found,
		company=str(company or ""),
		accepted_by=str((row or {}).get("accepted_by") or ""),
		accepted_at=str((row or {}).get("accepted_at") or ""),
	)


def _pattern_evidence(doc: Any) -> RuleEvidence:
	citation_section = str(doc.get("citation_section") or "").strip()
	note, note_cut = _briefing(doc.get("notes"))
	quote, quote_cut = _cut(doc.get("citation_quote"), QUOTE_MAX_CHARS)
	return RuleEvidence(
		kind=KIND_PATTERN,
		doctype=PATTERN,
		name=doc.name,
		label=str(doc.get("name_mn") or doc.name),
		purpose=_pattern_purpose(
			{
				"primary_document_mn": doc.get("primary_document_mn"),
				"family": doc.get("family"),
				"applies_to_vat": doc.get("applies_to_vat"),
			}
		),
		verified=bool(int(doc.get("verified") or 0)),
		verified_by=str(doc.get("verified_by") or ""),
		verified_at=str(doc.get("verified_at") or ""),
		uses=_pattern_uses(doc.name),
		lines=tuple(
			RuleLine(
				side=str(line.get("side") or ""),
				account=_account_label(line),
				amount_kind=str(line.get("amount_kind") or ""),
				optional=bool(int(line.get("optional") or 0)),
			)
			for line in doc.get("lines") or []
		),
		instrument=str(doc.get("citation_instrument") or ""),
		section=citation_section,
		quote=quote,
		quote_truncated=quote_cut,
		url=str(doc.get("citation_url") or ""),
		note=note,
		note_truncated=note_cut,
	)


def _layout_evidence(doc: Any) -> RuleEvidence:
	"""A learned bank layout as evidence: which bank, and which column plays which role.

	A layout has no legal citation and never will — the thing it is read against is the
	spreadsheet the accountant uploaded, not an instrument — so ``instrument``, ``section`` and
	``quote`` stay empty and ``cards`` prints the layout's own line instead of «no citation».
	"""
	bank = str(doc.get("bank") or "")
	mapping = _column_map(doc.get("column_map_json"))
	return RuleEvidence(
		kind=KIND_LAYOUT,
		doctype=LAYOUT,
		name=doc.name,
		label=str(doc.get("layout_id") or doc.name),
		purpose=_clip(
			mn.RULE_PURPOSE_LAYOUT.format(
				bank=mn.BANK_NAMES_MN.get(bank, bank) or mn.VALUE_UNKNOWN, columns=len(mapping)
			)
		),
		verified=bool(int(doc.get("verified") or 0)),
		value=", ".join(
			f"{mn.COLUMN_ROLES.get(role, role)} = «{header}»" for role, header in mapping.items()
		),
		unit=str(doc.get("amount_style") or ""),
	)


def _column_map(column_map_json: Any) -> dict[str, str]:
	"""``{role: header}`` as the layout stores it; an unreadable mapping shows as none at all."""
	value = column_map_json
	if isinstance(value, str):
		try:
			value = json.loads(value) if value.strip() else {}
		except ValueError:
			return {}
	return (
		{str(role): str(header) for role, header in (value or {}).items()} if isinstance(value, dict) else {}
	)


def _account_label(line: Any) -> str:
	"""``"70 Удирдлагын зардал (6210, 6910)"``: the class, its Mongolian name, the v1 code hint."""
	parts = [str(line.get("account_class") or "").strip(), str(line.get("class_name_mn") or "").strip()]
	hint = str(line.get("v1_code_hint") or line.get("v1_code_range") or "").strip()
	label = " ".join(part for part in parts if part)
	return f"{label} ({hint})" if hint else label or mn.VALUE_UNKNOWN


def _parameter_source(source_text: Any, article: Any) -> tuple[str, str]:
	"""``("… хууль (2000, consolidated)", "6.1")`` — the article, printed once.

	Every seeded tax parameter carries its article twice: in ``article`` and again in the tail of
	``source_text`` («…, art. 6.1»). The card's citation line is «{instrument}, {section}», so it
	read «…, art. 6.1, 6.1» on all 59 rows — which an accountant reads as two provisions, or as a
	citation nobody checked, on the screen where they decide whether the citation is real.
	"""
	instrument = str(source_text or "").strip()
	section = str(article or "").strip()
	for tail in (f", art. {section}", f", {section}"):
		if section and instrument.endswith(tail):
			return instrument[: -len(tail)].rstrip(), section
	return instrument, section


def _parameter_evidence(doc: Any) -> RuleEvidence:
	note, note_cut = _briefing(doc.get("note"))
	quote, quote_cut = _cut(doc.get("quote_mn"), QUOTE_MAX_CHARS)
	instrument, section = _parameter_source(doc.get("source_text"), doc.get("article"))
	return RuleEvidence(
		kind=KIND_PARAMETER,
		doctype=PARAMETER,
		name=doc.name,
		label=str(doc.get("key") or doc.name),
		purpose=_parameter_purpose(
			{
				"source_text": doc.get("source_text"),
				"article": doc.get("article"),
				"status": doc.get("status"),
			}
		),
		verified=bool(int(doc.get("verified") or 0)),
		verified_by=str(doc.get("verified_by") or ""),
		verified_at=str(doc.get("verified_at") or ""),
		value=_value_text(doc.get("value_json")),
		unit=str(doc.get("unit") or ""),
		effective_from=str(doc.get("effective_from") or ""),
		effective_to=str(doc.get("effective_to") or ""),
		instrument=instrument,
		section=section,
		quote=quote,
		quote_truncated=quote_cut,
		url=str(doc.get("source_url") or ""),
		note=note,
		note_truncated=note_cut,
	)


def _value_text(value_json: Any) -> str:
	"""The stored value as the admin reads it; a pending row has none and says so with a dash."""
	if value_json in (None, ""):
		return mn.VALUE_UNKNOWN
	value = value_json
	if isinstance(value_json, str):
		try:
			value = json.loads(value_json)
		except ValueError:
			return value_json
	if isinstance(value, (dict, list)):
		return json.dumps(value, ensure_ascii=False)
	return str(value)


# --- the tap ------------------------------------------------------------------------------------


def verify(kind: str, name: str, user: str, telegram_id: str | int | None = None) -> dict[str, Any]:
	"""Mark one rule verified, stamp who and when, and write the Nyabo Event. Idempotent.

	The event is the compliance record: the flag alone says a rule may post, not that a named
	human took responsibility for reading the source. Returns ``{"ok": …, "already": …}`` rather
	than raising, because every caller (a Telegram tap today) has a sentence to show either way.
	"""
	doctype = doctype_for(kind)
	if not doctype:
		return {"ok": False, "reason": "unknown_kind", "rule": name}
	if not frappe.db.exists(doctype, name):
		return {"ok": False, "reason": "not_found", "rule": name}
	doc = frappe.get_doc(doctype, name)
	if int(doc.get("verified") or 0):
		# Who it was is part of the answer: a second tapper is entitled to know whether a person
		# took responsibility for this row or whether the seed's citation is all there is.
		return {
			"ok": True,
			"already": True,
			"rule": name,
			"doctype": doctype,
			"verified_by": str(doc.get("verified_by") or ""),
			"verified_at": str(doc.get("verified_at") or ""),
		}
	from frappe.utils import now_datetime

	verified_at = now_datetime()
	doc.verified = 1
	doc.verified_by = user
	doc.verified_at = verified_at
	doc.flags.ignore_permissions = True
	try:
		doc.save()
	except Exception as exc:  # noqa: BLE001 - every failure here has the same answer for the tapper
		# ``verified_by`` is a Link to User, so this raises for a session user with no User row —
		# a Telegram admin whose ``ensure_frappe_user`` never ran, which is a real state on a site
		# linked before that step existed. Nothing was written and nothing may post, so the caller
		# gets the same shape as ``unknown_kind`` rather than a traceback and a silent tap.
		log_event(
			"rules.verify.save_failed",
			level="error",
			doctype=doctype,
			rule=name,
			user=user,
			error=type(exc).__name__,
		)
		return {"ok": False, "reason": "save_failed", "rule": name, "doctype": doctype}
	event = events.log(
		mn.EVENT_RULE_VERIFIED,
		ref_doctype=doctype,
		ref_name=name,
		reason=str(doc.get("name_mn") or doc.get("key") or name),
		payload={"doctype": doctype, "rule": name, "verified_by": user},
		actor_telegram_id=telegram_id,
	)
	log_event("rules.verify.verified", doctype=doctype, rule=name, user=user)
	return {
		"ok": True,
		"already": False,
		"rule": name,
		"doctype": doctype,
		"event": event,
		"verified_by": user,
		"verified_at": verified_at,
	}


def recent_request(
	rule: str, company: str | None = None, within_minutes: int = REQUEST_DEDUPE_MINUTES
) -> dict[str, Any] | None:
	"""The last request about this rule and company, if one is still recent; else ``None``.

	The caller uses it to answer a repeated tap without writing a second row into an append-only
	log or waking every admin again. It returns the earlier request's own payload, so the second
	tapper is told exactly what the first one was told — including that nobody was reachable.
	"""
	from frappe.utils import add_to_date, now_datetime

	since = add_to_date(now_datetime(), minutes=-int(within_minutes))
	rows = frappe.get_all(
		events.EVENT_DOCTYPE,
		filters={
			"event_type": mn.EVENT_RULE_VERIFY_REQUESTED,
			"reason": rule,
			"creation": [">=", since],
		},
		fields=["name", "company", "payload_json"],
		order_by="creation desc",
	)
	for row in rows:
		# The company is compared here rather than in the filter: it may be None, and "no company"
		# must not silently match every company's requests.
		if (row.get("company") or None) != (company or None):
			continue
		payload = row.get("payload_json")
		if isinstance(payload, str):
			try:
				payload = json.loads(payload)
			except ValueError:
				payload = {}
		return {"event": row["name"], **(payload or {})}
	return None


def requesters(rule: str, within_days: int = REQUEST_NOTICE_DAYS, company: str | None = None) -> list[str]:
	"""The Telegram chats this rule stopped recently, newest first and each one once.

	``company`` narrows them to the people whose books an acceptance actually unblocks: an
	acceptance clears the rule for one company, so telling another company's accountant that
	«the rule is cleared, press [Батлах] again» would be a promise their next tap breaks.

	Clearing a rule ends somebody's wait, and only the person who tapped used to be told. The
	accountant whose receipt was refused is promised «press [Батлах] again once it is cleared»
	with no way of learning when that happened — their proposal is still ``proposed`` and still
	wearing its own button, so the whole retry is one tap they do not know to make. The block
	events are the list of people owed that sentence: every refused [Батлах] writes one,
	whoever the reader was.
	"""
	from frappe.utils import add_to_date, now_datetime

	since = add_to_date(now_datetime(), days=-int(within_days))
	rows = frappe.get_all(
		events.EVENT_DOCTYPE,
		filters={
			"event_type": mn.EVENT_RULE_BLOCKED,
			"reason": rule,
			"creation": [">=", since],
		},
		fields=["actor_telegram_id", "company"],
		order_by="creation desc",
	)
	chats: list[str] = []
	for row in rows:
		# Compared here rather than in the filter: a caller with no company means "everyone this
		# rule stopped", which a `company = None` filter would turn into "nobody".
		if company and (row.get("company") or None) != company:
			continue
		chat = str(row.get("actor_telegram_id") or "").strip()
		if chat and chat not in chats:
			chats.append(chat)
	return chats


def request_verification(
	rule: str,
	company: str | None = None,
	user: str | None = None,
	telegram_id: str | int | None = None,
	admins_notified: int = 0,
	proposal: str | None = None,
) -> str:
	"""Record that somebody who may not clear this rule themselves was stopped by it.

	Since the accountant may now accept a rule for their own company (``accept``), the people who
	still take this path are the ones who genuinely cannot: an owner tapping [Батлах] under an
	auto-approve policy, and anyone with no active company. They are told «the request has been
	recorded»; this is the row that makes that true, so that a rule blocking real work is visible
	in the audit log even if nobody ever reads the notification chat. ``admins_notified`` is how
	many chats actually heard about it, so a repeat within ``REQUEST_DEDUPE_MINUTES`` can be
	answered from this row instead of sent again.
	"""
	return events.log(
		mn.EVENT_RULE_VERIFY_REQUESTED,
		company=company,
		reason=rule,
		payload={
			"rule": rule,
			"requested_by": user or frappe.session.user,
			"admins_notified": int(admins_notified),
			"proposal": proposal,
		},
		actor_telegram_id=telegram_id,
	)


def blocked_proposal(
	rule: str,
	company: str | None,
	telegram_id: str | int | None,
	within_minutes: int = REQUEST_DEDUPE_MINUTES,
) -> str | None:
	"""The proposal *this* person's own [Батлах] tap was refused on, minutes ago — or ``None``.

	WHY it is read back out of the audit log rather than carried in the callback datum: the datum
	is 64 bytes and a tax-parameter name already eats 49 of them (VER-03), and a rule card sitting
	in a shared chat must never let one person's tap post another person's document (VER-04). The
	request event records exactly the three things that make the continuation safe — the same
	Telegram chat, the same company and the same rule, inside the retry window — so
	``handlers.admin`` can finish the approval the accountant already asked for instead of asking
	them to press the same button twice.
	"""
	for payload in _recent_blocks(rule, company, telegram_id, within_minutes):
		name = str(payload.get("proposal") or "").strip()
		if name and frappe.db.exists(PROPOSAL, name):
			return name
	return None


def _recent_blocks(
	rule: str, company: str | None, telegram_id: str | int | None, within_minutes: int
) -> list[dict[str, Any]]:
	"""The payloads of this chat's own recent refusals of one rule for one company, newest first."""
	if not rule or telegram_id is None:
		return []
	from frappe.utils import add_to_date, now_datetime

	since = add_to_date(now_datetime(), minutes=-int(within_minutes))
	rows = frappe.get_all(
		events.EVENT_DOCTYPE,
		filters={
			"event_type": mn.EVENT_RULE_BLOCKED,
			"reason": rule,
			"actor_telegram_id": str(telegram_id),
			"creation": [">=", since],
		},
		fields=["company", "payload_json"],
		order_by="creation desc",
	)
	payloads: list[dict[str, Any]] = []
	for row in rows:
		# Compared here rather than in the filter: it may be None, and "no company" must not
		# silently match every company's refusals.
		if (row.get("company") or None) != (company or None):
			continue
		payload = row.get("payload_json")
		if isinstance(payload, str):
			try:
				payload = json.loads(payload)
			except ValueError:
				payload = {}
		payloads.append(payload or {})
	return payloads


def blocked_document(
	rule: str,
	company: str | None,
	telegram_id: str | int | None,
	within_minutes: int = REQUEST_DEDUPE_MINUTES,
) -> str | None:
	"""The statement *file* this person's own upload was refused on, for the same reason and window.

	A bank layout stops a document before any proposal exists, so what has to be finished is the
	import, not an approval. Re-sending the file is not an option Nyabo can offer honestly: the
	sha256 dedup would answer the second upload with «this document is already here» (§5.3). So
	the file that is already stored is what the confirmation re-reads.
	"""
	if not rule or telegram_id is None:
		return None
	for payload in _recent_blocks(rule, company, telegram_id, within_minutes):
		name = str(payload.get("document") or "").strip()
		if name and frappe.db.exists(DOCUMENT, name):
			return name
	return None


def record_block(
	rule: str,
	company: str | None,
	proposal: str | None = None,
	telegram_id: str | int | None = None,
	user: str | None = None,
	document: str | None = None,
) -> str:
	"""The Nyabo Event behind every refusal: which rule stopped which piece of work, for whom.

	Written whoever the reader is — accountant, owner or admin — because it is the trail
	``blocked_proposal`` / ``blocked_document`` read to finish that work once the rule is
	cleared, and because «this rule stopped real work» is the fact ``/дүрэм`` and the month-end
	checklist are both about. A posting names its proposal, a refused statement names its file.
	"""
	ref_doctype = PROPOSAL if proposal else (DOCUMENT if document else None)
	return events.log(
		mn.EVENT_RULE_BLOCKED,
		company=company,
		ref_doctype=ref_doctype,
		ref_name=proposal or document or None,
		reason=rule,
		payload={
			"rule": rule,
			"company": company,
			"proposal": proposal,
			"document": document,
			"user": user or frappe.session.user,
		},
		actor_telegram_id=telegram_id,
	)
