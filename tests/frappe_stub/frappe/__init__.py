"""In-memory Frappe for tests (docs/ARCHITECTURE.md section 8.2).

Importable when ``tests/frappe_stub`` is on ``sys.path`` and the real ``frappe`` is not
installed. The public surface follows frappe/__init__.py (version-16) for everything the
app calls; behaviour that is not mirrored raises ``NotImplementedError`` with a message
rather than returning something plausible. ``frappe._stub.reset()`` creates the site.
"""

from __future__ import annotations

import importlib
import inspect
import json
import logging
import traceback
from typing import Any

from frappe import _stub
from frappe._stub.dictlike import _dict
from frappe._stub.state import DEFAULT_SITE, Local, LocalProxy, Request
from frappe.exceptions import (  # noqa: F401 - re-exported like the real package
	AuthenticationError,
	CancelledLinkError,
	CharacterLengthExceededError,
	DataError,
	DocstatusTransitionError,
	DoesNotExistError,
	DuplicateEntryError,
	InvalidStatusError,
	LinkExistsError,
	LinkValidationError,
	MandatoryError,
	NameError,
	PermissionError,
	RateLimitExceededError,
	SessionExpired,
	TimestampMismatchError,
	UniqueValidationError,
	UpdateAfterSubmitError,
	ValidationError,
)

__version__ = "16.33.0"
in_test = True
STANDARD_USERS = ("Guest", "Administrator")

local: Local = Local(DEFAULT_SITE)
db = LocalProxy("db")
conf = LocalProxy("conf")
form_dict = LocalProxy("form_dict")
request = LocalProxy("request")
response = LocalProxy("response")
session = LocalProxy("session")
flags = LocalProxy("flags")
enqueued = LocalProxy("enqueued")
whitelisted = LocalProxy("whitelisted")


# --- messages ------------------------------------------------------------------------------


def _(txt: Any, lang: str | None = None, context: str | None = None) -> Any:
	"""Identity translation; the app keeps Mongolian strings in nyabo_mn.i18n.mn."""
	return txt


def bold(text: Any) -> str:
	return f"<b>{text}</b>"


def msgprint(
	msg: Any,
	title: str | None = None,
	raise_exception: Any = 0,
	as_table: bool = False,
	as_list: bool = False,
	indicator: str | None = None,
	alert: bool = False,
	primary_action: Any = None,
	is_minimizable: bool = False,
	wide: bool = False,
	*,
	realtime: bool = False,
) -> None:
	if isinstance(msg, (list, tuple)) and as_list:
		msg = "\n".join(str(m) for m in msg)
	entry = _dict(message=str(msg), title=title, indicator=indicator, raise_exception=1 if raise_exception else 0)
	local.message_log.append(entry)
	if raise_exception:
		if inspect.isclass(raise_exception) and issubclass(raise_exception, Exception):
			raise raise_exception(str(msg))
		if isinstance(raise_exception, Exception):
			if not raise_exception.args:
				raise_exception.args = (str(msg),)
			raise raise_exception
		raise ValidationError(str(msg))


def throw(
	msg: Any,
	exc: Any = ValidationError,
	title: str | None = None,
	is_minimizable: bool = False,
	wide: bool = False,
	as_list: bool = False,
	primary_action: Any = None,
) -> None:
	msgprint(msg, raise_exception=exc, title=title, as_list=as_list)


def get_message_log() -> list[_dict]:
	return list(local.message_log)


def clear_messages() -> None:
	local.message_log.clear()


def clear_last_message() -> None:
	if local.message_log:
		local.message_log.pop()


def errprint(msg: Any) -> None:
	local.message_log.append(_dict(message=str(msg), title="error"))


# --- documents ----------------------------------------------------------------------------


def get_meta(doctype: str, cached: bool = True) -> Any:
	meta = local.registry.get(doctype) if local.registry else None
	if meta is None:
		raise DoesNotExistError(f"DocType {doctype} not found (frappe stub knows no meta for it)")
	return meta


