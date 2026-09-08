"""``frappe.delete_doc`` in the order frappe/model/delete_doc.py (version-16) uses.

on_trash -> on_change -> link check (unless force) -> revert naming series -> delete rows
(children first) -> after_delete -> attached Files, Comments and Versions -> Deleted
Document row. Submitted documents cannot be deleted; cancel them first.
"""

from __future__ import annotations

from typing import Any

from frappe.exceptions import DoesNotExistError, LinkExistsError, ValidationError


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
) -> bool | None:
	import frappe

	if isinstance(name, (list, tuple)):
		for each in name:
			delete_doc(
				doctype,
				each,
				force=force,
				ignore_doctypes=ignore_doctypes,
				for_reload=for_reload,
				ignore_permissions=ignore_permissions,
				flags=flags,
				ignore_on_trash=ignore_on_trash,
				ignore_missing=ignore_missing,
				delete_permanently=delete_permanently,
			)
		return None
	if doctype is None or name is None:
		raise ValidationError("frappe stub: delete_doc needs doctype and name")
	try:
		doc = frappe.get_doc(doctype, name)
	except DoesNotExistError:
		if ignore_missing:
			return False
		raise
	if flags:
		doc.flags.update(flags)
	if ignore_permissions:
		doc.flags.ignore_permissions = True

	if not for_reload:
		if int(doc.docstatus) == 1:
			raise ValidationError(
				f"{doctype} {name}: Submitted Record cannot be deleted. You must Cancel it first."
			)
		doc.check_permission("delete")
		if not ignore_on_trash:
			doc.run_method("on_trash")
			doc.flags.in_delete = True
			doc.run_method("on_change")
		if not force:
			_check_if_doc_is_linked(doc, ignore_doctypes or [])

	from frappe.model.naming import revert_series_if_last

	autoname = doc.meta.autoname or ""
	if "#" in autoname and not autoname.lower().startswith("naming_series"):
		revert_series_if_last(autoname, doc.name, doc)

	for child in doc.get_all_children():
		if child.name:
			frappe.db.delete_row(child.doctype, child.name)
	frappe.db.delete_row(doctype, name)
	doc.run_method("after_delete")

	for file_name in frappe.get_all(
		"File", {"attached_to_doctype": doctype, "attached_to_name": name}, pluck="name"
	):
		delete_doc("File", file_name, ignore_permissions=True, force=True)
	frappe.db.delete("Comment", {"reference_doctype": doctype, "reference_name": name})
	frappe.db.delete("Version", {"ref_doctype": doctype, "docname": name})

	if not delete_permanently and doctype not in ("Deleted Document", "Version", "Comment", "File"):
		frappe.get_doc(
			{
				"doctype": "Deleted Document",
				"deleted_doctype": doctype,
				"deleted_name": name,
				"data": frappe.as_json(doc.as_dict(convert_dates_to_str=True), ensure_ascii=False),
			}
		).insert(ignore_permissions=True)
	return True


def _check_if_doc_is_linked(doc: Any, ignore_doctypes: list[str]) -> None:
	"""frappe/model/delete_doc.py ``get_linked_docs`` (version-16), for ``method = "Delete"``.

	The two ways a linking doctype is ignored differ by method, and the stub keeps the
	difference: ``if method == "Delete": ignored_doctypes.update(frappe.get_hooks(
	"ignore_links_on_delete"))``, while the document's own ``ignore_linked_doctypes``
	attribute is read only ``if method == "Cancel"`` (``Document.check_no_back_links_exist``
	in this stub). ``doc.get("ignore_linked_doctypes")`` is honoured here as well because
	ERPNext's controllers set it in ``on_trash`` too and the stub was written that way.
	"""
	import frappe

	ignored = set(ignore_doctypes) | set(frappe.get_hooks("ignore_links_on_delete") or [])
	for other_doctype, fieldname, other_name in frappe._stub.find_links_to(doc.doctype, doc.name):
		if other_doctype in ignored or other_doctype in (doc.get("ignore_linked_doctypes") or []):
			continue
		if other_doctype == doc.doctype and other_name == doc.name:
			continue
		row = frappe.db.table(other_doctype).get(other_name)
		if row is None or int(row.get("docstatus") or 0) == 2:
			continue
		raise LinkExistsError(
			f"Cannot delete or cancel because {doc.doctype} {doc.name} is linked with {other_doctype} {other_name} ({fieldname})"
		)
