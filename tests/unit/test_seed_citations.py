"""The verified gate: a seed row may say `verified: true` only with a legal citation behind it.

`rules.guard.require_verified` lets a verified Tax Parameter or Posting Pattern drive a real
posting, so a verified row without an article, a URL and the verbatim sentence it was read
from would be a silent hole in the product's legal footing. These tests pin the contract:
every verified row cites a primary-text page, an article/section and a quote; every quote is
reproduced in docs/legal/*.md (the human-readable side the accountant and the ministry
reviewer get); Order 116 sections come from the instrument's own numbering; unverified
rows say why. Nothing here reads the research scratchpad — the seed and docs/legal must
stand on their own.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nyabo_mn.nyabo.seed import load_seed

REPO = Path(__file__).resolve().parents[2]
LEGAL_DIR = REPO / "docs" / "legal"
ORDER116_URL = "https://legalinfo.mn/mn/detail?lawId=205201"
PRIMARY_HOSTS = ("https://legalinfo.mn/", "https://www.parliament.mn/")
QUOTE_RE = re.compile(r"^«(.+?)» — ", re.S)

# Section labels Order 116 (2000) itself carries, as tabulated in docs/legal/order116.md.
# A verified pattern may only cite these (composites are joined with "; ").
ORDER116_SECTIONS = {
	"1.1",
	"1.2",
	"1.4",
	"3.3",
	"3.4.1 а)",
	"3.4.1 б)",
	"3.4.1 в)",
	"3.4.1 г)",
	"3.4.1 д)",
	"3.4.1 ж)",
	"3.4.1 з)",
	"3.4.1 и)",
	"4.4",
	"4.7",
	"4.8.5",
	"4.8.6",
	"4.8.7",
	"5.1",
	"5.4",
	"6.2",
	"6.6",
	"6.9 А",
	"6.9 В",
	"6.9 Г",
	"9.4.1.1",
	"9.4.1.2",
	"10.7",
	"11.1",
	"11.2.1",
	"11.2.2",
	"12.2.1",
	"12.2.2 А",
	"12.2.2 Б",
	"12.2.3",
	"12.2.4",
	"12.2.5",
	"15.1",
	"15.2",
	"15.3",
}
LEGAL_FILES = (
	"README.md",
	"order116.md",
	"accounting_law.md",
	"vat_law.md",
	"cit_law.md",
	"pit_law.md",
	"social_insurance_law.md",
	"property_tax_law.md",
	"general_taxation_law.md",
	"tax_package_2026.md",
)


def _norm(text: str) -> str:
	return re.sub(r"\s+", " ", text).strip()


def _quote_of(row: dict) -> str | None:
	match = QUOTE_RE.match(row["note"])
	return _norm(match.group(1)) if match else None


@pytest.fixture(scope="module")
def legal_docs() -> str:
	return _norm(" ".join((LEGAL_DIR / name).read_text(encoding="utf-8") for name in LEGAL_FILES))


@pytest.fixture(scope="module")
def order116_doc() -> str:
	return _norm((LEGAL_DIR / "order116.md").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tax_rows() -> list[dict]:
	return load_seed("tax_parameters")["rows"]


@pytest.fixture(scope="module")
def pattern_rows() -> list[dict]:
	return load_seed("posting_patterns")["rows"]


def test_legal_docs_exist_and_are_indexed():
	readme = (LEGAL_DIR / "README.md").read_text(encoding="utf-8")
	for name in LEGAL_FILES:
		assert (LEGAL_DIR / name).exists(), name
		if name != "README.md":
			assert f"({name})" in readme, f"{name} not linked from docs/legal/README.md"


# --- tax parameters ---------------------------------------------------------------------------------


def test_verified_tax_parameters_cite_article_url_and_quote(tax_rows, legal_docs):
	verified = [r for r in tax_rows if r["verified"]]
	assert verified
	for row in verified:
		where = f"{row['key']}:{row['effective_from']}"
		assert row["status"] == "active", where
		assert row["article"], where
		assert row["source_url"] and row["source_url"].startswith(PRIMARY_HOSTS), where
		assert row["source_text"], where
		quote = _quote_of(row)
		assert quote and len(quote) >= 20, f"{where}: verified without a verbatim quote"
		assert quote in legal_docs, f"{where}: quote not reproduced in docs/legal"


def test_verified_tax_parameter_quotes_state_the_value(tax_rows):
	"""A quote must carry a number (or a printed word for it) — a bare heading is not a source."""
	for row in (r for r in tax_rows if r["verified"]):
		quote = _quote_of(row) or ""
		assert re.search(r"\d", quote), f"{row['key']}: quote has no figure"


def test_unverified_and_pending_tax_parameters_explain_themselves(tax_rows):
	for row in tax_rows:
		where = f"{row['key']}:{row['effective_from']}"
		if row["status"] == "pending":
			assert row["value"] is None and row["verified"] is False, where
			assert "INTENTIONALLY NULL" in row["note"], where
		if not row["verified"]:
			assert len(row["note"]) >= 40, f"{where}: unverified without a reason"


def test_derived_values_are_never_verified(tax_rows):
	"""Sums of printed rows and draft-law figures stay unverified (docs/legal/README.md, method)."""
	for row in tax_rows:
		note = row["note"]
		if "DERIVED" in note or "UNCONFIRMED" in note.split(" — ", 1)[-1][:120]:
			assert row["verified"] is False, row["key"]


# --- posting patterns -------------------------------------------------------------------------------


def test_pattern_verified_flags_agree(pattern_rows):
	for row in pattern_rows:
		assert row["citation"]["verified"] is row["verified"], row["pattern_id"]
		assert row["citation"]["instrument"] == "Заавар 116 (2000)", row["pattern_id"]
		assert row["citation"]["url"] == ORDER116_URL, row["pattern_id"]


def test_verified_patterns_cite_an_order116_section_with_a_quote(pattern_rows, order116_doc):
	verified = [r for r in pattern_rows if r["verified"]]
	assert len(verified) >= 20, "the mapping pass verified most of the instrument's entries"
	for row in verified:
		pid = row["pattern_id"]
		citation = row["citation"]
		assert citation["section"], f"{pid}: verified without a section"
		for label in citation["section"].split(";"):
			assert label.strip() in ORDER116_SECTIONS, (
				f"{pid}: {label.strip()!r} is not a section of Order 116"
			)
		quote = citation["quote"]
		assert quote and "Дт" in quote and "Кт" in quote, f"{pid}: quote is not a printed entry"
		assert _norm(quote) in order116_doc, f"{pid}: quote not reproduced in docs/legal/order116.md"
		assert f"`{pid}`" in order116_doc, f"{pid}: not tabulated in docs/legal/order116.md"


def test_unverified_patterns_have_no_section_and_name_their_candidates(pattern_rows):
	for row in (r for r in pattern_rows if not r["verified"]):
		pid = row["pattern_id"]
		assert row["citation"]["section"] is None and row["citation"]["quote"] is None, pid
		assert re.search(r"Citation:|Not prescribed by Order 116", row["notes"]), pid


def test_patterns_the_instrument_does_not_prescribe_stay_unverified(pattern_rows):
	by_id = {r["pattern_id"]: r for r in pattern_rows}
	for pid in ("customer_prepayment_recognize_vat_payer", "customer_prepayment_recognize_non_vat"):
		assert by_id[pid]["verified"] is False and "Not prescribed by Order 116" in by_id[pid]["notes"], pid
	# readings rated only "probable" (composites by extension) and reader disagreements
	for pid in ("purchase_expense_vat_payer", "purchase_expense_non_vat", "income_tax_accrue"):
		assert by_id[pid]["verified"] is False, pid
