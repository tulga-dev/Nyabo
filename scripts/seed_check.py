"""Validate the seed data under nyabo_mn/nyabo/seed/ (docs/seed/README.md).

    python scripts/seed_check.py            # exit 1 and list problems when anything is off
    python scripts/seed_check.py <seed dir> # check another copy (tests use a broken copy)

Why a script and not only tests: the seed is edited by hand (an accountant or the founder
changes a threshold, adds a pattern) and `rules.seed.sync` loads it on every migrate. A
wrong alias or an overlapping tax-parameter period would only surface as a MissingRuleError
on a real receipt, so the check runs before the data is committed and again in CI
(tests/unit/test_seed_check.py). It uses the same loaders as the runtime
(nyabo_mn.setup.chart.load_chart, nyabo_mn.core.rules_engine) so "valid here" means
"loads there".
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
	sys.path.insert(0, str(REPO))

from nyabo_mn.core import rules_engine, statements  # noqa: E402
from nyabo_mn.nyabo.seed import tax_parameter_quote  # noqa: E402
from nyabo_mn.setup import chart as chart_mod  # noqa: E402

SEED_DIR = REPO / "nyabo_mn" / "nyabo" / "seed"
V1_CHART_PATH = chart_mod.DEFAULT_CHART_PATH
EXPECTED_V1_LEAF_COUNT = 40

SEED_FILES = (
	"tax_parameters",
	"posting_patterns",
	"chart_v03",
	"aliases_v1_to_v03",
	"code_roles",
	"bank_layouts",
	"rules_default",
)

PARAMETER_UNITS = {"fraction", "MNT", "years", "schedule", "rule", "deadline"}
PARAMETER_STATUSES = {"active", "pending"}
COMPARATORS = {"lt", "lte", "gt", "gte"}
DEADLINE_PERIODS = {"monthly", "quarterly", "half_year", "annual"}
PARAMETER_KEYS = {
	"key",
	"value",
	"unit",
	"effective_from",
	"effective_to",
	"status",
	"verified",
	"source_text",
	"source_url",
	"article",
	"quote_mn",
	"note",
}
PATTERN_KEYS = {
	"pattern_id",
	"name_mn",
	"family",
	"document_types",
	"applies_to_vat",
	"applies_to_cit",
	"conditions",
	"lines",
	"primary_document_mn",
	"citation",
	"verified",
	"enabled",
	"reference_bullet",
	"notes",
}
LINE_KEYS = {
	"side",
	"account_class",
	"class_name_mn",
	"sub_account_mn",
	"role",
	"amount_kind",
	"optional",
	"alternatives",
	"v1_code_hint",
	"v1_code_range",
	"class_assumed",
}
# The vocabulary the engine actually matches on, read from it rather than retyped (F-12):
# the two selective values are the regime names.
APPLIES_TO_VAT = {rules_engine.ANY, rules_engine.VAT_STATUS_PAYER, rules_engine.VAT_STATUS_NON_VAT}
APPLIES_TO_CIT = {rules_engine.ANY, rules_engine.CIT_REGULAR, rules_engine.CIT_SIMPLIFIED}
DOCUMENT_TYPES = {"Purchase Invoice", "Sales Invoice", "Journal Entry", "Payment Entry", "Bank Transaction"}
BANKS = {"Khan Bank", "TDB", "Golomt Bank", "Trans Bank", "XacBank", "Other"}
RULE_MATCH_TYPES = {
	"supplier_register_no",
	"supplier_name_pattern",
	"description_pattern",
	"amount_band",
	"bank_fee",
}
RULE_STATUSES = {"active", "pending_confirmation", "disabled"}
VAT_TREATMENTS = {"withheld", "in_expense", "exempt", "zero", "none"}


class Report:
	"""Collects problems; the script exits 1 when any exist."""

	def __init__(self) -> None:
		self.problems: list[str] = []
		self.notes: list[str] = []

	def problem(self, where: str, text: str) -> None:
		self.problems.append(f"{where}: {text}")

	def note(self, text: str) -> None:
		self.notes.append(text)


def _load(seed_dir: Path, name: str, report: Report) -> Any:
	path = seed_dir / f"{name}.json"
	if not path.exists():
		report.problem(name, f"missing file {path}")
		return None
	try:
		with open(path, encoding="utf-8") as f:
			return json.load(f)
	except (OSError, ValueError) as exc:
		report.problem(name, f"invalid JSON: {exc}")
		return None


def _date(value: Any) -> dt.date | None:
	try:
		return rules_engine._parse_date(value)
	except (TypeError, ValueError):
		return None


# --- charts ------------------------------------------------------------------------------------


def check_charts(seed_dir: Path, report: Report) -> tuple[set[str], set[str], set[str]]:
	"""(v1 leaves, v03 leaves, v03 class codes). Both charts must load through the runtime loader."""
	v1_leaves: set[str] = set()
	v03_leaves: set[str] = set()
	v03_classes: set[str] = set()
	try:
		v1 = chart_mod.load_chart(V1_CHART_PATH)
		v1_leaves = v1.leaf_numbers()
		if len(v1_leaves) != EXPECTED_V1_LEAF_COUNT:
			report.problem("chart v1", f"expected {EXPECTED_V1_LEAF_COUNT} leaves, found {len(v1_leaves)}")
	except (chart_mod.ChartError, OSError, ValueError) as exc:
		report.problem("chart v1", str(exc))

	path = seed_dir / "chart_v03.json"
	if not path.exists():
		report.problem("chart_v03", f"missing file {path}")
		return v1_leaves, v03_leaves, v03_classes
	try:
		v03 = chart_mod.load_chart(path)
	except (chart_mod.ChartError, OSError, ValueError) as exc:
		report.problem("chart_v03", str(exc))
		return v1_leaves, v03_leaves, v03_classes
	for warning in v03.warnings:
		report.problem("chart_v03", f"loader warning: {warning}")
	v03_leaves = v03.leaf_numbers()
	for account in v03.accounts():
		if account.is_group and account.number:
			if not (len(account.number) == 2 and account.number.isdigit()):
				report.problem(
					"chart_v03", f"group {account.name!r} number {account.number!r} is not a 2-digit class"
				)
			v03_classes.add(account.number)
		elif not account.is_group:
			if not (len(account.number) == 4 and account.number.isdigit()):
				report.problem(
					"chart_v03", f"leaf {account.name!r} number {account.number!r} is not a 4-digit CCSS code"
				)
			elif account.number[:2] not in v03_classes and account.parent:
				# classes are yielded before their leaves; a leaf outside its class is a tree error
				report.problem("chart_v03", f"leaf {account.number} is not under class {account.number[:2]}")
	roots = [a for a in v03.accounts() if a.depth == 0]
	if {r.root_type for r in roots} != set(chart_mod.ROOT_TYPES):
		report.problem("chart_v03", "the five root types are not all present")
	return v1_leaves, v03_leaves, v03_classes


def check_aliases(seed_dir: Path, report: Report, v1_leaves: set[str], v03_leaves: set[str]) -> None:
	data = _load(seed_dir, "aliases_v1_to_v03", report)
	if not isinstance(data, dict):
		if data is not None:
			report.problem("aliases", "top level must be an object")
		return
	mapping = {k: v for k, v in data.items() if not k.startswith("_") and k != "unmapped"}
	unmapped = data.get("unmapped", [])
	if unmapped:
		report.problem("aliases", f"unmapped V1 codes: {unmapped}")
	for v1_code in sorted(v1_leaves):
		if v1_code not in mapping:
			report.problem("aliases", f"V1 leaf {v1_code} has no v0.3 alias")
	for v1_code, target in mapping.items():
		if v1_code not in v1_leaves:
			report.problem("aliases", f"{v1_code} is not a V1 leaf")
		if not isinstance(target, str) or target not in v03_leaves:
			report.problem("aliases", f"{v1_code} -> {target!r} is not a v0.3 leaf")


def check_code_roles(
	seed_dir: Path, report: Report, v1_leaves: set[str], v03_leaves: set[str]
) -> dict[str, Any]:
	data = _load(seed_dir, "code_roles", report)
	if not isinstance(data, dict):
		if data is not None:
			report.problem("code_roles", "top level must be an object")
		return {}
	required = data.get("required_roles") or []
	schemes = data.get("schemes") or {}
	descriptions = data.get("descriptions") or {}
	null_allowed = {k: set(v) for k, v in (data.get("null_allowed") or {}).items() if not k.startswith("_")}
	if set(schemes) != {"v1", "v03"}:
		report.problem("code_roles", f"schemes must be exactly v1 and v03, found {sorted(schemes)}")
	leaves_by_scheme = {"v1": v1_leaves, "v03": v03_leaves}
	for scheme, roles in schemes.items():
		leaves = leaves_by_scheme.get(scheme, set())
		for role in required:
			if role not in roles:
				report.problem("code_roles", f"{scheme}: required role {role!r} missing")
		for role, code in roles.items():
			if role not in descriptions:
				report.problem("code_roles", f"{scheme}: role {role!r} has no description")
			if code is None:
				if scheme == "v03":
					report.problem("code_roles", f"v03 (default scheme): role {role!r} is null")
				elif role not in null_allowed.get(scheme, set()):
					report.problem(
						"code_roles", f"{scheme}: role {role!r} is null but not listed in null_allowed"
					)
				continue
			if not isinstance(code, str) or code not in leaves:
				report.problem(
					"code_roles", f"{scheme}: role {role!r} -> {code!r} is not a leaf of that chart"
				)
		for role in null_allowed.get(scheme, set()):
			if roles.get(role) is not None:
				report.problem("code_roles", f"{scheme}: {role!r} listed in null_allowed but has a code")
	return data


# --- tax parameters --------------------------------------------------------------------------------


def check_tax_parameters(seed_dir: Path, report: Report) -> None:
	data = _load(seed_dir, "tax_parameters", report)
	if not isinstance(data, dict):
		if data is not None:
			report.problem("tax_parameters", "top level must be an object")
		return
	for key in ("schema_version", "horizon_start", "verified_means", "rows"):
		if key not in data:
			report.problem("tax_parameters", f"missing top-level key {key!r}")
	rows = data.get("rows") or []
	if not isinstance(rows, list):
		report.problem("tax_parameters", "rows must be a list")
		return
	parsed: list[rules_engine.ParameterRow] = []
	for index, row in enumerate(rows):
		where = f"tax_parameters[{index}] {row.get('key') if isinstance(row, dict) else '?'}"
		if not isinstance(row, dict):
			report.problem(where, "row must be an object")
			continue
		unknown = set(row) - PARAMETER_KEYS
		if unknown:
			report.problem(where, f"unknown keys {sorted(unknown)}")
		for key in ("key", "unit", "effective_from", "status", "verified", "source_text"):
			if key not in row:
				report.problem(where, f"missing {key!r}")
		if "value" not in row:
			report.problem(where, "missing 'value' (use null with status pending)")
		if row.get("unit") not in PARAMETER_UNITS:
			report.problem(where, f"unit {row.get('unit')!r} not in {sorted(PARAMETER_UNITS)}")
		if row.get("status") not in PARAMETER_STATUSES:
			report.problem(where, f"status {row.get('status')!r} not in {sorted(PARAMETER_STATUSES)}")
		if not isinstance(row.get("verified"), bool):
			report.problem(where, "verified must be true/false")
		start = _date(row.get("effective_from"))
		end = _date(row.get("effective_to"))
		if start is None:
			report.problem(where, f"effective_from {row.get('effective_from')!r} is not an ISO date")
		if row.get("effective_to") not in (None, "") and end is None:
			report.problem(where, f"effective_to {row.get('effective_to')!r} is not an ISO date")
		if start and end and end < start:
			report.problem(where, "effective_to before effective_from")
		value = row.get("value")
		status = row.get("status")
		if status == "pending" and value is not None:
			report.problem(where, "pending rows must have value null")
		if status == "active" and value is None:
			report.problem(where, "active rows must have a value (or be marked pending)")
		quote_mn = row.get("quote_mn")
		if quote_mn is not None and (not isinstance(quote_mn, str) or not quote_mn.strip()):
			report.problem(where, "quote_mn must be a non-empty string or absent")
		if row.get("verified") is True:
			if not row.get("source_url") or not row.get("article"):
				report.problem(where, "verified rows need source_url and article (see verified_means)")
			if not tax_parameter_quote(row):
				report.problem(
					where, "verified rows need the verbatim quote (quote_mn, or «…» — at the start of note)"
				)
			if status != "active":
				report.problem(where, "verified rows must be active")
		_check_parameter_value(where, row.get("unit"), value, report)
		try:
			parsed.append(rules_engine.ParameterRow.from_dict(row))
		except (ValueError, TypeError, KeyError) as exc:
			report.problem(where, f"rules_engine cannot load the row: {exc}")

	by_key: dict[str, list[rules_engine.ParameterRow]] = {}
	for prow in parsed:
		by_key.setdefault(prow.key, []).append(prow)
	for key, key_rows in by_key.items():
		ordered = sorted(key_rows, key=lambda r: r.effective_from)
		for earlier, later in zip(ordered, ordered[1:], strict=False):
			if earlier.effective_to is None or earlier.effective_to >= later.effective_from:
				report.problem(
					f"tax_parameters {key}",
					f"periods overlap: {earlier.effective_from}..{earlier.effective_to} and {later.effective_from}..{later.effective_to}",
				)
		for pending in (r for r in ordered if r.is_pending):
			report.note(
				f"tax_parameters {key}: pending from {pending.effective_from} (engine raises PendingRuleError there)"
			)


def _check_parameter_value(where: str, unit: Any, value: Any, report: Report) -> None:
	if value is None:
		return
	if unit == "fraction":
		if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
			report.problem(where, f"fraction value must be a number in 0..1, got {value!r}")
	elif unit == "MNT":
		if not isinstance(value, dict):
			report.problem(where, "MNT value must be an object {amount, comparator, basis}")
			return
		amount = value.get("amount")
		if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
			report.problem(where, f"MNT amount must be a positive integer, got {amount!r}")
		if value.get("comparator") not in COMPARATORS:
			report.problem(where, f"comparator {value.get('comparator')!r} not in {sorted(COMPARATORS)}")
		if not value.get("basis"):
			report.problem(where, "MNT value needs a basis")
	elif unit == "years":
		values = value.values() if isinstance(value, dict) else [value]
		for item in values:
			if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
				report.problem(where, f"years must be positive integers, got {item!r}")
	elif unit == "schedule":
		if (
			not isinstance(value, dict)
			or not isinstance(value.get("brackets"), list)
			or not value.get("basis")
		):
			report.problem(where, "schedule value must be {basis, brackets: [...]}")
			return
		brackets = value["brackets"]
		if not brackets or brackets[-1].get("up_to") is not None:
			report.problem(where, "the last bracket must have up_to null")
		for bracket in brackets:
			rate = bracket.get("rate")
			if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 <= rate <= 1:
				report.problem(where, f"bracket rate must be a fraction, got {rate!r}")
	elif unit == "deadline":
		if not isinstance(value, dict):
			report.problem(where, "deadline value must be an object")
			return
		if value.get("period") not in DEADLINE_PERIODS:
			report.problem(
				where, f"deadline period {value.get('period')!r} not in {sorted(DEADLINE_PERIODS)}"
			)
		for field in ("due_months_after_period_end", "due_day"):
			if field not in value:
				report.problem(where, f"deadline value needs {field!r} (null when not stated)")
			elif value[field] is not None and (
				isinstance(value[field], bool) or not isinstance(value[field], int)
			):
				report.problem(where, f"deadline {field} must be an integer or null")
	elif unit == "rule":
		if not isinstance(value, (dict, bool)):
			report.problem(where, "rule value must be an object or a boolean")


# --- posting patterns ------------------------------------------------------------------------------


def check_posting_patterns(
	seed_dir: Path, report: Report, v03_classes: set[str], code_roles: dict[str, Any], v1_leaves: set[str]
) -> set[str]:
	data = _load(seed_dir, "posting_patterns", report)
	if not isinstance(data, dict):
		if data is not None:
			report.problem("posting_patterns", "top level must be an object")
		return set()
	rows = data.get("rows") or []
	if not isinstance(rows, list) or not rows:
		report.problem("posting_patterns", "rows must be a non-empty list")
		return set()
	ids: set[str] = set()
	known_roles = set((code_roles.get("schemes") or {}).get("v03") or {})
	for index, row in enumerate(rows):
		where = f"posting_patterns[{index}] {row.get('pattern_id') if isinstance(row, dict) else '?'}"
		if not isinstance(row, dict):
			report.problem(where, "row must be an object")
			continue
		unknown = set(row) - PATTERN_KEYS
		if unknown:
			report.problem(where, f"unknown keys {sorted(unknown)}")
		pattern_id = row.get("pattern_id")
		if not pattern_id or not isinstance(pattern_id, str):
			report.problem(where, "pattern_id missing")
		elif pattern_id in ids:
			report.problem(where, f"duplicate pattern_id {pattern_id}")
		else:
			ids.add(pattern_id)
		for key in ("name_mn", "family", "document_types", "lines", "primary_document_mn", "citation"):
			if not row.get(key):
				report.problem(where, f"missing {key!r}")
		if row.get("applies_to_vat") not in APPLIES_TO_VAT:
			report.problem(
				where, f"applies_to_vat {row.get('applies_to_vat')!r} not in {sorted(APPLIES_TO_VAT)}"
			)
		if row.get("applies_to_cit") not in APPLIES_TO_CIT:
			report.problem(
				where, f"applies_to_cit {row.get('applies_to_cit')!r} not in {sorted(APPLIES_TO_CIT)}"
			)
		for doctype in row.get("document_types") or []:
			if doctype not in DOCUMENT_TYPES:
				report.problem(where, f"document type {doctype!r} not in {sorted(DOCUMENT_TYPES)}")
		citation = row.get("citation") or {}
		if not isinstance(citation, dict) or not citation.get("instrument"):
			report.problem(where, "citation needs an instrument")
		else:
			if citation.get("section") is None and (citation.get("verified") or row.get("verified")):
				report.problem(where, "verified without a citation section")
			if citation.get("verified") and not row.get("verified"):
				report.problem(where, "citation.verified and verified disagree")
		_check_pattern_lines(where, row.get("lines") or [], v03_classes, known_roles, v1_leaves, report)
		try:
			rules_engine.PatternSpec.from_dict(row)
		except (ValueError, TypeError, KeyError) as exc:
			report.problem(where, f"rules_engine cannot load the pattern: {exc}")
	return ids


def _check_pattern_lines(
	where: str,
	lines: list[Any],
	v03_classes: set[str],
	known_roles: set[str],
	v1_leaves: set[str],
	report: Report,
) -> None:
	if len(lines) < 2:
		report.problem(where, "a pattern needs at least two lines")
	sides = {line.get("side") for line in lines if isinstance(line, dict)}
	if not {"debit", "credit"} <= sides:
		report.problem(where, "a pattern needs a debit and a credit line")
	for number, line in enumerate(lines):
		lwhere = f"{where} line {number}"
		if not isinstance(line, dict):
			report.problem(lwhere, "line must be an object")
			continue
		unknown = set(line) - LINE_KEYS
		if unknown:
			report.problem(lwhere, f"unknown keys {sorted(unknown)}")
		if line.get("side") not in ("debit", "credit"):
			report.problem(lwhere, f"side {line.get('side')!r}")
		if not line.get("amount_kind"):
			report.problem(lwhere, "amount_kind missing")
		if line.get("account_class") not in v03_classes:
			report.problem(lwhere, f"account_class {line.get('account_class')!r} is not a v0.3 class")
		role = line.get("role")
		if role is not None and role not in known_roles:
			report.problem(lwhere, f"role {role!r} not in code_roles")
		if role is None and line.get("account_class") not in ("70", "71"):
			report.problem(
				lwhere, "a line without a role must be an expense class (70/71) resolved by classification"
			)
		hint = line.get("v1_code_hint")
		if hint is not None and hint not in v1_leaves:
			report.problem(lwhere, f"v1_code_hint {hint!r} is not a V1 leaf")
		for code in line.get("v1_code_range") or []:
			if code not in v1_leaves:
				report.problem(lwhere, f"v1_code_range code {code!r} is not a V1 leaf")
		for alternative in line.get("alternatives") or []:
			if not isinstance(alternative, dict):
				report.problem(lwhere, "alternative must be an object")
				continue
			if alternative.get("account_class") not in v03_classes:
				report.problem(
					lwhere, f"alternative class {alternative.get('account_class')!r} is not a v0.3 class"
				)
			alt_role = alternative.get("role")
			if alt_role is not None and alt_role not in known_roles:
				report.problem(lwhere, f"alternative role {alt_role!r} not in code_roles")
			if not alternative.get("when") or not alternative.get("when_mn"):
				report.problem(lwhere, "alternative needs when and when_mn")


# --- bank layouts and rules ------------------------------------------------------------------------


def check_bank_layouts(seed_dir: Path, report: Report) -> None:
	data = _load(seed_dir, "bank_layouts", report)
	if not isinstance(data, dict):
		if data is not None:
			report.problem("bank_layouts", "top level must be an object")
		return
	rows = data.get("rows") or []
	ids: set[str] = set()
	banks_seen: set[str] = set()
	for index, row in enumerate(rows):
		where = f"bank_layouts[{index}] {row.get('layout_id') if isinstance(row, dict) else '?'}"
		if not isinstance(row, dict):
			report.problem(where, "row must be an object")
			continue
		layout_id = row.get("layout_id")
		if not layout_id:
			report.problem(where, "layout_id missing")
		elif layout_id in ids:
			report.problem(where, f"duplicate layout_id {layout_id}")
		else:
			ids.add(layout_id)
		if row.get("bank") not in BANKS:
			report.problem(where, f"bank {row.get('bank')!r} not in {sorted(BANKS)}")
		banks_seen.add(str(row.get("bank")))
		if row.get("verified") is not False:
			report.problem(
				where, "seed layouts must ship with verified false (an admin verifies against a sample)"
			)
		if row.get("amount_style") not in statements.AMOUNT_STYLES:
			report.problem(where, f"amount_style {row.get('amount_style')!r}")
		if not row.get("date_formats"):
			report.problem(where, "date_formats missing")
		if row.get("header_signature") or row.get("column_map"):
			# A concrete layout must carry a sample it was verified against; none exists yet.
			report.problem(
				where, "column layout asserted without a sample export (never guess a bank's columns)"
			)
		if "keywords" in row:
			for role in row["keywords"]:
				if role not in statements.COLUMN_ROLES:
					report.problem(where, f"keyword role {role!r} not in {statements.COLUMN_ROLES}")
		try:
			statements.LayoutSpec.from_dict(row)
		except (ValueError, TypeError, KeyError) as exc:
			report.problem(where, f"statements cannot load the layout: {exc}")
	for bank in sorted(BANKS - {"Other"}):
		if bank not in banks_seen:
			report.problem("bank_layouts", f"no placeholder for {bank}")
	if "generic_mn" not in ids:
		report.problem("bank_layouts", "generic_mn keyword fallback missing")


def check_rules_default(
	seed_dir: Path, report: Report, pattern_ids: set[str], v1_leaves: set[str], v03_leaves: set[str]
) -> None:
	data = _load(seed_dir, "rules_default", report)
	if not isinstance(data, dict):
		if data is not None:
			report.problem("rules_default", "top level must be an object")
		return
	leaves_by_scheme = {"v1": v1_leaves, "v03": v03_leaves}
	ids: set[str] = set()
	for index, row in enumerate(data.get("rows") or []):
		where = f"rules_default[{index}] {row.get('rule_id') if isinstance(row, dict) else '?'}"
		if not isinstance(row, dict):
			report.problem(where, "row must be an object")
			continue
		rule_id = row.get("rule_id")
		if not rule_id:
			report.problem(where, "rule_id missing")
		elif rule_id in ids:
			report.problem(where, f"duplicate rule_id {rule_id}")
		else:
			ids.add(rule_id)
		scheme = row.get("scheme")
		if scheme not in leaves_by_scheme:
			report.problem(where, f"scheme {scheme!r} must be v1 or v03")
		elif row.get("target_account_code") not in leaves_by_scheme[scheme]:
			report.problem(
				where, f"target_account_code {row.get('target_account_code')!r} is not a {scheme} leaf"
			)
		if row.get("match_type") not in RULE_MATCH_TYPES:
			report.problem(where, f"match_type {row.get('match_type')!r}")
		if row.get("status") not in RULE_STATUSES:
			report.problem(where, f"status {row.get('status')!r}")
		if row.get("vat_treatment") not in VAT_TREATMENTS:
			report.problem(where, f"vat_treatment {row.get('vat_treatment')!r}")
		if row.get("source") != "seed":
			report.problem(where, "seed rules must have source 'seed'")
		if row.get("posting_pattern") and row["posting_pattern"] not in pattern_ids:
			report.problem(where, f"posting_pattern {row['posting_pattern']!r} does not exist")


# --- entry point -------------------------------------------------------------------------------------


def run(seed_dir: Path | str = SEED_DIR) -> Report:
	"""Check every seed file; the returned Report lists problems (empty = fine) and notes."""
	seed_dir = Path(seed_dir)
	report = Report()
	for name in SEED_FILES:
		_load(seed_dir, name, report)
	v1_leaves, v03_leaves, v03_classes = check_charts(seed_dir, report)
	check_aliases(seed_dir, report, v1_leaves, v03_leaves)
	code_roles = check_code_roles(seed_dir, report, v1_leaves, v03_leaves)
	check_tax_parameters(seed_dir, report)
	pattern_ids = check_posting_patterns(seed_dir, report, v03_classes, code_roles, v1_leaves)
	check_bank_layouts(seed_dir, report)
	check_rules_default(seed_dir, report, pattern_ids, v1_leaves, v03_leaves)
	return report


def main(argv: list[str] | None = None) -> int:
	args = sys.argv[1:] if argv is None else argv
	seed_dir = Path(args[0]) if args else SEED_DIR
	# Problems quote Mongolian account names; a cp1252 console must not turn that into a crash.
	reconfigure = getattr(sys.stdout, "reconfigure", None)
	if reconfigure is not None:
		reconfigure(encoding="utf-8", errors="replace")
	report = run(seed_dir)
	for note in report.notes:
		print(f"note: {note}")
	if report.problems:
		print(f"{len(report.problems)} problem(s) in {seed_dir}:")
		for problem in report.problems:
			print(f"- {problem}")
		return 1
	print(f"seed ok: {seed_dir}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
