"""``get_mapped_doc`` as in frappe/model/mapper.py (version-16), minus UI-only branches.

What is mirrored: the ``validation`` guard, ``field_map`` (dict or list of pairs),
``field_no_map``, ``no_copy`` fields (source no_copy and every table field are skipped,
default and child-table fields too), Link fields whose options equal the source doctype
get the source name, ``condition``/``filter``/``ignore``/``add_if_empty``/``reset_value``
on child maps, ``postprocess`` per map and the final ``postprocess(source, target)``.
Children whose source table has no target table with the same options are skipped.
"""

from __future__ import annotations

import json
from typing import Any

from frappe._stub.meta import CHILD_TABLE_FIELDS, DEFAULT_FIELDS, TABLE_FIELDS
from frappe.exceptions import ValidationError
from frappe.utils.data import cstr


def get_mapped_doc(
	from_doctype: str,
	from_docname: str,
	table_maps: dict[str, Any],
	target_doc: Any = None,
	postprocess: Any = None,
	ignore_permissions: bool = False,
	ignore_child_tables: bool = False,
	cached: bool = False,
) -> Any:
	import frappe

	if not target_doc:
		target_doctype = table_maps[from_doctype]["doctype"]
		target_doc = frappe.new_doc(target_doctype)
		ret_doc = target_doc
	elif isinstance(target_doc, str):
		target_doc = frappe.get_doc(json.loads(target_doc))
		ret_doc = target_doc
	else:
		ret_doc = target_doc

	if not ignore_permissions:
		target_doc.check_permission("create")
	source_doc = frappe.get_doc(from_doctype, from_docname)
	if not ignore_permissions:
		source_doc.check_permission("read")

	ret_doc.run_method("before_mapping", source_doc, table_maps)
	map_doc(source_doc, target_doc, table_maps[source_doc.doctype])

	row_exists_for_parentfield: dict[str, bool] = {}
	if not ignore_child_tables:
		for df in source_doc.meta.get_table_fields():
			source_child_doctype = df.options
			table_map = table_maps.get(source_child_doctype)
			if not table_map:
				target_df = target_doc.meta.get_field(df.fieldname)
				if (
					target_df
					and target_df.options == source_child_doctype
					and not df.get("no_copy")
					and not target_df.get("no_copy")
				):
					table_map = {"doctype": source_child_doctype}
			if not table_map:
				continue
			target_child_doctype = table_map["doctype"]
			target_parentfield = target_doc.get_parentfield_of_doctype(target_child_doctype)
			if target_parentfield is None or not frappe.db.has_table(target_child_doctype):
				continue
			if table_map.get("reset_value"):
				target_doc.set(target_parentfield, [])
			for source_d in source_doc.get(df.fieldname) or []:
				if "condition" in table_map and not table_map["condition"](source_d):
					continue
				if target_parentfield not in row_exists_for_parentfield:
					row_exists_for_parentfield[target_parentfield] = bool(target_doc.get(target_parentfield))
				if table_map.get("ignore"):
					continue
				if table_map.get("add_if_empty") and row_exists_for_parentfield.get(target_parentfield):
					continue
				if table_map.get("filter") and table_map.get("filter")(source_d):
					continue
				map_child_doc(source_d, target_doc, table_map, source_doc)

	if postprocess:
		postprocess(source_doc, target_doc)
	ret_doc.run_method("after_mapping", source_doc)
	ret_doc.set_onload("load_after_mapping", True)
	return ret_doc


def map_doc(source_doc: Any, target_doc: Any, table_map: dict[str, Any], source_parent: Any = None) -> None:
	if table_map.get("validation"):
		for key, condition in table_map["validation"].items():
			if condition[0] == "=" and source_doc.get(key) != condition[1]:
				raise ValidationError(f"Cannot map because following condition fails: {key}={cstr(condition[1])}")
	map_fields(source_doc, target_doc, table_map, source_parent)
	if "postprocess" in table_map:
		table_map["postprocess"](source_doc, target_doc, source_parent)


def map_fields(source_doc: Any, target_doc: Any, table_map: dict[str, Any], source_parent: Any) -> None:
	no_copy_fields = set(
		[d.fieldname for d in source_doc.meta.fields if d.get("no_copy") == 1 or d.fieldtype in TABLE_FIELDS]
		+ [d.fieldname for d in target_doc.meta.fields if d.fieldtype in TABLE_FIELDS]
		+ list(DEFAULT_FIELDS)
		+ list(CHILD_TABLE_FIELDS)
		+ list(table_map.get("field_no_map", []))
	)
	for df in target_doc.meta.get_data_fields():
		if df.fieldname in no_copy_fields:
			continue
		val = source_doc.get(df.fieldname) if source_doc.meta.has_field(df.fieldname) else None
		if val not in (None, ""):
			target_doc.set(df.fieldname, val)
		elif df.fieldtype == "Link" and not target_doc.get(df.fieldname):
			if df.options == source_doc.doctype:
				target_doc.set(df.fieldname, source_doc.name)
			elif source_parent is not None and df.options == source_parent.doctype:
				target_doc.set(df.fieldname, source_parent.name)

	field_map = table_map.get("field_map")
	if field_map:
		pairs = field_map.items() if isinstance(field_map, dict) else field_map
		for source_key, target_key in pairs:
			val = source_doc.get(source_key)
			if val not in (None, ""):
				target_doc.set(target_key, val)

	if source_doc.get("idx"):
		target_doc.idx = source_doc.idx


def map_child_doc(source_d: Any, target_parent: Any, table_map: dict[str, Any], source_parent: Any = None) -> Any:
	import frappe

	target_child_doctype = table_map["doctype"]
	target_parentfield = target_parent.get_parentfield_of_doctype(target_child_doctype)
	target_d = frappe.new_doc(target_child_doctype, parent_doc=target_parent, parentfield=target_parentfield)
	map_doc(source_d, target_d, table_map, source_parent)
	target_d.idx = None
	target_parent.append(target_parentfield, target_d)
	return target_d
