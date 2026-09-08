"""SYNTHETIC bank statement fixtures for the import/matching tests. NOT real bank exports.

Each builder returns (filename, bytes) and the layout the tests register as *verified*
for it (``layouts.json``). Column orders are deliberately different per file so the
detection and parsing paths are exercised; they are test scaffolds, not claims about
any bank's real format (see README.md). Run this module to (re)write the files::

    python tests/fixtures/statements/make_fixtures.py
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

KHAN_ACCOUNT_NO = "5001234567"
TDB_ACCOUNT_NO = "5007654321"

# Lines shared by the Khan Bank scaffold (the matching scenarios reference these amounts).
KHAN_LINES: list[dict[str, Any]] = [
	{"date": dt.date(2026, 9, 2), "text": "Петровис ХХК шатахуун", "out": 93500, "in": 0, "ref": "TX1001"},
	{"date": dt.date(2026, 9, 3), "text": "Банкны хураамж", "out": 1500, "in": 0, "ref": ""},
	{"date": dt.date(2026, 9, 4), "text": "Номин ХХК төлбөр", "out": 0, "in": 1250000, "ref": "TX1002"},
	{
		"date": dt.date(2026, 9, 5),
		"text": f"Өөрийн данс {TDB_ACCOUNT_NO} руу шилжүүлэг",
		"out": 200000,
		"in": 0,
		"ref": "TX1003",
	},
	{"date": dt.date(2026, 9, 6), "text": "Тэнгэр ХХК төлбөр", "out": 50000, "in": 0, "ref": "TX1004"},
]
KHAN_OPENING = 1_000_000

TDB_LINES: list[dict[str, Any]] = [
	{"date": dt.date(2026, 9, 1), "text": "Сүү ХХК орлого", "out": 0, "in": 300000, "ref": "R1"},
	{
		"date": dt.date(2026, 9, 5),
		"text": f"{KHAN_ACCOUNT_NO} дансаас шилжүүлэг",
		"out": 0,
		"in": 200000,
		"ref": "R2",
	},
	{"date": dt.date(2026, 9, 7), "text": "Гүйлгээний шимтгэл", "out": 900, "in": 0, "ref": ""},
]
TDB_OPENING = 500_000


def _xlsx(rows: Sequence[Sequence[Any]]) -> bytes:
	from openpyxl import Workbook

	wb = Workbook()
	ws = wb.active
	ws.title = "Statement"
	for row in rows:
		ws.append(list(row))
	buf = io.BytesIO()
	wb.save(buf)
	return buf.getvalue()


def _running(lines: Sequence[dict[str, Any]], opening: int) -> list[int]:
	balance = opening
	out = []
	for line in lines:
		balance += int(line["in"]) - int(line["out"])
		out.append(balance)
	return out


def khan_xlsx() -> tuple[str, bytes]:
	"""Title block, account number, Mongolian headers, date | narrative | debit | credit | balance | ref."""
	balances = _running(KHAN_LINES, KHAN_OPENING)
	rows: list[list[Any]] = [
		["Хаан банк — Дансны хуулга (SYNTHETIC TEST DATA)"],
		[f"Данс: {KHAN_ACCOUNT_NO}", "Валют: MNT"],
		[],
		["Огноо", "Гүйлгээний утга", "Зарлага", "Орлого", "Үлдэгдэл", "Лавлах"],
		["2026.09.01", "Эхний үлдэгдэл", "", "", KHAN_OPENING, ""],
	]
	for line, balance in zip(KHAN_LINES, balances, strict=True):
		rows.append(
			[
				line["date"].strftime("%Y.%m.%d"),
				line["text"],
				line["out"] or "",
				line["in"] or "",
				balance,
				line["ref"],
			]
		)
	rows.append(["2026.09.30", "Эцсийн үлдэгдэл", "", "", balances[-1], ""])
	return "khan_synthetic.xlsx", _xlsx(rows)


def tdb_xlsx() -> tuple[str, bytes]:
	"""Header on the first row, datetime cells, reference before the amounts, currency column."""
	balances = _running(TDB_LINES, TDB_OPENING)
	rows: list[list[Any]] = [
		["Огноо", "Лавлах дугаар", "Дебит", "Кредит", "Валют", "Гүйлгээний утга", "Үлдэгдэл"],
	]
	for line, balance in zip(TDB_LINES, balances, strict=True):
		rows.append(
			[
				dt.datetime.combine(line["date"], dt.time(10, 30)),
				line["ref"],
				line["out"] or None,
				line["in"] or None,
				"MNT",
				line["text"],
				balance,
			]
		)
	return "tdb_synthetic.xlsx", _xlsx(rows)


def golomt_xlsx() -> tuple[str, bytes]:
	"""One signed amount column, day-first dates as text, a title row above the header."""
	lines = [
		{"date": dt.date(2026, 9, 2), "text": "Мобиком ХХК төлбөр", "amount": -45000, "ref": "G1"},
		{"date": dt.date(2026, 9, 3), "text": "Худалдан авагч орлого", "amount": 120000, "ref": "G2"},
		{"date": dt.date(2026, 9, 3), "text": "Үйлчилгээний хураамж", "amount": -500, "ref": ""},
	]
	balance = 250_000
	rows: list[list[Any]] = [
		["Голомт банк · хуулга (SYNTHETIC)"],
		["Огноо", "Тайлбар", "Дүн", "Үлдэгдэл", "Лавлах"],
	]
	for line in lines:
		balance += line["amount"]
		rows.append([line["date"].strftime("%d.%m.%Y"), line["text"], line["amount"], balance, line["ref"]])
	return "golomt_synthetic.xlsx", _xlsx(rows)


def transbank_xlsx() -> tuple[str, bytes]:
	"""Credit before debit, narrative after the amounts, no balance column, amounts as text."""
	lines = [
		{
			"date": dt.date(2026, 9, 1),
			"text": "Түрээсийн төлбөр Оффис ХХК",
			"out": "750 000",
			"in": "",
			"ref": "T1",
		},
		{
			"date": dt.date(2026, 9, 4),
			"text": "Захиалагч орлого",
			"out": "",
			"in": "1,000,000.00",
			"ref": "T2",
		},
	]
	rows: list[list[Any]] = [["Гүйлгээний огноо", "Орлого", "Зарлага", "Гүйлгээний утга", "Лавлах"]]
	for line in lines:
		rows.append([line["date"].strftime("%Y-%m-%d"), line["in"], line["out"], line["text"], line["ref"]])
	return "transbank_synthetic.xlsx", _xlsx(rows)


def xacbank_xlsx() -> tuple[str, bytes]:
	"""English headers, withdrawal before deposit, timestamps as text, opening/closing rows."""
	lines = [
		{"date": "2026-09-02 09:15:00", "text": "UNITEL LLC payment", "out": 33000, "in": ""},
		{"date": "2026-09-05 16:40:00", "text": "Customer receipt", "out": "", "in": 400000},
		{"date": "2026-09-06 08:00:00", "text": "Service fee", "out": 700, "in": ""},
	]
	rows: list[list[Any]] = [
		["XacBank statement (SYNTHETIC)"],
		["Date", "Description", "Withdrawal", "Deposit", "Balance", "Reference"],
		["2026-09-01 00:00:00", "Opening balance", "", "", 100000, ""],
	]
	balance = 100000
	for index, line in enumerate(lines, start=1):
		balance += int(line["in"] or 0) - int(line["out"] or 0)
		rows.append([line["date"], line["text"], line["out"], line["in"], balance, f"X{index}"])
	rows.append(["2026-09-30 00:00:00", "Closing balance", "", "", balance, ""])
	return "xacbank_synthetic.xlsx", _xlsx(rows)


def khan_csv_cp1251() -> tuple[str, bytes]:
	"""The Khan scaffold as a semicolon CSV in cp1251.

	cp1251 cannot encode the Mongolian letters Ү/ү and Ө/ө, so the narratives here use
	only letters the code page has (a real cp1251 export would mangle them too).
	"""
	balances = _running(KHAN_LINES, KHAN_OPENING)
	safe_text = {
		0: "Петровис ХХК шатахуун",
		1: "Банкны хураамж",
		2: "Номин ХХК толбор",
		3: f"Оорийн данс {TDB_ACCOUNT_NO} руу шилжлэг",
		4: "Тэнгэр ХХК толбор",
	}
	buf = io.StringIO()
	writer = csv.writer(buf, delimiter=";", lineterminator="\n")
	writer.writerow(["Хаан банк (SYNTHETIC, cp1251)"])
	writer.writerow([f"Данс: {KHAN_ACCOUNT_NO}"])
	writer.writerow(["Огноо", "Гуйлгээний утга", "Зарлага", "Орлого", "Улдэгдэл", "Лавлах"])
	for index, (line, balance) in enumerate(zip(KHAN_LINES, balances, strict=True)):
		writer.writerow(
			[
				line["date"].strftime("%Y.%m.%d"),
				safe_text[index],
				f"{line['out']:,}".replace(",", " ") if line["out"] else "",
				f"{line['in']:,}".replace(",", " ") if line["in"] else "",
				f"{balance:,}".replace(",", " "),
				line["ref"],
			]
		)
	return "khan_synthetic_cp1251.csv", buf.getvalue().encode("cp1251")


LAYOUTS: list[dict[str, Any]] = [
	{
		"layout_id": "test_khan_synthetic",
		"bank": "Khan Bank",
		"verified": 1,
		"amount_style": "separate_debit_credit",
		"header_signature": ["огноо", "гүйлгээний утга", "зарлага", "орлого", "үлдэгдэл"],
		"column_map": {"date": 0, "description": 1, "debit": 2, "credit": 3, "balance": 4, "reference": 5},
		"date_formats": ["%Y.%m.%d"],
		"currency_default": "MNT",
	},
	{
		"layout_id": "test_khan_synthetic_cp1251",
		"bank": "Khan Bank",
		"verified": 1,
		"amount_style": "separate_debit_credit",
		"header_signature": ["огноо", "гуйлгээний утга", "зарлага", "орлого", "улдэгдэл"],
		"column_map": {"date": 0, "description": 1, "debit": 2, "credit": 3, "balance": 4, "reference": 5},
		"date_formats": ["%Y.%m.%d"],
		"currency_default": "MNT",
	},
	{
		"layout_id": "test_tdb_synthetic",
		"bank": "TDB",
		"verified": 1,
		"amount_style": "separate_debit_credit",
		"header_signature": ["огноо", "лавлах дугаар", "дебит", "кредит", "валют"],
		"column_map": {
			"date": "Огноо",
			"reference": "Лавлах дугаар",
			"debit": "Дебит",
			"credit": "Кредит",
			"currency": "Валют",
			"description": "Гүйлгээний утга",
			"balance": "Үлдэгдэл",
		},
		"date_formats": ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"],
		"currency_default": "MNT",
	},
	{
		"layout_id": "test_golomt_synthetic",
		"bank": "Golomt Bank",
		"verified": 1,
		"amount_style": "signed_amount",
		"header_signature": ["огноо", "тайлбар", "дүн", "үлдэгдэл"],
		"column_map": {"date": 0, "description": 1, "amount": 2, "balance": 3, "reference": 4},
		"date_formats": ["%d.%m.%Y"],
		"currency_default": "MNT",
	},
	{
		"layout_id": "test_transbank_synthetic",
		"bank": "Trans Bank",
		"verified": 1,
		"amount_style": "separate_debit_credit",
		"header_signature": ["гүйлгээний огноо", "орлого", "зарлага", "гүйлгээний утга"],
		"column_map": {"date": 0, "credit": 1, "debit": 2, "description": 3, "reference": 4},
		"date_formats": ["%Y-%m-%d"],
		"currency_default": "MNT",
	},
	{
		"layout_id": "test_xacbank_synthetic",
		"bank": "XacBank",
		"verified": 1,
		"amount_style": "separate_debit_credit",
		"header_signature": ["date", "description", "withdrawal", "deposit", "balance"],
		"column_map": {"date": 0, "description": 1, "debit": 2, "credit": 3, "balance": 4, "reference": 5},
		"date_formats": ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"],
		"currency_default": "MNT",
	},
]

BUILDERS = (khan_xlsx, tdb_xlsx, golomt_xlsx, transbank_xlsx, xacbank_xlsx, khan_csv_cp1251)


def build_all() -> dict[str, bytes]:
	return dict(builder() for builder in BUILDERS)


def write_all(target: Path = HERE) -> list[Path]:
	written: list[Path] = []
	for name, data in build_all().items():
		path = target / name
		path.write_bytes(data)
		written.append(path)
	layouts = target / "layouts.json"
	layouts.write_text(
		json.dumps(
			{"note": "SYNTHETIC test layouts for the files in this folder", "rows": LAYOUTS},
			ensure_ascii=False,
			indent=1,
		)
		+ "\n",
		encoding="utf-8",
	)
	written.append(layouts)
	return written


if __name__ == "__main__":
	for path in write_all():
		print(path)
