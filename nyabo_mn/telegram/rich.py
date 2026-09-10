"""Rich cards: one structure, three renderings (Bot API 10.3 rich messages, read 2026-09-10).

Telegram's ``sendRichMessage`` (Bot API 10.1, 2026-06) draws headings, tables, collapsible
``details``, checklists, footers and rows of styled buttons inside one bubble — the shape of
an accountant's answer rather than a wall of text. The message body is passed as Rich HTML
(``InputRichMessage.html``): the tags used here are exactly the ones the reference lists
under "Rich HTML style" — ``<h1>``–``<h6>``, ``<p>``, ``<table bordered striped compact>``
with ``<tr><th><td align>``, ``<details open><summary>``, ``<ul><li><input type="checkbox"
checked>``, ``<footer>``, ``<hr/>``, ``<tg-button-row>`` with ``<tg-button type=… style=…
data=… url=…>``, the inline ``<b> <i> <code> <mark>`` and, for drafts only, ``<tg-thinking>``.
Limits from the same page: 32768 characters, 500 blocks, 20 table columns, and a table cell
holds inline formatting only.

Why a structure and not an HTML string: every card also needs a plain-text twin. A client
older than Bot API 10.1 cannot draw a rich message, ``sendRichMessage`` can be refused, and
the tests read what the user would have seen — so ``render_text`` turns the same card into
the text ``sendMessage`` would carry, with the buttons as an ordinary inline keyboard whose
callback data is byte-for-byte the rich buttons' data. One card, one set of callbacks, two
drawings.

Text is untrusted (supplier names, model sentences) and is escaped on the way into HTML;
only the ``Inline`` helpers below produce markup, and they escape what they wrap.
"""

from __future__ import annotations

import dataclasses
import html
from collections.abc import Iterable, Sequence
from typing import Any

from nyabo_mn.telegram.api import MAX_CALLBACK_DATA_BYTES

MAX_RICH_CHARS = 32768
MAX_TABLE_COLUMNS = 20
MAX_BUTTONS_PER_ROW = 8

STYLE_PRIMARY = "primary"
STYLE_SUCCESS = "success"
STYLE_DANGER = "danger"
STYLE_LINK = "link"
STYLES = (STYLE_PRIMARY, STYLE_SUCCESS, STYLE_DANGER, STYLE_LINK)

ALIGN_RIGHT = "right"
ALIGN_CENTER = "center"


# --- inline text -----------------------------------------------------------------------------------


class Inline:
	"""A run of inline content rendered both ways; the only thing allowed to carry HTML."""

	__slots__ = ("html", "text")

	def __init__(self, html_: str, text: str):
		self.html = html_
		self.text = text

	def __add__(self, other: Any) -> Inline:
		o = inline(other)
		return Inline(self.html + o.html, self.text + o.text)

	def __radd__(self, other: Any) -> Inline:
		o = inline(other)
		return Inline(o.html + self.html, o.text + self.text)

	def __bool__(self) -> bool:
		return bool(self.text)

	def __repr__(self) -> str:  # pragma: no cover - debugging aid
		return f"Inline({self.text!r})"


InlineLike = str | Inline | Sequence[Any] | None


def inline(value: InlineLike) -> Inline:
	"""Plain text is escaped; an ``Inline`` is taken as is; a sequence is concatenated."""
	if value is None:
		return Inline("", "")
	if isinstance(value, Inline):
		return value
	if isinstance(value, str):
		return Inline(html.escape(value, quote=False), value)
	parts = [inline(v) for v in value]
	return Inline("".join(p.html for p in parts), "".join(p.text for p in parts))


def _wrap(tag: str, value: InlineLike, text_mark: str = "") -> Inline:
	inner = inline(value)
	return Inline(f"<{tag}>{inner.html}</{tag}>", f"{text_mark}{inner.text}{text_mark}")


def bold(value: InlineLike) -> Inline:
	return _wrap("b", value)


def italic(value: InlineLike) -> Inline:
	return _wrap("i", value)


def code(value: InlineLike) -> Inline:
	return _wrap("code", value)


def mark(value: InlineLike) -> Inline:
	"""``<mark>``: the one figure the reader's eye should land on. Plain text shows it bare."""
	return _wrap("mark", value)


def join(values: Iterable[InlineLike], sep: InlineLike = " · ") -> Inline:
	out = Inline("", "")
	separator = inline(sep)
	for index, value in enumerate(values):
		if index:
			out = out + separator
		out = out + inline(value)
	return out


# --- blocks ------------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Heading:
	text: InlineLike
	size: int = 4  # 1 largest … 6 smallest, as InputRichBlockSectionHeading.size


@dataclasses.dataclass(frozen=True)
class Paragraph:
	text: InlineLike


@dataclasses.dataclass(frozen=True)
class Cell:
	text: InlineLike = ""
	header: bool = False
	align: str | None = None


