from __future__ import annotations

import pytest

from nyabo_mn.agent import prompts

# The version each prompt is on. It is pinned rather than merely "the highest on disk" so a
# new file has to be paired with a deliberate bump here — the version travels into
# ``Nyabo Proposal.prompt_version`` and an eval regression is tied to it.
EXPECTED = {"receipt_extract": 1, "classify": 1, "question": 2, "explain": 1}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_prompt_loads_at_its_pinned_version(name: str):
	text, version = prompts.load(name)
	assert version == EXPECTED[name]
	assert not text.startswith("version:")
	system, user = prompts.split(text)
	assert system.strip() and user.strip()
	assert "{{UNTRUSTED}}" in user and user.rstrip().endswith("{{NOW}}")
	assert "{{" not in system  # static part has no slots


def test_exact_version_and_missing_prompt():
	assert prompts.load("classify.v1")[1] == 1
	with pytest.raises(prompts.PromptError):
		prompts.load("classify.v9")
	with pytest.raises(prompts.PromptError):
		prompts.load("nonexistent")


def test_version_line_must_match_file_name(tmp_path):
	(tmp_path / "x.v2.md").write_text(
		"version: 3\nhello\n===USER===\n{{UNTRUSTED}}\n{{NOW}}\n", encoding="utf-8"
	)
	with pytest.raises(prompts.PromptError, match="declares version 3"):
		prompts.load("x", prompts_dir=tmp_path)
	(tmp_path / "y.v1.md").write_text("hello\n", encoding="utf-8")
	with pytest.raises(prompts.PromptError, match="first line"):
		prompts.load("y", prompts_dir=tmp_path)


def test_highest_version_is_picked(tmp_path):
	for n in (1, 3, 2):
		(tmp_path / f"z.v{n}.md").write_text(
			f"version: {n}\nv{n}\n===USER===\n{{{{UNTRUSTED}}}}\n{{{{NOW}}}}\n", encoding="utf-8"
		)
	text, version = prompts.load("z", prompts_dir=tmp_path)
	assert version == 3 and text.startswith("v3")
	assert prompts.available(tmp_path) == {"z": [1, 2, 3]}


def test_fill_refuses_unfilled_slots():
	assert prompts.fill("a {{X}} b", X="1") == "a 1 b"
	with pytest.raises(prompts.PromptError, match="Y"):
		prompts.fill("a {{X}} {{Y}}", X="1")


def test_extraction_prompt_encodes_the_receipt_rules():
	text, _ = prompts.load("receipt_extract")
	for token in (
		"Төлөх дүн",
		"Төлсөн",
		"Бүртгэгдсэн дүн",
		"НӨАТ",
		"НХАТ",
		"Сугалааны дугаар",
		"ДДТД",
		"ТТД",
		"РД",
		"QPay",
	):
		assert token in text, token
	assert 'NOT "card"' in text or 'NOT "card"' in text


def test_classification_prompt_encodes_the_guard_rules():
	text, _ = prompts.load("classify")
	assert "MUST be one of the codes" in text and "160 characters" in text and "never" in text.lower()
	assert "not a VAT payer" in text and "withheld" in text
