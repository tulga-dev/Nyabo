"""Site-config settings with validation.

Secrets live in the Frappe site config (Frappe Cloud -> Site -> Site Config), never in the
repo. Keys are read as written first, then lower-cased, so both TELEGRAM_BOT_TOKEN and
telegram_bot_token work.

Usage:
    from nyabo_mn.config import get_settings
    settings = get_settings()
    settings.require("telegram")          # raises MissingSettingError naming the key

    bench --site <site> execute nyabo_mn.config.check   # prints what is missing per feature
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

DEFAULT_OPENAI_MODEL = "gpt-5.6-terra"
DEFAULT_OPENAI_SWEEP_MODEL = "gpt-5.6-luna"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"


@dataclass(frozen=True)
class KeySpec:
	name: str
	feature: str | None = None  # feature that cannot run without it; None = optional
	default: Any = None
	secret: bool = True


KEY_SPECS: tuple[KeySpec, ...] = (
	KeySpec("TELEGRAM_BOT_TOKEN", feature="telegram"),
	KeySpec("TELEGRAM_WEBHOOK_SECRET", feature="telegram"),
	KeySpec("ADMIN_TELEGRAM_IDS", feature="telegram", secret=False),
	KeySpec("OPENAI_API_KEY", feature="llm"),
	KeySpec("OPENAI_MODEL", default=DEFAULT_OPENAI_MODEL, secret=False),
	KeySpec("ANTHROPIC_API_KEY"),
	KeySpec("ANTHROPIC_MODEL", default=DEFAULT_ANTHROPIC_MODEL, secret=False),
	KeySpec("OPENAI_SWEEP_MODEL", default=DEFAULT_OPENAI_SWEEP_MODEL, secret=False),
	KeySpec("EBARIMT_API_BASE", feature="ebarimt", secret=False),
)
FEATURES: tuple[str, ...] = ("telegram", "llm", "ebarimt")


class MissingSettingError(RuntimeError):
	pass


@dataclass(frozen=True)
class Settings:
	values: Mapping[str, Any] = field(default_factory=dict)

	@classmethod
	def from_mapping(cls, conf: Mapping[str, Any]) -> Settings:
		values: dict[str, Any] = {}
		for spec in KEY_SPECS:
			raw = conf.get(spec.name)
			if raw in (None, ""):
				raw = conf.get(spec.name.lower())
			if raw in (None, ""):
				raw = spec.default
			values[spec.name] = raw
		return cls(values=values)

	def get(self, name: str) -> Any:
		return self.values.get(name)

	@property
	def telegram_bot_token(self) -> str:
		return str(self.values.get("TELEGRAM_BOT_TOKEN") or "")

	@property
	def telegram_webhook_secret(self) -> str:
		return str(self.values.get("TELEGRAM_WEBHOOK_SECRET") or "")

	@property
	def admin_telegram_ids(self) -> frozenset[int]:
		return parse_id_list(self.values.get("ADMIN_TELEGRAM_IDS"))

	@property
	def openai_api_key(self) -> str:
		return str(self.values.get("OPENAI_API_KEY") or "")

	@property
	def openai_model(self) -> str:
		return str(self.values.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL)

	@property
	def anthropic_api_key(self) -> str:
		return str(self.values.get("ANTHROPIC_API_KEY") or "")

	@property
	def anthropic_model(self) -> str:
		return str(self.values.get("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL)

	@property
	def openai_sweep_model(self) -> str:
		return str(self.values.get("OPENAI_SWEEP_MODEL") or DEFAULT_OPENAI_SWEEP_MODEL)

	@property
	def ebarimt_api_base(self) -> str:
		return str(self.values.get("EBARIMT_API_BASE") or "").rstrip("/")

	def missing(self, feature: str) -> list[str]:
		if feature not in FEATURES:
			raise ValueError(f"unknown feature {feature!r}; expected one of {FEATURES}")
		return [s.name for s in KEY_SPECS if s.feature == feature and self.values.get(s.name) in (None, "")]

	def require(self, *features: str) -> None:
		missing = [k for f in features for k in self.missing(f)]
		if missing:
			raise MissingSettingError(
				"Site config is missing "
				+ ", ".join(missing)
				+ ". Add it in Frappe Cloud -> your site -> Site Config (or: bench --site <site> set-config KEY value)."
			)

	def report(self) -> dict[str, list[str]]:
		return {feature: self.missing(feature) for feature in FEATURES}

	def redacted(self) -> dict[str, str]:
		out: dict[str, str] = {}
		for spec in KEY_SPECS:
			value = self.values.get(spec.name)
			if value in (None, ""):
				out[spec.name] = "<missing>"
			elif spec.secret:
				out[spec.name] = "<set>"
			else:
				out[spec.name] = str(value)
		return out


def parse_id_list(raw: Any) -> frozenset[int]:
	"""ADMIN_TELEGRAM_IDS may be a JSON list, a Python list, an int, or a comma-separated string."""
	if raw in (None, ""):
		return frozenset()
	if isinstance(raw, int):
		return frozenset({raw})
	items = raw if isinstance(raw, (list, tuple, set)) else str(raw).replace(";", ",").split(",")
	ids: set[int] = set()
	for item in items:
		text = str(item).strip()
		if not text:
			continue
		if not text.lstrip("-").isdigit():
			raise ValueError(f"ADMIN_TELEGRAM_IDS contains a non-numeric id: {text!r}")
		ids.add(int(text))
	return frozenset(ids)


def get_settings() -> Settings:
	import frappe

	return Settings.from_mapping(frappe.conf)


def check() -> dict[str, Any]:
	"""bench --site <site> execute nyabo_mn.config.check"""
	settings = get_settings()
	return {"missing_by_feature": settings.report(), "values": settings.redacted()}
