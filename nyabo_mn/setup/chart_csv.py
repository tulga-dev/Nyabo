"""The accountant's own chart of accounts from a CSV (code, name, parent_code, root_type, account_type).

Pure Python: the rows become the same ERPNext tree shape `setup.chart` normalises, so
the accountant's chart installs through the one `create_charts` path. Rows without a
`parent_code` are roots and must carry a `root_type`; every row that is named as a
parent becomes a group. Account categories are not guessed from the accountant's
codes: a leaf inherits the category of the v0.3 template account it matches by name,
because a wrong category misplaces the account on the Balance Sheet.

`match_template` pairs the accountant's leaves with the v0.3 template by normalised
name so provisioning can create the Nyabo Account Alias rows automatically and report
what did not match (the accountant fills those in the desk).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.setup import chart as chart_mod
from nyabo_mn.setup.chart import ROOT_TYPES, ChartError, NormalizedChart

COLUMNS: tuple[str, ...] = ("code", "name", "parent_code", "root_type", "account_type")
COLUMN_ALIASES: dict[str, str] = {
	"code": "code",
	"account_number": "code",
	"код": "code",
	"дугаар": "code",
	"name": "name",
	"account_name": "name",
	"нэр": "name",
	"дансны нэр": "name",
	"parent_code": "parent_code",
	"parent": "parent_code",
	"эцэг": "parent_code",
	"эцэг код": "parent_code",
	"root_type": "root_type",
	"төрөл": "root_type",
	"account_type": "account_type",
	"дансны төрөл": "account_type",
}
CHART_NAME = mn.CHART_CSV_NAME
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(frozen=True)
class CsvAccount:
	code: str
	name: str
	parent_code: str | None
	root_type: str | None
	account_type: str | None


@dataclass
class TemplateMatch:
	"""Template code -> accountant code for the leaves whose names match, plus the leftovers."""

	aliases: dict[str, str] = field(default_factory=dict)
	unmatched_template: list[str] = field(default_factory=list)
	unmatched_chart: list[str] = field(default_factory=list)


def normalize_name(text: Any) -> str:
	"""Case-, accent- and punctuation-insensitive key for matching account names."""
	value = unicodedata.normalize("NFKC", str(text or "")).casefold()
	value = _NON_WORD.sub(" ", value)
	return " ".join(value.split())


def read_rows(source: str | Path | Iterable[Any]) -> list[CsvAccount]:
	"""Rows from a CSV path/text, a list of dicts, or a list of lists with a header row."""
	if isinstance(source, (str, Path)):
		path = Path(source)
		text = path.read_text(encoding="utf-8-sig") if path.exists() else str(source)
		reader = csv.reader(io.StringIO(text))
		return _from_lists(list(reader))
	items = list(source)
	if not items:
		raise ChartError(mn.MSG_CHART_CSV_COLUMNS)
	if isinstance(items[0], Mapping):
		return [_account_from_mapping(_canonical_keys(row)) for row in items if _has_values(row)]
	return _from_lists(items)


def _has_values(row: Mapping[str, Any]) -> bool:
	return any(str(v or "").strip() for v in row.values())


def _canonical_keys(row: Mapping[str, Any]) -> dict[str, Any]:
	out: dict[str, Any] = {}
	for key, value in row.items():
		canonical = COLUMN_ALIASES.get(normalize_name(key))
		if canonical:
			out[canonical] = value
	if "code" not in out or "name" not in out:
		raise ChartError(mn.MSG_CHART_CSV_COLUMNS)
	return out


def _from_lists(rows: Sequence[Sequence[Any]]) -> list[CsvAccount]:
	if not rows:
		raise ChartError(mn.MSG_CHART_CSV_COLUMNS)
	header = [COLUMN_ALIASES.get(normalize_name(cell)) for cell in rows[0]]
	if "code" not in header or "name" not in header:
		raise ChartError(mn.MSG_CHART_CSV_COLUMNS)
	out: list[CsvAccount] = []
	for row in rows[1:]:
		if not any(str(cell or "").strip() for cell in row):
			continue
		mapping = {key: row[i] if i < len(row) else None for i, key in enumerate(header) if key}
		out.append(_account_from_mapping(mapping))
	return out


def _clean(value: Any) -> str | None:
	text = str(value or "").strip()
	return text or None


def _account_from_mapping(row: Mapping[str, Any]) -> CsvAccount:
	code = _clean(row.get("code"))
	name = _clean(row.get("name"))
	if not code or not name:
		raise ChartError(mn.MSG_CHART_CSV_COLUMNS)
	return CsvAccount(
		code=code,
		name=name,
		parent_code=_clean(row.get("parent_code")),
		root_type=_clean(row.get("root_type")),
		account_type=_clean(row.get("account_type")),
	)


def build_tree(accounts: Sequence[CsvAccount]) -> dict[str, Any]:
	"""ERPNext tree ({name: {account_number, ..., children}}) from flat rows."""
	by_code = {a.code: a for a in accounts}
	children: dict[str | None, list[CsvAccount]] = {}
	for account in accounts:
		if account.parent_code and account.parent_code not in by_code:
			raise ChartError(
				mn.MSG_CHART_CSV_PARENT_MISSING.format(code=account.code, parent=account.parent_code)
			)
		children.setdefault(account.parent_code, []).append(account)
	roots = children.get(None, [])
	if not roots:
		raise ChartError(mn.MSG_CHART_CSV_COLUMNS)

	def node(account: CsvAccount, is_root: bool) -> dict[str, Any]:
		out: dict[str, Any] = {"account_number": account.code}
		if is_root:
			if account.root_type not in ROOT_TYPES:
				raise ChartError(
					mn.MSG_CHART_CSV_ROOT_TYPE.format(code=account.code, root_type=account.root_type)
				)
			out["root_type"] = account.root_type
		if account.account_type:
			out["account_type"] = account.account_type
		for child in children.get(account.code, []):
			out[child.name] = node(child, False)
		return out

	return {root.name: node(root, True) for root in roots}


def load_csv_chart(source: str | Path | Iterable[Any], currency: str = "MNT") -> NormalizedChart:
	"""Parse, normalise and validate the accountant's chart; categories are dropped (see module doc)."""
	raw = {"name": CHART_NAME, "country_code": "mn", "tree": build_tree(read_rows(source))}
	chart = chart_mod.normalize(raw, currency=currency)
	_strip_categories(chart.tree)
	errors = chart_mod.validate(chart)
	if errors:
		raise ChartError("chart is not valid:\n- " + "\n- ".join(errors))
	return chart


