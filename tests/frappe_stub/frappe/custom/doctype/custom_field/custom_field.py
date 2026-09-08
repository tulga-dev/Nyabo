"""Custom Field: ``create_custom_fields`` / ``create_custom_field`` and the controller.

Mirrors frappe/custom/doctype/custom_field/custom_field.py (version-16): name is
``<dt>-<fieldname>``; a new Custom Field on a fieldname the DocType already has as a
standard field is refused; ``create_custom_fields`` creates missing fields and, with
``update=True``, saves changed ones. Saving a Custom Field updates the in-memory meta so
documents accept the field straight away, like ``frappe.clear_cache(doctype=...)`` does.
"""

from __future__ import annotations

from typing import Any

from frappe._stub.dictlike import _dict
from frappe.exceptions import DuplicateEntryError, ValidationError
from frappe.model.document import Document

META_PROPERTIES = (
	"fieldname",
	"fieldtype",
	"label",
	"options",
	"reqd",
	"default",
	"read_only",
	"allow_on_submit",
	"no_copy",
	"unique",
	"precision",
	"hidden",
	"insert_after",
	"collapsible",
	"in_list_view",
	"in_standard_filter",
	"depends_on",
	"description",
	"length",
	"is_virtual",
	"fetch_from",
	"fetch_if_empty",
	"permlevel",
	"mandatory_depends_on",
	"read_only_depends_on",
	"translatable",
	"set_only_once",
	"non_negative",
)


class CustomField(Document):
	def autoname(self) -> None:
		self.set_fieldname()
		self.name = self.dt + "-" + self.fieldname

	def set_fieldname(self) -> None:
		import frappe

		if not self.fieldname:
			if not self.label:
				raise ValidationError("Label is mandatory")
			self.fieldname = frappe.scrub(self.label)
		self.fieldname = self.fieldname.lower()

	def validate(self) -> None:
		import frappe

		if not self.fieldname:
			raise ValidationError("Fieldname not set for Custom Field")
		meta = frappe.get_meta(self.dt)
		existing = meta.get_field(self.fieldname)
		if self.is_new() and existing is not None and not existing.get("is_custom_field"):
			raise ValidationError(
				f"A field with the name <b>{self.fieldname}</b> already exists in {self.dt}"
			)
		if self.insert_after == "append":
			self.insert_after = meta.fields[-1].fieldname
		if self.insert_after and self.insert_after in [f.fieldname for f in meta.fields]:
			self.idx = [f.fieldname for f in meta.fields].index(self.insert_after) + 1

	def on_update(self) -> None:
		import frappe

		meta = frappe.get_meta(self.dt)
		df = {key: self.get(key) for key in META_PROPERTIES if self.get(key) not in (None, "")}
		df["fieldname"] = self.fieldname
		df["fieldtype"] = self.fieldtype or "Data"
		meta.add_custom_field(df)

	def on_trash(self) -> None:
		import frappe

		meta = frappe.get_meta(self.dt)
		df = meta.get_field(self.fieldname)
		if df is not None and df.get("is_custom_field"):
			meta.fields.remove(df)
			meta._fields_by_name.pop(self.fieldname, None)


def create_custom_field(
	doctype: str, df: dict[str, Any], ignore_validate: bool = False, is_system_generated: bool = True
) -> Any:
	import frappe

	df = _dict(df)
	if not df.fieldname and df.label:
		df.fieldname = frappe.scrub(df.label)
	if not frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": df.fieldname}):
		custom_field = frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": doctype,
				"permlevel": 0,
				"fieldtype": "Data",
				"hidden": 0,
				"is_system_generated": is_system_generated,
			}
		)
		custom_field.update({k: v for k, v in df.items() if k != "doctype"})
		custom_field.flags.ignore_validate = ignore_validate
		custom_field.flags.ignore_permissions = True
		custom_field.insert()
		return custom_field
	return None


def get_existing_custom_fields(custom_fields: dict[Any, Any]) -> dict[tuple[str, str], _dict]:
	import frappe

	out: dict[tuple[str, str], _dict] = {}
	for doctypes in custom_fields:
		for doctype in (doctypes,) if isinstance(doctypes, str) else doctypes:
			for row in frappe.get_all("Custom Field", filters={"dt": doctype}, fields=["*"]):
				out[(doctype, row.fieldname)] = row
	return out


def create_custom_fields(
	custom_fields: dict[Any, Any], ignore_validate: bool = False, update: bool = True
) -> None:
	"""``{'Sales Invoice': [dict(fieldname='test')]}`` -> Custom Field rows + meta update."""
	import frappe

	try:
		frappe.flags.in_create_custom_fields = True
		existing = get_existing_custom_fields(custom_fields)
		for doctypes, fields in custom_fields.items():
			if isinstance(fields, dict):
				fields = (fields,)
			if isinstance(doctypes, str):
				doctypes = (doctypes,)
			for doctype in doctypes:
				for df in fields:
					field = existing.get((doctype, df["fieldname"]))
					if not field:
						try:
							payload = dict(df)
							payload["owner"] = "Administrator"
							created = create_custom_field(doctype, payload, ignore_validate=ignore_validate)
							if created is not None:
								existing[(doctype, created.fieldname)] = _dict(created.as_dict())
						except DuplicateEntryError:
							pass
					elif update:
						doc = frappe.get_doc("Custom Field", field.name)
						before = doc.as_dict()
						doc.update({k: v for k, v in df.items() if k != "doctype"})
						if before != doc.as_dict():
							doc.flags.ignore_validate = bool(ignore_validate)
							doc.flags.ignore_permissions = True
							doc.save()
	finally:
		frappe.flags.in_create_custom_fields = False
