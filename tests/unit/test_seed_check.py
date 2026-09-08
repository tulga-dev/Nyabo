"""scripts/seed_check.py must pass on the shipped seed and fail on a broken copy."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seed_check.py"
SEED_DIR = REPO / "nyabo_mn" / "nyabo" / "seed"


def _load_module():
	spec = importlib.util.spec_from_file_location("seed_check", SCRIPT)
	module = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(module)
	return module


@pytest.fixture(scope="module")
def seed_check():
	return _load_module()


@pytest.fixture
def seed_copy(tmp_path: Path) -> Path:
	target = tmp_path / "seed"
	shutil.copytree(SEED_DIR, target, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
	return target


def _edit(seed_dir: Path, name: str, mutate) -> None:
	path = seed_dir / f"{name}.json"
	data = json.loads(path.read_text(encoding="utf-8"))
	mutate(data)
	path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def test_shipped_seed_has_no_problems(seed_check):
	report = seed_check.run(SEED_DIR)
	assert report.problems == []
	assert any("pending" in note for note in report.notes)


def test_script_exit_codes(seed_copy: Path):
	ok = subprocess.run(
		[sys.executable, str(SCRIPT)], capture_output=True, text=True, encoding="utf-8", cwd=REPO
	)
	assert ok.returncode == 0, ok.stdout + ok.stderr
	assert "seed ok" in ok.stdout
	_edit(seed_copy, "aliases_v1_to_v03", lambda d: d.pop("6210"))
	bad = subprocess.run(
		[sys.executable, str(SCRIPT), str(seed_copy)],
		capture_output=True,
		text=True,
		encoding="utf-8",
		cwd=REPO,
	)
	assert bad.returncode == 1
	assert "6210 has no v0.3 alias" in bad.stdout


def test_invalid_json_is_a_problem(seed_check, seed_copy: Path):
	(seed_copy / "rules_default.json").write_text("{not json", encoding="utf-8")
	problems = seed_check.run(seed_copy).problems
	assert any("rules_default" in p and "invalid JSON" in p for p in problems)


def test_missing_file_is_a_problem(seed_check, seed_copy: Path):
	(seed_copy / "bank_layouts.json").unlink()
	problems = seed_check.run(seed_copy).problems
	assert any("bank_layouts" in p and "missing file" in p for p in problems)


def test_duplicate_pattern_id_and_bad_class(seed_check, seed_copy: Path):
	def mutate(d):
		d["rows"][1]["pattern_id"] = d["rows"][0]["pattern_id"]
		d["rows"][2]["lines"][0]["account_class"] = "99"
		d["rows"][3]["lines"][0]["role"] = "no_such_role"
		d["rows"][4]["applies_to_vat"] = "maybe"

	_edit(seed_copy, "posting_patterns", mutate)
	problems = seed_check.run(seed_copy).problems
	assert any("duplicate pattern_id" in p for p in problems)
	assert any("'99' is not a v0.3 class" in p for p in problems)
	assert any("'no_such_role' not in code_roles" in p for p in problems)
	assert any("applies_to_vat 'maybe'" in p for p in problems)


def test_verified_pattern_without_section_is_refused(seed_check, seed_copy: Path):
	def mutate(d):
		row = d["rows"][0]
		row["verified"] = True
		row["citation"]["section"] = None

	_edit(seed_copy, "posting_patterns", mutate)
	problems = seed_check.run(seed_copy).problems
	assert any("verified without a citation section" in p for p in problems)


def test_overlapping_and_malformed_tax_parameters(seed_check, seed_copy: Path):
	def mutate(d):
		rows = d["rows"]
		threshold = [r for r in rows if r["key"] == "vat.registration_threshold"]
		threshold[0]["effective_to"] = "2027-03-31"  # overlaps the 2027 row
		rate = next(r for r in rows if r["key"] == "vat.rate")
		rate.update({"verified": True, "source_url": None, "article": None})  # verified without provenance
		pending = next(r for r in rows if r["status"] == "pending")
		pending["value"] = {"x": 1}
		rows.append(
			{
				"key": "bogus.fraction",
				"value": 12,
				"unit": "fraction",
				"effective_from": "2026-01-01",
				"effective_to": None,
				"status": "active",
				"verified": False,
				"source_text": "x",
				"source_url": None,
				"article": None,
				"note": "",
				"surprise": 1,
			}
		)

	_edit(seed_copy, "tax_parameters", mutate)
	problems = seed_check.run(seed_copy).problems
	assert any("vat.registration_threshold" in p and "periods overlap" in p for p in problems)
	assert any("vat.rate" in p and "verified rows need source_url and article" in p for p in problems)
	assert any("pending rows must have value null" in p for p in problems)
	assert any("fraction value must be a number in 0..1" in p for p in problems)
	assert any("unknown keys ['surprise']" in p for p in problems)


def test_chart_and_role_problems(seed_check, seed_copy: Path):
	def find(node: dict, number: str) -> dict | None:
		for value in node.values():
			if isinstance(value, dict):
				if value.get("account_number") == number:
					return value
				found = find(value, number)
				if found is not None:
					return found
		return None

	def break_chart(d):
		# duplicate an account number: the runtime loader must refuse it
		leaf = find(d["tree"], "7003")
		assert leaf is not None
		leaf["account_number"] = "7004"

	_edit(seed_copy, "chart_v03", break_chart)
	problems = seed_check.run(seed_copy).problems
	assert any("chart_v03" in p and "duplicate account_number 7004" in p for p in problems)


def test_role_null_rules(seed_check, seed_copy: Path):
	def mutate(d):
		d["schemes"]["v03"]["bank"] = None
		d["schemes"]["v1"]["cash"] = None
		d["schemes"]["v1"]["payable"] = "9999"

	_edit(seed_copy, "code_roles", mutate)
	problems = seed_check.run(seed_copy).problems
	assert any("v03 (default scheme): role 'bank' is null" in p for p in problems)
	assert any("v1: role 'cash' is null but not listed in null_allowed" in p for p in problems)
	assert any("v1: role 'payable' -> '9999' is not a leaf" in p for p in problems)


def test_bank_layout_guessing_is_refused(seed_check, seed_copy: Path):
	def mutate(d):
		d["rows"][0]["header_signature"] = ["Огноо", "Гүйлгээний утга"]
		d["rows"][1]["verified"] = True

	_edit(seed_copy, "bank_layouts", mutate)
	problems = seed_check.run(seed_copy).problems
	assert any("never guess a bank's columns" in p for p in problems)
	assert any("verified false" in p for p in problems)


def test_rules_default_targets(seed_check, seed_copy: Path):
	def mutate(d):
		d["rows"][0]["target_account_code"] = "7012"  # a v0.3 code on the v1 rule
		d["rows"][1]["posting_pattern"] = "no_such_pattern"

	_edit(seed_copy, "rules_default", mutate)
	problems = seed_check.run(seed_copy).problems
	assert any("target_account_code '7012' is not a v1 leaf" in p for p in problems)
	assert any("posting_pattern 'no_such_pattern' does not exist" in p for p in problems)
