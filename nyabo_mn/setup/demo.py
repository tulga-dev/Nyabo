"""Demo entries for a test company, so the dashboard shows figures before a real receipt lands.

What it writes, dated over the last six months up to today: monthly sales receipts into the
bank, rent and salaries out of it, a few supplies and a phone bill out of cash — every one a
submitted ERPNext voucher carrying ``nyabo_primary_document_ref`` = «ДЕМО …», which is the
honest answer to art. 13.7 (there is no paper document, and the entry says so); then two bank
deposits nobody matched, with a ``statement_imported`` event so the bank card can show a
statement balance beside the ledger balance; and, when the company keeps stock, a small
opening list through the same intake the wizard uses.

What it refuses: any company whose ledger already holds a posting. The seed is for an empty
test ledger, and a second run on the same company answers «already seeded» from the
``demo_seeded`` event instead of doubling every figure. It also never invents an account: each
line asks the chart for a role (``reports.accounts``) and falls back to the company's default
expense account, so a chart without a rent leaf still seeds, just less colourfully.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import frappe

from nyabo_mn.core import dates
from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event
from nyabo_mn.reports import accounts as report_accounts

DEMO_TAG = "ДЕМО"
EVENT_SEEDED = "demo_seeded"
MONTHS = 6

# (customer, base amount); the amount grows month over month so the trend has a shape.
SALES = (("Ганзориг ХХК", Decimal("7400000")), ("Сарнай ХХК", Decimal("4700000")))
RENT = ("Монгол Пропертиз ХХК", Decimal("4200000"))
SALARY = Decimal("3650000")
SUPPLIES = (("Номин Супермаркет", Decimal("186500")), ("МСS Кока-Кола ХХК", Decimal("412300")))
PHONE = ("Юнител ХХК", Decimal("89000"))
CASH_FLOAT = Decimal("1000000")
UNMATCHED = (("Болд Б. · INV-031 үлдэгдэл", Decimal("150000")), ("Сарнай ХХК", Decimal("50000")))
STOCK = (
	("Цаас A4, боодол", 120, 12500),
	("Принтерийн хор", 4, 185000),
	("Картридж HP 305", 1, 62000),
	("Ус, 19л", 40, 6000),
	("Кофе, кг", 20, 43000),
)

# Expense leaves are found by what their name says, so the top-expenses card has more than one
# row; anything without a leaf goes to the company's default expense account.
EXPENSE_KEYWORDS = {
	"rent": ("түрээс",),
	"phone": ("холбоо", "интернэт", "утас"),
	"supplies": ("бичиг хэрэг", "материал", "хангамж"),
}


class DemoRefused(ValueError):
	"""The company is not an empty test ledger; nothing was written."""


def _ref(what: str) -> str:
	return f"{DEMO_TAG}: {what}"


def already_seeded(company: str) -> bool:
	return bool(
		frappe.db.exists("DocType", "Nyabo Event")
		and frappe.db.exists("Nyabo Event", {"event_type": EVENT_SEEDED, "company": company})
	)


def _ledger_is_empty(company: str) -> bool:
	return frappe.db.count("GL Entry", {"company": company, "is_cancelled": 0}) == 0


def _expense_leaf(company: str, kind: str, default: str) -> str:
	names = frappe.get_all(
		"Account",
		filters={"company": company, "root_type": "Expense", "is_group": 0},
		fields=["name", "account_name"],
	)
	for row in names:
		label = (row.account_name or row.name).lower()
		if any(word in label for word in EXPENSE_KEYWORDS[kind]):
			return row.name
	return default


def _accounts(company: str) -> dict[str, str]:
	default_expense = report_accounts.role_account(company, "default_expense")
	out = {
		"bank": report_accounts.role_account(company, "bank"),
		"cash": report_accounts.role_account(company, "cash"),
		"revenue": report_accounts.role_account_or_none(company, "revenue_sales")
		or report_accounts.role_account(company, "revenue_services"),
		"salary": report_accounts.role_account_or_none(company, "salary_expense") or default_expense,
		"default_expense": default_expense,
	}
	for kind in EXPENSE_KEYWORDS:
		out[kind] = _expense_leaf(company, kind, default_expense)
	return out


def _ensure_supplier(name: str) -> str:
	if not frappe.db.exists("Supplier", name):
		frappe.get_doc({"doctype": "Supplier", "supplier_name": name}).insert(ignore_permissions=True)
	return name


def _journal(company: str, day: dt.date, debit: str, credit: str, amount: Decimal, what: str) -> str:
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": company,
			"posting_date": day.isoformat(),
			"user_remark": _ref(what),
			"nyabo_primary_document_ref": _ref(what),
			"nyabo_explanation": _ref(what),
			"accounts": [
				{"account": debit, "debit_in_account_currency": float(amount)},
				{"account": credit, "credit_in_account_currency": float(amount)},
			],
		}
	)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name


def _purchase(
	company: str, day: dt.date, supplier: str, amount: Decimal, expense: str, paid_from: str, what: str
) -> str:
	_ensure_supplier(supplier)
	pi = frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"company": company,
			"supplier": supplier,
			"posting_date": day.isoformat(),
			"bill_no": f"{DEMO_TAG}-{day.strftime('%y%m')}-{int(amount)}",
			"is_paid": 1,
			"cash_bank_account": paid_from,
			"paid_amount": float(amount),
			"nyabo_primary_document_ref": _ref(what),
			"nyabo_explanation": _ref(what),
			"remarks": _ref(what),
			"items": [{"item_name": what, "qty": 1, "rate": float(amount), "expense_account": expense}],
		}
	)
	pi.flags.ignore_permissions = True
	pi.insert()
	pi.submit()
	return pi.name


def _month_days(today: dt.date, months: int) -> list[tuple[str, dt.date]]:
	"""``(period, a day in it)`` for the last ``months`` months, oldest first; this month up to today."""
	out = []
	year, month = today.year, today.month
	for offset in range(months - 1, -1, -1):
		index = year * 12 + (month - 1) - offset
		y, m = index // 12, index % 12 + 1
		out.append((f"{y:04d}-{m:02d}", dt.date(y, m, 1)))
	return out


def _clamp(day: dt.date, today: dt.date) -> dt.date:
	return min(day, today)


def _seed_ledger(company: str, today: dt.date, acc: dict[str, str]) -> list[str]:
	created: list[str] = []
	for index, (_period, first) in enumerate(_month_days(today, MONTHS)):
		growth = Decimal(1) + Decimal(index) * Decimal("0.09")
		for position, (customer, base) in enumerate(SALES):
			amount = (base * growth).quantize(Decimal("1"))
			day = _clamp(first.replace(day=9 + 5 * position), today)
			created.append(
				_journal(company, day, acc["bank"], acc["revenue"], amount, f"{customer} · борлуулалт")
			)
		# Cash for the small purchases below comes out of the bank once a month, so the cash
		# account never runs negative on a card.
		day = _clamp(first.replace(day=1), today)
		created.append(_journal(company, day, acc["cash"], acc["bank"], CASH_FLOAT, "Кассанд мөнгө татах"))
		created.append(_purchase(company, day, RENT[0], RENT[1], acc["rent"], acc["bank"], "Оффисын түрээс"))
		day = _clamp(first.replace(day=8), today)
		created.append(_journal(company, day, acc["salary"], acc["bank"], SALARY, "Цалин"))
		for offset, (supplier, amount) in enumerate(SUPPLIES):
			day = _clamp(first.replace(day=2 + offset * 4), today)
			created.append(
				_purchase(
					company, day, supplier, amount, acc["supplies"], acc["cash"], "Бичиг хэрэг, хангамж"
				)
			)
		day = _clamp(first.replace(day=4), today)
		created.append(
			_purchase(company, day, PHONE[0], PHONE[1], acc["phone"], acc["bank"], "Интернэт, утас")
		)
	return created


def _seed_bank(company: str, today: dt.date) -> dict[str, Any]:
	"""Two deposits nobody matched, plus the statement balance the bank would have printed."""
	from erpnext.accounts.utils import get_balance_on

	from nyabo_mn.matching import common

	rows = [r for r in common.bank_rows(company) if r.get("erpnext_bank_account")]
	if not rows:
		return {"skipped": "no bank account configured (run /эхлэх or provisioning first)"}
	row = rows[0]
	bank_account = str(row["erpnext_bank_account"])
	gl_account = row.get("gl_account") or common.gl_account_of(bank_account)
	created = []
	for offset, (description, amount) in enumerate(UNMATCHED):
		day = today - dt.timedelta(days=1 + offset)
		doc = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"date": day.isoformat(),
				"deposit": float(amount),
				"withdrawal": 0.0,
				"description": description,
				"reference_number": f"{DEMO_TAG}-{offset + 1}",
				"transaction_id": f"{DEMO_TAG}-{company}-{offset + 1}",
				"bank_account": bank_account,
				"company": company,
				"currency": str(row.get("currency") or "MNT"),
				"status": "Pending",
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		doc.submit()
		created.append(doc.name)
	ledger = Decimal(str(get_balance_on(gl_account, today.isoformat()) or 0)) if gl_account else Decimal(0)
	closing = ledger + sum((amount for _d, amount in UNMATCHED), Decimal(0))
	common.write_event(
		"statement_imported",
		company=company,
		payload={
			"document": None,
			"bank": row.get("bank"),
			"layout": DEMO_TAG,
			"bank_account": bank_account,
			"currency": str(row.get("currency") or "MNT"),
			"count": len(created),
			"new": len(created),
			"dup": 0,
			"transactions": created,
			"row_hashes": [],
			"closing_balance": common.decimal_str(closing),
			"closing_date": today.isoformat(),
		},
	)
	return {"bank_account": bank_account, "transactions": created, "closing_balance": str(closing)}


def _seed_stock(company: str, today: dt.date, user: str) -> dict[str, Any]:
	from nyabo_mn.setup import inventory_intake

	settings = frappe.db.get_value("Nyabo Company Settings", {"company": company}, "has_inventory")
	if not settings:
		return {"skipped": "company keeps no stock (has_inventory = 0)"}
	rows = [{"item_name": name, "qty": qty, "rate": rate} for name, qty, rate in STOCK]
	intake = inventory_intake.create_intake(company, "text", rows, today)
	inventory_intake.confirm_intake(intake.name, user)
	created = inventory_intake.post_intake(intake.name, user)
	return {"intake": intake.name, **created}


def seed(company: str, today: dt.date | None = None, user: str | None = None) -> dict[str, Any]:
	"""Fill an empty test ledger; refuse a ledger with postings; answer «already» on a second run."""
	today = today or dt.date.today()
	user = user or frappe.session.user
	if not frappe.db.exists("Company", company):
		raise DemoRefused(mn.MSG_DEMO_NO_COMPANY.format(company=company))
	if already_seeded(company):
		return {"company": company, "already": True}
	if not _ledger_is_empty(company):
		raise DemoRefused(mn.MSG_DEMO_LEDGER_NOT_EMPTY.format(company=company))
	acc = _accounts(company)
	vouchers = _seed_ledger(company, today, acc)
	bank = _seed_bank(company, today)
	stock = _seed_stock(company, today, user)
	from nyabo_mn.matching import common

	common.write_event(
		EVENT_SEEDED,
		company=company,
		payload={"vouchers": len(vouchers), "bank": bank, "stock": stock, "months": MONTHS},
		actor_user=user,
	)
	log_event("demo.seeded", company=company, vouchers=len(vouchers), user=user)
	return {
		"company": company,
		"already": False,
		"vouchers": len(vouchers),
		"period_from": dates.period_of(_month_days(today, MONTHS)[0][1]),
		"period_to": dates.period_of(today),
		"bank": bank,
		"stock": stock,
	}


__all__ = ["DEMO_TAG", "DemoRefused", "already_seeded", "seed"]
