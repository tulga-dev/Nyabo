"""Generate Frappe DocType JSON files from scripts/doctype_specs.py.

    python scripts/gen_doctypes.py          # write/update files
    python scripts/gen_doctypes.py --check  # exit 1 if any file would change (CI)

Frappe only re-imports a DocType JSON when its "modified" timestamp is newer than the
one stored in the site, so the timestamp is bumped only when the content changes.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from doctype_specs import DOCTYPES, MODULE  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOCTYPE_DIR = REPO / "nyabo_mn" / "nyabo" / "doctype"
VOLATILE_KEYS = {"modified", "creation"}


def scrub(name: str) -> str:
	return re.sub(r"[\s-]+", "_", name.strip()).lower()


def class_name(name: str) -> str:
	"""Frappe's own rule, which is not a title-case: ``doctype.replace(" ", "").replace("-", "")``.

	frappe/model/base_document.py (version-16) builds the controller class name that way and
	raises ImportError when no class of that name is in the module, so a DocType whose
	controller is named any other way cannot be loaded — and a DocType that cannot be loaded
	is skipped by migrate and never created on the site. Capitalising each word broke exactly
	one name, "Nyabo LLM Call": the generator wrote ``NyaboLlmCall`` where Frappe looks for
	``NyaboLLMCall``, so the site ran with 20 of the 21 DocTypes and every attempt to record
	an LLM call — including the one on the accountant's Батлах tap — died with
	"DocType Nyabo LLM Call not found".
	"""
	return name.replace(" ", "").replace("-", "")


def build_json(name: str, spec: dict) -> dict:
	fields = spec["fields"]
	doc = {
		"actions": [],
		"allow_rename": 0,
		"creation": "2026-09-08 00:00:00.000000",
		"doctype": "DocType",
		"editable_grid": 1,
		"engine": "InnoDB",
		"field_order": [f["fieldname"] for f in fields],
		"fields": fields,
		"idx": 0,
		"index_web_pages_for_search": 0,
		"istable": spec.get("istable", 0),
		"links": [],
		"modified": "2026-09-08 00:00:00.000000",
		"modified_by": "Administrator",
		"module": MODULE,
		"name": name,
		"owner": "Administrator",
		"permissions": spec.get("permissions", []),
		"sort_field": "modified",
		"sort_order": "DESC",
		"states": [],
		"track_changes": spec.get("track_changes", 1),
	}
	for key in ("autoname", "naming_rule", "title_field", "search_fields", "description"):
		if key in spec:
			doc[key] = spec[key]
	return doc


def stable(doc: dict) -> str:
	return json.dumps(
		{k: v for k, v in doc.items() if k not in VOLATILE_KEYS}, ensure_ascii=False, sort_keys=True
	)


def write_doctype(name: str, spec: dict, check: bool) -> bool:
	folder = DOCTYPE_DIR / scrub(name)
	json_path = folder / f"{scrub(name)}.json"
	py_path = folder / f"{scrub(name)}.py"
	init_path = folder / "__init__.py"
	new_doc = build_json(name, spec)

	changed = True
	if json_path.exists():
		old_doc = json.loads(json_path.read_text(encoding="utf-8"))
		if stable(old_doc) == stable(new_doc):
			changed = False
		else:
			new_doc["creation"] = old_doc.get("creation", new_doc["creation"])
			new_doc["modified"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
	if check:
		return changed
	if changed:
		folder.mkdir(parents=True, exist_ok=True)
		json_path.write_text(
			json.dumps(new_doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
		)
	if not init_path.exists():
		folder.mkdir(parents=True, exist_ok=True)
		init_path.write_text("", encoding="utf-8")
	if not py_path.exists():
		py_path.write_text(
			"from frappe.model.document import Document\n\n\nclass "
			+ class_name(name)
			+ "(Document):\n\tpass\n",
			encoding="utf-8",
		)
	return changed


def main() -> int:
	check = "--check" in sys.argv
	(DOCTYPE_DIR / "__init__.py").parent.mkdir(parents=True, exist_ok=True)
	if not (DOCTYPE_DIR / "__init__.py").exists() and not check:
		(DOCTYPE_DIR / "__init__.py").write_text("", encoding="utf-8")
	changed = [name for name, spec in DOCTYPES.items() if write_doctype(name, spec, check)]
	if check and changed:
		print("DocType JSON out of date for: " + ", ".join(changed))
		return 1
	print(f"{len(DOCTYPES)} doctypes, {len(changed)} written")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
