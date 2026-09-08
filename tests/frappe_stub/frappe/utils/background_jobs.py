"""``frappe.utils.background_jobs``: ``enqueue`` is the inline runner from ``frappe``."""

from __future__ import annotations

from typing import Any


def enqueue(*args: Any, **kwargs: Any) -> Any:
	import frappe

	return frappe.enqueue(*args, **kwargs)


def get_jobs(*args: Any, **kwargs: Any) -> dict:
	import frappe

	return {frappe.local.site: [j.method for j in frappe.local.enqueued]}


def is_job_enqueued(job_id: str) -> bool:
	import frappe

	return any(j.job_name == job_id for j in frappe.local.enqueued)
