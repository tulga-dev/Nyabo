"""``frappe.utils.file_manager.save_file`` as in frappe/utils/file_manager.py (version-16).

Writes the content under the site's files directory, then inserts a File that points at
it (``file_url``, ``content_hash``, ``file_size``, attachment fields). A file with the same
hash and privacy is reused instead of written twice.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
from typing import Any


def get_content_hash(content: bytes | str) -> str:
	if isinstance(content, str):
		content = content.encode("utf-8")
	return hashlib.md5(content).hexdigest()  # noqa: S324 - Frappe uses md5 for content hashes


def save_file(
	fname: str,
	content: bytes | str,
	dt: str | None,
	dn: str | None,
	folder: str | None = None,
	decode: bool = False,
	is_private: int = 0,
	df: str | None = None,
) -> Any:
	import frappe

	if decode:
		if isinstance(content, str):
			content = content.encode("utf-8")
		if b"," in content:
			content = content.split(b",")[1]
		content = base64.b64decode(content)
	if isinstance(content, str):
		content = content.encode("utf-8")

	file_size = len(content)
	content_hash = get_content_hash(content)
	content_type = mimetypes.guess_type(fname)[0]
	fname = get_file_name(fname, content_hash[-6:])
	file_data = get_file_data_from_hash(content_hash, is_private=is_private)
	if not file_data:
		file_data = save_file_on_filesystem(fname, content, content_type=content_type, is_private=is_private)
	file_data = dict(file_data)
	file_data.update(
		{
			"doctype": "File",
			"attached_to_doctype": dt,
			"attached_to_name": dn,
			"attached_to_field": df,
			"folder": folder,
			"file_size": file_size,
			"content_hash": content_hash,
			"is_private": is_private,
		}
	)
	f = frappe.get_doc(file_data)
	f.flags.ignore_permissions = True
	f.insert()
	return f


def get_file_data_from_hash(content_hash: str, is_private: int = 0) -> dict[str, Any] | bool:
	import frappe

	for name in frappe.get_all(
		"File", {"content_hash": content_hash, "is_private": is_private}, pluck="name"
	):
		b = frappe.get_doc("File", name)
		return {"file_name": b.file_name, "file_url": b.file_url}
	return False


def save_file_on_filesystem(
	fname: str, content: bytes, content_type: str | None = None, is_private: int = 0
) -> dict[str, str]:
	fpath = write_file(content, fname, is_private)
	file_url = f"/private/files/{fname}" if is_private else f"/files/{fname}"
	return {"file_name": os.path.basename(fpath), "file_url": file_url}


def write_file(content: bytes | str, fname: str, is_private: int = 0) -> str:
	from frappe.utils import get_files_path

	directory = get_files_path(is_private=bool(is_private))
	os.makedirs(directory, exist_ok=True)
	if isinstance(content, str):
		content = content.encode("utf-8")
	path = os.path.join(directory, fname)
	with open(path, "wb") as f:
		f.write(content)
	return path


def get_file_name(fname: str, optional_suffix: str) -> str:
	import frappe
	from frappe.utils import get_files_path

	fname = str(fname)
	n_records = frappe.get_all("File", {"file_name": fname}, pluck="name")
	if (
		n_records
		or os.path.exists(get_files_path(fname))
		or os.path.exists(get_files_path(fname, is_private=True))
	):
		partial, dot, extn = fname.rpartition(".")
		if not dot:
			partial, extn = fname, ""
		else:
			extn = "." + extn
		return f"{partial}{optional_suffix}{extn}"
	return fname


def get_file(fname: str) -> tuple[str, bytes]:
	import frappe

	name = frappe.db.get_value("File", {"file_url": fname}, "name") or frappe.db.get_value(
		"File", {"file_name": fname}, "name"
	)
	if not name:
		raise frappe.DoesNotExistError(f"File {fname} not found")
	doc = frappe.get_doc("File", name)
	return doc.file_name, doc.get_content()


def remove_all(dt: str, dn: str, from_delete: bool = False, delete_permanently: bool = False) -> None:
	import frappe

	for name in frappe.get_all("File", {"attached_to_doctype": dt, "attached_to_name": dn}, pluck="name"):
		frappe.delete_doc("File", name, ignore_permissions=True, force=True)
