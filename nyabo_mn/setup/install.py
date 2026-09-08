"""Install and migrate hooks (see hooks.py). Everything here must be idempotent.

Both hooks run the same steps, in this order, because a migrate is how a redeploy
reaches an existing site: custom fields (update=True), roles (fixtures, applied by
bench before this hook), the rules seed (never overwriting verified rows), ERPNext's
financial report templates (skipped with a log line when this ERPNext has none), the
external exchange-rate provider switched off (Nyabo records Монголбанк rates itself,
ARCHITECTURE §2), and a warning per missing site-config key.
"""

from __future__ import annotations

from typing import Any

import frappe

from nyabo_mn.config import get_settings
from nyabo_mn.log import log_error, log_event
from nyabo_mn.setup.custom_fields import ensure_custom_fields

CURRENCY_EXCHANGE_SETTINGS = "Currency Exchange Settings"


def after_install() -> None:
	_setup("install")


def after_migrate() -> None:
	_setup("migrate")


def _setup(stage: str) -> dict[str, Any]:
	report: dict[str, Any] = {}
	report["custom_fields"] = ensure_custom_fields()
	log_event(f"{stage}.custom_fields", doctypes=report["custom_fields"])
	report["seed"] = _sync_seed(stage)
	report["financial_report_templates"] = _sync_financial_report_templates(stage)
	report["currency_exchange_disabled"] = _disable_exchange_provider(stage)
	_warn_missing_settings()
	return report


def _sync_seed(stage: str) -> dict[str, Any]:
	from nyabo_mn.rules import seed

	counts = seed.sync()
	log_event(f"{stage}.seed", **{k.replace(" ", "_"): v for k, v in counts.items()})
	return counts


def _sync_financial_report_templates(stage: str) -> bool:
	try:
		from erpnext.accounts.doctype.financial_report_template.financial_report_template import (
			sync_financial_report_templates,
		)
	except ImportError as exc:
		log_event(f"{stage}.financial_report_templates.skipped", level="warning", error=repr(exc))
		return False
	try:
		sync_financial_report_templates()
	except Exception as exc:  # a template error must not block the whole migrate
		log_error(f"{stage}.financial_report_templates", exc)
		return False
	return True


def _disable_exchange_provider(stage: str) -> bool:
	"""`Currency Exchange Settings.disabled = 1` (ARCHITECTURE §2); skipped when the Single is absent."""
	if not frappe.db.exists("DocType", CURRENCY_EXCHANGE_SETTINGS):
		log_event(f"{stage}.currency_exchange_settings.absent", level="warning")
		return False
	try:
		frappe.db.set_single_value(CURRENCY_EXCHANGE_SETTINGS, "disabled", 1)
	except Exception as exc:
		log_error(f"{stage}.currency_exchange_settings", exc)
		return False
	return True


def _warn_missing_settings() -> None:
	"""Missing secrets must not block a deploy; features check again and fail loudly when used."""
	missing = {feature: keys for feature, keys in get_settings().report().items() if keys}
	if missing:
		log_event("config.missing", level="warning", **missing)
		for feature, keys in missing.items():
			print(f"nyabo_mn: site config is missing {', '.join(keys)} (needed for {feature})")