@dataclasses.dataclass(frozen=True)
class Table:
	"""``rows`` of cells; a row of ``Cell(header=True)`` is a header row. Cells are inline-only."""

	rows: Sequence[Sequence[Cell | InlineLike]]
	bordered: bool = True
	striped: bool = False
	compact: bool = True
	caption: InlineLike = None


@dataclasses.dataclass(frozen=True)
class Details:
	summary: InlineLike
	blocks: Sequence[Block] = ()
	open: bool = False


@dataclasses.dataclass(frozen=True)
class CheckItem:
	text: InlineLike
	checked: bool = False


@dataclasses.dataclass(frozen=True)
class Checklist:
	items: Sequence[CheckItem]


@dataclasses.dataclass(frozen=True)
class Button:
	"""Exactly one of ``data`` / ``url`` / ``web_app`` names the kind; ``disabled`` overrides."""

	text: str
	data: str | None = None
	url: str | None = None
	web_app: str | None = None
	style: str | None = None
	disabled: bool = False

	def __post_init__(self) -> None:
		kinds = [k for k in (self.data, self.url, self.web_app) if k]
		if not self.disabled and len(kinds) != 1:
			raise ValueError(f"a button needs exactly one of data/url/web_app: {self.text!r}")
		if self.data is not None and len(self.data.encode("utf-8")) > MAX_CALLBACK_DATA_BYTES:
			raise ValueError(f"callback data exceeds {MAX_CALLBACK_DATA_BYTES} bytes: {self.data!r}")
		if self.style is not None and self.style not in STYLES:
			raise ValueError(f"unknown button style {self.style!r}")


@dataclasses.dataclass(frozen=True)
class Buttons:
	buttons: Sequence[Button]

	def __post_init__(self) -> None:
		if not 1 <= len(self.buttons) <= MAX_BUTTONS_PER_ROW:
			raise ValueError(f"a button row holds 1-{MAX_BUTTONS_PER_ROW} buttons")


@dataclasses.dataclass(frozen=True)
class Footer:
	text: InlineLike


@dataclasses.dataclass(frozen=True)
class Divider:
	pass


@dataclasses.dataclass(frozen=True)
class Thinking:
	"""``<tg-thinking>``: drafts only (``sendRichMessageDraft``); never in a sent message."""

	text: InlineLike


Block = Heading | Paragraph | Table | Details | Checklist | Buttons | Footer | Divider | Thinking


@dataclasses.dataclass(frozen=True)
class Card:
	blocks: Sequence[Block]

	# Helpers so a builder can add blocks conditionally without list juggling.
	def with_blocks(self, *more: Block | None) -> Card:
		return Card([*self.blocks, *[b for b in more if b is not None]])


def card(*blocks: Block | None) -> Card:
	"""``None`` entries are dropped, so a builder can write ``card(a, b if cond else None)``."""
	return Card([b for b in blocks if b is not None])


# --- rendering: Rich HTML ------------------------------------------------------------------------------


def _attr(value: str) -> str:
	return html.escape(value, quote=True)


def _cell(value: Cell | InlineLike) -> Cell:
	return value if isinstance(value, Cell) else Cell(value)


def _table_html(block: Table) -> str:
	attrs = "".join(
		f" {name}"
		for name, on in (("bordered", block.bordered), ("striped", block.striped), ("compact", block.compact))
		if on
	)
	out = [f"<table{attrs}>"]
	if block.caption:
		out.append(f"<caption>{inline(block.caption).html}</caption>")
	for row in block.rows:
		cells = [_cell(c) for c in row]
		if len(cells) > MAX_TABLE_COLUMNS:
			raise ValueError(f"a table row holds at most {MAX_TABLE_COLUMNS} cells")
		out.append("<tr>")
		for c in cells:
			tag = "th" if c.header else "td"
			align = f' align="{_attr(c.align)}"' if c.align else ""
			out.append(f"<{tag}{align}>{inline(c.text).html}</{tag}>")
		out.append("</tr>")
	out.append("</table>")
	return "".join(out)


def _button_html(b: Button) -> str:
	label = html.escape(b.text, quote=False)
	style = f' style="{_attr(b.style)}"' if b.style else ""
	if b.disabled:
		return f'<tg-button type="disabled"{style}>{label}</tg-button>'
	if b.data is not None:
		return f'<tg-button type="callback_data"{style} data="{_attr(b.data)}">{label}</tg-button>'
	if b.web_app is not None:
		return f'<tg-button type="web_app"{style} url="{_attr(b.web_app)}">{label}</tg-button>'
	return f'<tg-button type="url"{style} url="{_attr(b.url or "")}">{label}</tg-button>'


