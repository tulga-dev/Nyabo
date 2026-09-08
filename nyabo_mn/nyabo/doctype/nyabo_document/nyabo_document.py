"""Nyabo Document: the primary document (photo, statement) behind every Nyabo posting.

Retention stamping and delete protection are compliance hooks (``nyabo_mn.compliance``);
this controller only offers the status transitions the pipeline uses so the vocabulary
(``received -> extracted -> proposed -> approved/rejected -> posted`` or ``failed``) is
written in one place, and a helper to read the stored file back.
"""

from __future__ import annotations

from frappe.model.document import Document

STATUSES = ("received", "extracted", "proposed", "approved", "rejected", "posted", "failed")


class NyaboDocument(Document):
	def validate(self) -> None:
		if self.status and self.status not in STATUSES:
			from frappe import ValidationError

			raise ValidationError(f"Nyabo Document: unknown status {self.status!r}")
		if self.error and len(self.error) > 1000:
			self.error = self.error[:1000]

	def mark(self, status: str, **values: object) -> None:
		"""Persist a status change without re-running validation on a possibly stale document."""
		self.db_set({"status": status, **values})

	def mark_failed(self, error: str) -> None:
		self.mark("failed", error=str(error)[:1000])

	def file_content(self) -> bytes:
		"""Bytes of the attached file (``file`` is the File's ``file_url``)."""
		import frappe

		name = frappe.db.get_value("File", {"file_url": self.file}, "name")
		if not name:
			raise frappe.DoesNotExistError(f"File for {self.name} ({self.file}) not found")
		content = frappe.get_doc("File", name).get_content()
		return content.encode("utf-8") if isinstance(content, str) else content
