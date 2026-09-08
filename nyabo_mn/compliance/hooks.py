"""PLACEHOLDER: functions referenced by nyabo_mn/hooks.py.

No-op bodies keep the hooks importable until the owning stage-2 module lands.
Each function keeps the exact name and signature the hooks reference.
"""

from __future__ import annotations

from typing import Any


def validate_accounting_document(doc: Any, method: str | None = None) -> None:
	"""PLACEHOLDER: implemented in stage 2."""
	return None


def require_primary_document(doc: Any, method: str | None = None) -> None:
	"""PLACEHOLDER: implemented in stage 2."""
	return None


def guard_no_edit_after_submit(doc: Any, method: str | None = None) -> None:
	"""PLACEHOLDER: implemented in stage 2."""
	return None


def block_delete_of_posted(doc: Any, method: str | None = None) -> None:
	"""PLACEHOLDER: implemented in stage 2."""
	return None


def block_retained_file_delete(doc: Any, method: str | None = None) -> None:
	"""PLACEHOLDER: implemented in stage 2."""
	return None


def stamp_retention(doc: Any, method: str | None = None) -> None:
	"""PLACEHOLDER: implemented in stage 2."""
	return None


def block_retained_document_delete(doc: Any, method: str | None = None) -> None:
	"""PLACEHOLDER: implemented in stage 2."""
	return None
