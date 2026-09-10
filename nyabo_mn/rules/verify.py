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

#: ``Nyabo Document.status`` while a bank statement has been stored and not yet read into the
#: ledger. ``matching.bank_import`` writes ``extracted`` the moment an import goes through, so
#: this is what tells a statement still waiting on its layout from one that is already booked.
STATEMENT_UNREAD = "received"

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

#: The same paragraph in Mongolian, written for the accountant who is actually at the button, and
#: appended to each note after the English one. This is the sentence the card shows.
#:
#: WHY it exists (reversing VER-10): everything else on the card is Mongolian and this — the one
#: sentence that says what the person is taking responsibility for — was English and addressed to
#: an admin, on the screen where a Mongolian accountant decides. VER-10 left it untranslated
#: because a second, unreviewed Mongolian wording of a legal caveat would be a new claim about the
#: law with nobody's name on it, and said in as many words to reverse it once the notes themselves
#: were translated. They now are: the Mongolian is in the seed beside the English, reviewed with
#: it, so there is one text and not a rendering-time paraphrase of another.
#:
#: The English stays in the note above it. It is the repository's own record — ``docs/legal``
#: quotes those paragraphs verbatim and ``tests/unit/test_seed_citations.py`` pins them — and it
#: is what a later reader compares the Mongolian against. Only the Mongolian reaches the card.
#: The wording itself is in ``i18n.mn`` with the rest of what the card says: these headings are
#: printed as well as searched for, and every string a user reads lives there (UX-08).
BRIEFING_MARKERS_MN: tuple[str, ...] = mn.RULE_BRIEFING_MARKERS_MN

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
	#: What the seed says the accountant would be taking responsibility for; see `_briefing`.
	note: str = ""
	note_truncated: bool = False
	#: True when ``note`` is the Mongolian paragraph written for the reader at the button. False
	#: means the card is falling back to the English one and owes them the line that says so.
	note_mn: bool = False
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
	"""``{"rules", "companies", "acceptances", "stale"}`` for one guarded DocType — the third provenance.

	Counted separately from ``verified_counts`` and never added to it: an acceptance says «this
	company's accountant applies this rule to these books», which is a different claim from «the
	law prints this entry», and a certification reader who saw one number would read the weaker
	claim as the stronger one for every row in it.

	The first three numbers count only what is **in force**: an acceptance whose fingerprint no
	longer matches the rule covers nothing, the guard refuses on it, and counting it told the
	compliance page more rules were cleared than are. ``stale`` is the rest of them, kept and
	shown as its own number rather than dropped, because a row a deploy has outrun is a fact
	about this site somebody has to answer for — it is exactly the queue of «rules an accountant
	must look at again», and the ``rule_changed_after_acceptance`` events are its history.
	"""
	empty = {"rules": 0, "companies": 0, "acceptances": 0, "stale": 0}
	if not frappe.db.exists("DocType", ACCEPTANCE):
		return empty
	rows = frappe.get_all(
		ACCEPTANCE, filters={"rule_doctype": doctype}, fields=["rule", "company", "rule_fingerprint"]
	)
	if not rows:
		return empty
	current: dict[str, str] = {}
	live = []
	stale = 0
	for row in rows:
		rule = str(row["rule"])
		if rule not in current:
			current[rule] = rule_fingerprint(doctype, rule)
		fingerprint_now = current[rule]
		if fingerprint_now and str(row.get("rule_fingerprint") or "") == fingerprint_now:
			live.append(row)
		else:
			stale += 1
	return {
		"rules": len({row["rule"] for row in live}),
		"companies": len({row["company"] for row in live}),
		"acceptances": len(live),
		"stale": stale,
	}


def kinds() -> tuple[str, ...]:
	"""The verifiable kinds, in the order a bare rule name is looked up (patterns are the common case)."""
	return tuple(DOCTYPES)


def doctype_for(kind: str) -> str | None:
	return DOCTYPES.get(kind)


# --- what an acceptance was given for -----------------------------------------------------------

