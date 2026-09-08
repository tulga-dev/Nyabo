"""``/бодлого``: the accounting-policy document draft as a PDF."""

from __future__ import annotations

from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import _deps
from nyabo_mn.telegram.context import Ctx


def handle_command(ctx: Ctx) -> Any:
	if not ctx.company:
		ctx.reply(mn.MSG_NO_COMPANY)
		return None
	pdf = _deps.policy_pdf(ctx.company)
	filename = f"nyabo-policy-{_ascii_slug(ctx.company)}.pdf"
	ctx.send_document(pdf, filename, caption=mn.MSG_POLICY_GENERATED)
	return {"filename": filename}


def _ascii_slug(text: str) -> str:
	"""Filenames stay ASCII so every Telegram client saves them; the caption carries the name."""
	slug = "".join(ch if ch.isascii() and ch.isalnum() else "-" for ch in text).strip("-").lower()
	return slug or "company"
