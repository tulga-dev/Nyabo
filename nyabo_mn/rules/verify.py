"""The verification write path: what is blocking work, the evidence behind one rule, and the tap.

WHY this module exists: §1.2 refuses a Nyabo Posting Pattern or a Nyabo Tax Parameter with
``verified = 0`` for a real posting, and ``guard.UnverifiedRuleError`` tells the accountant that
an admin compares the rule with the primary text and marks it verified. Until now the only place
that could happen was the ERPNext desk, so from Telegram that sentence pointed at nothing. The
citation pass has since verified the everyday path — ``purchase_expense_non_vat`` and the rest of
an ordinary non-VAT day post without a tick — but nine posting patterns and thirteen tax
parameters still wait for a human, and every one of them stops somebody's work when it is reached.

Verification is deliberately *not* a workflow. It is one human saying "I have read the source and
I take responsibility": the flag, who, when, and a Nyabo Event — no states, no second approver,
and no un-verify from the chat (a mistake is corrected in the desk, where the edit is itself a
Version row and the row stops posting again the moment the flag comes off).

``verified = 1`` has two provenances and they must never be confused (DECISIONS VER-07). A row
the seed ships verified carries the repository's own citation — two readers, a reconciler and a
verbatim quote in ``docs/legal`` — and an empty ``verified_by``. A row a person ticked carries
their name, the time and a Nyabo Event. ``SOURCE_SEED`` / ``SOURCE_PERSON`` and
``verified_counts`` exist so no screen ever prints the first as if it were the second.

Bank layouts are guarded by the same rule but are not listed here: a layout is a per-site column
mapping learned from one accountant's upload, its evidence is that spreadsheet rather than a legal
text, and ``telegram.handlers.statement`` already names the layout to the admins when it saves one.
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
PROPOSAL = "Nyabo Proposal"

# One-letter kinds because they ride in Telegram callback data, which is capped at 64 bytes and
# already has to carry a rule name of up to 49 characters (``key:effective_from``).
KIND_PATTERN = "p"
KIND_PARAMETER = "t"
DOCTYPES: dict[str, str] = {KIND_PATTERN: PATTERN, KIND_PARAMETER: PARAMETER}

#: Who vouched for a verified row. ``verified_by`` is empty exactly when nobody on this site did
#: and the flag came from the seed, whose evidence is the citation on the row itself.
SOURCE_SEED = "seed"
SOURCE_PERSON = "person"

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

	@property
	def verified_source(self) -> str:
		"""``SOURCE_PERSON`` when a named human ticked this row, else ``SOURCE_SEED``."""
		return SOURCE_PERSON if self.verified_by else SOURCE_SEED

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


def kinds() -> tuple[str, ...]:
	"""The verifiable kinds, in the order a bare rule name is looked up (patterns are the common case)."""
	return tuple(DOCTYPES)


def doctype_for(kind: str) -> str | None:
	return DOCTYPES.get(kind)


# --- what is blocking work ----------------------------------------------------------------------


def pending(limit: int | None = None) -> list[PendingRule]:
	"""Unverified posting patterns and tax parameters, most-used first (see ``PendingRule.sort_key``).

	A disabled pattern is left out: it blocks nothing, because it is never selected.
	"""
	rules = [*_pending_patterns(), *_pending_parameters()]
	rules.sort(key=lambda rule: rule.sort_key)
	return rules[:limit] if limit else rules


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


def evidence(kind: str, name: str) -> RuleEvidence | None:
	"""What the admin reads before deciding; ``None`` when the row is not there any more."""
	doctype = doctype_for(kind)
	if not doctype or not frappe.db.exists(doctype, name):
		return None
	doc = frappe.get_doc(doctype, name)
	if doctype == PATTERN:
		return _pattern_evidence(doc)
	return _parameter_evidence(doc)


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


def request_verification(
	rule: str,
	company: str | None = None,
	user: str | None = None,
	telegram_id: str | int | None = None,
	admins_notified: int = 0,
) -> str:
	"""Record that somebody who may not verify was stopped by this rule.

	The accountant is told «the request has been recorded»; this is the row that makes that true,
	so that a rule blocking real work is visible in the audit log even if no admin ever reads the
	notification chat. ``admins_notified`` is how many chats actually heard about it, so a repeat
	within ``REQUEST_DEDUPE_MINUTES`` can be answered from this row instead of sent again.
	"""
	return events.log(
		mn.EVENT_RULE_VERIFY_REQUESTED,
		company=company,
		reason=rule,
		payload={
			"rule": rule,
			"requested_by": user or frappe.session.user,
			"admins_notified": int(admins_notified),
		},
		actor_telegram_id=telegram_id,
	)