def _block_html(block: Block) -> str:
	if isinstance(block, Heading):
		size = min(6, max(1, int(block.size)))
		return f"<h{size}>{inline(block.text).html}</h{size}>"
	if isinstance(block, Paragraph):
		return f"<p>{inline(block.text).html}</p>"
	if isinstance(block, Table):
		return _table_html(block)
	if isinstance(block, Details):
		open_attr = " open" if block.open else ""
		inner = "".join(_block_html(b) for b in block.blocks)
		return f"<details{open_attr}><summary>{inline(block.summary).html}</summary>{inner}</details>"
	if isinstance(block, Checklist):
		items = "".join(
			f'<li><input type="checkbox"{" checked" if item.checked else ""}>{inline(item.text).html}</li>'
			for item in block.items
		)
		return f"<ul>{items}</ul>"
	if isinstance(block, Buttons):
		return "<tg-button-row>" + "".join(_button_html(b) for b in block.buttons) + "</tg-button-row>"
	if isinstance(block, Footer):
		return f"<footer>{inline(block.text).html}</footer>"
	if isinstance(block, Divider):
		return "<hr/>"
	if isinstance(block, Thinking):
		return f"<tg-thinking>{inline(block.text).html}</tg-thinking>"
	raise TypeError(f"unknown block {type(block).__name__}")  # pragma: no cover - defensive


def render_html(card_: Card) -> str:
	"""The ``html`` field of ``InputRichMessage``; refuses a card over Telegram's 32768 limit."""
	out = "".join(_block_html(b) for b in card_.blocks)
	if len(out) > MAX_RICH_CHARS:
		raise ValueError(f"rich message exceeds {MAX_RICH_CHARS} characters ({len(out)})")
	return out


# --- rendering: plain text + inline keyboard ------------------------------------------------------------


def _table_text(block: Table) -> list[str]:
	lines: list[str] = []
	if block.caption:
		lines.append(inline(block.caption).text)
	for row in block.rows:
		cells = [inline(_cell(c).text).text for c in row]
		lines.append(" | ".join(c for c in cells if c) if any(cells) else "")
	return [line for line in lines if line]


def _button_markup(b: Button) -> dict[str, Any]:
	drawn: dict[str, Any] = {"text": b.text}
	if b.style and b.style != STYLE_LINK:
		drawn["style"] = b.style
	if b.disabled:
		drawn["disabled"] = {}
	elif b.data is not None:
		drawn["callback_data"] = b.data
	elif b.web_app is not None:
		drawn["web_app"] = {"url": b.web_app}
	else:
		drawn["url"] = b.url
	return drawn


def _block_text(block: Block, keyboard: list[list[dict[str, Any]]]) -> list[str]:
	if isinstance(block, Heading):
		return [inline(block.text).text]
	if isinstance(block, Paragraph):
		return [inline(block.text).text]
	if isinstance(block, Table):
		return _table_text(block)
	if isinstance(block, Details):
		lines = [inline(block.summary).text]
		for b in block.blocks:
			lines.extend(_block_text(b, keyboard))
		return lines
	if isinstance(block, Checklist):
		return [("☑ " if item.checked else "☐ ") + inline(item.text).text for item in block.items]
	if isinstance(block, Buttons):
		keyboard.append([_button_markup(b) for b in block.buttons])
		return []
	if isinstance(block, Footer):
		return [inline(block.text).text]
	if isinstance(block, Divider):
		return ["—"]
	if isinstance(block, Thinking):
		return [inline(block.text).text]
	raise TypeError(f"unknown block {type(block).__name__}")  # pragma: no cover - defensive


def render_text(card_: Card) -> tuple[str, dict[str, Any] | None]:
	"""What ``sendMessage`` would carry: the lines of the card and its buttons as a keyboard."""
	keyboard: list[list[dict[str, Any]]] = []

	lines: list[str] = []
	for block in card_.blocks:
		lines.extend(_block_text(block, keyboard))
	text = "\n".join(line for line in lines if line is not None)
	return text, ({"inline_keyboard": keyboard} if keyboard else None)


def buttons_of(card_: Card) -> list[Button]:
	"""Every button on the card, reading order; what a test asserts callback data against."""
	out: list[Button] = []

	def walk(blocks: Sequence[Block]) -> None:
		for b in blocks:
			if isinstance(b, Buttons):
				out.extend(b.buttons)
			elif isinstance(b, Details):
				walk(b.blocks)

	walk(card_.blocks)
	return out


__all__ = [
	"ALIGN_CENTER",
	"ALIGN_RIGHT",
	"Button",
	"Buttons",
	"Card",
	"Cell",
	"CheckItem",
	"Checklist",
	"Details",
	"Divider",
	"Footer",
	"Heading",
	"Inline",
	"Paragraph",
	"STYLE_DANGER",
	"STYLE_LINK",
	"STYLE_PRIMARY",
	"STYLE_SUCCESS",
	"Table",
	"Thinking",
	"bold",
	"buttons_of",
	"card",
	"code",
	"inline",
	"italic",
	"join",
	"mark",
	"render_html",
	"render_text",
]