def get_doc(*args: Any, **kwargs: Any) -> Any:
	from frappe._stub.controllers import get_controller

	if args and isinstance(args[0], dict):
		doctype = args[0].get("doctype")
		if not doctype:
			raise ValidationError("frappe stub: get_doc(dict) needs a 'doctype' key")
		return get_controller(doctype)(args[0])
	if not args and kwargs:
		doctype = kwargs.get("doctype")
		if not doctype:
			raise ValidationError("frappe stub: get_doc(**kwargs) needs doctype")
		if kwargs.get("name") and len(kwargs) == 2:
			return get_controller(doctype)(doctype, kwargs["name"])
		return get_controller(doctype)(kwargs)
	doctype = args[0]
	if not isinstance(doctype, str):
		raise ValidationError(f"frappe stub: get_doc got {doctype!r}")
	name = args[1] if len(args) > 1 else kwargs.get("name")
	meta = get_meta(doctype)
	if meta.issingle and name is None:
		name = doctype
	if isinstance(name, dict):
		found = db.exists(doctype, name)
		if not found:
			raise DoesNotExistError(f"{doctype} {name} not found")
		name = found
	if name is None:
		raise ValidationError(f"frappe stub: get_doc({doctype!r}) needs a name (use new_doc for a new document)")
	return get_controller(doctype)(doctype, name, for_update=kwargs.get("for_update"))


get_cached_doc = get_doc
get_lazy_doc = get_doc


def get_single(doctype: str) -> Any:
	return get_doc(doctype)


def new_doc(doctype: str, parent_doc: Any = None, parentfield: str | None = None, as_dict: bool = False, **kwargs: Any) -> Any:
	from frappe._stub.controllers import get_controller

	doc = get_controller(doctype)(doctype)
	if parent_doc is not None:
		doc.parent = parent_doc.name
		doc.parenttype = parent_doc.doctype
		doc.parentfield = parentfield
	doc.update(kwargs)
	doc._set_defaults()
	return doc.as_dict() if as_dict else doc


def copy_doc(doc: Any, ignore_no_copy: bool = True) -> Any:
	d = doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)
	meta = get_meta(d["doctype"])
	for key in ("name", "owner", "creation", "modified", "modified_by", "__islocal"):
		d.pop(key, None)
	d["docstatus"] = 0
	if not ignore_no_copy:
		for df in meta.fields:
			if df.get("no_copy"):
				d.pop(df.fieldname, None)
	for df in meta.get_table_fields():
		rows = []
		for row in d.get(df.fieldname) or []:
			row = dict(row)
			for key in ("name", "parent", "owner", "creation", "modified", "modified_by"):
				row.pop(key, None)
			rows.append(row)
		d[df.fieldname] = rows
	return get_doc(d)


def get_all(doctype: str, *args: Any, **kwargs: Any) -> list:
	kwargs.pop("ignore_permissions", None)
	if "limit_page_length" not in kwargs and "limit" not in kwargs:
		kwargs["limit_page_length"] = 0
	return db.get_all(doctype, *args, **kwargs)


def get_list(doctype: str, *args: Any, **kwargs: Any) -> list:
	kwargs.pop("ignore_permissions", None)
	return db.get_all(doctype, *args, **kwargs)


def get_value(*args: Any, **kwargs: Any) -> Any:
	return db.get_value(*args, **kwargs)


def get_cached_value(doctype: str, name: Any, fieldname: Any = "name", as_dict: bool = False) -> Any:
	return db.get_value(doctype, name, fieldname, as_dict=as_dict)


def get_single_value(doctype: str, fieldname: str) -> Any:
	return db.get_single_value(doctype, fieldname)


def get_system_settings(key: str) -> Any:
	return db.get_single_value("System Settings", key)


def get_last_doc(doctype: str, filters: Any = None, order_by: str = "creation desc", *, for_update: bool = False) -> Any:
	names = get_all(doctype, filters=filters, order_by=order_by, limit=1, pluck="name")
	if not names:
		raise DoesNotExistError(f"{doctype} not found")
	return get_doc(doctype, names[0])