def _strip_categories(tree: dict[str, Any]) -> None:
	for key, value in list(tree.items()):
		if key == "account_category":
			del tree[key]
		elif key not in chart_mod.METADATA_KEYS and isinstance(value, dict):
			_strip_categories(value)


def match_template(chart: NormalizedChart, template: NormalizedChart | None = None) -> TemplateMatch:
	"""Pair the accountant's leaves with the v0.3 template leaves by normalised name.

	The same code in both charts also counts as a match when the names differ, because
	an accountant who kept the Заавар 116 numbering did so on purpose.
	"""
	if template is None:
		from nyabo_mn.nyabo.seed import seed_path

		template = chart_mod.load_chart(seed_path("chart_v03"))
	chart_leaves = {a.number: a for a in chart.accounts() if a.number and not a.is_group}
	template_leaves = {a.number: a for a in template.accounts() if a.number and not a.is_group}
	by_name: dict[str, list[str]] = {}
	for code, account in chart_leaves.items():
		by_name.setdefault(normalize_name(account.name), []).append(code)
	result = TemplateMatch()
	used: set[str] = set()
	for t_code, t_account in template_leaves.items():
		candidates = [c for c in by_name.get(normalize_name(t_account.name), []) if c not in used]
		target = (
			candidates[0]
			if candidates
			else (t_code if t_code in chart_leaves and t_code not in used else None)
		)
		if target is None:
			result.unmatched_template.append(t_code)
			continue
		used.add(target)
		result.aliases[t_code] = target
	result.unmatched_chart = sorted(c for c in chart_leaves if c not in used)
	return result


def apply_template_categories(
	chart: NormalizedChart, template: NormalizedChart, match: TemplateMatch
) -> None:
	"""Copy account_category from the matched template leaf so financial statements group correctly."""
	template_categories = {code: category for code, category in _leaf_categories(template.tree) if code}
	by_target = {target: template_categories.get(t_code) for t_code, target in match.aliases.items()}
	_set_categories(chart.tree, by_target)


def _leaf_categories(tree: dict[str, Any]) -> Iterable[tuple[str, str | None]]:
	for key, node in tree.items():
		if key in chart_mod.METADATA_KEYS or not isinstance(node, dict):
			continue
		has_children = any(k not in chart_mod.METADATA_KEYS and isinstance(v, dict) for k, v in node.items())
		if has_children:
			yield from _leaf_categories(node)
		else:
			yield str(node.get("account_number") or ""), node.get("account_category")


def _set_categories(tree: dict[str, Any], by_code: Mapping[str, str | None]) -> None:
	for key, node in tree.items():
		if key in chart_mod.METADATA_KEYS or not isinstance(node, dict):
			continue
		code = str(node.get("account_number") or "")
		category = by_code.get(code)
		if category and not node.get("is_group"):
			node["account_category"] = category
		_set_categories(node, by_code)