#: How many hex characters of the sha256 an acceptance stores and its document name carries.
#: WHY a hash and not a version number or a stored copy compared field by field: the question is
#: «is this the same content the accountant read», it has to be answerable in one indexed
#: comparison on every posting, and a number somebody has to remember to bump is a number a
#: deploy forgets. WHY truncated: this is not an adversarial signature — nobody is trying to
#: forge posting lines that collide — it is a change detector, and 64 bits makes an accidental
#: collision impossible in practice while keeping the row's name inside Frappe's 140 characters
#: and readable in the desk. The full canonical content is stored beside it (``rule_content_json``)
#: so a refusal can say *what* changed and not merely that something did.
FINGERPRINT_CHARS = 16

#: The fields of each guarded DocType that decide what actually gets posted. Everything else on a
#: row — the Mongolian name, the citation, the notes — may be corrected by a deploy without the
#: accountant's acceptance meaning anything different, and treating those as content would refuse
#: real work every time a typo was fixed.
#:
#: The test of what belongs here is «could a deploy change this and change what the company's
#: ledger ends up saying», and every field of every guarded DocType has been put to it:
#:
#: * ``Nyabo Posting Pattern``: the scope fields decide which documents reach the lines and
#:   ``enabled`` decides whether the pattern is selected at all; ``lines`` is the entry itself
#:   (``CONTENT_LINE_FIELDS``). ``conditions`` is deliberately out — it is a paragraph of prose
#:   describing when a human would reach for the pattern, read by nothing in the engine
#:   (``core.rules_engine`` parses it into a field and never consults it). If it is ever made
#:   selective it belongs here the same day.
#: * ``Nyabo Tax Parameter``: the value, its unit, the dates it is in force between and its
#:   status are the whole of what ``rules.params`` reads; the rest of the row is its citation.
#: * ``Nyabo Bank Layout``: everything ``core.statements`` reads a file *with*. ``date_formats``
#:   and ``header_signature_json`` were missing and both change how a statement is parsed — a
#:   date format decides which rows are read at all, and the signature decides where the header
#:   is and whether this layout is the one that reads the file. ``keywords_json`` stays out: it
#:   is used only as a template when *no* layout matches (``statements._guess_layout``), and what
#:   comes out of that is a new, unverified layout row with an acceptance of its own to earn.
CONTENT_FIELDS: dict[str, tuple[str, ...]] = {
	PATTERN: ("applies_to_vat", "applies_to_cit", "document_types", "enabled"),
	PARAMETER: ("value_json", "unit", "effective_from", "effective_to", "status"),
	LAYOUT: (
		"column_map_json",
		"amount_style",
		"header_row_hint",
		"currency_default",
		"date_formats",
		"header_signature_json",
	),
}

#: A posting pattern's lines, in order: the debit and the credit themselves. This is the thing
#: MAJOR 2 is about — a deploy that changes them changes what the company posts under the
#: accountant's name. Every column of ``Nyabo Posting Pattern Line`` is here, because every one
#: of them says something about the entry:
#:
#: * ``alternatives_json`` names a second account class for the same line under a stated
#:   condition (``evals.harness._apply_alternatives`` swaps the line for it when the condition
#:   holds), so adding, removing or re-conditioning one changes which account this company posts
#:   to on the days the condition is met.
#: * ``class_assumed`` says whether the class was assumed rather than printed in the instrument.
#:   It is a statement about how much of this line rests on evidence, and it is exactly what an
#:   accountant is being asked to take responsibility for; a deploy that flipped it would change
#:   what the acceptance means without changing the acceptance.
CONTENT_LINE_FIELDS: tuple[str, ...] = (
	"side",
	"account_class",
	"class_name_mn",
	"sub_account_mn",
	"amount_kind",
	"role",
	"optional",
	"alternatives_json",
	"class_assumed",
	"v1_code_hint",
	"v1_code_range",
)


def rule_content(doctype: str | None, name: str) -> dict[str, Any]:
	"""The part of a rule an acceptance is *about*, canonically, or ``{}`` when the row is gone."""
	if not doctype or not name or not frappe.db.exists(doctype, name):
		return {}
	doc = frappe.get_doc(doctype, name)
	content: dict[str, Any] = {
		field: _content_value(doc.get(field)) for field in CONTENT_FIELDS.get(doctype, ())
	}
	if doctype == PATTERN:
		content["lines"] = [
			{field: _content_value(line.get(field)) for field in CONTENT_LINE_FIELDS}
			for line in doc.get("lines") or []
		]
	return content


