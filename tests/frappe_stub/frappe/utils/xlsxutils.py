"""``frappe.utils.xlsxutils.make_xlsx`` on openpyxl (Frappe 16 uses xlsxwriter; same output shape).

``make_xlsx(data, sheet_name, wb=None, column_widths=None, styles=None) -> BytesIO`` with
the first row bold, HTML in cells flattened to text, and formula-looking strings written
as literal text, as the version-16 source does.
"""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

ILLEGAL_CHARACTERS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")
FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@")


def handle_html(data: str) -> str:
	if "<" not in data or ">" not in data:
		return data
	from frappe.utils.data import strip_html

	return strip_html(data).replace("\n", " ").strip()


def make_xlsx(
	data: list[list[Any]],
	sheet_name: str,
	wb: Any = None,
	column_widths: list[int] | None = None,
	styles: dict[str, Any] | None = None,
) -> BytesIO | None:
	try:
		import openpyxl
		from openpyxl.styles import Font
	except ImportError as exc:  # pragma: no cover - environment problem
		raise ImportError("frappe stub: make_xlsx needs openpyxl (pip install openpyxl)") from exc

	created = wb is None
	if created:
		wb = openpyxl.Workbook()
		ws = wb.active
		ws.title = get_sanitized_sheet_name(sheet_name)
	else:
		ws = wb.create_sheet(get_sanitized_sheet_name(sheet_name))

	for i, width in enumerate(column_widths or []):
		if width:
			ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = width

	for row_idx, row in enumerate(data, 1):
		for col_idx, value in enumerate(row, 1):
			if isinstance(value, str):
				value = handle_html(value)
				value = ILLEGAL_CHARACTERS_RE.sub("", value)
				if value.startswith(FORMULA_TRIGGER_CHARS):
					cell = ws.cell(row=row_idx, column=col_idx, value=value)
					cell.data_type = "s"
					continue
			if isinstance(value, (dict, list, tuple, set)):
				value = str(value)
			ws.cell(row=row_idx, column=col_idx, value=value)
	for cell in ws[1] if data else []:
		cell.font = Font(bold=True)

	if not created:
		return None
	out = BytesIO()
	wb.save(out)
	out.seek(0)
	return out


def get_sanitized_sheet_name(sheet_name: str) -> str:
	return re.sub(r"[\\/*?:\[\]]", "", sheet_name)[:31] or "Sheet1"


def read_xlsx_file_from_attached_file(
	file_url: str | None = None, fcontent: bytes | None = None, filepath: str | None = None
) -> list[list[Any]]:
	import openpyxl

	if fcontent is not None:
		wb = openpyxl.load_workbook(BytesIO(fcontent), read_only=True, data_only=True)
	elif filepath:
		wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
	else:
		raise NotImplementedError("frappe stub: read_xlsx_file_from_attached_file needs fcontent or filepath")
	ws = wb.active
	return [list(row) for row in ws.iter_rows(values_only=True)]


def build_xlsx_response(data: list[list[Any]], filename: str, styles: dict[str, Any] | None = None) -> None:
	import frappe

	frappe.local.response.filename = f"{filename}.xlsx"
	frappe.local.response.filecontent = make_xlsx(data, filename, styles=styles).getvalue()
	frappe.local.response.type = "binary"
