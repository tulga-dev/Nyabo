"""``frappe.model.document.Document`` for the in-memory site.

The lifecycle follows frappe/model/document.py and base_document.py (version-16):
insert = defaults -> permission -> links -> before_insert -> naming -> validate /
before_save -> mandatory & selects -> rows -> after_insert -> on_update -> Version;
save on an existing document derives ``_action`` from the docstatus transition
(save / submit / update_after_submit / cancel) and runs the matching triggers; hooks from
``doc_events`` run after the controller method with ``(doc, method)``.

Two deliberate deviations, both there to make tests stricter than a real site would be:
setting a field the DocType does not have raises ``ValidationError`` (Frappe would drop it
silently on save), and Link targets are only checked when the target table has rows,
unless ``frappe.flags.stub_strict_links`` is set.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from frappe._stub.dictlike import _dict
from frappe._stub.meta import (
	CHILD_TABLE_FIELDS,
	DEFAULT_FIELDS,
	NO_VALUE_FIELDS,
	TABLE_FIELDS,
)
from frappe._stub.values import cast_for_storage, is_empty
from frappe.exceptions import (
	CancelledLinkError,
	DocstatusTransitionError,
	DoesNotExistError,
	LinkValidationError,
	MandatoryError,
	PermissionError,
	UpdateAfterSubmitError,
	ValidationError,
)
from frappe.model.docstatus import DocStatus
from frappe.utils.data import cint, cstr, flt, get_datetime, getdate, now_datetime, nowdate, nowtime

# Attributes a Document may carry that are not DocType fields (frappe/model/base_document.py
# keeps them in __dict__ too). Private names (leading underscore) are always allowed.
DOCUMENT_ATTRS = frozenset(
	{
		"doctype",
		"flags",
		"dont_update_if_missing",
		"ignore_linked_doctypes",
		"ignore_children_type",
		"ignore_validate_update_after_submit",
		"ignore_in_setter",
		"in_reference_doctype",
		"__islocal",
		"__unsaved",
		"__onload",
		"__run_link_triggers",
	}
)
RESERVED_KEYWORDS = frozenset(
	{"meta", "as_dict", "get", "set", "append", "save", "insert", "submit", "cancel"}
)


class Document:
	"""An in-memory Frappe document. Subclass in DocType controllers exactly like on a site."""

	# Controllers may declare extra non-field attributes they set on self.
	_stub_extra_fields: frozenset[str] = frozenset()

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		object.__setattr__(self, "flags", _dict())
		object.__setattr__(self, "dont_update_if_missing", [])
		object.__setattr__(self, "_doc_before_save", None)
		object.__setattr__(self, "_action", None)
		object.__setattr__(self, "_parent_doc", None)
		if args and isinstance(args[0], str):
			object.__setattr__(self, "doctype", args[0])
			self._init_fields()
			if len(args) > 1 or kwargs.get("name"):
				self.name = args[1] if len(args) > 1 else kwargs["name"]
				if kwargs.get("for_update"):
					self.flags.for_update = True
				self.load_from_db()
			else:
				self.name = None
				self.set("__islocal", True)
		elif args and isinstance(args[0], dict):
			d = dict(args[0])
			if not d.get("doctype"):
				raise ValidationError("frappe stub: get_doc(dict) needs a 'doctype' key")
			object.__setattr__(self, "doctype", d["doctype"])
			self._init_fields()
			self.update(d)
			if not d.get("name"):
				self.set("__islocal", True)
		elif kwargs:
			d = dict(kwargs)
			object.__setattr__(self, "doctype", d.get("doctype") or type(self).__name__)
			self._init_fields()
			self.update(d)
			if not d.get("name"):
				self.set("__islocal", True)
		else:
			raise ValidationError("frappe stub: Document needs a doctype, a name or a dict")
		if hasattr(self, "__setup__"):
			self.__setup__()

	# --- attribute plumbing -----------------------------------------------------------

	def _init_fields(self) -> None:
		"""Every data field starts as None so ``doc.field`` never raises AttributeError."""
		meta = self.meta
		fieldnames = [df.fieldname for df in meta.fields if df.fieldtype not in NO_VALUE_FIELDS]
		object.__setattr__(self, "_table_fieldnames", {df.fieldname for df in meta.get_table_fields()})
		for key in DEFAULT_FIELDS:
			if key != "doctype":
				object.__setattr__(self, key, None)
		for key in fieldnames:
			object.__setattr__(self, key, None)
		for key in self._table_fieldnames:
			object.__setattr__(self, key, [])
		object.__setattr__(self, "docstatus", DocStatus(0))
		object.__setattr__(self, "idx", 0)

	@property
	def meta(self) -> Any:
		import frappe

		return frappe.get_meta(self.doctype)

	def _allowed_attr(self, key: str) -> bool:
		if (
			key.startswith("_")
			or key in DEFAULT_FIELDS
			or key in DOCUMENT_ATTRS
			or key in self._stub_extra_fields
		):
			return True
		meta = self.meta
		if meta.get("permissive"):
			return True
		return meta.has_field(key)

	def __setattr__(self, key: str, value: Any) -> None:
		if not self._allowed_attr(key):
			raise ValidationError(
				f"frappe stub: {self.doctype} has no field {key!r}; check the fieldname against the DocType "
				"JSON (custom fields from nyabo_mn.setup.custom_fields are merged at reset). Controllers may "
				"declare non-field attributes in `_stub_extra_fields` or use a leading underscore."
			)
		if key == "docstatus":
			value = DocStatus(cint(value))
		object.__setattr__(self, key, value)

	def __getattr__(self, key: str) -> Any:
		# Only reached for attributes missing from __dict__: mirror Frappe, which returns None
		# for unset fields but raises for unknown names (so typos on reads fail loudly too).
		if key.startswith("__"):
			raise AttributeError(key)
		try:
			doctype = object.__getattribute__(self, "doctype")
		except AttributeError:
			raise AttributeError(key) from None
		import frappe

		meta = frappe.get_meta(doctype)
		if meta.get("permissive") or meta.has_field(key) or key in DEFAULT_FIELDS:
			return None
		raise AttributeError(f"{doctype} has no field or attribute {key!r}")

	def __repr__(self) -> str:
		return f"<{type(self).__name__}: {self.doctype} {self.name or '(new)'}>"

	def __str__(self) -> str:
		return f"{self.doctype} {self.name or '(new)'}"

	# --- get / set API -----------------------------------------------------------------

	def update(self, d: dict[str, Any]) -> Document:
		for key, value in d.items():
			if key in RESERVED_KEYWORDS:
				continue
			self.set(key, value)
		return self

	def update_if_missing(self, d: dict[str, Any]) -> Document:
		for key, value in d.items():
			if value is not None and is_empty(self.get(key)):
				self.set(key, value)
		return self

	def get(self, key: Any, filters: Any = None, limit: int | None = None, default: Any = None) -> Any:
		if isinstance(key, dict):
			return _filter(self.get_all_children(), key, limit=limit)
		if filters:
			if isinstance(filters, dict):
				return _filter(self.__dict__.get(key, []), filters, limit=limit)
			default = filters
		value = self.__dict__.get(key, default)
		if limit and isinstance(value, (list, tuple)) and len(value) > limit:
			value = value[:limit]
		return value

	def get_value(self, fieldname: str) -> Any:
		return self.get(fieldname)

	def set(self, key: str, value: Any, as_value: bool = False) -> None:
		if key in RESERVED_KEYWORDS:
			return
		if not as_value and key in self._table_fieldnames:
			object.__setattr__(self, key, [])
			if value:
				self.extend(key, value)
			return
		setattr(self, key, value)

	def append(self, key: str, value: Any = None, position: int = -1) -> Document:
		if value is None:
			value = {}
		if key not in self._table_fieldnames:
			raise ValidationError(f"frappe stub: {self.doctype} has no child table {key!r}")
		table = self.__dict__.setdefault(key, [])
		d = self._init_child(value, key)
		if position == -1:
			table.append(d)
			if not getattr(d, "idx", 0):
				d.idx = len(table)
		else:
			table.insert(position, d)
			for i, row in enumerate(table, 1):
				row.idx = i
		d._parent_doc = self
		return d

	def extend(self, key: str, value: Any) -> None:
		try:
			value = iter(value)
		except TypeError as exc:
			raise ValueError(f"frappe stub: {key} must be a list of rows") from exc
		for v in value:
			self.append(key, v)

	def remove(self, doc: Document) -> None:
		table = self.get(doc.parentfield) or []
		if doc in table:
			table.remove(doc)
		for i, row in enumerate(table, 1):
			row.idx = i

	def _init_child(self, value: Any, key: str) -> Document:
		from frappe._stub.controllers import get_controller

		df = self.meta.get_field(key)
		child_doctype = df.options
		if isinstance(value, Document):
			if value.doctype != child_doctype:
				raise ValidationError(f"frappe stub: {key} takes {child_doctype} rows, not {value.doctype}")
			child = value
		else:
			payload = dict(value)
			payload["doctype"] = child_doctype
			child = get_controller(child_doctype)(payload)
		child.parent = self.name
		child.parenttype = self.doctype
		child.parentfield = key
		if not child.name:
			child.set("__islocal", True)
		return child

	def get_all_children(self, parenttype: str | None = None) -> list[Document]:
		out: list[Document] = []
		for fieldname in self._table_fieldnames:
			for row in self.get(fieldname) or []:
				if parenttype is None or row.doctype == parenttype:
					out.append(row)
		return out

	def get_parentfield_of_doctype(self, doctype: str) -> str | None:
		for df in self.meta.get_table_fields():
			if df.options == doctype:
				return df.fieldname
		return None

	def is_new(self) -> bool:
		return bool(self.get("__islocal"))

	def get_field(self, fieldname: str) -> Any:
		return self.meta.get_field(fieldname)

	def precision(self, fieldname: str, parentfield: str | None = None) -> int:
		if parentfield:
			df = self.meta.get_field(parentfield)
			import frappe

			child_meta = frappe.get_meta(df.options)
			return child_meta.get_field_precision(child_meta.get_field(fieldname))
		df = self.meta.get_field(fieldname)
		if df is None:
			return 2
		return self.meta.get_field_precision(df)

	def get_title(self) -> str:
		return cstr(self.get("title") or self.name)

	def get_url(self) -> str:
		return f"/app/{self.doctype.lower().replace(' ', '-')}/{self.name}"

	def set_onload(self, key: str, value: Any) -> None:
		onload = self.get("__onload") or _dict()
		onload[key] = value
		self.set("__onload", onload)

	def get_onload(self, key: str | None = None) -> Any:
		onload = self.get("__onload") or _dict()
		return onload if key is None else onload.get(key)

	def get_valid_dict(
		self,
		sanitize: bool = True,
		convert_dates_to_str: bool = False,
		ignore_nulls: bool = False,
		ignore_virtual: bool = False,
	) -> _dict:
		d = _dict()
		for key in DEFAULT_FIELDS:
			if key == "doctype":
				continue
			value = self.get(key)
			if key == "docstatus":
				value = int(value or 0)
			d[key] = value
		for df in self.meta.fields:
			if df.fieldtype in NO_VALUE_FIELDS:
				continue
			value = self.get(df.fieldname)
			if df.fieldtype == "Check":
				value = 1 if cint(value) else 0
			elif df.fieldtype == "Int" and value is not None:
				value = cint(value)
			elif (
				df.fieldtype in ("Currency", "Float", "Percent")
				and value is not None
				and not isinstance(value, float)
			):
				value = flt(value)
			elif df.fieldtype == "JSON" and isinstance(value, (dict, list)):
				value = json.dumps(value, ensure_ascii=False)
			elif isinstance(value, list):
				raise ValidationError(f"Value for {df.label or df.fieldname} cannot be a list")
			if convert_dates_to_str and hasattr(value, "isoformat"):
				value = str(value)
			if ignore_nulls and value is None:
				continue
			d[df.fieldname] = value
		return d

	def as_dict(
		self,
		no_nulls: bool = False,
		no_default_fields: bool = False,
		convert_dates_to_str: bool = False,
		no_child_table_fields: bool = False,
		no_private_properties: bool = False,
		**kwargs: Any,
	) -> _dict:
		doc = self.get_valid_dict(convert_dates_to_str=convert_dates_to_str, ignore_nulls=no_nulls)
		doc["doctype"] = self.doctype
		for fieldname in self._table_fieldnames:
			doc[fieldname] = [
				row.as_dict(
					no_nulls=no_nulls,
					no_default_fields=no_default_fields,
					convert_dates_to_str=convert_dates_to_str,
					no_child_table_fields=no_child_table_fields,
					no_private_properties=no_private_properties,
				)
				for row in self.get(fieldname) or []
			]
		if no_default_fields:
			for key in DEFAULT_FIELDS:
				doc.pop(key, None)
		if no_child_table_fields:
			for key in CHILD_TABLE_FIELDS:
				doc.pop(key, None)
		if not no_private_properties:
			for key in ("__islocal", "__onload", "__unsaved"):
				value = self.get(key)
				if value:
					doc[key] = value
		return doc

	def as_json(self) -> str:
		import frappe

		return frappe.as_json(self.as_dict(convert_dates_to_str=True))

	def copy(self) -> Document:
		import frappe

		return frappe.copy_doc(self)

	# --- permissions -------------------------------------------------------------------

	def has_permission(self, permtype: str = "read", debug: bool = False, user: str | None = None) -> bool:
		if self.flags.ignore_permissions:
			return True
		import frappe

		return frappe.has_permission(self.doctype, permtype, self, user=user)

	def check_permission(self, permtype: str = "read", permlevel: Any = None) -> None:
		if not self.has_permission(permtype):
			self.raise_no_permission_to(permtype)

	def raise_no_permission_to(self, perm_type: str) -> None:
		import frappe

		frappe.flags.error_message = f"Insufficient Permission for {self.doctype}"
		raise PermissionError(f"No permission for {perm_type} on {self.doctype} {self.name or ''}".strip())

	# --- defaults, users, timestamps ----------------------------------------------------

	def _set_defaults(self) -> None:
		"""Fill empty fields with the DocType defaults (Frappe does this on save too, not only insert)."""
		import frappe

		for df in self.meta.fields:
			if df.fieldtype in NO_VALUE_FIELDS or df.fieldname in self.dont_update_if_missing:
				continue
			if not is_empty(self.get(df.fieldname)):
				continue
			default = df.get("default")
			if default in (None, ""):
				continue
			value = _resolve_default(self, df, default, frappe)
			if value is not None:
				self.set(df.fieldname, value)
		for child in self.get_all_children():
			child._set_defaults()

	def set_user_and_timestamp(self) -> None:
		import frappe

		now = now_datetime()
		user = frappe.session.user
		if self.is_new() or not self.get("owner"):
			self.owner = user
		if self.is_new() or not self.get("creation"):
			self.creation = now
		self.modified = now
		self.modified_by = user
		for child in self.get_all_children():
			child.owner = child.owner or user
			child.creation = child.creation or now
			child.modified = now
			child.modified_by = user

	def set_docstatus(self) -> None:
		self.docstatus = DocStatus(cint(self.docstatus))
		for child in self.get_all_children():
			child.docstatus = self.docstatus

	def set_parent_in_children(self) -> None:
		for fieldname in self._table_fieldnames:
			for row in self.get(fieldname) or []:
				row.parent = self.name
				row.parenttype = self.doctype
				row.parentfield = fieldname
				row._parent_doc = self

	def set_name_in_children(self) -> None:
		import frappe

		for row in self.get_all_children():
			if not row.name:
				row.name = frappe.generate_hash(length=10)

	def set_new_name(
		self, force: bool = False, set_name: str | None = None, set_child_names: bool = True
	) -> None:
		from frappe.model.naming import set_new_name

		if self.flags.name_set and not force:
			return
		set_new_name(self, set_name=set_name)
		if set_child_names:
			self.set_name_in_children()
		self.flags.name_set = True

	# --- validation ---------------------------------------------------------------------

	def check_if_latest(self) -> None:
		import frappe

		if self.is_new():
			self.check_docstatus_transition(0)
			return
		row = frappe.db.table(self.doctype).get(self.name) if not self.meta.issingle else None
		if row is None and not self.meta.issingle:
			raise DoesNotExistError(f"{self.doctype} {self.name} not found")
		self.check_docstatus_transition(int((row or {}).get("docstatus") or 0))

	def check_docstatus_transition(self, db_docstatus: int) -> None:
		mine = int(self.docstatus)
		if db_docstatus == 0:
			if mine == 0:
				self._action = "save"
			elif mine == 1:
				self._action = "submit"
				self.check_permission("submit")
			elif mine == 2:
				raise DocstatusTransitionError("Cannot change docstatus from 0 (Draft) to 2 (Cancelled)")
			else:
				raise ValidationError(f"Invalid docstatus {mine}")
		elif db_docstatus == 1:
			if mine == 1:
				self._action = "update_after_submit"
				self.check_permission("submit")
			elif mine == 2:
				self._action = "cancel"
				self.check_permission("cancel")
			elif mine == 0:
				raise DocstatusTransitionError("Cannot change docstatus from 1 (Submitted) to 0 (Draft)")
			else:
				raise ValidationError(f"Invalid docstatus {mine}")
		elif db_docstatus == 2:
			raise ValidationError("Cannot edit cancelled document")

	def _validate_links(self) -> None:
		if self.flags.ignore_links or self._action == "cancel":
			return
		invalid: list[str] = []
		cancelled: list[str] = []
		for doc in [self, *self.get_all_children()]:
			bad, gone = doc.get_invalid_links(is_submittable=self.meta.is_submittable)
			invalid.extend(m for _, _, m in bad)
			cancelled.extend(m for _, _, m in gone)
		if invalid:
			raise LinkValidationError("Could not find " + ", ".join(invalid))
		if cancelled:
			raise CancelledLinkError("Cannot link cancelled document: " + ", ".join(cancelled))

	def get_invalid_links(self, is_submittable: bool = False) -> tuple[list, list]:
		import frappe

		strict = frappe.flags.get("stub_strict_links")
		invalid: list = []
		cancelled: list = []
		for df in self.meta.get_link_fields() + self.meta.get_dynamic_link_fields():
			docname = self.get(df.fieldname)
			if not docname:
				continue
			if df.fieldtype == "Link":
				doctype = df.options
				if not doctype:
					raise ValidationError(f"Options not set for link field {df.fieldname}")
			else:
				doctype = self.get(df.options)
				if not doctype:
					raise ValidationError(f"{self.meta.get_label(df.options)} must be set first")
			if strict is False:
				continue
			target = frappe._stub.registry().get(doctype)
			if target is None:
				if strict:
					raise DoesNotExistError(
						f"frappe stub: {self.doctype}.{df.fieldname} links to {doctype!r}, which has no meta in the stub"
					)
				continue
			if doctype == "DocType" and not strict:
				continue  # the stub's DocType table is only a partial view of a real site
			if target.issingle:
				continue
			table = frappe.db.table(doctype)
			if not table and not strict:
				continue
			row = table.get(docname)
			label = (
				f"Row #{self.idx}: {df.label}: {docname}"
				if self.get("parentfield")
				else f"{df.label}: {docname}"
			)
			if row is None:
				invalid.append((df.fieldname, docname, label))
			elif (
				df.fieldname != "amended_from"
				and is_submittable
				and target.is_submittable
				and int(row.get("docstatus") or 0) == 2
			):
				cancelled.append((df.fieldname, docname, label))
		return invalid, cancelled

	def _get_missing_mandatory_fields(self) -> list[tuple[str, str]]:
		missing: list[tuple[str, str]] = []
		for df in self.meta.fields:
			if not df.get("reqd") or df.fieldtype in NO_VALUE_FIELDS and df.fieldtype not in TABLE_FIELDS:
				continue
			value = self.get(df.fieldname)
			if df.fieldtype == "Check":
				continue
			if value in (None, [], "") or (isinstance(value, str) and not value.strip()):
				if df.fieldtype in TABLE_FIELDS:
					msg = f"Error: Data missing in table {df.label}"
				elif self.get("parentfield"):
					msg = f"Error: {self.doctype} Row #{self.idx}: Value missing for: {df.label}"
				else:
					msg = f"Error: Value missing for {self.doctype}: {df.label}"
				missing.append((df.fieldname, msg))
		if self.meta.istable:
			for fieldname in ("parent", "parenttype"):
				if not self.get(fieldname):
					missing.append((fieldname, f"Error: Value missing for {self.doctype}: {fieldname}"))
		return missing

	def _validate_mandatory(self) -> None:
		if self.flags.ignore_mandatory:
			return
		missing = self._get_missing_mandatory_fields()
		for child in self.get_all_children():
			missing.extend(child._get_missing_mandatory_fields())
		if not missing:
			return
		import frappe

		for _, msg in missing:
			frappe.msgprint(msg)
		raise MandatoryError(
			"[{doctype}, {name}]: {fields}; {messages}".format(
				doctype=self.doctype,
				name=self.name,
				fields=", ".join(f for f, _ in missing),
				messages=" | ".join(m for _, m in missing),
			)
		)

	def _validate_selects(self) -> None:
		for df in self.meta.fields:
			if df.fieldtype != "Select" or df.fieldname == "naming_series" or not df.options:
				continue
			value = self.get(df.fieldname)
			if value in (None, ""):
				continue
			options = (df.options or "").split("\n")
			if not [o for o in options if o]:
				continue
			value = cstr(value).strip()
			self.set(df.fieldname, value)
			if value not in options:
				prefix = f"Row #{self.idx}: " if self.get("parentfield") else ""
				raise ValidationError(
					f'{prefix}{self.meta.get_label(df.fieldname)} cannot be "{value}". It should be one of "'
					+ '", "'.join(o for o in options if o)
					+ '"'
				)

	def _fix_numeric_types(self) -> None:
		for df in self.meta.fields:
			if df.fieldtype == "Check":
				self.set(df.fieldname, cint(self.get(df.fieldname)))
			elif self.get(df.fieldname) is not None:
				if df.fieldtype == "Int":
					self.set(df.fieldname, cint(self.get(df.fieldname)))
				elif df.fieldtype in ("Float", "Currency", "Percent"):
					self.set(df.fieldname, flt(self.get(df.fieldname)))

	def _validate(self) -> None:
		self._validate_mandatory()
		self._validate_selects()
		self._fix_numeric_types()
		for child in self.get_all_children():
			child._validate_selects()
			child._fix_numeric_types()

	def validate_update_after_submit(self) -> None:
		if self.flags.ignore_validate_update_after_submit:
			return
		self._validate_update_after_submit()
		for child in self.get_all_children():
			if child.name:
				child._validate_update_after_submit()

	def _validate_update_after_submit(self) -> None:
		import frappe

		if self.meta.istable:
			row = frappe.db.table(self.doctype).get(self.name)
			if row is None:
				return  # a new child row on a submitted parent is caught by the table count
			db_values = _dict(row)
		else:
			db_values = frappe.get_doc(self.doctype, self.name).as_dict()
		for df in self.meta.fields:
			if df.fieldtype in NO_VALUE_FIELDS and df.fieldtype not in TABLE_FIELDS:
				continue
			if df.get("allow_on_submit") or df.get("is_virtual"):
				continue
			db_value = db_values.get(df.fieldname)
			if df.fieldtype in TABLE_FIELDS:
				self_value: Any = len(self.get(df.fieldname) or [])
				db_value = len(db_value or [])
			else:
				self_value = cast_for_storage(df.fieldtype, self.get(df.fieldname))
				db_value = cast_for_storage(df.fieldtype, db_value)
			if self_value in (None, "") and db_value in (None, ""):
				continue
			if self_value != db_value:
				prefix = f"Row #{self.idx}: " if self.get("parent") else ""
				raise UpdateAfterSubmitError(
					f"{prefix}Not allowed to change {df.label} after submission from {db_value} to {self_value}"
				)

	# --- triggers ---------------------------------------------------------------------

	def run_method(self, method: str, *args: Any, **kwargs: Any) -> Any:
		if method.startswith("_"):
			raise Exception("Run method is for hooks, avoid usage on internal methods")
		import frappe

		return_value: Any = None

		def collect(value: Any) -> None:
			nonlocal return_value
			if value is None:
				return
			if isinstance(value, dict) and isinstance(return_value, dict):
				return_value.update(value)
			else:
				return_value = value

		fn = getattr(self, method, None)
		if callable(fn):
			collect(fn(*args, **kwargs))
		doc_events = frappe.get_doc_hooks()
		handlers = list(doc_events.get(self.doctype, {}).get(method, [])) + list(
			doc_events.get("*", {}).get(method, [])
		)
		for path in handlers:
			handler = frappe.get_attr(path)
			if not args and not _accepts_method_argument(handler):
				collect(handler(self, **kwargs))
			else:
				collect(handler(self, method, *args, **kwargs))
		return return_value

	def run_before_save_methods(self) -> None:
		if self._action in ("save", "submit"):
			self.run_method("before_validate")
		if self.flags.ignore_validate:
			return
		if self._action == "save":
			self.run_method("validate")
			self.run_method("before_save")
		elif self._action == "submit":
			self.run_method("validate")
			self.run_method("before_submit")
		elif self._action == "cancel":
			self.run_method("before_cancel")
		elif self._action == "update_after_submit":
			self.run_method("before_update_after_submit")

	def run_post_save_methods(self) -> None:
		if self._action == "save":
			self.run_method("on_update")
		elif self._action == "submit":
			self.run_method("on_update")
			self.run_method("on_submit")
		elif self._action == "cancel":
			self.run_method("on_cancel")
			self.check_no_back_links_exist()
		elif self._action == "update_after_submit":
			self.run_method("on_update_after_submit")
		self.save_version()
		self.run_method("on_change")

	def check_no_back_links_exist(self) -> None:
		"""Cancelling a document other submitted documents link to is refused (frappe.model.delete_doc)."""
		import frappe

		if self.flags.ignore_links:
			return
		ignore = set(self.get("ignore_linked_doctypes") or [])
		for doctype, fieldname, name in frappe._stub.find_links_to(self.doctype, self.name):
			if doctype in ignore or doctype == self.doctype and name == self.name:
				continue
			row = frappe.db.table(doctype).get(name)
			if row is not None and int(row.get("docstatus") or 0) == 1:
				raise LinkValidationError(
					f"Cannot cancel because {self.doctype} {self.name} is linked with {doctype} {name} ({fieldname})"
				)

	# --- persistence --------------------------------------------------------------------

	def insert(
		self,
		ignore_permissions: bool | None = None,
		ignore_links: bool | None = None,
		ignore_if_duplicate: bool = False,
		ignore_mandatory: bool | None = None,
		set_name: str | None = None,
		set_child_names: bool = True,
	) -> Document:
		import frappe

		if ignore_permissions is not None:
			self.flags.ignore_permissions = ignore_permissions
		if ignore_links is not None:
			self.flags.ignore_links = ignore_links
		if ignore_mandatory is not None:
			self.flags.ignore_mandatory = ignore_mandatory
		self.set("__islocal", True)
		self._set_defaults()
		self.set_user_and_timestamp()
		self.set_docstatus()
		self.check_permission("create")
		self.check_if_latest()
		self._validate_links()
		self.run_method("before_insert")
		self.set_new_name(set_name=set_name, set_child_names=set_child_names)
		self.set_parent_in_children()
		self.flags.in_insert = True
		self.run_before_save_methods()
		self._validate()
		self.set_docstatus()
		self.flags.in_insert = False

		if self.meta.issingle:
			frappe.db.set_single_value(self.doctype, self.get_valid_dict())
		else:
			if ignore_if_duplicate and frappe.db.exists(self.doctype, self.name):
				return self
			self.db_insert()
		for child in self.get_all_children():
			child.db_insert()
			child.__dict__.pop("__islocal", None)
		self.run_method("after_insert")
		self.flags.in_insert = True
		self.run_post_save_methods()
		self.flags.in_insert = False
		self.__dict__.pop("__islocal", None)
		self.__dict__.pop("__unsaved", None)
		return self

	def save(self, *args: Any, **kwargs: Any) -> Document:
		return self._save(*args, **kwargs)

	def _save(self, ignore_permissions: bool | None = None, ignore_version: bool | None = None) -> Document:
		import frappe

		if ignore_permissions is not None:
			self.flags.ignore_permissions = ignore_permissions
		if ignore_version is not None:
			self.flags.ignore_version = ignore_version
		if self.is_new() or not self.get("name"):
			return self.insert()
		self._set_defaults()
		self.check_permission("write", "save")
		self.set_user_and_timestamp()
		self.set_docstatus()
		self.check_if_latest()
		self.set_parent_in_children()
		self.set_name_in_children()
		self.load_doc_before_save()
		self._validate_links()
		self.run_before_save_methods()
		if self._action != "cancel":
			self._validate()
		if self._action == "update_after_submit":
			self.validate_update_after_submit()
		self.set_docstatus()
		if self.meta.issingle:
			frappe.db.set_single_value(self.doctype, self.get_valid_dict())
		else:
			self.db_update()
		self.update_children()
		self.run_post_save_methods()
		self.__dict__.pop("__unsaved", None)
		return self

	def submit(self) -> Document:
		self.docstatus = DocStatus(1)
		return self.save()

	def cancel(self) -> Document:
		self.docstatus = DocStatus(2)
		return self.save()

	def delete(
		self, ignore_permissions: bool = False, force: bool = False, *, delete_permanently: bool = False
	) -> None:
		import frappe

		frappe.delete_doc(
			self.doctype,
			self.name,
			ignore_permissions=ignore_permissions,
			flags=self.flags,
			force=force,
			delete_permanently=delete_permanently,
		)

	def db_insert(self, ignore_if_duplicate: bool = False) -> None:
		import frappe

		if not self.name:
			if self.meta.istable:
				self.name = frappe.generate_hash(length=10)
			else:
				raise ValidationError(f"frappe stub: {self.doctype} has no name at db_insert")
		frappe.db.insert_row(self.doctype, self.get_valid_dict())

	def db_update(self) -> None:
		import frappe

		frappe.db.update_row(self.doctype, self.name, self.get_valid_dict())

	def update_children(self) -> None:
		import frappe

		for fieldname in self._table_fieldnames:
			df = self.meta.get_field(fieldname)
			if not frappe.db.has_table(df.options):
				continue
			existing = {
				r["name"]: r for r in frappe.db.child_rows(self.doctype, self.name, fieldname, df.options)
			}
			current = self.get(fieldname) or []
			keep = {row.name for row in current if row.name}
			for name in existing:
				if name not in keep:
					frappe.db.delete_row(df.options, name)
			for row in current:
				row.parent = self.name
				row.parenttype = self.doctype
				row.parentfield = fieldname
				row.docstatus = self.docstatus
				if row.name and row.name in existing:
					row.db_update()
				else:
					row.__dict__.pop("__islocal", None)
					row.db_insert()

	def db_set(
		self,
		fieldname: Any,
		value: Any = None,
		update_modified: bool = True,
		notify: bool = False,
		commit: bool = False,
	) -> None:
		import frappe

		if isinstance(fieldname, dict):
			self.update(fieldname)
		else:
			self.set(fieldname, value)
		if update_modified:
			self.modified = now_datetime()
			self.modified_by = frappe.session.user
		if not self.get_doc_before_save() and not self.meta.istable:
			self.load_doc_before_save()
		self.run_method("before_change")
		if self.name is None:
			return
		values = dict(fieldname) if isinstance(fieldname, dict) else {fieldname: value}
		if self.meta.issingle:
			frappe.db.set_single_value(self.doctype, values)
		else:
			frappe.db.set_value(
				self.doctype,
				self.name,
				values,
				modified=self.modified,
				modified_by=self.modified_by,
				update_modified=update_modified,
			)
		self.run_method("on_change")
		if commit:
			frappe.db.commit()

	def reload(self) -> Document:
		return self.load_from_db()

	def load_from_db(self) -> Document:
		import frappe

		meta = self.meta
		if meta.issingle:
			values = frappe.db.singles.get(self.doctype, {})
			self._init_fields()
			self.update(dict(values))
			self.name = self.doctype
			self.__dict__.pop("__islocal", None)
			return self
		row = frappe.db.table(self.doctype).get(self.name)
		if row is None:
			raise DoesNotExistError(f"{self.doctype} {self.name} not found")
		name = self.name
		self._init_fields()
		for key, value in row.items():
			if key.startswith("_"):
				continue
			object.__setattr__(self, key, DocStatus(cint(value)) if key == "docstatus" else value)
		self.name = name
		self.load_children_from_db()
		self.__dict__.pop("__islocal", None)
		self.__dict__.pop("__unsaved", None)
		if hasattr(self, "__setup__"):
			self.__setup__()
		return self

	def load_children_from_db(self) -> None:
		import frappe
		from frappe._stub.controllers import get_controller

		for fieldname in self._table_fieldnames:
			df = self.meta.get_field(fieldname)
			object.__setattr__(self, fieldname, [])
			if not frappe.db.has_table(df.options):
				continue
			for raw in frappe.db.child_rows(self.doctype, self.name, fieldname, df.options):
				payload = {k: v for k, v in raw.items() if not k.startswith("_")}
				payload["doctype"] = df.options
				child = get_controller(df.options)(payload)
				child.__dict__.pop("__islocal", None)
				child._parent_doc = self
				self.__dict__[fieldname].append(child)

	def load_doc_before_save(self) -> None:
		import frappe

		self._doc_before_save = None
		if self.is_new() or self.meta.istable:
			return
		try:
			self._doc_before_save = frappe.get_doc(self.doctype, self.name)
		except DoesNotExistError:
			self._doc_before_save = None

	def get_doc_before_save(self) -> Document | None:
		return getattr(self, "_doc_before_save", None)

	def has_value_changed(self, fieldname: str) -> bool:
		previous = self.get_doc_before_save()
		if not previous:
			return True
		previous_value = previous.get(fieldname)
		current_value = self.get(fieldname)
		if hasattr(previous_value, "hour") and current_value not in (None, ""):
			current_value = get_datetime(current_value)
		elif hasattr(previous_value, "year") and current_value not in (None, ""):
			current_value = getdate(current_value)
		return previous_value != current_value

	def save_version(self) -> None:
		import frappe

		if (
			not self.meta.track_changes
			or self.doctype == "Version"
			or self.flags.ignore_version
			or frappe.flags.in_install
			or self.meta.istable
		):
			return
		from frappe._stub.version import get_diff

		before = self.get_doc_before_save()
		if before is None:
			if not self.flags.updater_reference:
				return
			data = {
				"creation": str(self.creation),
				"updater_reference": self.flags.updater_reference,
				"created_by": self.owner,
			}
		else:
			diff = get_diff(before, self)
			if not diff:
				return
			data = diff
		frappe.get_doc(
			{
				"doctype": "Version",
				"ref_doctype": self.doctype,
				"docname": self.name,
				"data": frappe.as_json(data, indent=None, separators=(",", ":"), ensure_ascii=False),
			}
		).insert(ignore_permissions=True)

	def add_comment(
		self,
		comment_type: str = "Comment",
		text: str | None = None,
		comment_email: str | None = None,
		comment_by: str | None = None,
	) -> Document:
		import frappe

		return frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": comment_type,
				"comment_email": comment_email or frappe.session.user,
				"comment_by": comment_by,
				"reference_doctype": self.doctype,
				"reference_name": self.name,
				"content": text or comment_type,
			}
		).insert(ignore_permissions=True)

	def notify_update(self) -> None:
		return None

	def clear_cache(self) -> None:
		return None

	def queue_action(self, action: str, **kwargs: Any) -> Any:
		"""Frappe runs the action in a background job; the stub runs it inline (enqueue does too)."""
		return getattr(self, action)(**kwargs)

	def validate_value(
		self, fieldname: str, condition: str, val2: Any, doc: Any = None, raise_exception: Any = None
	) -> None:
		import operator

		ops = {
			"=": operator.eq,
			"!=": operator.ne,
			"<": operator.lt,
			">": operator.gt,
			"<=": operator.le,
			">=": operator.ge,
		}
		doc = doc or self
		if not ops[condition](doc.get(fieldname), val2):
			raise ValidationError(f"{doc.doctype} {fieldname}: value must be {condition} {val2}")

	def get_signature(self) -> str:
		return f"{self.doctype}:{self.name}"

	def get_password(self, fieldname: str = "password", raise_exception: bool = True) -> Any:
		return self.get(fieldname)


def _accepts_method_argument(handler: Any) -> bool:
	try:
		params = list(inspect.signature(handler).parameters.values())
	except (TypeError, ValueError):
		return True
	positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
	return len(positional) >= 2 or any(p.kind == p.VAR_POSITIONAL for p in params)


def _filter(rows: list, filters: dict, limit: int | None = None) -> list:
	out = []
	for row in rows:
		ok = True
		for key, expected in filters.items():
			value = row.get(key)
			if isinstance(expected, (list, tuple)) and len(expected) == 2 and isinstance(expected[0], str):
				op, target = expected
				if op == "=":
					ok = value == target
				elif op == "!=":
					ok = value != target
				elif op == "in":
					ok = value in target
				elif op == "not in":
					ok = value not in target
				else:
					raise ValidationError(f"frappe stub: doc.get() filter operator {op!r} not supported")
			else:
				ok = value == expected
			if not ok:
				break
		if ok:
			out.append(row)
			if limit and len(out) >= limit:
				break
	return out


def _resolve_default(doc: Document, df: Any, default: Any, frappe: Any) -> Any:
	"""Frappe's dynamic defaults (frappe/model/base_document.py + model/utils): Today, Now, __user, :Company."""
	if isinstance(default, str):
		text = default.strip()
		if text in ("Today", "today") and df.fieldtype in ("Date", "Datetime"):
			return nowdate() if df.fieldtype == "Date" else now_datetime()
		if text in ("Now", "now"):
			if df.fieldtype == "Time":
				return nowtime()
			if df.fieldtype == "Datetime":
				return now_datetime()
			return nowdate()
		if text in ("__user", "user"):
			return frappe.session.user
		if text.startswith(":"):
			source_doctype = text[1:]
			source_name = doc.get(frappe.scrub(source_doctype)) if source_doctype != doc.doctype else None
			if (
				source_name
				and frappe.db.has_table(source_doctype)
				and frappe.get_meta(source_doctype).has_field(df.fieldname)
			):
				return frappe.db.get_value(source_doctype, source_name, df.fieldname)
			return None
	if df.fieldtype == "Check" or df.fieldtype == "Int":
		return cint(default)
	if df.fieldtype in ("Currency", "Float", "Percent"):
		return flt(default)
	return default
