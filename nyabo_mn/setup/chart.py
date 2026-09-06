"""Chart of accounts loader for the Mongolian SME draft chart.

Pure Python on purpose: importable without Frappe so the tree can be unit-tested
(see tests/test_chart.py). Everything that touches the database lives in chart_db.py.

The source file (setup/data/mn_sme_coa.json) is the founder's draft in ERPNext tree
format. It is meant to be replaced by the official Ministry of Finance list later, so
this module never hard-codes account names: pipeline code addresses accounts by V1
code (e.g. "6210") through chart_db.account_for_code().

What normalisation does to the raw tree before handing it to ERPNext's create_charts():
- strips documentation keys (anything starting with "_"); ERPNext would otherwise treat
  "_comment" as a child account and crash;
- drops account numbers that are not plain digits (the draft uses ranges like
  "1100-1800" on two groups; ERPNext would put that string into the account name);
- sets is_group explicitly, sets account_currency, and applies two small overlays
  (tax_rate on the VAT accounts, account_category for ERPNext v16 financial statements).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_CHART_PATH = DATA_DIR / "mn_sme_coa.json"

# Keys ERPNext's create_charts() treats as metadata, not child accounts. Source:
# erpnext/accounts/doctype/account/chart_of_accounts/chart_of_accounts.py (get_chart_metadata_fields).
METADATA_KEYS = frozenset(
	{
		"account_name",
		"account_number",
		"account_type",
		"account_category",
		"root_type",
		"is_group",
		"tax_rate",
		"account_currency",
	}
)
ROOT_TYPES = frozenset({"Asset", "Liability", "Equity", "Income", "Expense"})
BALANCE_SHEET_ROOT_TYPES = frozenset({"Asset", "Liability", "Equity"})

_PLAIN_NUMBER = re.compile(r"^[0-9]+$")

# Account.tax_rate is informational in ERPNext (default rate shown on tax rows). Keyed by V1 code.
TAX_RATE_BY_CODE: dict[str, float] = {"2210": 10.0, "1810": 10.0}

# ERPNext v16 groups accounts into financial statements by Account Category. The draft chart
# has none, so we assign them by code. chart_db drops any category that does not exist on the
# site, so this overlay is safe on older ERPNext versions too.
ACCOUNT_CATEGORY_BY_CODE: dict[str, str] = {
	"1110": "Cash and Cash Equivalents",
	"1120": "Cash and Cash Equivalents",
	"1310": "Trade Receivables",
	"1410": "Stock Assets",
	"1810": "Other Current Assets",
	"1510": "Tangible Assets",
	"1519": "Tangible Assets",
	"1530": "Tangible Assets",
	"2110": "Trade Payables",
	"2120": "Other Payables",
	"2210": "Current Tax Liabilities",
	"2220": "Current Tax Liabilities",
	"2310": "Other Current Liabilities",
	"3110": "Share Capital",
	"3120": "Reserves and Surplus",
	"3210": "Reserves and Surplus",
	"4110": "Revenue from Operations",
	"4120": "Revenue from Operations",
	"5110": "Cost of Goods Sold",
	"5120": "Other Direct Costs",
	"5130": "Other Direct Costs",
	"6810": "Finance Costs",
	"6930": "Finance Costs",
	"9110": "Tax Expense",
}
DEFAULT_EXPENSE_CATEGORY = "Operating Expenses"


class ChartError(ValueError):
	"""Raised when the chart file cannot be turned into a valid ERPNext tree."""


@dataclass(frozen=True)
class ChartAccount:
	name: str
	number: str
	root_type: str
	account_type: str | None
	is_group: bool
	parent: str | None
	depth: int

	@property
	def report_type(self) -> str:
		return "Balance Sheet" if self.root_type in BALANCE_SHEET_ROOT_TYPES else "Profit and Loss"


@dataclass
class NormalizedChart:
	name: str
	country_code: str
	tree: dict[str, Any]
	warnings: list[str] = field(default_factory=list)

	def accounts(self) -> list[ChartAccount]:
		return list(iter_accounts(self.tree))

	def by_number(self) -> dict[str, ChartAccount]:
		return {a.number: a for a in self.accounts() if a.number}

	def leaf_numbers(self) -> set[str]:
		return {a.number for a in self.accounts() if a.number and not a.is_group}


def load_raw(path: Path | str = DEFAULT_CHART_PATH) -> dict[str, Any]:
	with open(path, encoding="utf-8") as f:
		raw = json.load(f)
	if not isinstance(raw, dict) or "tree" not in raw:
		raise ChartError(f"{path}: expected an object with a 'tree' key")
	return raw


def normalize(raw: dict[str, Any], currency: str = "MNT") -> NormalizedChart:
	warnings: list[str] = []
	tree: dict[str, Any] = {}
	for root_name, root_node in raw["tree"].items():
		if root_name.startswith("_"):
			continue
		if not isinstance(root_node, dict):
			raise ChartError(f"tree/{root_name}: root must be an object")
		tree[root_name] = _normalize_node(root_node, True, warnings, currency, root_name)
	return NormalizedChart(
		name=str(raw.get("name", "")),
		country_code=str(raw.get("country_code", "")),
		tree=tree,
		warnings=warnings,
	)


def _normalize_node(
	node: dict[str, Any], is_root: bool, warnings: list[str], currency: str, path: str
) -> dict[str, Any]:
	out: dict[str, Any] = {}
	children: dict[str, dict[str, Any]] = {}
	for key, value in node.items():
		if key.startswith("_"):
			continue
		if key in METADATA_KEYS:
			out[key] = value
		elif isinstance(value, dict):
			children[key] = value
		else:
			raise ChartError(f"{path}: unexpected key {key!r} (value {value!r})")

	number = str(out.get("account_number") or "").strip()
	if number and not _PLAIN_NUMBER.match(number):
		warnings.append(
			f"{path}: account_number {number!r} is not a plain code; dropped so ERPNext does not put it in the name"
		)
		number = ""
	out["account_number"] = number

	if is_root:
		if out.get("root_type") not in ROOT_TYPES:
			raise ChartError(f"{path}: root account needs root_type in {sorted(ROOT_TYPES)}")
	elif "root_type" in out:
		raise ChartError(f"{path}: root_type is only allowed on root accounts")

	out["is_group"] = 1 if children else 0
	out["account_currency"] = currency
	if number in TAX_RATE_BY_CODE:
		out["tax_rate"] = TAX_RATE_BY_CODE[number]
	if not children and number:
		category = _category_for(number)
		if category:
			out.setdefault("account_category", category)

	for child_name, child_node in children.items():
		out[child_name] = _normalize_node(child_node, False, warnings, currency, f"{path}/{child_name}")
	return out


def _category_for(number: str) -> str | None:
	if number in ACCOUNT_CATEGORY_BY_CODE:
		return ACCOUNT_CATEGORY_BY_CODE[number]
	if number.startswith("6"):
		return DEFAULT_EXPENSE_CATEGORY
	return None


def iter_accounts(
	tree: dict[str, Any], parent: str | None = None, root_type: str | None = None, depth: int = 0
) -> Iterator[ChartAccount]:
	for name, node in tree.items():
		if name in METADATA_KEYS or not isinstance(node, dict):
			continue
		this_root_type = node.get("root_type") if depth == 0 else root_type
		account = ChartAccount(
			name=name,
			number=str(node.get("account_number") or ""),
			root_type=str(this_root_type or ""),
			account_type=node.get("account_type") or None,
			is_group=bool(node.get("is_group")),
			parent=parent,
			depth=depth,
		)
		yield account
		yield from iter_accounts(node, parent=name, root_type=this_root_type, depth=depth + 1)


def validate(chart: NormalizedChart) -> list[str]:
	"""Return a list of problems (empty when the chart is fine)."""
	errors: list[str] = []
	seen_numbers: dict[str, str] = {}
	seen_names: dict[str, int] = {}
	for account in chart.accounts():
		seen_names[account.name] = seen_names.get(account.name, 0) + 1
		if account.number:
			if account.number in seen_numbers:
				errors.append(
					f"duplicate account_number {account.number}: {seen_numbers[account.number]!r} and {account.name!r}"
				)
			seen_numbers[account.number] = account.name
		elif not account.is_group:
			errors.append(
				f"leaf account {account.name!r} has no account_number; Nyabo addresses accounts by code"
			)
		if account.depth == 0 and not account.is_group:
			errors.append(f"root account {account.name!r} must be a group")
		if account.root_type not in ROOT_TYPES:
			errors.append(f"account {account.name!r} has no root_type")
	for name, count in seen_names.items():
		if count > 1:
			errors.append(f"account name {name!r} appears {count} times (ERPNext would suffix it)")
	return errors


def load_chart(path: Path | str = DEFAULT_CHART_PATH, currency: str = "MNT") -> NormalizedChart:
	chart = normalize(load_raw(path), currency=currency)
	errors = validate(chart)
	if errors:
		raise ChartError("chart is not valid:\n- " + "\n- ".join(errors))
	return chart


def vat_defaults(raw: dict[str, Any]) -> dict[str, list[str]]:
	"""V1 VAT flags per account code: {'output_vat_10': [...], 'input_vat_10': [...], 'exempt': [...]}."""
	vat = raw.get("vat") or {}
	defaults = vat.get("account_defaults_from_v1") or {}
	return {k: [str(c) for c in v] for k, v in defaults.items() if not k.startswith("_")}
