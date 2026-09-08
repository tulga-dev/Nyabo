"""Document builders shared by the compliance and report flow tests (V1 chart of Тест ХХК)."""

from __future__ import annotations

import frappe

EXPENSE = "6210 - Шатахуун - TST"
CASH = "1110 - Касс - TST"
BANK = "1120 - Банкны харилцах данс - TST"
PAYABLE = "2110 - Дансны өглөг - TST"
INPUT_VAT = "1810 - Татан суутгах НӨАТ - TST"
OUTPUT_VAT = "2210 - Төлөх НӨАТ - TST"
RECEIVABLE = "1310 - Дансны авлага - TST"
INCOME = "4110 - Борлуулалтын орлого - TST"


def make_je(company, amount=85000, posting_date="2026-03-05", debit=EXPENSE, credit=CASH, **extra):
	return frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": company,
			"posting_date": posting_date,
			"user_remark": "Тест",
			"accounts": [
				{"account": debit, "debit_in_account_currency": amount},
				{"account": credit, "credit_in_account_currency": amount},
			],
			**extra,
		}
	)


def make_nyabo_document(company, **extra):
	return frappe.get_doc(
		{
			"doctype": "Nyabo Document",
			"company": company,
			"doc_type": "receipt",
			"file": "/private/files/receipt.jpg",
			"status": "received",
			"received_at": "2026-03-05 10:00:00",
			**extra,
		}
	).insert()


def make_supplier(name="Петровис ХХК"):
	return frappe.get_doc({"doctype": "Supplier", "supplier_name": name, "tin": "12345678"}).insert()


def make_pi(company, supplier, **extra):
	return frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"company": company,
			"supplier": supplier.name if hasattr(supplier, "name") else supplier,
			"posting_date": "2026-03-10",
			"bill_no": "AB-1",
			"items": [{"item_name": "Бензин", "qty": 2, "rate": 42500, "expense_account": EXPENSE}],
			**extra,
		}
	)


def make_si(company, customer, amount=200000, posting_date="2026-03-15", vat=True, **extra):
	taxes = (
		[{"account_head": OUTPUT_VAT, "charge_type": "On Net Total", "rate": 10, "description": "НӨАТ 10%"}]
		if vat
		else []
	)
	return frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": company,
			"customer": customer.name if hasattr(customer, "name") else customer,
			"posting_date": posting_date,
			"items": [{"item_name": "Үйлчилгээ", "qty": 1, "rate": amount, "income_account": INCOME}],
			"taxes": taxes,
			**extra,
		}
	)
