"""Inventory intake: parsing owner text and spreadsheets, posting as JE or Stock Reconciliation."""

from __future__ import annotations

from decimal import Decimal

import frappe
import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.setup import inventory_intake as intake
from nyabo_mn.setup.provision_company import provision_company

TEXT = 'Принтерийн хор, 5, 45 000\nЦаас А4; 10; 12,500₮\n`Кабель, 3, 1500, м`\n\nМонитор 24", 2, 450000'
TABLE = [
	["Барааны жагсаалт", None, None, None],
	["Нэр", "Тоо", "Нэгж үнэ", "Нэгж"],
	["Хор", 5, 45000, "ш"],
	["Цаас", "10", "12 500", None],
	[None, None, None, None],
	["Нийт", None, None, None],
]


def test_parse_text_lines():
	rows = intake.parse_text(TEXT)
	assert [(r.item_name, r.qty, r.rate, r.uom) for r in rows] == [
		("Принтерийн хор", Decimal("5.00"), Decimal("45000.00"), "ш"),
		("Цаас А4", Decimal("10.00"), Decimal("12500.00"), "ш"),
		("Кабель", Decimal("3.00"), Decimal("1500.00"), "м"),
		('Монитор 24"', Decimal("2.00"), Decimal("450000.00"), "ш"),
	]
	assert intake.total_of(rows) == Decimal("1254500.00")
	with pytest.raises(intake.IntakeParseError, match="2-р мөр"):
		intake.parse_text("Хор, 5, 45000\nЦаас, арван")
	with pytest.raises(intake.IntakeParseError, match="эерэг"):
		intake.parse_text("Хор, 0, 45000")
	with pytest.raises(intake.IntakeParseError) as excinfo:
		intake.parse_text("\n\n")
	assert excinfo.value.message_mn == mn.MSG_INTAKE_EMPTY


def test_parse_table_with_header_detection_and_without_header():
	rows = intake.parse_table(TABLE)
	assert [(r.item_name, r.qty, r.rate, r.uom) for r in rows] == [
		("Хор", Decimal("5"), Decimal("45000"), "ш"),
		("Цаас", Decimal("10.00"), Decimal("12500.00"), "ш"),
	]
	english = intake.parse_table([["Item", "Qty", "Rate"], ["Pen", 2, 1000]])
	assert english[0].item_name == "Pen" and english[0].amount == Decimal("2000.00")
	headerless = intake.parse_table([["Хор", 5, 45000], ["Цаас", 10, 12500]])
	assert len(headerless) == 2
	with pytest.raises(intake.IntakeParseError, match="баганууд"):
		intake.parse_table([["a", "b", "c"], ["x", "y", "z"]])
	with pytest.raises(intake.IntakeParseError, match="хоосон"):
		intake.parse_table([])


def test_intake_validate_recomputes_amounts(company_v03):
	rows = intake.parse_text("Хор, 5, 45000\nЦаас, 10, 12500")
	doc = intake.create_intake(company_v03, "text", rows, "2026-01-01")
	assert doc.status == "draft" and doc.total_amount == 350000.0
	assert [(r.amount, r.uom) for r in doc.items] == [(225000.0, "ш"), (125000.0, "ш")]
	doc.items[0].qty = 6
	doc.save()
	assert doc.items[0].amount == 270000.0 and doc.total_amount == 395000.0
	doc.items[1].rate = -1
	with pytest.raises(frappe.ValidationError, match="эерэг"):
		doc.save()


def test_post_intake_journal_entry_when_perpetual_inventory_is_off(company_v03):
	rows = intake.parse_text("Хор, 5, 45000\nЦаас, 10, 12500")
	doc = intake.create_intake(company_v03, "text", rows, "2026-01-01")
	with pytest.raises(frappe.ValidationError, match="баталгаажаагүй"):
		intake.post_intake(doc.name, "Administrator")
	intake.confirm_intake(doc.name, "Administrator")
	created = intake.post_intake(doc.name, "Administrator")
	assert created["items"] == ["Хор", "Цаас"] and created["journal_entry"].startswith("ACC-JV-")
	je = frappe.get_doc("Journal Entry", created["journal_entry"])
	assert je.docstatus == 1 and je.is_opening == "Yes" and je.voucher_type == "Opening Entry"
	assert [(a.account, a.debit, a.credit) for a in je.accounts] == [
		("1501 - Бараа - GUR", 350000.0, 0.0),
		("1890 - Түр нээлтийн данс - GUR", 0.0, 350000.0),
	]
	assert je.nyabo_explanation == mn.EXPL_INVENTORY_OPENING.format(intake=doc.name)
	assert je.nyabo_primary_document_ref == doc.name
	item = frappe.get_doc("Item", "Хор")
	assert (item.is_stock_item, item.stock_uom, item.item_group) == (1, "ш", mn.ITEM_GROUP_INVENTORY)
	assert frappe.db.exists("UOM", "ш") and frappe.db.exists("Item Group", mn.ITEM_GROUP_INVENTORY)
	doc.reload()
	assert doc.status == "posted" and doc.confirmed_by == "Administrator"
	assert doc.items[0].item_code == "Хор" and doc.items[0].warehouse == "Stores - GUR"
	assert frappe.parse_json(doc.created_docs_json)["journal_entry"] == je.name
	with pytest.raises(frappe.ValidationError, match="аль хэдийн"):
		intake.post_intake(doc.name, "Administrator")
	# a second intake reuses the Items
	second = intake.create_intake(company_v03, "text", intake.parse_text("Хор, 1, 45000"), "2026-01-02")
	intake.confirm_intake(second.name, "Administrator")
	intake.post_intake(second.name, "Administrator")
	assert frappe.db.count("Item") == 2


def test_post_intake_stock_reconciliation_when_perpetual_inventory_is_on(seeded):
	provision_company("Тав ХХК", "TAV", chart_scheme="v03", has_inventory=1, enable_perpetual_inventory=1)
	doc = intake.create_intake(
		"Тав ХХК", "excel", intake.parse_table(TABLE), "2026-01-01", file_url="/private/files/x.xlsx"
	)
	intake.confirm_intake(doc.name, "Administrator")
	created = intake.post_intake(doc.name, "Administrator")
	assert "journal_entry" not in created and created["stock_reconciliation"].startswith("MAT-RECO-")
	reco = frappe.get_doc("Stock Reconciliation", created["stock_reconciliation"])
	assert reco.docstatus == 1 and reco.purpose == "Opening Stock" and reco.set_posting_time == 1
	assert reco.expense_account == "1890 - Түр нээлтийн данс - TAV"
	assert [(i.item_code, i.warehouse, i.qty, i.valuation_rate) for i in reco.items] == [
		("Хор", "Stores - TAV", 5.0, 45000.0),
		("Цаас", "Stores - TAV", 10.0, 12500.0),
	]


def test_post_intake_needs_company_settings(site, company):
	frappe.delete_doc("Nyabo Company Settings", company, force=True, ignore_permissions=True)
	doc = intake.create_intake(company, "text", intake.parse_text("Хор, 1, 100"), "2026-01-01")
	intake.confirm_intake(doc.name, "Administrator")
	with pytest.raises(frappe.ValidationError, match="тохиргоо байхгүй"):
		intake.post_intake(doc.name, "Administrator")
	assert frappe.db.get_value("Nyabo Inventory Intake", doc.name, "status") == "confirmed"
