"""Property Setter: ``make_property_setter`` and a controller that patches the meta.

Mirrors frappe/custom/doctype/property_setter/property_setter.py (version-16). Name is
``<doctype>-<field or 'main'>-<property>``; on save the value is applied to the field
(or the DocType) in the in-memory meta, cast by ``property_type``.
"""

from __future__ import annotations

from typing import Any

from frappe.exceptions import ValidationError
from frappe.model.document import Document
from frappe.utils.data import cint, flt


class PropertySetter(Document):
	def autoname(self) -> None:
		self.name = "{doctype}-{field}-{property}".format(
			doctype=self.doc_type, field=self.field_name or self.row_name or "main", property=self.property
		)

	def validate(self) -> None:
		import frappe

		if self.doctype_or_field == "DocField" and self.flags.validate_fields_for_doctype is not False:
			meta = frappe.get_meta(self.doc_type)
			if not self.field_name or not meta.has_field(self.field_name):
				raise ValidationError(
					f"{self.doc_type} has no field {self.field_name!r} for the Property Setter"
				)

	def on_update(self) -> None:
		import frappe

		meta = frappe.get_meta(self.doc_type)
		value = _cast(self.property_type, self.value)
		if self.doctype_or_field == "DocType":
			meta[self.property] = value
		elif self.doctype_or_field == "DocField":
			df = meta.get_field(self.field_name)
			if df is not None:
				df[self.property] = value


def _cast(property_type: str | None, value: Any) -> Any:
	if property_type in ("Check", "Int"):
		return cint(value)
	if property_type in ("Float", "Currency"):
		return flt(value)
	return value


def make_property_setter(
	doctype: str,
	fieldname: str | None,
	property: str,  # noqa: A002 - Frappe signature
	value: Any,
	property_type: str,
	for_doctype: bool = False,
	validate_fields_for_doctype: bool = True,
	is_system_generated: bool = True,
) -> PropertySetter:
	import frappe

	property_setter = frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": (for_doctype and "DocType") or "DocField",
			"doc_type": doctype,
			"field_name": fieldname,
			"property": property,
			"value": value,
			"property_type": property_type,
			"is_system_generated": is_system_generated,
		}
	)
	property_setter.flags.ignore_permissions = True
	property_setter.flags.validate_fields_for_doctype = validate_fields_for_doctype
	existing = frappe.db.exists("Property Setter", property_setter.name or "")
	if existing:
		frappe.delete_doc("Property Setter", existing, ignore_permissions=True, force=True)
	property_setter.insert()
	return property_setter