def _content_value(value: Any) -> Any:
	"""Normalise for comparison: a JSON column reparsed, a check as 0/1, everything else as text.

	Without this the fingerprint would change when a column's storage did — a JSON field written
	with different key order, an Int read back as a string — and every company would be refused
	work by a migration that changed nothing anybody reads.
	"""
	if value in (None, ""):
		return None
	if isinstance(value, str):
		text = value.strip()
		if text.startswith(("{", "[")):
			try:
				return json.loads(text)
			except ValueError:
				return text
		return text
	if isinstance(value, bool):
		return int(value)
	if isinstance(value, (dict, list, int, float)):
		return value
	return str(value)


def fingerprint(content: dict[str, Any]) -> str:
	"""``FINGERPRINT_CHARS`` hex characters over the canonical content; ``""`` for nothing."""
	if not content:
		return ""
	import hashlib

	canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]


def rule_fingerprint(doctype: str | None, name: str) -> str:
	"""The fingerprint of the row as it reads *now* — the thing an acceptance is compared against."""
	return fingerprint(rule_content(doctype, name))


def content_lines(doctype: str | None, content: dict[str, Any]) -> tuple[str, ...]:
	"""One readable line per thing the content says, in the words the rule card already uses.

	The refusal has to say *what* changed, not that something did: «the rule changed, accept it
	again» with nothing beside it asks the accountant to take responsibility twice for a text
	they cannot see.
	"""
	if not content:
		return ()
	if doctype == PATTERN:
		return (
			*(_pattern_content_line(line) for line in content.get("lines") or ()),
			_pattern_scope_line(content),
		)
	if doctype == PARAMETER:
		value = content.get("value_json")
		return (
			mn.CARD_RULE_VALUE.format(
				value=_value_text(value) if value is not None else mn.VALUE_UNKNOWN,
				unit=str(content.get("unit") or mn.VALUE_UNKNOWN),
			),
			mn.CARD_RULE_EFFECTIVE.format(
				effective_from=content.get("effective_from") or mn.VALUE_UNKNOWN,
				effective_to=content.get("effective_to") or mn.CARD_RULE_OPEN_ENDED,
			),
		)
	mapping = content.get("column_map_json") or {}
	columns = (
		tuple(f"{mn.COLUMN_ROLES.get(role, role)} = «{header}»" for role, header in mapping.items())
		if isinstance(mapping, dict)
		else ()
	)
	return (*columns, _layout_reading_line(content))


def _layout_reading_line(content: dict[str, Any]) -> str:
	"""How the file is *read*, printed beside the mapping — the layout's own scope line.

	The columns alone are not the layout: the date formats decide which rows parse at all, the
	amount style decides whether a figure is a debit or a signed amount, and the header signature
	decides where the header is and whether this layout reads the file. A card that printed only
	the mapping showed the same two lines twice when one of those moved — «the layout changed,
	here it is, and here it is again» — which reads as a bug and teaches the accountant to tap
	through the warning. Exactly the reason ``_pattern_scope_line`` exists.
	"""
	signature = content.get("header_signature_json")
	return mn.CARD_RULE_CHANGED_LAYOUT_READING.format(
		dates=_joined(content.get("date_formats")) or mn.VALUE_UNKNOWN,
		amount_style=str(content.get("amount_style") or mn.VALUE_UNKNOWN),
		header_row=content.get("header_row_hint") if content.get("header_row_hint") is not None else "—",
		currency=str(content.get("currency_default") or mn.VALUE_UNKNOWN),
		signature=_joined(signature) or mn.VALUE_UNKNOWN,
	)


def _joined(value: Any) -> str:
	"""A newline-separated Small Text or a JSON list as one readable, comma-separated line."""
	if isinstance(value, (list, tuple)):
		return ", ".join(str(item) for item in value)
	return ", ".join(part.strip() for part in str(value or "").splitlines() if part.strip())


