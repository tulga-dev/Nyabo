"""Accounting behaviour of the stub: GL Entry rows, balances, reversals, period lock, FX, bank match."""

from __future__ import annotations

import pytest

import frappe
from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note
from erpnext.accounts.utils import get_balance_on
from erpnext.setup.utils import get_exchange_rate

EXPENSE = "6210 - Шатахуун - TST"
CASH = "1110 - Касс - TST"
BANK = "1120 - Банкны харилцах данс - TST"
PAYABLE = "2110 - Дансны өглөг - TST"
INPUT_VAT = "1810 - Татан суутгах НӨАТ - TST"
OUTPUT_VAT = "2210 - Төлөх НӨАТ - TST"
RECEIVABLE = "1310 - Дансны авлага - TST"
INCOME = "4110 - Борлуулалтын орлого - TST"


@pytest.fixture
def books(company, frappe_hooks):
	"""A provisioned company with Nyabo's compliance hooks (another module) switched off."""
	with frappe_hooks(without_apps=("nyabo_mn",)):
		frappe.get_doc({"doctype": "Supplier", "supplier_name": "Петровис ХХК", "tin": "12345678"}).insert()
		frappe.get_doc({"doctype": "Customer", "customer_name": "Хэрэглэгч ХХК"}).insert()
		yield company


def _je(company, debit, credit, amount, posting_date="2026-03-05", **extra):
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


def test_journal_entry_submit_writes_gl_and_balance(books):
	je = _je(books, EXPENSE, CASH, 85000).insert()
	assert je.total_debit == 85000 and je.difference == 0
	assert frappe.db.count("GL Entry", {"voucher_no": je.name}) == 0
	je.submit()
	rows = frappe.get_all("GL Entry", filters={"voucher_no": je.name}, fields=["account", "debit", "credit", "is_cancelled", "docstatus"])
	assert {(r.account, r.debit, r.credit) for r in rows} == {(EXPENSE, 85000.0, 0.0), (CASH, 0.0, 85000.0)}
	assert all(r.is_cancelled == 0 and r.docstatus == 1 for r in rows)
	assert get_balance_on(EXPENSE, "2026-03-31") == 85000.0
	assert get_balance_on(CASH, "2026-03-31") == -85000.0
	assert get_balance_on(EXPENSE, "2026-03-04") == 0.0
	assert get_balance_on(EXPENSE, "2025-12-31") == 0.0  # before any fiscal year
	assert get_balance_on("Зардал - TST") == 85000.0  # group account
	je.cancel()
	rows = frappe.get_all("GL Entry", filters={"voucher_no": je.name}, fields=["account", "debit", "credit", "is_cancelled"])
	assert len(rows) == 4 and all(r.is_cancelled == 1 for r in rows)
	assert (CASH, 85000.0, 0.0) in {(r.account, r.debit, r.credit) for r in rows}
	assert get_balance_on(EXPENSE) == 0.0


def test_unbalanced_or_group_account_entries_are_refused(books):
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": books,
			"posting_date": "2026-03-05",
			"accounts": [
				{"account": EXPENSE, "debit_in_account_currency": 100},
				{"account": CASH, "credit_in_account_currency": 90},
			],
		}
	)
	with pytest.raises(frappe.ValidationError, match="Total Debit must be equal to Total Credit"):
		je.insert()
	group = _je(books, "Зардал - TST", CASH, 100).insert()
	with pytest.raises(frappe.ValidationError, match="Group Account"):
		group.submit()
	with pytest.raises(frappe.ValidationError, match="not in any active Fiscal Year"):
		_je(books, EXPENSE, CASH, 100, posting_date="2031-01-01").insert().submit()


