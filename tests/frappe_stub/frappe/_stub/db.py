"""In-memory ``frappe.db``: one dict of rows per DocType, filters evaluated in Python.

Filter semantics follow frappe/model/db_query.py (version-16): NULL columns compare as
their fallback ('' / 0 / 0001-01-01) except that ``!= <fallback>`` never matches a NULL,
``like`` is case-insensitive, ``in``/``not in`` take lists, ``between`` is inclusive,
``is set`` / ``is not set`` test for '' or NULL. Anything SQL-shaped (``frappe.db.sql``,
aggregate fields, child-table joins, ``descendants of``) raises NotImplementedError so a
test never passes on invented behaviour.
"""

from __future__ import annotations

import datetime
import itertools
import re
from collections.abc import Iterable
from typing import Any

from frappe._stub.dictlike import _dict
from frappe._stub.meta import DEFAULT_FIELDS, NO_VALUE_FIELDS, Meta, MetaRegistry
from frappe._stub.values import cast_for_compare, cast_for_storage, null_fallback
from frappe.exceptions import DoesNotExistError, DuplicateEntryError, ValidationError
from frappe.utils.data import now_datetime

OPERATORS = frozenset(
	{"=", "!=", "<>", "==", "in", "not in", ">", ">=", "<", "<=", "like", "not like", "between", "is"}
)
UNSUPPORTED_OPERATORS = frozenset(
	{
		"descendants of",
		"ancestors of",
		"not descendants of",
		"not ancestors of",
		"timespan",
		"previous",
		"next",
		"descendants of (inclusive)",
	}
)
DEFAULT_ORDER = object()
# Column types of the standard fields (frappe/database/schema.py): timestamps compare as datetimes.
DEFAULT_FIELDTYPES = {
	"creation": "Datetime",
	"modified": "Datetime",
	"docstatus": "Int",
	"idx": "Int",
	"owner": "Data",
	"modified_by": "Data",
	"parent": "Data",
	"parentfield": "Data",
	"parenttype": "Data",
}
_AGGREGATE = re.compile(r"^\s*(count|sum|avg|min|max|group_concat)\s*\(", re.IGNORECASE)
_seq = itertools.count(1)


class Filter:
	__slots__ = ("fieldname", "operator", "value")

	def __init__(self, fieldname: str, operator: str, value: Any) -> None:
		self.fieldname = fieldname
		self.operator = operator.lower()
		self.value = value