def _pattern_scope_line(content: dict[str, Any]) -> str:
	"""Which regime and which documents reach these lines — printed so a scope change is visible.

	Without it a deploy that widened ``applies_to_vat`` and left the debits and credits alone
	produced a card showing the same two lines twice: «the rule changed, here it is, and here it
	is again». That reads as a bug, and it teaches the accountant to tap through the warning.
	"""
	scope = SCOPE_LABELS.get(str(content.get("applies_to_vat") or SCOPE_ANY), SCOPE_LABELS[SCOPE_ANY])
	documents = str(content.get("document_types") or "").strip() or mn.VALUE_UNKNOWN
	return mn.CARD_RULE_CHANGED_SCOPE.format(scope=scope, documents=documents)


def _pattern_content_line(line: dict[str, Any]) -> str:
	side = mn.CARD_RULE_SIDE_LABELS.get(str(line.get("side") or ""), mn.VALUE_UNKNOWN)
	amount = mn.CARD_RULE_AMOUNT_LABELS.get(
		str(line.get("amount_kind") or ""), mn.CARD_RULE_AMOUNT_LABELS[""]
	)
	if line.get("optional"):
		amount = f"{amount} ({mn.CARD_RULE_LINE_OPTIONAL})"
	account = _account_label(
		{
			"account_class": line.get("account_class"),
			"class_name_mn": line.get("class_name_mn"),
			"v1_code_hint": line.get("v1_code_hint"),
			"v1_code_range": line.get("v1_code_range"),
		}
	)
	return mn.CARD_RULE_ENTRY_LINE.format(side=side, account=account, amount=amount)


@dataclasses.dataclass(frozen=True)
class RuleChange:
	"""An acceptance the rule has outgrown: who accepted what, and what the row says now.

	It is not an error state and not a workflow — it is the sentence the accountant is owed
	before being asked the same question a second time.
	"""

	rule: str
	doctype: str
	company: str
	accepted_by: str
	accepted_at: str
	accepted_fingerprint: str
	current_fingerprint: str
	before: tuple[str, ...]
	after: tuple[str, ...]


# --- the accountant's acceptance, per company ---------------------------------------------------


ACCEPTANCE_FIELDS = (
	"name",
	"company",
	"rule",
	"rule_doctype",
	"accepted_by",
	"accepted_at",
	"had_citation",
	"rule_fingerprint",
	"rule_content_json",
)


def acceptance(company: str | None, rule: str, doctype: str | None = None) -> dict[str, Any] | None:
	"""``company``'s acceptance of ``rule`` **as the rule reads now**, or ``None``.

	The question ``rules.guard`` asks, and the reason it names the content: an acceptance is one
	person saying «I have read this and these books work this way», so it covers the debit and
	credit lines that were in front of them and not a rule id for ever. A deploy that rewrites
	those lines leaves the row standing and the acceptance meaning nothing (MAJOR 2), and this is
	where that is noticed — before anything posts, on every posting.

	``doctype`` narrows the lookup when the caller knows which kind of rule it holds; without it
	any acceptance of that name for that company counts, which is right because a pattern id, a
	layout id and a ``key:effective_from`` never collide.
	"""
	current = rule_fingerprint(doctype or _acceptance_doctype(company, rule), rule)
	for row in _acceptance_rows(company, rule, doctype):
		if current and str(row.get("rule_fingerprint") or "") == current:
			return row
	return None


def _acceptance_rows(company: str | None, rule: str, doctype: str | None = None) -> list[dict[str, Any]]:
	"""Every acceptance this company has ever made of this rule, newest first."""
	if not company or not rule or not frappe.db.exists("DocType", ACCEPTANCE):
		return []
	filters: dict[str, Any] = {"company": company, "rule": rule}
	if doctype:
		filters["rule_doctype"] = doctype
	return [
		dict(row)
		for row in frappe.get_all(
			ACCEPTANCE, filters=filters, fields=list(ACCEPTANCE_FIELDS), order_by="creation desc"
		)
	]


