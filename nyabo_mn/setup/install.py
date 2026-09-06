"""Install and migrate hooks (see hooks.py). Everything here must be idempotent."""

from __future__ import annotations

from nyabo_mn.config import get_settings
from nyabo_mn.log import log_event
from nyabo_mn.setup.custom_fields import ensure_custom_fields


def after_install() -> None:
	doctypes = ensure_custom_fields()
	log_event("install.custom_fields", doctypes=doctypes)
	_warn_missing_settings()


def after_migrate() -> None:
	doctypes = ensure_custom_fields()
	log_event("migrate.custom_fields", doctypes=doctypes)
	_warn_missing_settings()


def _warn_missing_settings() -> None:
	"""Missing secrets must not block a deploy; features check again and fail loudly when used."""
	missing = {feature: keys for feature, keys in get_settings().report().items() if keys}
	if missing:
		log_event("config.missing", level="warning", **missing)
		for feature, keys in missing.items():
			print(f"nyabo_mn: site config is missing {', '.join(keys)} (needed for {feature})")