class Database:
	"""The stub database. Rows are plain dicts keyed by name; child rows live in their own table."""

	def __init__(self, registry: MetaRegistry) -> None:
		self.registry = registry
		self.tables: dict[str, dict[str, dict[str, Any]]] = {}
		self.singles: dict[str, dict[str, Any]] = {}
		self.series: dict[str, int] = {}
		self.defaults: dict[str, Any] = {}
		self.savepoints: list[str] = []
		self.commit_count = 0
		self.rollback_count = 0
		self.db_type = "mariadb"

	# --- table plumbing ----------------------------------------------------------------

	def meta(self, doctype: str) -> Meta:
		meta = self.registry.get(doctype)
		if meta is None:
			raise DoesNotExistError(f"DocType {doctype} not found (frappe stub knows no meta for it)")
		return meta

	def has_table(self, doctype: str) -> bool:
		return self.registry.get(doctype) is not None

	def table(self, doctype: str) -> dict[str, dict[str, Any]]:
		if doctype == "DocType":
			return {row["name"]: row for row in self.registry.doctype_rows()}
		self.meta(doctype)
		return self.tables.setdefault(doctype, {})

	def rows(self, doctype: str) -> list[dict[str, Any]]:
		return list(self.table(doctype).values())

	def _fieldtype(self, meta: Meta, fieldname: str) -> str | None:
		df = meta.get_field(fieldname)
		if df is not None:
			return df.fieldtype
		if fieldname in DEFAULT_FIELDTYPES:
			return DEFAULT_FIELDTYPES[fieldname]
		if fieldname in DEFAULT_FIELDS or fieldname.startswith("_"):
			return None
		if meta.get("permissive"):
			return None
		raise ValidationError(f"frappe stub: {meta.name} has no field {fieldname!r}")

	def typed_row(self, doctype: str, values: dict[str, Any]) -> dict[str, Any]:
		meta = self.meta(doctype)
		row: dict[str, Any] = {}
		for key, value in values.items():
			if key == "doctype":
				continue
			df = meta.get_field(key)
			if df is not None and df.fieldtype in NO_VALUE_FIELDS:
				continue
			row[key] = cast_for_storage(self._fieldtype(meta, key), value)
		for df in meta.get_data_fields():
			if df.fieldname not in row:
				row[df.fieldname] = cast_for_storage(df.fieldtype, None)
		for key in DEFAULT_FIELDS:
			if key != "doctype":
				row.setdefault(key, None)
		if row.get("docstatus") is None:
			row["docstatus"] = 0
		if row.get("idx") is None:
			row["idx"] = 0
		return row

	def insert_row(self, doctype: str, values: dict[str, Any]) -> dict[str, Any]:
		table = self.table(doctype)
		row = self.typed_row(doctype, values)
		name = row.get("name")
		if name in (None, ""):
			raise ValidationError(f"frappe stub: cannot insert {doctype} without a name")
		if name in table:
			raise DuplicateEntryError(doctype, name, f"Duplicate entry '{name}' for key 'PRIMARY'")
		row["_seq"] = next(_seq)
		table[name] = row
		return row

	def update_row(self, doctype: str, name: str, values: dict[str, Any]) -> dict[str, Any]:
		table = self.table(doctype)
		row = table.get(name)
		if row is None:
			raise DoesNotExistError(f"{doctype} {name} not found")
		meta = self.meta(doctype)
		for key, value in values.items():
			if key == "doctype":
				continue
			df = meta.get_field(key)
			if df is not None and df.fieldtype in NO_VALUE_FIELDS:
				continue
			row[key] = cast_for_storage(self._fieldtype(meta, key), value)
		return row

	def delete_row(self, doctype: str, name: str) -> None:
		self.table(doctype).pop(name, None)

	def child_rows(
		self, parenttype: str, parent: str, parentfield: str, child_doctype: str
	) -> list[dict[str, Any]]:
		rows = [
			r
			for r in self.rows(child_doctype)
			if r.get("parent") == parent
			and r.get("parenttype") == parenttype
			and r.get("parentfield") == parentfield
		]
		rows.sort(key=lambda r: (r.get("idx") or 0, r["_seq"]))
		return rows

	# --- filters -----------------------------------------------------------------------

	def normalize_filters(self, doctype: str, filters: Any) -> list[Filter]:
		if filters is None or filters == {} or filters == []:
			return []
		if isinstance(filters, (str, int)):
			return [Filter("name", "=", filters)]
		out: list[Filter] = []
		if isinstance(filters, dict):
			for key, value in filters.items():
				if isinstance(value, (list, tuple)):
					if (
						len(value) == 2
						and isinstance(value[0], str)
						and (value[0].lower() in OPERATORS or value[0].lower() in UNSUPPORTED_OPERATORS)
					):
						out.append(Filter(key, value[0], value[1]))
					else:
						raise ValidationError(
							f"frappe stub: filter {key!r}: a list value must be [operator, value] (got {value!r}); use ['in', [...]] for lists"
						)
				else:
					out.append(Filter(key, "=", value))
			return out
		if isinstance(filters, (list, tuple)):
			for item in filters:
				if not isinstance(item, (list, tuple)):
					raise ValidationError(f"frappe stub: unsupported filter item {item!r}")
				if len(item) == 4:
					if item[0] != doctype:
						raise NotImplementedError(
							f"frappe stub: filters on another DocType ({item[0]!r}) are not supported; query {item[0]} directly"
						)
					out.append(Filter(item[1], item[2], item[3]))
				elif len(item) == 3:
					out.append(Filter(item[0], item[1], item[2]))
				elif len(item) == 2:
					out.append(Filter(item[0], "=", item[1]))
				else:
					raise ValidationError(f"frappe stub: unsupported filter item {item!r}")
			return out
		raise ValidationError(f"frappe stub: unsupported filters {filters!r}")

	def _matches(self, meta: Meta, row: dict[str, Any], flt: Filter) -> bool:
		if flt.operator in UNSUPPORTED_OPERATORS:
			raise NotImplementedError(f"frappe stub: filter operator {flt.operator!r} is not implemented")
		if flt.operator not in OPERATORS:
			raise ValidationError(f"frappe stub: unknown filter operator {flt.operator!r}")
		fieldtype = self._fieldtype(meta, flt.fieldname)
		stored = row.get(flt.fieldname)
		fallback = null_fallback(fieldtype)
		op = flt.operator

		if op == "is":
			if flt.value == "set":
				return stored is not None and stored != ""
			if flt.value == "not set":
				return stored is None or stored == ""
			raise ValidationError(f"frappe stub: 'is' expects 'set' or 'not set', got {flt.value!r}")

		if op in ("in", "not in"):
			values = flt.value
			if isinstance(values, str):
				values = [v.strip() for v in values.split(",")]
			values = cast_for_compare(fieldtype, list(values or []))
			present = (stored if stored is not None else fallback) in values
			return present if op == "in" else not present

		if op == "between":
			low, high = cast_for_compare(fieldtype, list(flt.value))
			if stored is None:
				return False
			return low <= stored <= high

		if op in ("like", "not like"):
			pattern = (
				re.escape(str(flt.value if flt.value is not None else ""))
				.replace("%", ".*")
				.replace("_", ".")
			)
			text = "" if stored is None else str(stored)
			hit = re.fullmatch(pattern, text, re.IGNORECASE | re.DOTALL) is not None
			return hit if op == "like" else not hit

		value = cast_for_compare(fieldtype, flt.value)
		if value is None:
			# Frappe turns `field = None` into a NULL/'' check, `!= None` into "is set".
			empty = stored is None or stored == ""
			return empty if op in ("=", "==") else not empty
		if stored is None:
			if op in ("!=", "<>") and value == fallback:
				return False
			stored = fallback
		if op in ("=", "=="):
			return stored == value
		if op in ("!=", "<>"):
			return stored != value
		try:
			if op == ">":
				return stored > value
			if op == ">=":
				return stored >= value
			if op == "<":
				return stored < value
			if op == "<=":
				return stored <= value
		except TypeError as exc:
			raise ValidationError(
				f"frappe stub: cannot compare {meta.name}.{flt.fieldname} value {stored!r} with {value!r}"
			) from exc
		raise ValidationError(f"frappe stub: unknown filter operator {op!r}")

	def filter_rows(self, doctype: str, filters: Any) -> list[dict[str, Any]]:
		meta = self.meta(doctype) if doctype != "DocType" else self.registry.get("DocType")
		conditions = self.normalize_filters(doctype, filters)
		out = []
		for row in self.rows(doctype):
			if all(self._matches(meta, row, c) for c in conditions):
				out.append(row)
		return out

	# --- ordering, projection --------------------------------------------------------

	@staticmethod
	def _sort_key(value: Any) -> tuple:
		"""NULLs first (as in SQL asc); mixed types compare by their string form."""
		if value is None:
			return (0, "")
		if isinstance(value, (int, float)):
			return (1, value)
		if isinstance(value, (datetime.date, datetime.datetime)):
			return (2, value.isoformat())
		return (3, str(value))

	def order_rows(self, doctype: str, rows: list[dict[str, Any]], order_by: Any) -> list[dict[str, Any]]:
		meta = self.meta(doctype) if doctype != "DocType" else self.registry.get("DocType")
		if order_by is DEFAULT_ORDER or order_by is None:
			if meta.istable:
				return sorted(rows, key=lambda r: ((r.get("idx") or 0), r.get("_seq", 0)))
			return sorted(
				rows, key=lambda r: (self._sort_key(r.get("modified")), r.get("_seq", 0)), reverse=True
			)
		clauses = []
		for part in str(order_by).split(","):
			part = part.strip()
			if not part:
				continue
			tokens = part.split()
			field = tokens[0]
			if "." in field:
				field = field.split(".")[-1]
			field = field.strip("`")
			direction = tokens[1].lower() if len(tokens) > 1 else "asc"
			if direction not in ("asc", "desc"):
				raise ValidationError(f"frappe stub: order_by direction must be asc or desc: {order_by!r}")
			self._fieldtype(meta, field)  # raises on typos
			clauses.append((field, direction == "desc"))
		ordered = sorted(rows, key=lambda r: r.get("_seq", 0))
		for field, desc in reversed(clauses):
			ordered.sort(key=lambda r, f=field: self._sort_key(r.get(f)), reverse=desc)
		return ordered

	def _columns(self, doctype: str, meta: Meta, fields: Any) -> list[tuple[str, str]]:
		"""(source column, output key) pairs; ``*`` expands to every stored column."""
		if fields is None:
			return [("name", "name")]
		if isinstance(fields, str):
			fields = [fields]
		out: list[tuple[str, str]] = []
		for raw in fields:
			field = raw.strip()
			if field == "*":
				out.extend((c, c) for c in self._all_columns(meta))
				continue
			if _AGGREGATE.match(field):
				raise NotImplementedError(
					f"frappe stub: aggregate field {field!r} is not supported; fetch rows and sum in Python"
				)
			alias = field
			m = re.match(r"^(.+?)\s+as\s+(\w+)$", field, re.IGNORECASE)
			if m:
				field, alias = m.group(1).strip(), m.group(2)
			if "." in field:
				table, column = field.rsplit(".", 1)
				table = table.strip("`")
				if table != f"tab{doctype}":
					raise NotImplementedError(
						f"frappe stub: field {raw!r} refers to another table; child-table joins are not supported"
					)
				field = column
			field = field.strip("`")
			if alias == raw:
				alias = field
			self._fieldtype(meta, field)
			out.append((field, alias))
		return out

	@staticmethod
	def _all_columns(meta: Meta) -> list[str]:
		columns = [k for k in DEFAULT_FIELDS if k != "doctype"]
		columns += [df.fieldname for df in meta.get_data_fields() if df.fieldname not in columns]
		return columns

	# --- public API ----------------------------------------------------------------------

	def get_all(
		self,
		doctype: str,
		filters: Any = None,
		fields: Any = None,
		order_by: Any = DEFAULT_ORDER,
		limit: int | None = None,
		limit_start: int = 0,
		limit_page_length: int | None = None,
		pluck: str | None = None,
		as_list: bool = False,
		distinct: bool = False,
		start: int | None = None,
		page_length: int | None = None,
		or_filters: Any = None,
		group_by: Any = None,
		**kwargs: Any,
	) -> list:
		if or_filters:
			raise NotImplementedError("frappe stub: or_filters are not supported")
		if group_by:
			raise NotImplementedError("frappe stub: group_by is not supported")
		if kwargs.get("filters_on_child"):
			raise NotImplementedError("frappe stub: child table filters are not supported")
		meta = self.meta(doctype) if doctype != "DocType" else self.registry.get("DocType")
		rows = self.order_rows(doctype, self.filter_rows(doctype, filters), order_by)
		offset = start if start is not None else limit_start or 0
		length = (
			limit
			if limit is not None
			else (limit_page_length if limit_page_length is not None else page_length)
		)
		if offset:
			rows = rows[offset:]
		if length is not None and length != 0:
			rows = rows[:length]
		if pluck:
			self._fieldtype(meta, pluck)
			values = [r.get(pluck) for r in rows]
			return list(dict.fromkeys(values)) if distinct else values
		columns = self._columns(doctype, meta, fields)
		out: list = []
		for r in rows:
			if as_list:
				out.append(tuple(r.get(c) for c, _ in columns))
			else:
				out.append(_dict((alias, r.get(c)) for c, alias in columns))
		if distinct:
			seen: list = []
			for item in out:
				if item not in seen:
					seen.append(item)
			out = seen
		return out

	get_list = get_all

	def get_value(
		self,
		doctype: str,
		filters: Any = None,
		fieldname: Any = "name",
		ignore: Any = None,
		as_dict: bool = False,
		debug: bool = False,
		order_by: Any = DEFAULT_ORDER,
		cache: bool = False,
		for_update: bool = False,
		run: bool = True,
		pluck: bool = False,
		distinct: bool = False,
	) -> Any:
		rows = self.get_values(
			doctype, filters=filters, fieldname=fieldname, as_dict=as_dict, order_by=order_by, limit=1
		)
		if not rows:
			return None
		row = rows[0]
		if as_dict:
			return row
		if isinstance(fieldname, (list, tuple)) or fieldname == "*":
			return row
		return row[0]

	def get_values(
		self,
		doctype: str,
		filters: Any = None,
		fieldname: Any = "name",
		ignore: Any = None,
		as_dict: bool = False,
		debug: bool = False,
		order_by: Any = DEFAULT_ORDER,
		update: Any = None,
		cache: bool = False,
		for_update: bool = False,
		limit: int | None = None,
		**kwargs: Any,
	) -> list:
		meta = self.meta(doctype) if doctype != "DocType" else self.registry.get("DocType")
		if meta.issingle:
			values = self.singles.get(doctype, {})
			names = [fieldname] if isinstance(fieldname, str) else list(fieldname)
			if as_dict:
				return [_dict((n, values.get(n)) for n in names)]
			return [tuple(values.get(n) for n in names)]
		fields = [fieldname] if isinstance(fieldname, str) else list(fieldname)
		rows = self.get_all(doctype, filters=filters, fields=fields, order_by=order_by, limit=limit)
		if as_dict:
			return rows
		return [tuple(r.values()) for r in rows]

	def set_value(
		self,
		doctype: str,
		dn: Any,
		field: Any,
		val: Any = None,
		modified: Any = None,
		modified_by: str | None = None,
		update_modified: bool = True,
		debug: bool = False,
		for_update: bool = True,
	) -> None:
		meta = self.meta(doctype)
		if meta.issingle:
			self.set_single_value(doctype, field, val)
			return
		values = dict(field) if isinstance(field, dict) else {field: val}
		if update_modified:
			import frappe

			values["modified"] = modified or now_datetime()
			values["modified_by"] = modified_by or frappe.session.user
		if isinstance(dn, (dict, list)):
			names = [r["name"] for r in self.filter_rows(doctype, dn)]
		else:
			names = [dn]
		for name in names:
			self.update_row(doctype, name, values)

	def exists(self, dt: Any, dn: Any = None, cache: bool = False) -> str | None:
		if isinstance(dt, dict):
			dt = dict(dt)
			doctype = dt.pop("doctype", None)
			if doctype is None:
				raise ValidationError("frappe stub: exists() dict needs a 'doctype' key")
			dn = dt
			dt = doctype
		if dn is None:
			meta = self.registry.get(dt)
			return dt if meta is not None and meta.issingle else None
		if not self.has_table(dt):
			raise DoesNotExistError(f"DocType {dt} not found (frappe stub knows no meta for it)")
		if isinstance(dn, (dict, list)):
			rows = self.filter_rows(dt, dn)
			return rows[0]["name"] if rows else None
		row = self.table(dt).get(dn)
		return row["name"] if row else None

	def count(self, dt: str, filters: Any = None, cache: bool = False, distinct: bool = True) -> int:
		return len(self.filter_rows(dt, filters))

	def delete(self, doctype: str, filters: Any = None, debug: bool = False) -> None:
		for row in self.filter_rows(doctype, filters):
			self.delete_row(doctype, row["name"])

	def truncate(self, doctype: str) -> None:
		self.table(doctype).clear()

	def get_single_value(self, doctype: str, fieldname: str, cache: bool = False) -> Any:
		meta = self.registry.get(doctype)
		if meta is None:
			meta = self.registry.register_single(doctype)
		if not meta.issingle:
			raise ValidationError(f"frappe stub: {doctype} is not a Single DocType")
		return self.singles.get(doctype, {}).get(fieldname)

	def set_single_value(
		self, doctype: str, fieldname: Any, value: Any = None, *args: Any, **kwargs: Any
	) -> None:
		meta = self.registry.get(doctype)
		if meta is None:
			meta = self.registry.register_single(doctype)
		if not meta.issingle:
			raise ValidationError(f"frappe stub: {doctype} is not a Single DocType")
		values = dict(fieldname) if isinstance(fieldname, dict) else {fieldname: value}
		self.singles.setdefault(doctype, {}).update(values)

	def get_default(self, key: str, parent: str = "__default") -> Any:
		return self.defaults.get(key)

	def set_default(
		self, key: str, val: Any, parent: str = "__default", parenttype: str | None = None
	) -> None:
		self.defaults[key] = val

	def sql(self, *args: Any, **kwargs: Any) -> Any:
		raise NotImplementedError(
			"frappe stub: frappe.db.sql is not available; use frappe.get_all / frappe.db.get_value or extend the stub"
		)

	sql_list = sql
	multisql = sql

	def escape(self, s: Any, percent: bool = True) -> str:
		text = str(s).replace("\\", "\\\\").replace("'", "\\'")
		return f"'{text}'"

	def commit(self) -> None:
		self.commit_count += 1
		self.savepoints.clear()

	def rollback(self, save_point: str | None = None) -> None:
		"""No transaction to undo in memory; the call is counted so tests can assert it happened."""
		self.rollback_count += 1
		if save_point and save_point in self.savepoints:
			del self.savepoints[self.savepoints.index(save_point) :]
		elif save_point is None:
			self.savepoints.clear()

	def savepoint(self, save_point: str) -> None:
		self.savepoints.append(save_point)

	def release_savepoint(self, save_point: str) -> None:
		if save_point in self.savepoints:
			self.savepoints.remove(save_point)

	def begin(self, *args: Any, **kwargs: Any) -> None:
		return None

	def get_next_sequence_val(self, doctype: str) -> int:
		self.series[f"seq:{doctype}"] = self.series.get(f"seq:{doctype}", 0) + 1
		return self.series[f"seq:{doctype}"]

	def get_creation_count(self, doctype: str, minutes: int) -> int:
		return len(self.rows(doctype))

	def table_exists(self, doctype: str) -> bool:
		return self.has_table(doctype)

	def has_column(self, doctype: str, column: str) -> bool:
		meta = self.registry.get(doctype)
		return bool(meta and (meta.has_field(column) or column in DEFAULT_FIELDS))

	def get_table_columns(self, doctype: str) -> list[str]:
		return self._all_columns(self.meta(doctype))

	def add_index(self, *args: Any, **kwargs: Any) -> None:
		return None

	def iter_rows(self, doctype: str) -> Iterable[dict[str, Any]]:
		return iter(self.rows(doctype))