def _acceptance_doctype(company: str | None, rule: str) -> str | None:
	"""Which guarded DocType this rule is, read off the acceptance when the caller did not say."""
	rows = _acceptance_rows(company, rule)
	return str(rows[0].get("rule_doctype") or "") or None if rows else None


def rule_change(company: str | None, rule: str, doctype: str | None = None) -> RuleChange | None:
	"""The acceptance this rule has outgrown, with both versions spelled out — or ``None``.

	``None`` covers both good states and they are not the same: no acceptance at all (the
	ordinary refusal, which has nothing to explain), and an acceptance that still covers the
	content (nothing to refuse). Only a company that *did* answer for this rule and is being
	refused anyway has something to be told.
	"""
	rows = _acceptance_rows(company, rule, doctype)
	if not rows:
		return None
	doctype = doctype or str(rows[0].get("rule_doctype") or "") or None
	current = rule_content(doctype, rule)
	current_fingerprint = fingerprint(current)
	if any(
		str(row.get("rule_fingerprint") or "") == current_fingerprint for row in rows if current_fingerprint
	):
		return None
	row = rows[0]  # the newest answer this company gave, which is the one that was outrun
	return RuleChange(
		rule=rule,
		doctype=str(doctype or ""),
		company=str(company or ""),
		accepted_by=str(row.get("accepted_by") or ""),
		accepted_at=str(row.get("accepted_at") or ""),
		accepted_fingerprint=str(row.get("rule_fingerprint") or ""),
		current_fingerprint=current_fingerprint,
		before=content_lines(doctype, _stored_content(row)),
		after=content_lines(doctype, current),
	)


def _stored_content(row: dict[str, Any]) -> dict[str, Any]:
	content = row.get("rule_content_json")
	if isinstance(content, str):
		try:
			content = json.loads(content) if content.strip() else {}
		except ValueError:
			return {}
	return content if isinstance(content, dict) else {}


def note_rule_changed_after_save(doc: Any, method: str | None = None) -> None:
	"""``on_update`` on every guarded DocType: say so when a save has outrun somebody's acceptance.

	WHY the hook and not the caller: this used to be called from ``rules.seed``'s update branch
	only, so a deploy was covered and a rule edited by hand in the ERPNext desk was not. The
	fingerprint stopped matching, every acceptance silently stopped covering the rule, and nothing
	was written saying why — an accountant watched a rule they had cleared start refusing again
	with no explanation anywhere. The notice belongs where the change happens, and the one place
	every change goes through is the save itself: a migrate, a desk edit, a bench console, a
	patch. ``doc_events`` is Frappe's own name for «whenever this document is written».

	Failures are swallowed and logged: the row is already saved, and neither a migrate nor an
	accountant's edit in the desk may be left half-done by the note about it. An error in the log
	is not the silence this exists to remove.
	"""
	try:
		note_rule_changed(doc.doctype, doc.name)
	except Exception as exc:  # noqa: BLE001 - the save stands; the note about it may fail
		log_event(
			"rules.verify.changed_note_failed",
			level="error",
			doctype=getattr(doc, "doctype", ""),
			rule=getattr(doc, "name", ""),
			error=type(exc).__name__,
		)


