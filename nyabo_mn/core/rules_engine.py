"""Rules as data: dated tax parameters, regime history and posting patterns.

Three ideas, all from docs/ARCHITECTURE.md §1:

1. A lookup always takes the transaction date. `resolve_parameter` finds the one row in
   force on that date and refuses (raises) when there is none or when the row is
   pending — it never falls back to the previous value, because a silent fallback is
   exactly how a 2027 rate ends up on 2026 books or vice versa.
2. Regime branching happens once. `regime_on` turns a company's regime history into a
   RegimeContext; everything downstream reads `is_vat_payer` and friends.
3. Patterns are templates, not code. `instantiate` fills a PatternSpec's lines with the
   amounts of one document and asks a resolver for the concrete account codes, so the
   same engine serves the V1 chart, the v0.3 chart and an accountant's own chart.

No frappe import; the Frappe-side `nyabo_mn.rules` package loads the DocType rows and
calls into here.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from nyabo_mn.core.models import (
	Citation,
	DocumentKind,
	ProposedEntry,
	ProposedLine,
	Regime,
	RegimeContext,
	VatTreatment,
)
from nyabo_mn.core.money import ZERO, quantize, to_decimal
from nyabo_mn.i18n import mn

SUMMARY_VAT_MONTHLY = "vat_monthly"
SUMMARY_SIMPLIFIED_QUARTERLY = "simplified_quarterly"

# A pattern's applies_to_vat / applies_to_cit vocabulary. The two selective values *are* the
# regime names (a pattern that applies to a VAT payer, one that applies to the 1% regime), so
# they are read off the Regime enum instead of being spelled again (F-12).
CIT_REGULAR = "regular"
CIT_SIMPLIFIED = Regime.SIMPLIFIED_1PCT.value
VAT_STATUS_PAYER = Regime.VAT_PAYER.value
VAT_STATUS_NON_VAT = "non_vat"
ANY = "any"

# ProposedEntry.document_kind values and the ERPNext DocType a pattern lists them as.
DOCUMENT_KIND_TO_DOCTYPE: dict[str, str] = {
	"purchase_invoice": "Purchase Invoice",
	"journal_entry": "Journal Entry",
	"sales_invoice": "Sales Invoice",
	"payment_entry": "Payment Entry",
	"bank_transaction": "Bank Transaction",
}


# --- errors ------------------------------------------------------------------------------------


class RuleError(Exception):
	"""Base for rule lookups that must stop a posting. `message_mn` is card-ready."""

	message_mn: str = ""

	def __init__(self, message: str, message_mn: str):
		super().__init__(message)
		self.message_mn = message_mn


class MissingRuleError(RuleError):
	"""No row of the key covers the date."""


class PendingRuleError(RuleError):
	"""The row in force is status "pending" or has no value: the law changed, the text is not encoded yet."""


class AmbiguousRuleError(RuleError):
	"""Two rows of the same key overlap on the date; a seed or admin error."""


class NoPatternError(RuleError):
	"""No posting pattern matches the document and regime."""


class MissingAmountError(RuleError):
	"""A mandatory pattern line has no amount."""


# --- tax parameters ------------------------------------------------------------------------------


def _parse_date(value: Any) -> dt.date | None:
	if value in (None, ""):
		return None
	if isinstance(value, dt.datetime):
		return value.date()
	if isinstance(value, dt.date):
		return value
	return dt.date.fromisoformat(str(value))


@dataclass(frozen=True)
class ParameterRow:
	"""One row of tax_parameters.json / Nyabo Tax Parameter."""

	key: str
	value: Any
	unit: str
	effective_from: dt.date
	effective_to: dt.date | None = None
	status: str = "active"
	verified: bool = False
	source_text: str = ""
	source_url: str | None = None
	article: str | None = None
	note: str = ""

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> ParameterRow:
		"""Accepts the seed row shape and the DocType row shape (value_json)."""
		value = data.get("value", data.get("value_json"))
		effective_from = _parse_date(data.get("effective_from"))
		if effective_from is None:
			raise ValueError(f"parameter {data.get('key')!r} has no effective_from")
		return cls(
			key=str(data["key"]),
			value=value,
			unit=str(data.get("unit") or ""),
			effective_from=effective_from,
			effective_to=_parse_date(data.get("effective_to")),
			status=str(data.get("status") or "active"),
			verified=bool(data.get("verified", False)),
			source_text=str(data.get("source_text") or data.get("source") or ""),
			source_url=data.get("source_url") or None,
			article=data.get("article") or None,
			note=str(data.get("note") or ""),
		)

	def covers(self, on_date: dt.date) -> bool:
		if on_date < self.effective_from:
			return False
		return self.effective_to is None or on_date <= self.effective_to

	@property
	def is_pending(self) -> bool:
		return self.status == "pending" or self.value is None

	def as_decimal(self) -> Decimal:
		"""Numeric rows (fraction, MNT, years) and thresholds ({"amount": ...}) as Decimal."""
		value = self.value
		if isinstance(value, Mapping) and "amount" in value:
			value = value["amount"]
		if isinstance(value, (int, float, str, Decimal)) and not isinstance(value, bool):
			return to_decimal(value)
		raise TypeError(f"parameter {self.key} ({self.unit}) is not numeric: {value!r}")


def resolve_parameter(rows: Iterable[ParameterRow], key: str, on_date: dt.date) -> ParameterRow:
	"""The single row of `key` in force on `on_date`.

	Raises MissingRuleError (no row covers the date), AmbiguousRuleError (more than one
	does) or PendingRuleError (the row is pending / has no value). Never falls back.
	"""
	matches = [row for row in rows if row.key == key and row.covers(on_date)]
	date_text = on_date.isoformat()
	if not matches:
		raise MissingRuleError(
			f"no tax parameter {key!r} covers {date_text}",
			mn.MSG_RULE_MISSING.format(key=key, date=date_text),
		)
	if len(matches) > 1:
		raise AmbiguousRuleError(
			f"{len(matches)} rows of {key!r} cover {date_text}",
			mn.MSG_RULE_AMBIGUOUS.format(key=key, date=date_text),
		)
	row = matches[0]
	if row.is_pending:
		raise PendingRuleError(
			f"tax parameter {key!r} is pending on {date_text}",
			mn.MSG_RULE_PENDING.format(key=key, date=date_text),
		)
	return row


def parameter_decimal(rows: Iterable[ParameterRow], key: str, on_date: dt.date) -> Decimal:
	"""Shortcut for numeric parameters (VAT rate, thresholds)."""
	return resolve_parameter(rows, key, on_date).as_decimal()


# --- regimes -------------------------------------------------------------------------------------


def regime_on(
	history: Sequence[tuple[Regime | str, dt.date | str | None, dt.date | str | None]],
	on_date: dt.date,
) -> RegimeContext:
	"""RegimeContext for a date from (regime, effective_from, effective_to) rows.

	The only place that turns a regime name into behaviour: a VAT payer recovers input
	VAT and files monthly; a simplified-regime company puts VAT into cost and files the
	1% summary quarterly. No row for the date raises MissingRuleError (onboarding not done).
	"""
	matches: list[tuple[Regime, dt.date | None]] = []
	for regime, start, end in history:
		start_date = _parse_date(start)
		end_date = _parse_date(end)
		if start_date is not None and on_date < start_date:
			continue
		if end_date is not None and on_date > end_date:
			continue
		matches.append((Regime(regime) if not isinstance(regime, Regime) else regime, start_date))
	if not matches:
		raise MissingRuleError(
			f"no tax regime covers {on_date.isoformat()}",
			mn.MSG_REGIME_MISSING.format(date=on_date.isoformat()),
		)
	# Overlaps are an admin error; the most recently started row wins so a correction row
	# added later takes precedence, and the seed check reports the overlap separately.
	matches.sort(key=lambda m: m[1] or dt.date.min)
	regime, effective_from = matches[-1]
	is_vat_payer = regime == Regime.VAT_PAYER
	return RegimeContext(
		regime=regime,
		is_vat_payer=is_vat_payer,
		input_vat_recoverable=is_vat_payer,
		summary_kind=SUMMARY_VAT_MONTHLY if is_vat_payer else SUMMARY_SIMPLIFIED_QUARTERLY,
		effective_from=effective_from,
	)


def vat_status_of(ctx: RegimeContext) -> str:
	return VAT_STATUS_PAYER if ctx.is_vat_payer else VAT_STATUS_NON_VAT


def cit_regime_of(ctx: RegimeContext) -> str:
	return CIT_SIMPLIFIED if ctx.regime == Regime.SIMPLIFIED_1PCT else CIT_REGULAR


# --- posting patterns ------------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternAlternative:
	"""Another account for the same line under a stated condition (cash instead of bank...)."""

	account_class: str
	role: str | None = None
	when: str = ""
	when_mn: str = ""

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> PatternAlternative:
		return cls(
			account_class=str(data.get("account_class") or ""),
			role=data.get("role") or None,
			when=str(data.get("when") or ""),
			when_mn=str(data.get("when_mn") or ""),
		)


@dataclass(frozen=True)
class PatternLine:
	side: str  # debit | credit
	account_class: str
	class_name_mn: str
	sub_account_mn: str
	amount_kind: str
	role: str | None = None
	code: str | None = None
	optional: bool = False
	alternatives: tuple[PatternAlternative, ...] = ()
	v1_code_hint: str | None = None
	class_assumed: bool = False

	@property
	def selector(self) -> str:
		"""What the resolver is asked for: an explicit code, a role, or a model-chart class."""
		if self.code:
			return self.code
		if self.role:
			return f"role:{self.role}"
		return f"class:{self.account_class}"

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> PatternLine:
		alternatives = data.get("alternatives")
		if alternatives is None:
			alternatives = data.get("alternatives_json")
		alternatives = alternatives or []
		if isinstance(alternatives, str):  # DocType child row stores alternatives_json as text
			alternatives = json.loads(alternatives) if alternatives.strip() else []
		return cls(
			side=str(data["side"]),
			account_class=str(data["account_class"]),
			class_name_mn=str(data.get("class_name_mn") or ""),
			sub_account_mn=str(data.get("sub_account_mn") or ""),
			amount_kind=str(data["amount_kind"]),
			role=data.get("role") or None,
			code=data.get("code") or None,
			optional=bool(data.get("optional", False)),
			alternatives=tuple(PatternAlternative.from_dict(a) for a in alternatives),
			v1_code_hint=data.get("v1_code_hint") or None,
			class_assumed=bool(data.get("class_assumed", False)),
		)


@dataclass(frozen=True)
class PatternSpec:
	pattern_id: str
	name_mn: str
	family: str
	document_types: tuple[str, ...]
	applies_to_vat: str = ANY
	applies_to_cit: str = ANY
	conditions: str = ""
	lines: tuple[PatternLine, ...] = ()
	primary_document_mn: str = ""
	citation: Citation = field(default_factory=lambda: Citation("", None, False))
	verified: bool = False
	enabled: bool = True
	notes: str = ""

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> PatternSpec:
		"""Accepts the seed shape and the DocType shape (document_types as a comma list)."""
		doc_types = data.get("document_types") or ()
		if isinstance(doc_types, str):
			doc_types = [d.strip() for d in doc_types.replace("\n", ",").split(",") if d.strip()]
		citation = data.get("citation")
		if not isinstance(citation, Mapping):
			citation = {
				"instrument": data.get("citation_instrument") or "",
				"section": data.get("citation_section"),
				"verified": bool(data.get("verified", False)),
				"url": data.get("citation_url"),
				"quote": data.get("citation_quote"),
			}
		return cls(
			pattern_id=str(data.get("pattern_id") or data.get("id") or data.get("name")),
			name_mn=str(data.get("name_mn") or ""),
			family=str(data.get("family") or ""),
			document_types=tuple(str(d) for d in doc_types),
			applies_to_vat=str(data.get("applies_to_vat") or ANY),
			applies_to_cit=str(data.get("applies_to_cit") or ANY),
			conditions=str(data.get("conditions") or ""),
			lines=tuple(PatternLine.from_dict(line) for line in data.get("lines") or ()),
			primary_document_mn=str(data.get("primary_document_mn") or ""),
			citation=Citation(
				instrument=str(citation.get("instrument") or ""),
				section=citation.get("section") or None,
				verified=bool(citation.get("verified", False)),
				url=citation.get("url") or None,
				quote=citation.get("quote") or None,
			),
			verified=bool(data.get("verified", False)),
			enabled=bool(data.get("enabled", True)),
			notes=str(data.get("notes") or ""),
		)

	def applies(self, ctx: RegimeContext) -> bool:
		vat_ok = self.applies_to_vat in (ANY, vat_status_of(ctx))
		cit_ok = self.applies_to_cit in (ANY, cit_regime_of(ctx))
		return vat_ok and cit_ok

	@property
	def specificity(self) -> int:
		return int(self.applies_to_vat != ANY) + int(self.applies_to_cit != ANY)


def citation_suffix(citation: Citation) -> str:
	"""The text appended to every explanation: ' — Заавар 116 (2000), <section>'."""
	section = citation.section or mn.CITATION_SECTION_PENDING
	return mn.EXPL_SUFFIX_CITATION.format(instrument=citation.instrument, section=section)


def select_pattern(
	patterns: Iterable[PatternSpec],
	document_kind: str,
	ctx: RegimeContext,
	hints: Mapping[str, Any] | None = None,
) -> PatternSpec:
	"""Pick the pattern for a document under a regime.

	`document_kind` is a ProposedEntry kind ("purchase_invoice") or an ERPNext DocType
	("Purchase Invoice"). `hints["family"]` narrows to a pattern family such as
	"purchase_expense"; `hints["pattern_id"]` forces one pattern (still regime-checked).
	The most specific match wins; a tie keeps seed order. Raises NoPatternError.
	"""
	hints = dict(hints or {})
	doctype = DOCUMENT_KIND_TO_DOCTYPE.get(document_kind, document_kind)
	family = hints.get("family")
	wanted_id = hints.get("pattern_id")
	candidates: list[PatternSpec] = []
	for pattern in patterns:
		if not pattern.enabled or not pattern.applies(ctx):
			continue
		if wanted_id and pattern.pattern_id != wanted_id:
			continue
		if doctype not in pattern.document_types:
			continue
		if family and pattern.family != family:
			continue
		candidates.append(pattern)
	if not candidates:
		raise NoPatternError(
			f"no posting pattern for {doctype!r} family={family!r} regime={ctx.regime.value}",
			mn.MSG_PATTERN_NOT_FOUND.format(document=doctype),
		)
	best = max(candidates, key=lambda p: p.specificity)  # first max keeps seed order on ties
	return best


def instantiate(
	pattern: PatternSpec,
	amounts: Mapping[str, Decimal | int | str],
	resolve_code: Callable[[str], str],
	*,
	company: str = "",
	posting_date: dt.date | None = None,
	explanation: str = "",
	vat_treatment: VatTreatment = "none",
	document_kind: DocumentKind | None = None,
	supplier: str | None = None,
	description: str = "",
	warnings: Iterable[str] = (),
	cleared: bool | None = None,
) -> ProposedEntry:
	"""Fill a pattern with one document's amounts.

	`amounts` maps amount kinds ("net", "vat", "gross", "gross_salary", ...) to values.
	A mandatory line without an amount raises MissingAmountError; an optional line with
	no amount or a zero amount is dropped (the VAT line of a receipt from a non-VAT
	seller). `resolve_code` receives the line selector ("class:70", "role:input_vat",
	or an explicit code) and returns the account code for the company's chart.

	`cleared` answers, for `company`, the same two questions `rules.guard` asks: is the
	pattern's own row verified, **or** has this company's accountant accepted it (DECISIONS
	ACC-01). The caller resolves it, because that second question needs the database and this
	module has no frappe import. `None` means «nobody asked», and then only the row's own flag
	counts — which is what the evals and any core-only caller want. WHY it matters: the warning
	below is the ⚠️ on the receipt card, and reading `pattern.verified` alone kept telling an
	accountant that a rule they had accepted for their own books was unverified.
	"""
	lines: list[ProposedLine] = []
	for line in pattern.lines:
		raw = amounts.get(line.amount_kind)
		if raw is None:
			if line.optional:
				continue
			raise MissingAmountError(
				f"pattern {pattern.pattern_id}: no amount {line.amount_kind!r}",
				mn.MSG_PATTERN_AMOUNT_MISSING.format(pattern=pattern.name_mn, amount_kind=line.amount_kind),
			)
		amount = quantize(to_decimal(raw))
		if amount == ZERO and line.optional:
			continue
		code = resolve_code(line.selector)
		lines.append(
			ProposedLine(
				account_code=code,
				debit=amount if line.side == "debit" else ZERO,
				credit=amount if line.side == "credit" else ZERO,
				description=description or line.sub_account_mn,
			)
		)

	warnings_out = list(warnings)
	cleared_here = bool(pattern.verified) if cleared is None else bool(cleared)
	if not cleared_here and mn.WARN_UNVERIFIED_RULE not in warnings_out:
		warnings_out.append(mn.WARN_UNVERIFIED_RULE)

	gross = amounts.get("gross")
	total = quantize(to_decimal(gross)) if gross is not None else sum((line.debit for line in lines), ZERO)
	vat = amounts.get("vat")
	vat_amount = quantize(to_decimal(vat)) if vat is not None else ZERO

	if document_kind is None:
		document_kind = _default_document_kind(pattern, vat_treatment)

	return ProposedEntry(
		company=company,
		posting_date=posting_date or dt.date.today(),
		lines=tuple(lines),
		pattern_id=pattern.pattern_id,
		citation=pattern.citation,
		explanation=(explanation or "") + citation_suffix(pattern.citation),
		document_kind=document_kind,
		vat_treatment=vat_treatment,
		warnings=tuple(warnings_out),
		total=total,
		vat_amount=vat_amount,
		supplier=supplier,
	)


def _default_document_kind(pattern: PatternSpec, vat_treatment: str) -> DocumentKind:
	"""ARCHITECTURE §5.3 step 6: a Purchase Invoice only when the input VAT is withheld."""
	if "Purchase Invoice" in pattern.document_types and vat_treatment == "withheld":
		return "purchase_invoice"
	return "journal_entry"
