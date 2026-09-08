"""``frappe.utils.logger.get_logger``: stdlib loggers, no site log files."""

from __future__ import annotations

import logging
from typing import Any


def get_logger(
	module: str | None = None,
	with_more_info: bool = False,
	allow_site: bool = True,
	filter: Any = None,  # noqa: A002 - Frappe signature
	max_size: int = 100_000,
	file_count: int = 20,
	stream_only: bool = False,
) -> logging.Logger:
	return logging.getLogger(f"frappe.{module}" if module else "frappe")


def set_log_level(level: str) -> None:
	logging.getLogger("frappe").setLevel(level)
