"""Per-"request" state of the stub: ``frappe.local`` and the proxies that stand in for it.

Real Frappe keeps ``db``, ``session``, ``flags``, ``conf``, ``request``, ``response`` and
``form_dict`` on a werkzeug ``Local`` and exposes them as ``LocalProxy`` objects, so
``frappe.flags is frappe.local.flags`` holds and a module that did ``from frappe import
flags`` keeps working after the site is re-initialised. The stub mirrors that with a
tiny proxy so ``reset()`` can swap the whole state without stale references in tests.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from frappe._stub.dictlike import _dict

STUB_DIR = Path(__file__).resolve().parent.parent.parent  # tests/frappe_stub
REPO_ROOT = STUB_DIR.parent.parent
SITE_CONFIG_PATH = REPO_ROOT / "tests" / "fixtures" / "site" / "site_config.json"
DEFAULT_SITE = "test.localhost"
ADMIN = "Administrator"


class Request:
	"""The subset of ``werkzeug.Request`` that webhook code touches.

	Headers are case-insensitive like werkzeug's ``EnvironHeaders``; ``data`` is bytes.
	"""

	def __init__(
		self,
		data: bytes | str | None = None,
		headers: dict[str, str] | None = None,
		method: str = "POST",
		path: str = "/",
		args: dict[str, Any] | None = None,
		remote_addr: str = "127.0.0.1",
	) -> None:
		self.method = method
		self.path = path
		self.remote_addr = remote_addr
		self.args = _dict(args or {})
		self.form = _dict()
		self.files = _dict()
		self.headers = _Headers(headers or {})
		self.data = data.encode("utf-8") if isinstance(data, str) else (data or b"")
		self.url = f"http://{DEFAULT_SITE}{path}"
		self.host = DEFAULT_SITE
		self.environ: dict[str, Any] = {}

	def get_data(self, as_text: bool = False) -> bytes | str:
		return self.data.decode("utf-8") if as_text else self.data

	def get_json(self, force: bool = False, silent: bool = False) -> Any:
		if not force and not self.is_json:
			if silent:
				return None
			raise ValueError("frappe stub: request content type is not JSON (pass force=True)")
		try:
			return json.loads(self.data.decode("utf-8") or "null")
		except ValueError:
			if silent:
				return None
			raise

	@property
	def json(self) -> Any:
		return self.get_json(silent=True)

	@property
	def is_json(self) -> bool:
		return "json" in (self.headers.get("Content-Type") or "").lower()

	@property
	def content_type(self) -> str:
		return self.headers.get("Content-Type") or ""


class _Headers(dict):
	"""Case-insensitive header mapping (werkzeug ``Headers`` semantics for get/in)."""

	def __init__(self, values: dict[str, str]) -> None:
		super().__init__()
		for key, value in values.items():
			self[key] = value

	@staticmethod
	def _key(key: str) -> str:
		return key.lower()

	def __setitem__(self, key: str, value: str) -> None:
		super().__setitem__(self._key(key), value)

	def __getitem__(self, key: str) -> str:
		return super().__getitem__(self._key(key))

	def __contains__(self, key: object) -> bool:
		return isinstance(key, str) and super().__contains__(self._key(key))

	def get(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002 - werkzeug signature
		value = super().get(self._key(key), default)
		if type is not None and value is not None:
			return type(value)
		return value


class Local:
	"""What ``frappe.local`` carries between ``init`` and ``destroy``."""

	def __init__(self, site: str = DEFAULT_SITE) -> None:
		self.site = site
		self.site_path = tempfile.mkdtemp(prefix="nyabo-stub-site-")
		self.sites_path = str(Path(self.site_path).parent)
		self.flags = _dict()
		self.session = _dict(user=ADMIN, sid=ADMIN, data=_dict(), csrf_token="stub")
		self.conf = _dict(_load_site_config())
		self.request = Request()
		self.response = _dict(docs=[])
		self.form_dict = _dict()
		self.message_log: list[_dict] = []
		self.lang = "en"
		self.db: Any = None
		self.registry: Any = None
		self.hooks_cache: _dict | None = None
		self.doc_events_hooks: dict | None = None
		self.hooks_overrides: list[dict] = []
		self.enqueued: list[_dict] = []
		self.recorded_calls: dict[str, list[dict]] = {}
		self.whitelisted: set = set()
		self.error_log: list[_dict] = []
		self.cache_store: dict = {}
		self.role_cache: dict[str, list[str]] = {}
		self.app_modules = {"frappe": [], "erpnext": [], "nyabo_mn": ["Nyabo"]}
		self.module_app = {"Nyabo": "nyabo_mn"}
		self.currently_saving: list = []

	def destroy(self) -> None:
		shutil.rmtree(self.site_path, ignore_errors=True)


def _load_site_config() -> dict[str, Any]:
	"""tests/fixtures/site/site_config.json plays the role of the site's site_config.json."""
	if SITE_CONFIG_PATH.exists():
		with open(SITE_CONFIG_PATH, encoding="utf-8") as f:
			return json.load(f)
	return {}


class LocalProxy:
	"""``frappe.db`` etc.: every attribute access is forwarded to ``frappe.local.<name>``."""

	__slots__ = ("_name",)

	def __init__(self, name: str) -> None:
		object.__setattr__(self, "_name", name)

	def _target(self) -> Any:
		from frappe import local

		target = getattr(local, object.__getattribute__(self, "_name"), None)
		if target is None:
			raise RuntimeError(
				f"frappe stub: frappe.{object.__getattribute__(self, '_name')} is not initialised; "
				"call frappe._stub.reset() (the `site` fixture does it)"
			)
		return target

	def __getattr__(self, key: str) -> Any:
		return getattr(self._target(), key)

	def __setattr__(self, key: str, value: Any) -> None:
		setattr(self._target(), key, value)

	def __delattr__(self, key: str) -> None:
		delattr(self._target(), key)

	def __getitem__(self, key: Any) -> Any:
		return self._target()[key]

	def __setitem__(self, key: Any, value: Any) -> None:
		self._target()[key] = value

	def __delitem__(self, key: Any) -> None:
		del self._target()[key]

	def __contains__(self, key: Any) -> bool:
		return key in self._target()

	def __iter__(self) -> Any:
		return iter(self._target())

	def __len__(self) -> int:
		return len(self._target())

	def __bool__(self) -> bool:
		return bool(self._target())

	def __eq__(self, other: object) -> bool:
		return self._target() == other

	def __hash__(self) -> int:
		return id(self)

	def __repr__(self) -> str:
		return f"<LocalProxy frappe.{object.__getattribute__(self, '_name')} -> {self._target()!r}>"

	def __call__(self, *args: Any, **kwargs: Any) -> Any:
		return self._target()(*args, **kwargs)
