"""Every DocType controller must be named the way Frappe looks it up.

``frappe.model.base_document.import_controller`` (version-16) derives the class name as
``doctype.replace(" ", "").replace("-", "")`` and raises ImportError when the module has no
class of that name. A DocType whose controller cannot be imported is skipped by migrate and
is simply absent from the site, which is silent: the app installs, the tests pass, and the
first write to that DocType fails in production with "DocType ... not found".

That is what happened to "Nyabo LLM Call". The generator title-cased each word, so it wrote
``NyaboLlmCall`` where Frappe wanted ``NyaboLLMCall``; the live site ran with 20 of the 21
DocTypes, and the accountant's Батлах tap died on the missing one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DOCTYPE_DIR = Path(__file__).resolve().parents[2] / "nyabo_mn" / "nyabo" / "doctype"
CONTROLLER_CLASS = re.compile(r"^class\s+(\w+)\s*\(\s*Document\s*\)", re.MULTILINE)


def _doctype_folders() -> list[Path]:
	return sorted(p for p in DOCTYPE_DIR.iterdir() if p.is_dir() and (p / f"{p.name}.json").exists())


def test_there_are_doctypes_to_check():
	assert len(_doctype_folders()) >= 20


@pytest.mark.parametrize("folder", _doctype_folders(), ids=lambda p: p.name)
def test_the_controller_class_is_the_name_frappe_will_look_for(folder: Path) -> None:
	name = json.loads((folder / f"{folder.name}.json").read_text(encoding="utf-8"))["name"]
	expected = name.replace(" ", "").replace("-", "")
	source = (folder / f"{folder.name}.py").read_text(encoding="utf-8")
	found = CONTROLLER_CLASS.search(source)
	assert found, f"{folder.name}.py declares no Document subclass"
	assert found.group(1) == expected, (
		f"{name}: controller is {found.group(1)}, but Frappe imports {expected} "
		f"(base_document.import_controller). A mismatch makes the DocType unloadable, "
		f"so migrate skips it and the site runs without it."
	)
