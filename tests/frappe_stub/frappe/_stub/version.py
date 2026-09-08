"""``get_diff`` as in frappe/core/doctype/version/version.py: what a Version row records."""

from __future__ import annotations

from typing import Any

from frappe._stub.dictlike import _dict
from frappe._stub.meta import NO_VALUE_FIELDS, TABLE_FIELDS


def _row_dict(row: Any) -> dict[str, Any]:
	return (
		row.as_dict(no_default_fields=True, no_child_table_fields=True)
		if hasattr(row, "as_dict")
		else dict(row)
	)


def get_diff(old: Any, new: Any, for_child: bool = False, compare_cancelled: bool = False) -> _dict | None:
	"""Field-level diff: ``changed`` for scalars, ``added``/``removed``/``row_changed`` for tables."""
	if not compare_cancelled and old is not None and int(old.get("docstatus") or 0) == 2:
		return None
	out = _dict(changed=[], added=[], removed=[], row_changed=[], data_import=None, updater_reference=None)
	for df in new.meta.fields:
		if df.fieldtype in NO_VALUE_FIELDS and df.fieldtype not in TABLE_FIELDS:
			continue
		old_value, new_value = old.get(df.fieldname), new.get(df.fieldname)
		if not for_child and df.fieldtype in TABLE_FIELDS:
			old_rows = {r.get("name"): r for r in (old_value or [])}
			new_rows = {r.get("name"): r for r in (new_value or [])}
			for name, row in new_rows.items():
				if name not in old_rows:
					out.added.append([df.fieldname, _row_dict(row)])
					continue
				row_diff = get_diff(old_rows[name], row, for_child=True)
				if row_diff and row_diff.changed:
					out.row_changed.append([df.fieldname, row.get("idx"), name, row_diff.changed])
			for name, row in old_rows.items():
				if name not in new_rows:
					out.removed.append([df.fieldname, _row_dict(row)])
		elif old_value != new_value:
			out.changed.append([df.fieldname, old_value, new_value])
	if not for_child and int(old.get("docstatus") or 0) != int(new.get("docstatus") or 0):
		out.changed.append(["docstatus", int(old.get("docstatus") or 0), int(new.get("docstatus") or 0)])
	if any((out.changed, out.added, out.removed, out.row_changed)):
		return out
	return None