def note_rule_changed(doctype: str, name: str) -> int:
	"""Write one Nyabo Event per acceptance a change to this rule has just outrun; returns how many.

	Called from ``note_rule_changed_after_save`` on every save of a guarded row, because that is
	when it happens and nobody is in the chat to be told. «Do not silently invalidate» is the
	requirement: the guard will refuse and the accountant will be shown both versions the next
	time they post, but the record of *when the content moved out from under their name* belongs
	to the moment it moved.

	A row that has just been inserted has no acceptances to outrun, so the hook is a no-op there
	without needing to ask Frappe whether it is inside an insert.
	"""
	if not frappe.db.exists("DocType", ACCEPTANCE):
		return 0
	current = rule_fingerprint(doctype, name)
	rows = frappe.get_all(
		ACCEPTANCE,
		filters={"rule": name, "rule_doctype": doctype},
		fields=["name", "company", "accepted_by", "accepted_at", "rule_fingerprint"],
	)
	written = 0
	for row in rows:
		accepted = str(row.get("rule_fingerprint") or "")
		if not accepted or accepted == current:
			continue
		events.log(
			mn.EVENT_RULE_CHANGED_AFTER_ACCEPTANCE,
			company=str(row.get("company") or "") or None,
			ref_doctype=doctype,
			ref_name=name,
			reason=name,
			payload={
				"doctype": doctype,
				"rule": name,
				"company": row.get("company"),
				"acceptance": row.get("name"),
				"accepted_by": row.get("accepted_by"),
				"accepted_at": str(row.get("accepted_at") or ""),
				"accepted_fingerprint": accepted,
				"fingerprint": current,
			},
		)
		written += 1
	if written:
		log_event("rules.verify.changed_after_acceptance", doctype=doctype, rule=name, acceptances=written)
	return written


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

	The row records the rule's *content* as well as its name (``rule_fingerprint``,
	``rule_content_json``), because that is what the person actually read. A later deploy that
	rewrites the posting lines therefore leaves this row saying exactly what it always said, and
	the guard stops treating it as covering the new content (MAJOR 2). Re-accepting the changed
	rule writes a second row rather than editing this one: there were two decisions, made on two
	texts, and rewriting the first would put this accountant's name against words they never saw.

	Returns ``{"ok", "already", ...}`` rather than raising, exactly like ``verify``: every caller
	is a tap that needs a sentence either way. Idempotent both before and during the write: the
	``acceptance`` check below answers a second tap, and two taps that race past it collide on the
	document name, which says the acceptance exists — success, not a failure to report.
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
	content = rule_content(doctype, name)
	doc = frappe.get_doc(
		{
			"doctype": ACCEPTANCE,
			"company": company,
			"rule_kind": kind,
			"rule": name,
			"rule_doctype": doctype,
			"rule_label": found.label if found is not None else name,
			"had_citation": 1 if (found is not None and found.has_citation) else 0,
			"rule_fingerprint": fingerprint(content),
			"rule_content_json": json.dumps(content, ensure_ascii=False, sort_keys=True),
			"accepted_by": user,
			"accepted_telegram_id": str(telegram_id) if telegram_id is not None else None,
			"accepted_at": accepted_at,
		}
	)
	doc.flags.ignore_permissions = True
	try:
		doc.insert()
	except frappe.DuplicateEntryError:
		# Two taps on the same card raced past the ``acceptance`` check above and the second one
		# lost. The row is named ``company:kind:rule:fingerprint``, so what this exception says is
		# that this company's acceptance of exactly this content already exists — which is what
		# the tapper wanted. Reporting it as ``save_failed`` told them their answer had not been
		# recorded while it sat in the database with their colleague's name on it, and sent them
		# looking for a fault there is none of.
		existing = acceptance(company, name, doctype) or {}
		log_event("rules.verify.accept_raced", doctype=doctype, rule=name, company=company, user=user)
		return {
			"ok": True,
			"already": True,
			"rule": name,
			"doctype": doctype,
			"company": company,
			"accepted_by": str(existing.get("accepted_by") or ""),
			"accepted_at": str(existing.get("accepted_at") or ""),
		}
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
		# ``acceptance`` and not «has a row»: an acceptance the rule has since outgrown clears
		# nothing, so the rule is back on the list of what will refuse this company's postings.
		rules = [rule for rule in rules if acceptance(company, rule.name, rule.doctype) is None]
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


