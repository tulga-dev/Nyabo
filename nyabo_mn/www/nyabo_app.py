"""``/nyabo_app``: the Telegram Mini App page (``nyabo_mn.miniapp`` explains the trust model).

A plain document, never cached and never in the sitemap: it draws nothing until Telegram's
``initData`` has been verified server-side, so there is nothing on it for a search engine or
a stray visitor.
"""

from __future__ import annotations

from typing import Any

no_cache = 1
no_sitemap = 1


def get_context(context: Any) -> Any:
	context.no_cache = 1
	return context
