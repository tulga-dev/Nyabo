"""File controller: content written to the site's files directory on insert.

Mirrors frappe/core/doctype/file/file.py (version-16): the name is a 10-character
hash, ``file_name`` is kept (suffixed with the content hash when a file of that name
exists), ``file_url`` is ``/private/files/<name>`` or ``/files/<name>``, ``content_hash``
and ``file_size`` are filled, ``get_content()`` reads the bytes back, and ``on_trash``
removes the file from disk. Remote (http) file URLs are not written.
"""

from __future__ import annotations

import os
import re
from typing import Any

from frappe.exceptions import ValidationError
from frappe.model.document import Document
from frappe.utils.data import cint
from frappe.utils.file_manager import get_content_hash, get_file_name


class File(Document):
	_stub_extra_fields = frozenset({"content", "decode", "is_remote_file", "content_type"})

	def autoname(self) -> None:
		import frappe

		if self.is_folder:
			self.name = self.file_name
		else:
			self.name = frappe.generate_hash(length=10)

	@property
	def is_remote_file(self) -> bool:  # type: ignore[override]
		return bool(self.file_url and self.file_url.startswith(("http://", "https://")))

	def before_insert(self) -> None:
		if self.attached_to_doctype and not self.attached_to_name:
			self.attached_to_doctype = None
			self.attached_to_field = None
		self.file_url = self.file_url or ""
		self.is_private = cint(self.is_private)
		if self.is_folder:
			return
		content = self.get("content")
		if content is None and self.file_url and not self.is_remote_file:
			if not self.file_name:
				self.file_name = os.path.basename(self.file_url)
			return
		if content is None:
			raise ValidationError("frappe stub: a File needs `content` or a `file_url`")
		self.save_file(content=content)

	def save_file(self, content: bytes | str | None = None, decode: bool = False, ignore_existing_file_check: bool = False, overwrite: bool = False) -> None:
		if self.is_remote_file:
			return
		if content is not None:
			self.content = content
		content = self.get("content")
		if isinstance(content, str):
			content = content.encode("utf-8")
		if content is None:
			return
		self._content = content
		if not self.file_name:
			raise ValidationError("File name is required (file_name)")
		self.file_size = len(content)
		self.content_hash = get_content_hash(content)
		if not overwrite:
			self.file_name = get_file_name(self.file_name, self.content_hash[-6:])
		self.save_file_on_filesystem()

	def save_file_on_filesystem(self) -> dict[str, str]:
		safe_file_name = re.sub(r"[/\\%?#]", "_", self.file_name)
		self.file_url = f"/private/files/{safe_file_name}" if self.is_private else f"/files/{safe_file_name}"
		fpath = self.write_file()
		return {"file_name": os.path.basename(fpath), "file_url": self.file_url}

	def write_file(self) -> str:
		file_path = self.get_full_path()
		os.makedirs(os.path.dirname(file_path), exist_ok=True)
		with open(file_path, "wb") as f:
			f.write(self._content)
		return file_path

	def get_full_path(self) -> str:
		from frappe.utils import get_site_path

		file_path = self.file_url or self.file_name or ""
		if file_path.startswith("/private/files/"):
			return get_site_path("private", "files", file_path[len("/private/files/") :])
		if file_path.startswith("/files/"):
			return get_site_path("public", "files", file_path[len("/files/") :])
		if self.is_remote_file:
			raise ValidationError(f"frappe stub: remote file {self.file_url} has no local path")
		return get_site_path("private" if self.is_private else "public", "files", os.path.basename(file_path))

	def exists_on_disk(self) -> bool:
		try:
			return os.path.exists(self.get_full_path())
		except ValidationError:
			return False

	def get_content(self, encodings: Any = None) -> bytes:
		"""Bytes of the stored file. (Frappe decodes text files to str; keep bytes for hashing.)"""
		if self.is_folder:
			raise ValidationError("Cannot get file contents of a Folder")
		content = self.get("content")
		if content is not None:
			return content.encode("utf-8") if isinstance(content, str) else content
		if self.is_remote_file:
			raise NotImplementedError("frappe stub: remote files are not fetched")
		with open(self.get_full_path(), "rb") as f:
			self._content = f.read()
		return self._content

	def on_trash(self) -> None:
		if self.is_home_folder or self.is_attachments_folder:
			raise ValidationError("Cannot delete Home and Attachments folders")
		self._delete_file_on_disk()

	def _delete_file_on_disk(self) -> None:
		import frappe

		if self.is_folder or self.is_remote_file:
			return
		others = frappe.get_all("File", {"content_hash": self.content_hash, "name": ["!=", self.name]}, pluck="name")
		if others or not self.content_hash:
			return
		path = self.get_full_path()
		if os.path.exists(path):
			os.remove(path)

	def validate_file_extension(self) -> None:
		return None
