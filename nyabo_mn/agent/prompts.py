"""Prompt files: ``agent/prompts/<name>.v<N>.md`` with a first line ``version: N``.

Why files and not Python strings: the accountant-facing wording and the extraction
rules are reviewed by people who do not read Python, and the version travels into
``Nyabo Proposal.prompt_version`` so an eval regression can be tied to a prompt change.

Layout of a prompt file::

    version: 1
    <system instructions - static, cached by the providers>
    ===USER===
    <user template with {{SLOT}} placeholders; the untrusted fence goes here and the
    {{NOW}} timestamp line is last>

``load(name)`` returns ``(text, version)`` for the highest version on disk (or the exact
one when ``name`` already carries ``.vN``); ``split`` separates the two sections and
``fill`` substitutes slots, refusing to leave one unfilled.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
USER_MARKER = "===USER==="
_VERSION_RE = re.compile(r"^version:\s*(\d+)\s*$")
_FILE_RE = re.compile(r"^(?P<name>[a-z0-9_]+)\.v(?P<version>\d+)\.md$")
_SLOT_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


class PromptError(RuntimeError):
	pass


def available(prompts_dir: Path = PROMPTS_DIR) -> dict[str, list[int]]:
	"""Map of prompt name to the versions present on disk."""
	found: dict[str, list[int]] = {}
	for path in sorted(prompts_dir.glob("*.md")):
		match = _FILE_RE.match(path.name)
		if match:
			found.setdefault(match["name"], []).append(int(match["version"]))
	return {k: sorted(v) for k, v in found.items()}


def _resolve(name: str, prompts_dir: Path) -> tuple[Path, int]:
	exact = re.match(r"^(?P<name>[a-z0-9_]+)\.v(?P<version>\d+)$", name)
	if exact:
		version = int(exact["version"])
		path = prompts_dir / f"{exact['name']}.v{version}.md"
		if not path.is_file():
			raise PromptError(f"prompt {name!r} not found in {prompts_dir}")
		return path, version
	versions = available(prompts_dir).get(name)
	if not versions:
		raise PromptError(f"prompt {name!r} not found in {prompts_dir}")
	version = versions[-1]
	return prompts_dir / f"{name}.v{version}.md", version


@lru_cache(maxsize=32)
def _load_cached(name: str, prompts_dir: str) -> tuple[str, int]:
	path, version = _resolve(name, Path(prompts_dir))
	raw = path.read_text(encoding="utf-8")
	first, _, rest = raw.partition("\n")
	match = _VERSION_RE.match(first.strip())
	if not match:
		raise PromptError(f"{path.name}: first line must be 'version: N', got {first!r}")
	declared = int(match.group(1))
	if declared != version:
		raise PromptError(f"{path.name}: declares version {declared} but the file name says {version}")
	return rest.strip("\n") + "\n", version


def load(name: str, prompts_dir: Path | None = None) -> tuple[str, int]:
	"""Return ``(text_without_the_version_line, version)``."""
	return _load_cached(name, str(prompts_dir or PROMPTS_DIR))


def split(text: str) -> tuple[str, str]:
	"""Separate the system section from the user template; the marker line is required."""
	if USER_MARKER not in text:
		raise PromptError(f"prompt has no {USER_MARKER} marker")
	system, _, user = text.partition(USER_MARKER)
	return system.strip() + "\n", user.strip() + "\n"


def fill(template: str, **slots: str) -> str:
	"""Substitute ``{{SLOT}}`` placeholders; an unfilled slot is a programming error."""
	out = template
	for key, value in slots.items():
		out = out.replace("{{" + key + "}}", value)
	left = _SLOT_RE.findall(out)
	if left:
		raise PromptError(f"unfilled prompt slots: {', '.join(sorted(set(left)))}")
	return out


def version_tag(name: str, version: int) -> str:
	"""What goes into ``prompt_version`` fields, e.g. ``receipt_extract.v1``."""
	return f"{name}.v{version}"


__all__ = ["PROMPTS_DIR", "USER_MARKER", "PromptError", "available", "fill", "load", "split", "version_tag"]