def _briefing(note: Any) -> tuple[str, bool, bool]:
	"""``(the paragraph, was it cut, is it Mongolian)`` — what the reader at the button is shown.

	An unverifiable row's note ends with the sentence CORE-18 / CORE-19 require — what the
	accountant would be vouching for, or what would unblock the row — first in the English the
	citation pass wrote for the repository, then in the Mongolian written for the person at the
	button. The Mongolian is what the card shows, and it is last in the note, so «from the first
	Mongolian marker to the end» is the whole of it and nothing English trails after it.

	A row with no Mongolian block yet falls back to the English one and says so through the third
	return value, which is what puts ``CARD_RULE_BRIEFING_LANGUAGE`` on the card: a reader who
	meets a paragraph they cannot read, on the screen where they take responsibility, must at
	least be told what it is. A note with no marker at all yields nothing rather than a paragraph
	of notes-to-self, and `tests/unit/test_seed_citations.py` is what keeps both sets there.
	"""
	text = " ".join(str(note or "").split())
	for markers, in_mongolian in ((BRIEFING_MARKERS_MN, True), (BRIEFING_MARKERS, False)):
		found = [start for start in (text.find(marker) for marker in markers) if start >= 0]
		if found:
			body, cut = _cut(text[min(found) :], NOTE_MAX_CHARS)
			return body, cut, in_mongolian
	return "", False, False


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
	note, note_cut, note_mn = _briefing(doc.get("notes"))
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
		note_mn=note_mn,
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
	note, note_cut, note_mn = _briefing(doc.get("note"))
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
		note_mn=note_mn,
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


def _existing_block(
	rule: str,
	company: str | None,
	proposal: str | None,
	document: str | None,
	telegram_id: str | int | None,
	within_minutes: int = REQUEST_DEDUPE_MINUTES,
) -> str | None:
	"""The name of this chat's own identical, still-recent block row, if there is one."""
	if telegram_id is None:
		return None
	from frappe.utils import add_to_date, now_datetime

	since = add_to_date(now_datetime(), minutes=-int(within_minutes))
	rows = frappe.get_all(
		events.EVENT_DOCTYPE,
		filters={
			"event_type": mn.EVENT_RULE_BLOCKED,
			"reason": rule,
			"actor_telegram_id": str(telegram_id),
			"ref_name": proposal or document or "",
			"creation": [">=", since],
		},
		fields=["name", "company"],
		order_by="creation desc",
		limit=1,
	)
	for row in rows:
		if (row.get("company") or None) == (company or None):
			return str(row["name"])
	return None


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


def waiting_statement(rule: str, company: str | None) -> str | None:
	"""The statement file this bank layout is *still* holding for this company — or ``None``.

	WHY this exists beside ``blocked_document``: that one is deliberately narrow (VER-04) — the
	same chat, inside ``REQUEST_DEDUPE_MINUTES`` — because it finishes a *posting*, and one
	person's tap must never post another person's document. A layout confirmation posts nothing:
	it re-reads a spreadsheet into Bank Transaction rows and cards that still need their own
	[Батлах]. Keeping the narrow lookup as the only one meant that an accountant who mapped the
	columns, was called away for twenty minutes and then tapped [Манай компанид хамаарна] was told
	«send this statement again» — and the sha256 dedup answered the second upload «this document
	is already here» (§5.3). That is a dead end, and it is the one this whole flow exists to
	remove.

	So the question is asked of the books rather than of the chat: this company's own refusals of
	this layout, whatever minute they happened in and whoever sent the file, naming a document
	that is still sitting unread. ``status`` is what makes it safe to widen — an import that went
	through sets ``extracted`` (``matching.bank_import``), so a statement already in the ledger is
	never read a second time by this.
	"""
	if not rule or not company or not frappe.db.exists("DocType", DOCUMENT):
		return None
	rows = frappe.get_all(
		events.EVENT_DOCTYPE,
		filters={
			"event_type": mn.EVENT_RULE_BLOCKED,
			"reason": rule,
			"company": company,
			"ref_doctype": DOCUMENT,
		},
		fields=["ref_name"],
		order_by="creation desc",
	)
	for row in rows:
		document = str(row.get("ref_name") or "").strip()
		if not document or not frappe.db.exists(DOCUMENT, document):
			continue
		if str(frappe.db.get_value(DOCUMENT, document, "status") or "") == STATEMENT_UNREAD:
			return document
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

	Repeated inside ``REQUEST_DEDUPE_MINUTES`` it returns the row that is already there instead of
	writing another. Tapping [Батлах] again is what a person does when nothing seems to happen,
	and this is an append-only log — the one log nobody can tidy up afterwards. The first row says
	everything a second identical one would.
	"""
	existing = _existing_block(rule, company, proposal, document, telegram_id)
	if existing:
		return existing
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
