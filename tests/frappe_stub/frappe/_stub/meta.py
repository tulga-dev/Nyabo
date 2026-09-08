"""DocType metadata for the stub: Nyabo DocType JSON files + erpnext_meta.json + a few built-ins.

The registry is rebuilt on every ``frappe._stub.reset()`` so custom fields added by one
test never leak into the next. Layout fields (Section/Column/Tab Break, HTML, ...) are
kept in ``fields`` like Frappe does but never count as data columns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from frappe._stub.dictlike import _dict

STUB_DIR = Path(__file__).resolve().parent.parent.parent  # tests/frappe_stub
REPO_ROOT = STUB_DIR.parent.parent
NYABO_DOCTYPE_DIR = REPO_ROOT / "nyabo_mn" / "nyabo" / "doctype"
ERPNEXT_META_PATH = STUB_DIR / "erpnext_meta.json"

# Mirrors frappe.model constants (frappe/model/__init__.py, version-16).
DEFAULT_FIELDS = (
	"doctype",
	"name",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"parent",
	"parentfield",
	"parenttype",
	"idx",
	"docstatus",
)
CHILD_TABLE_FIELDS = ("parent", "parentfield", "parenttype")
TABLE_FIELDS = ("Table", "Table MultiSelect")
NUMERIC_FIELDTYPES = ("Currency", "Int", "Long Int", "Float", "Percent", "Check")
NO_VALUE_FIELDS = (
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Table",
	"Table MultiSelect",
	"Button",
	"Image",
	"Fold",
	"Heading",
)
LAYOUT_FIELDS = ("Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading")

# DocTypes that Frappe itself owns; everything else in erpnext_meta.json belongs to erpnext.
FRAPPE_DOCTYPES = frozenset(
	{
		"Currency",
		"File",
		"User",
		"Has Role",
		"Role",
		"Version",
		"Deleted Document",
		"Error Log",
		"Report",
		"Print Format",
		"Comment",
		"Custom Field",
		"Property Setter",
		"DocType",
	}
)


class Meta(_dict):
	"""Subset of frappe.model.meta.Meta that application code touches."""

	def __init__(self, name: str, spec: dict[str, Any], app: str, module: str | None = None) -> None:
		super().__init__()
		self.name = name
		self.app = app
		self.module = module
		self.autoname = spec.get("autoname") or ""
		self.istable = 1 if spec.get("istable") else 0
		self.issingle = 1 if spec.get("issingle") else 0
		self.is_submittable = 1 if spec.get("is_submittable") else 0
		self.track_changes = 1 if spec.get("track_changes") else 0
		self.permissions = [_dict(p) for p in spec.get("permissions") or []]
		self.custom = 1 if spec.get("custom") else 0
		self.fields: list[_dict] = []
		self._fields_by_name: dict[str, _dict] = {}
		for raw in spec.get("fields") or []:
			self._add_field(_dict(raw))

	# --- construction -------------------------------------------------------------------

	def _add_field(self, df: _dict, insert_after: str | None = None) -> _dict:
		df.setdefault("parent", self.name)
		df.setdefault("label", df.fieldname)
		if insert_after and insert_after in self._fields_by_name:
			index = next(i for i, f in enumerate(self.fields) if f.fieldname == insert_after) + 1
			self.fields.insert(index, df)
		else:
			self.fields.append(df)
		self._fields_by_name[df.fieldname] = df
		return df

	def add_custom_field(self, df: dict[str, Any]) -> _dict:
		"""Used by the Custom Field stub; an existing field with the same name is replaced in place."""
		new = _dict(df)
		new["is_custom_field"] = 1
		existing = self._fields_by_name.get(new.fieldname)
		if existing is not None:
			existing.update(new)
			return existing
		return self._add_field(new, insert_after=new.get("insert_after"))

	# --- queries used by application code ----------------------------------------------

	def has_field(self, fieldname: str) -> bool:
		return fieldname in self._fields_by_name

	def get_field(self, fieldname: str) -> _dict | None:
		return self._fields_by_name.get(fieldname)

	def get_label(self, fieldname: str) -> str:
		df = self.get_field(fieldname)
		if df is not None:
			return df.label or fieldname
		return fieldname.replace("_", " ").title()

	def get_options(self, fieldname: str) -> str | None:
		df = self.get_field(fieldname)
		return df.options if df is not None else None

	def get(self, key: str, filters: dict[str, Any] | None = None, default: Any = None) -> Any:  # type: ignore[override]
		"""``meta.get("fields", {"fieldtype": "Link"})`` is a common Frappe idiom."""
		value = super().get(key, default)
		if filters and isinstance(value, list):
			return [row for row in value if all(row.get(k) == v for k, v in filters.items())]
		return value

	def get_table_fields(self) -> list[_dict]:
		return [df for df in self.fields if df.fieldtype in TABLE_FIELDS]

	def get_link_fields(self) -> list[_dict]:
		return [df for df in self.fields if df.fieldtype == "Link"]

	def get_dynamic_link_fields(self) -> list[_dict]:
		return [df for df in self.fields if df.fieldtype == "Dynamic Link"]

	def get_data_fields(self) -> list[_dict]:
		"""Fields that hold a value (not layout, not child tables)."""
		return [df for df in self.fields if df.fieldtype not in NO_VALUE_FIELDS]

	def get_valid_columns(self) -> list[str]:
		columns = list(DEFAULT_FIELDS)
		columns += [df.fieldname for df in self.fields if df.fieldtype not in LAYOUT_FIELDS]
		return columns

	def get_field_precision(self, df: _dict) -> int:
		if df.get("precision"):
			return int(df.precision)
		if df.fieldtype == "Currency":
			return 2
		if df.fieldtype in ("Float", "Percent"):
			return 3
		return 0

	def get_title_field(self) -> str:
		return "name"

	def get_search_fields(self) -> list[str]:
		return ["name"]

	def is_nested_set(self) -> bool:
		return self.has_field("lft") and self.has_field("rgt")


class MetaRegistry:
	"""All known DocTypes. ``load()`` reads the JSON files again; nothing is cached across resets."""

	def __init__(self) -> None:
		self.metas: dict[str, Meta] = {}

	def load(self) -> None:
		self.metas = {}
		for name, spec in _load_erpnext_meta().items():
			app = "frappe" if name in FRAPPE_DOCTYPES else "erpnext"
			self.metas[name] = Meta(name, spec, app=app)
		for name, spec in _load_nyabo_meta().items():
			self.metas[name] = Meta(name, spec, app="nyabo_mn", module=spec.get("module"))
		for name, spec in BUILTIN_METAS.items():
			self.metas[name] = Meta(name, spec, app="frappe")

	def get(self, doctype: str) -> Meta | None:
		return self.metas.get(doctype)

	def register_single(self, doctype: str) -> Meta:
		"""Singles (Accounts Settings, ...) are not shipped as JSON; they accept any field."""
		meta = Meta(doctype, {"issingle": 1, "fields": []}, app="stub")
		meta["permissive"] = 1
		self.metas[doctype] = meta
		return meta

	def doctype_rows(self) -> list[dict[str, Any]]:
		"""Rows for the pseudo table ``tabDocType`` (frappe.db.exists("DocType", ...))."""
		rows = []
		for meta in self.metas.values():
			rows.append(
				{
					"name": meta.name,
					"module": meta.module or ("Nyabo" if meta.app == "nyabo_mn" else None),
					"app": meta.app,
					"istable": meta.istable,
					"issingle": meta.issingle,
					"is_submittable": meta.is_submittable,
					"track_changes": meta.track_changes,
					"autoname": meta.autoname,
					"custom": meta.custom,
				}
			)
		return rows


def _load_erpnext_meta() -> dict[str, Any]:
	with open(ERPNEXT_META_PATH, encoding="utf-8") as f:
		return json.load(f)


def _load_nyabo_meta() -> dict[str, Any]:
	out: dict[str, Any] = {}
	if not NYABO_DOCTYPE_DIR.exists():
		return out
	for folder in sorted(NYABO_DOCTYPE_DIR.iterdir()):
		path = folder / f"{folder.name}.json"
		if not path.exists():
			continue
		with open(path, encoding="utf-8") as f:
			raw = json.load(f)
		out[raw["name"]] = raw
	return out


# Frappe-owned DocTypes the stub needs but whose JSON is not worth shipping: only the columns
# the stub itself reads and writes are declared. Marked ``stub_builtin`` so nobody mistakes
# them for verified ERPNext metadata.
BUILTIN_METAS: dict[str, dict[str, Any]] = {
	"DocType": {
		"autoname": "Prompt",
		"stub_builtin": 1,
		"fields": [
			{"fieldname": "module", "fieldtype": "Link", "options": "Module Def"},
			{"fieldname": "app", "fieldtype": "Data"},
			{"fieldname": "istable", "fieldtype": "Check"},
			{"fieldname": "issingle", "fieldtype": "Check"},
			{"fieldname": "is_submittable", "fieldtype": "Check"},
			{"fieldname": "track_changes", "fieldtype": "Check"},
			{"fieldname": "autoname", "fieldtype": "Data"},
			{"fieldname": "custom", "fieldtype": "Check"},
		],
	},
	"Series": {
		"autoname": "Prompt",
		"stub_builtin": 1,
		"fields": [{"fieldname": "current", "fieldtype": "Int"}],
	},
}