def test_reverse_journal_entry_helper(books):
	je = _je(books, EXPENSE, CASH, 50000).insert()
	je.submit()
	with pytest.raises(frappe.ValidationError, match="condition fails"):
		make_reverse_journal_entry(_je(books, EXPENSE, CASH, 1).insert().name)
	rev = make_reverse_journal_entry(je.name)
	assert rev.is_new() and rev.reversal_of == je.name
	assert rev.posting_date is None and rev.user_remark is None  # no_copy
	assert [(r.account, r.debit_in_account_currency, r.credit_in_account_currency) for r in rev.accounts] == [
		(EXPENSE, 0.0, 50000.0),
		(CASH, 50000.0, 0.0),
	]
	rev.posting_date = "2026-03-06"
	rev.user_remark = "Буруу данс"
	rev.insert()
	rev.submit()
	assert get_balance_on(EXPENSE, "2026-03-31") == 0.0
	with pytest.raises(frappe.ValidationError, match="already a Reverse Journal Entry"):
		make_reverse_journal_entry(rev.name)
	with pytest.raises(frappe.ValidationError, match="already exists"):
		make_reverse_journal_entry(je.name)


def _purchase_invoice(company, vat=True):
	taxes = [{"account_head": INPUT_VAT, "charge_type": "On Net Total", "rate": 10, "description": "НӨАТ 10%"}] if vat else []
	return frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"company": company,
			"supplier": "Петровис ХХК",
			"posting_date": "2026-03-10",
			"bill_no": "AB-1",
			"items": [{"item_name": "Бензин", "qty": 2, "rate": 42500, "expense_account": EXPENSE}],
			"taxes": taxes,
		}
	)


def test_purchase_invoice_gl_and_debit_note(books):
	pi = _purchase_invoice(books).insert()
	assert (pi.net_total, pi.total_taxes_and_charges, pi.grand_total) == (85000.0, 8500.0, 93500.0)
	assert pi.credit_to == PAYABLE and pi.status == "Draft"
	assert pi.naming_series == "ACC-PINV-.YYYY.-" and pi.name.startswith("ACC-PINV-2026-")
	pi.submit()
	rows = {(r.account, r.debit, r.credit) for r in frappe.get_all("GL Entry", filters={"voucher_no": pi.name}, fields=["account", "debit", "credit"])}
	assert rows == {(EXPENSE, 85000.0, 0.0), (INPUT_VAT, 8500.0, 0.0), (PAYABLE, 0.0, 93500.0)}
	assert frappe.db.get_value("Purchase Invoice", pi.name, "status") == "Unpaid"
	assert get_balance_on(PAYABLE, "2026-03-31", party_type="Supplier", party="Петровис ХХК") == -93500.0

	note = make_debit_note(pi.name)
	assert note.is_return == 1 and note.return_against == pi.name and note.is_new()
	assert note.items[0].qty == -2 and note.grand_total == -93500.0
	note.posting_date = note.due_date = "2026-03-12"
	note.insert()
	note.submit()
	assert frappe.db.get_value("Purchase Invoice", pi.name, "status") == "Debit Note Issued"
	assert frappe.db.get_value("Purchase Invoice", note.name, "status") == "Return"
	rows = {(r.account, r.debit, r.credit) for r in frappe.get_all("GL Entry", filters={"voucher_no": note.name}, fields=["account", "debit", "credit"])}
	assert rows == {(EXPENSE, 0.0, 85000.0), (INPUT_VAT, 0.0, 8500.0), (PAYABLE, 93500.0, 0.0)}
	assert get_balance_on(PAYABLE, "2026-03-31") == 0.0
	assert get_balance_on(EXPENSE, "2026-03-31") == 0.0


def test_sales_invoice_gl(books):
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": books,
			"customer": "Хэрэглэгч ХХК",
			"posting_date": "2026-03-15",
			"items": [{"item_name": "Үйлчилгээ", "qty": 1, "rate": 200000, "income_account": INCOME}],
			"taxes": [{"account_head": OUTPUT_VAT, "charge_type": "On Net Total", "rate": 10, "description": "НӨАТ 10%"}],
		}
	).insert()
	assert si.debit_to == RECEIVABLE and si.grand_total == 220000.0
	si.submit()
	rows = {(r.account, r.debit, r.credit) for r in frappe.get_all("GL Entry", filters={"voucher_no": si.name}, fields=["account", "debit", "credit"])}
	assert rows == {(RECEIVABLE, 220000.0, 0.0), (INCOME, 0.0, 200000.0), (OUTPUT_VAT, 0.0, 20000.0)}
	assert get_balance_on(INCOME, "2026-03-31") == -200000.0


