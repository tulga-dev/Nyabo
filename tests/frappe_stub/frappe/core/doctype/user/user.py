"""User controller: named by e-mail, ``add_roles`` / ``remove_roles`` / ``get_roles``."""

from __future__ import annotations

from frappe.exceptions import ValidationError
from frappe.model.document import Document


class User(Document):
	def autoname(self) -> None:
		if not self.email:
			raise ValidationError("Email is mandatory for User")
		self.email = self.email.strip().lower()
		self.name = self.email

	def validate(self) -> None:
		if self.enabled is None:
			self.enabled = 1
		self.full_name = " ".join(p for p in (self.first_name, self.middle_name, self.last_name) if p)

	def on_update(self) -> None:
		import frappe

		frappe.local.role_cache.pop(self.name, None)

	def add_roles(self, *roles: str) -> None:
		existing = {r.role for r in self.get("roles") or []}
		for role in roles:
			if role not in existing:
				self.append("roles", {"role": role})
		self.save()

	def remove_roles(self, *roles: str) -> None:
		self.set("roles", [r for r in self.get("roles") or [] if r.role not in roles])
		self.save()

	def get_roles(self) -> list[str]:
		import frappe

		return frappe.get_roles(self.name)
