"""Quarantine for untrusted text (docs/ARCHITECTURE.md §1.9).

Receipts, bank statements and Telegram messages are *data*. Before any of that text
enters a prompt it is wrapped in an ``<untrusted>`` fence so the model can tell the
instructions (ours) from the content (theirs), and it is scanned for instruction-looking
phrases so the pipeline can log an ``injection_suspected`` event and never act on them.

Pure Python by design: this module is imported by the agent layer and by the simulator,
neither of which may depend on Frappe.
"""

from __future__ import annotations

import re
import unicodedata

FENCE_OPEN = "<untrusted"
FENCE_CLOSE = "</untrusted>"

# Characters that carry no content but can hide or reorder text for a reader/model:
# zero-width joiners, bidi overrides, byte-order marks. Removed before any scan.
_INVISIBLE = frozenset(
	chr(cp)
	for cp in (
		0x200B,  # zero width space
		0x200C,  # zero width non-joiner
		0x200D,  # zero width joiner
		0x200E,  # left-to-right mark
		0x200F,  # right-to-left mark
		0x202A,  # bidi embedding / override block
		0x202B,
		0x202C,
		0x202D,
		0x202E,
		0x2060,  # word joiner
		0x2066,  # bidi isolates
		0x2067,
		0x2068,
		0x2069,
		0xFEFF,  # byte order mark
	)
)
_KEEP_CONTROL = frozenset({"\n", "\t", "\r"})

_LABEL_RE = re.compile(r"[^a-z0-9_.-]+")

# Order matters only for readability; every pattern is tried. Cyrillic patterns use the
# stems accountants would not print on a receipt: "заавар" (instruction), "промпт",
# "дүрмийг март" (forget the rules), and imperative "батал…" aimed at the bot.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
	re.compile(p, re.IGNORECASE | re.UNICODE)
	for p in (
		# English
		r"\bignore\s+(all\s+|the\s+|any\s+|your\s+)?(previous|prior|above|earlier|preceding|other)\s+(instructions?|rules?|prompts?|messages?|guidance)",
		r"\bignore\s+(all|everything|the rules)\b",
		r"\bdisregard\s+(all\s+|the\s+|your\s+|any\s+)?(previous|prior|above|earlier)?\s*(instructions?|rules?|prompts?)",
		r"\bforget\s+(all\s+|the\s+|your\s+)?(previous|prior|above|earlier)?\s*(instructions?|rules?|prompts?|training)",
		r"\bsystem\s+prompt\b",
		r"\byou\s+are\s+now\b",
		r"\bact\s+as\s+(an?\s+)?(admin|administrator|accountant|system|developer)",
		r"(^|\n|\s)(assistant|system|user|developer)\s*:\s",
		r"\bapprove\s+(this|the)\s+(receipt|entry|transaction|expense|proposal|invoice|document)",
		r"\bauto[\s-]?approve\b",
		r"\b(do\s+not|don'?t|never)\s+(verify|validate|check|ask|flag|report)\b",
		r"\bnew\s+instructions?\s*:",
		r"\b(override|bypass)\s+(the\s+)?(rules?|checks?|validation|approval|accountant)",
		r"\bset\s+(the\s+)?(vat|total|amount|account)\s+to\b",
		# Mongolian
		r"заавр(ыг|уудыг)\s+(үл\s+тоо|мартаж|март|хэрэгсэхгүй|үл\s+хэрэгс)",
		r"өмнөх\s+(бүх\s+)?(заавар|заавр|дүрм|дүрэм|мессеж)",
		r"систем(ийн)?\s+промпт",
		r"\bпромпт\b",
		r"(бүх|өмнөх)\s+дүрм(ийг|үүдийг)\s+март",
		r"(дүрм|заавр)(ийг|уудыг|ыг)\s+(март|үл\s+тоо|зөрч|алгас)",
		r"(чи|та)\s+одоо\s+(бол|нь)?\s*\S*\s*(админ|нягтлан|систем|хөгжүүлэгч|туслах)",
		r"(энэ|уг|доорх|дээрх)\s+(баримт|гүйлгээ|зардл|санал|нэхэмжлэх)\S*\s+(шууд\s+|заавал\s+|яаралтай\s+)?(батал|зөвшөөр|бүртгэ)",
		# "батлах" loses its second а before an ending ("батлаарай"): match the stem бата?л.
		r"(шууд|заавал|яаралтай|асуулгүй|шалгалгүй|шалгахгүй)\s+(бата?л|зөвшөөр|бүртгэ)",
		r"\bбатлах\s+(товч|команд|үйлдлийг)",
		r"\bбата?л(на\s+уу|аарай|аач|аад\s+өг|ж\s+өг|ах\s+хэрэгтэй)\b",
		r"нягтлан(д|гүй)\s+(хэлэлгүй|мэдэгдэлгүй|шалгуулалгүй)",
		r"(шалг|баталгаажуул)\w*\s+(хэрэггүй|шаардлагагүй|байхгүй)",
		r"(шинэ|дараах)\s+заавар\s*:",
	)
)


def strip_control_chars(text: str) -> str:
	"""Drop control and invisible characters; keep newlines and tabs.

	Bidi overrides and zero-width characters let an attacker show one thing and encode
	another, and NUL/escape bytes confuse downstream regexes and JSON, so they are
	removed rather than escaped.
	"""
	out: list[str] = []
	for ch in text:
		if ch in _KEEP_CONTROL:
			out.append(ch)
			continue
		if ch in _INVISIBLE:
			continue
		category = unicodedata.category(ch)
		if category in ("Cc", "Cf"):
			continue
		out.append(ch)
	return "".join(out)


def _escape_fence_tokens(text: str) -> str:
	"""Neutralise anything that could close or reopen the fence from inside."""
	return re.sub(r"<(/?)untrusted", r"&lt;\1untrusted", text, flags=re.IGNORECASE)


def fence(text: str, label: str = "document") -> str:
	"""Wrap ``text`` as untrusted content the model may read but must not obey.

	The closing tag inside the content is escaped so the fence cannot be terminated
	early; the label is restricted to safe ASCII so it cannot carry an attribute
	injection of its own.
	"""
	safe_label = _LABEL_RE.sub("_", (label or "document").lower()).strip("_") or "document"
	body = _escape_fence_tokens(strip_control_chars(text or ""))
	return f'{FENCE_OPEN} label="{safe_label}">\n{body}\n{FENCE_CLOSE}'


def find_injection(text: str) -> str | None:
	"""Return the first instruction-looking fragment, or None. Useful for event payloads."""
	if not text:
		return None
	cleaned = strip_control_chars(text)
	for pattern in _INJECTION_PATTERNS:
		match = pattern.search(cleaned)
		if match:
			return match.group(0).strip()
	return None


def looks_like_injection(text: str) -> bool:
	"""True when the text contains phrases addressed to the model rather than to a buyer.

	Pattern-based on purpose: a second model call to judge the first would itself be
	attackable. False negatives are acceptable because the fence and the no-tools calls
	are the real defence; this check only decides whether to raise a warning.
	"""
	return find_injection(text) is not None