def test_closed_accounting_period_blocks_postings(books):
	frappe.get_doc(
		{"doctype": "Accounting Period", "period_name": "2026-02", "company": books, "start_date": "2026-02-01", "end_date": "2026-02-28"}
	).insert()
	with pytest.raises(frappe.ValidationError, match="closed Accounting Period <b>2026-02 - TST</b>"):
		_je(books, EXPENSE, CASH, 100, posting_date="2026-02-10").insert()
	with pytest.raises(frappe.ValidationError, match="You cannot create a Purchase Invoice"):
		pi = _purchase_invoice(books)
		pi.posting_date = "2026-02-28"
		pi.insert()
	_je(books, EXPENSE, CASH, 100, posting_date="2026-03-01").insert()
	with pytest.raises(frappe.ValidationError, match="future date"):
		frappe.get_doc(
			{"doctype": "Accounting Period", "period_name": "2099-01", "company": books, "start_date": "2099-01-01", "end_date": "2099-01-31"}
		).insert()
	with pytest.raises(frappe.ValidationError, match="overlaps"):
		frappe.get_doc(
			{"doctype": "Accounting Period", "period_name": "2026-02b", "company": books, "start_date": "2026-02-15", "end_date": "2026-03-15"}
		).insert()
	period = frappe.get_doc("Accounting Period", "2026-02 - TST")
	period.disabled = 1
	period.save()
	_je(books, EXPENSE, CASH, 100, posting_date="2026-02-10").insert()


def test_exchange_rate_from_currency_exchange_rows(books):
	assert get_exchange_rate("MNT", "MNT") == 1
	frappe.get_doc(
		{"doctype": "Currency Exchange", "date": "2026-03-01", "from_currency": "USD", "to_currency": "MNT", "exchange_rate": 3450, "for_buying": 1, "for_selling": 1}
	).insert()
	frappe.get_doc(
		{"doctype": "Currency Exchange", "date": "2026-03-10", "from_currency": "USD", "to_currency": "MNT", "exchange_rate": 3500, "for_buying": 1, "for_selling": 1}
	).insert()
	assert get_exchange_rate("USD", "MNT", "2026-03-05") == 3450.0
	assert get_exchange_rate("USD", "MNT", "2026-03-12") == 3500.0
	assert frappe.db.exists("Currency Exchange", "2026-03-10-USD-MNT")
	with pytest.raises(NotImplementedError):
		get_exchange_rate("EUR", "MNT", "2026-03-12")
	frappe.db.set_single_value("Currency Exchange Settings", "disabled", 1)
	assert get_exchange_rate("EUR", "MNT", "2026-03-12") == 0.0


def test_bank_transaction_add_payment_entries_reconciles(books):
	bank = frappe.get_doc({"doctype": "Bank", "bank_name": "Khan Bank"}).insert()
	bank_account = frappe.get_doc(
		{"doctype": "Bank Account", "account_name": "Хаан MNT", "bank": bank.name, "account": BANK, "company": books, "is_company_account": 1}
	).insert()
	je = _je(books, EXPENSE, BANK, 50000, posting_date="2026-03-20").insert()
	je.submit()
	bt = frappe.get_doc(
		{
			"doctype": "Bank Transaction",
			"date": "2026-03-21",
			"bank_account": bank_account.name,
			"company": books,
			"withdrawal": 50000,
			"description": "PETROVIS 50,000",
			"currency": "MNT",
		}
	).insert()
	bt.submit()
	assert (bt.status, bt.unallocated_amount) == ("Unreconciled", 50000.0)
	bt.add_payment_entries([{"payment_doctype": "Journal Entry", "payment_name": je.name}])
	bt.save()
	bt.reload()
	assert (bt.status, bt.allocated_amount, bt.unallocated_amount) == ("Reconciled", 50000.0, 0.0)
	assert bt.payment_entries[0].allocated_amount == 50000.0
	assert str(frappe.db.get_value("Journal Entry", je.name, "clearance_date")) == "2026-03-21"
	with pytest.raises(frappe.ValidationError, match="already fully reconciled"):
		bt.add_payment_entries([{"payment_doctype": "Journal Entry", "payment_name": je.name}])