def delete_doc(
	doctype: str | None = None,
	name: Any = None,
	force: bool = False,
	ignore_doctypes: list[str] | None = None,
	for_reload: bool = False,
	ignore_permissions: bool = False,
	flags: Any = None,
	ignore_on_trash: bool = False,
	ignore_missing: bool = True,
	delete_permanently: bool = False,
) -> Any:
	from frappe.model.delete_doc import delete_doc as _delete

	return _delete(
		doctype,
		name,
		force=force,
		ignore_doctypes=ignore_doctypes,
		for_reload=for_reload,
		ignore_permissions=ignore_permissions,
		flags=flags,
		ignore_on_trash=ignore_on_trash,
		ignore_missing=ignore_missing,
		delete_permanently=delete_permanently,
	)


def delete_doc_if_exists(doctype: str, name: str, force: bool = False) -> None:
	if db.exists(doctype, name):
		delete_doc(doctype, name, force=force, ignore_permissions=True)


def rename_doc(*args: Any, **kwargs: Any) -> Any:
	raise NotImplementedError("frappe stub: rename_doc is not implemented")


def generate_hash(txt: str | None = None, length: int = 56) -> str:
	import secrets

	return secrets.token_hex(max(1, (length + 1) // 2))[:length]


# --- hooks, modules, jobs -----------------------------------------------------------------


def get_hooks(hook: str | None = None, default: Any = "_KEEP_DEFAULT_LIST", app_name: str | None = None) -> Any:
	from frappe._stub.hooks import get_hooks as _get_hooks

	return _get_hooks(hook, default, app_name)


def get_doc_hooks() -> dict[str, dict[str, list[str]]]:
	from frappe._stub.hooks import get_doc_hooks as _get_doc_hooks

	return _get_doc_hooks()


def clear_cache(doctype: str | None = None, user: str | None = None) -> None:
	from frappe._stub.hooks import clear_hooks_cache

	clear_hooks_cache()
	local.role_cache.clear()


def get_installed_apps(*, _ensure_on_bench: bool = False) -> list[str]:
	from frappe._stub.hooks import INSTALLED_APPS

	return list(INSTALLED_APPS)


def get_module(modulename: str) -> Any:
	return importlib.import_module(modulename)


def get_attr(method_string: str) -> Any:
	"""Import ``package.module.function``; a missing module or name names the full dotted path."""
	module_name, _sep, attr = method_string.rpartition(".")
	if not module_name:
		raise ImportError(f"frappe stub: {method_string!r} is not a dotted path")
	try:
		module = importlib.import_module(module_name)
	except ImportError as exc:
		raise ImportError(f"frappe stub: cannot import hook handler {method_string!r}: {exc}") from exc
	try:
		return getattr(module, attr)
	except AttributeError as exc:
		raise AttributeError(f"frappe stub: {module_name} has no attribute {attr!r} (handler {method_string!r})") from exc


def call(fn: Any, *args: Any, **kwargs: Any) -> Any:
	if isinstance(fn, str):
		fn = get_attr(fn)
	params = inspect.signature(fn).parameters
	if any(p.kind == p.VAR_KEYWORD for p in params.values()):
		return fn(*args, **kwargs)
	return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


def get_app_path(app_name: str, *joins: str) -> str:
	module = importlib.import_module(app_name)
	import os

	return os.path.join(os.path.dirname(module.__file__), *joins)


def get_module_path(module: str, *joins: str) -> str:
	app = local.module_app.get(module)
	if not app:
		raise DoesNotExistError(f"frappe stub: module {module!r} belongs to no installed app")
	return get_app_path(app, scrub(module), *joins)


def get_site_path(*joins: str) -> str:
	import os

	return os.path.join(local.site_path, *joins)


def get_pymodule_path(modulename: str, *joins: str) -> str:
	import os

	module = importlib.import_module(modulename)
	return os.path.join(os.path.dirname(module.__file__), *joins)


def enqueue(
	method: Any,
	queue: str = "default",
	timeout: int | None = None,
	event: str | None = None,
	is_async: bool = True,
	job_name: str | None = None,
	now: bool = False,
	enqueue_after_commit: bool = False,
	*,
	at_front: bool = False,
	job_id: str | None = None,
	deduplicate: bool = False,
	**kwargs: Any,
) -> Any:
	"""Runs the job inline (also when ``enqueue_after_commit`` is set) and records the call."""
	fn = get_attr(method) if isinstance(method, str) else method
	record = _dict(
		method=method if isinstance(method, str) else f"{fn.__module__}.{fn.__qualname__}",
		queue=queue,
		timeout=timeout,
		job_name=job_name or job_id,
		enqueue_after_commit=enqueue_after_commit,
		kwargs=dict(kwargs),
		result=None,
	)
	local.enqueued.append(record)
	record.result = fn(**kwargs)
	return _dict(id=job_id or job_name or record.method, result=record.result, is_finished=True)


def enqueue_doc(doctype: str, name: str, method: str, queue: str = "default", timeout: int | None = None, now: bool = False, **kwargs: Any) -> Any:
	doc = get_doc(doctype, name)
	return enqueue(getattr(doc, method), queue=queue, timeout=timeout, now=now, job_name=f"{doctype}:{name}:{method}", **kwargs)


def whitelist(allow_guest: bool = False, xss_safe: bool = False, methods: Any = None) -> Any:
	def decorator(fn: Any) -> Any:
		fn.is_whitelisted = True
		fn.allow_guest = allow_guest
		fn.xss_safe = xss_safe
		fn.allowed_http_methods = methods
		local.whitelisted.add(fn)
		return fn

	return decorator


def is_whitelisted(method: Any) -> None:
	if not getattr(method, "is_whitelisted", False):
		raise PermissionError(f"{getattr(method, '__name__', method)} is not whitelisted")


def read_only() -> Any:
	def decorator(fn: Any) -> Any:
		return fn

	return decorator


def request_cache(fn: Any) -> Any:
	return fn


# --- users and permissions ------------------------------------------------------------------


def set_user(username: str) -> None:
	local.session.user = username
	local.session.sid = username
	local.role_cache.clear()


def get_roles(username: str | None = None) -> list[str]:
	user = username or local.session.user
	if user in local.role_cache:
		return list(local.role_cache[user])
	if user == "Administrator":
		roles = get_all("Role", pluck="name")
		if "Administrator" not in roles:
			roles.append("Administrator")
	elif user == "Guest" or not user:
		roles = ["Guest"]
	else:
		roles = ["All", "Guest"]
		if db.exists("User", user):
			roles += get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role")
	roles = list(dict.fromkeys(r for r in roles if r))
	local.role_cache[user] = roles
	return list(roles)


def get_user() -> Any:
	user = local.session.user
	return _dict(name=user, roles=get_roles(user), get_roles=lambda: get_roles(user))


def has_permission(
	doctype: str | None = None,
	ptype: str = "read",
	doc: Any = None,
	user: str | None = None,
	throw: bool = False,  # noqa: A002 - Frappe signature
	*,
	parent_doctype: str | None = None,
	debug: bool = False,
	ignore_share_permissions: bool = False,
) -> bool:
	"""Role table of the DocType JSON, permlevel 0. Administrator can do everything."""
	if doc is not None and doctype is None:
		doctype = doc.doctype if hasattr(doc, "doctype") else None
	if doctype is None:
		raise ValidationError("frappe stub: has_permission needs a doctype or a doc")
	user = user or local.session.user
	if user == "Administrator":
		return True
	meta = get_meta(doctype)
	if meta.istable:
		return True
	roles = set(get_roles(user))
	allowed = False
	for perm in meta.permissions:
		if perm.get("permlevel", 0):
			continue
		if perm.role in roles and perm.get(ptype):
			allowed = True
			break
	if not allowed and throw:
		raise PermissionError(f"No permission for {doctype} ({ptype})")
	return allowed


def only_for(roles: Any, message: bool = False) -> None:
	if local.session.user == "Administrator":
		return
	if isinstance(roles, str):
		roles = [roles]
	if not set(roles).intersection(get_roles()):
		raise PermissionError(
			f"This action is only allowed for {', '.join(roles)}" if message else "Not permitted"
		)


def has_website_permission(*args: Any, **kwargs: Any) -> bool:
	return False


# --- logging, errors --------------------------------------------------------------------------


def logger(
	module: str | None = None,
	with_more_info: bool = False,
	allow_site: bool = True,
	filter: Any = None,  # noqa: A002 - Frappe signature
	max_size: int = 100_000,
	file_count: int = 20,
) -> logging.Logger:
	return logging.getLogger(f"frappe.{module}" if module else "frappe")


def get_traceback(with_context: bool = False) -> str:
	return traceback.format_exc()


def log_error(
	title: str | None = None,
	message: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	*,
	defer_insert: bool = False,
) -> Any:
	if message is None:
		message = get_traceback()
	entry = _dict(title=title, message=message, reference_doctype=reference_doctype, reference_name=reference_name)
	local.error_log.append(entry)
	doc = get_doc(
		{
			"doctype": "Error Log",
			"method": title,
			"error": message,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert()
	return doc


def publish_realtime(*args: Any, **kwargs: Any) -> None:
	_stub.record_call("publish_realtime", args=args, kwargs=kwargs)


def sendmail(**kwargs: Any) -> None:
	_stub.record_call("sendmail", **kwargs)


# --- templates, json, misc ---------------------------------------------------------------------


def render_template(template: str, context: dict[str, Any] | None = None, is_path: bool | None = None, safe_render: bool = True) -> str:
	"""Jinja2 with ``_`` and ``frappe`` in the context; a ``.html`` path is read from the app."""
	try:
		import jinja2
	except ImportError as exc:  # pragma: no cover - environment problem, not a test outcome
		raise ImportError("frappe stub: render_template needs jinja2 (pip install jinja2)") from exc
	import os
	import sys

	context = dict(context or {})
	context.setdefault("_", _)
	context.setdefault("frappe", sys.modules[__name__])
	if is_path or (is_path is None and template.endswith(".html") and "\n" not in template and "{" not in template):
		parts = template.split("/")
		path = get_app_path(parts[0], *parts[1:]) if len(parts) > 1 else template
		if not os.path.exists(path):
			raise DoesNotExistError(f"frappe stub: template {template!r} not found at {path}")
		with open(path, encoding="utf-8") as f:
			template = f.read()
	env = jinja2.Environment(autoescape=False, undefined=jinja2.Undefined if safe_render else jinja2.StrictUndefined)
	return env.from_string(template).render(**context)


def scrub(txt: str) -> str:
	return str(txt).replace(" ", "_").replace("-", "_").lower()


def unscrub(txt: str) -> str:
	return str(txt).replace("_", " ").replace("-", " ").title()


def as_json(obj: Any, indent: int | None = 1, separators: Any = None, ensure_ascii: bool = True) -> str:
	from frappe.utils.data import json_default

	return json.dumps(obj, indent=indent, sort_keys=True, default=json_default, separators=separators, ensure_ascii=ensure_ascii)


def parse_json(val: Any) -> Any:
	if isinstance(val, str):
		return json.loads(val, object_hook=_dict)
	if isinstance(val, dict):
		return _dict(val)
	return val


def as_unicode(text: Any, encoding: str = "utf-8") -> str:
	if isinstance(text, bytes):
		return text.decode(encoding)
	return str(text)


def safe_decode(text: Any, encoding: str = "utf-8") -> Any:
	return text.decode(encoding) if isinstance(text, bytes) else text


def safe_encode(text: Any, encoding: str = "utf-8") -> Any:
	return text.encode(encoding) if isinstance(text, str) else text


def format(value: Any, df: Any = None, doc: Any = None, currency: str | None = None, **kwargs: Any) -> str:  # noqa: A001 - Frappe name
	from frappe.utils.data import fmt_money, formatdate

	fieldtype = df if isinstance(df, str) else (df.get("fieldtype") if df else None)
	if fieldtype == "Date" and value not in (None, ""):
		return formatdate(value)
	if fieldtype == "Currency" and value not in (None, ""):
		return fmt_money(value, currency=currency)
	return "" if value is None else str(value)


format_value = format


def get_request_header(key: str, default: Any = None) -> Any:
	return local.request.headers.get(key, default) if local.request else default


def get_url(uri: str | None = None, full_address: bool = False) -> str:
	from frappe.utils.data import get_url as _get_url

	return _get_url(uri, full_address)


def utcnow() -> Any:
	import datetime

	return datetime.datetime.now(datetime.timezone.utc)


class _Cache:
	"""Dict-backed stand-in for the Redis wrapper (``frappe.cache`` is callable for old code)."""

	def __call__(self) -> _Cache:
		return self

	def _store(self) -> dict:
		return local.cache_store

	def get_value(self, key: Any, generator: Any = None, user: Any = None, expires: bool = False, shared: bool = False) -> Any:
		store = self._store()
		if key in store:
			return store[key]
		if generator:
			store[key] = generator()
			return store[key]
		return None

	def set_value(self, key: Any, val: Any, user: Any = None, expires_in_sec: int | None = None, shared: bool = False) -> None:
		self._store()[key] = val

	def delete_value(self, keys: Any, user: Any = None, make_keys: bool = True, shared: bool = False) -> None:
		for key in keys if isinstance(keys, (list, tuple, set)) else [keys]:
			self._store().pop(key, None)

	delete_key = delete_value

	def get(self, key: Any) -> Any:
		return self._store().get(key)

	def set(self, key: Any, val: Any, **kwargs: Any) -> None:
		self._store()[key] = val

	def setex(self, name: Any, time: Any, value: Any) -> None:
		self._store()[name] = value

	def exists(self, key: Any) -> bool:
		return key in self._store()

	def hget(self, name: Any, key: Any, generator: Any = None, shared: bool = False) -> Any:
		bucket = self._store().setdefault(("h", name), {})
		if key in bucket:
			return bucket[key]
		if generator:
			bucket[key] = generator()
			return bucket[key]
		return None

	def hset(self, name: Any, key: Any, value: Any, shared: bool = False) -> None:
		self._store().setdefault(("h", name), {})[key] = value

	def hdel(self, name: Any, key: Any, shared: bool = False) -> None:
		self._store().setdefault(("h", name), {}).pop(key, None)

	def hgetall(self, name: Any) -> dict:
		return dict(self._store().get(("h", name), {}))

	def delete_keys(self, pattern: str) -> None:
		for key in [k for k in self._store() if isinstance(k, str) and k.startswith(pattern.rstrip("*"))]:
			del self._store()[key]

	def flushall(self) -> None:
		self._store().clear()


cache = _Cache()


def local_cache(namespace: str, key: Any, generator: Any, regenerate_if_none: bool = False) -> Any:
	return cache.hget(namespace, key, generator=generator)


class _Defaults:
	"""``frappe.defaults`` subset: global and user defaults share one dict in the stub."""

	@staticmethod
	def get_global_default(key: str) -> Any:
		return db.get_default(key)

	@staticmethod
	def get_user_default(key: str, user: str | None = None) -> Any:
		return db.get_default(key)

	@staticmethod
	def get_defaults(user: str | None = None) -> _dict:
		return _dict(db.defaults)

	@staticmethod
	def set_global_default(key: str, value: Any) -> None:
		db.set_default(key, value)

	@staticmethod
	def set_user_default(key: str, value: Any, user: str | None = None, parenttype: str | None = None) -> None:
		db.set_default(key, value)

	@staticmethod
	def clear_user_default(key: str, user: str | None = None) -> None:
		db.defaults.pop(key, None)

	@staticmethod
	def clear_default(*args: Any, **kwargs: Any) -> None:
		return None


defaults = _Defaults()


def init(site: str = DEFAULT_SITE, sites_path: str = ".", new_site: bool = False, force: bool = False) -> None:
	"""On a bench ``frappe.init`` + ``frappe.connect`` open the site; here ``_stub.reset`` does both."""
	_stub.reset(site)


def connect(site: str | None = None, db_name: str | None = None, set_admin_as_user: bool = True) -> None:
	if local.db is None:
		_stub.reset(site or DEFAULT_SITE)


def destroy() -> None:
	if isinstance(local, Local):
		local.destroy()


__all__ = [name for name in dir() if not name.startswith("__")]
__all__ += ["Request", "_dict", "_stub"]
