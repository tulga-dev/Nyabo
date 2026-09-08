"""erpnext.accounts.general_ledger for the stub: write GL Entry rows and reverse them.

Mirrors the version-16 behaviour the balances depend on (quoted in SOURCES.md):
negative amounts are toggled to the other side (``toggle_debit_credit_if_negative``),
the map must balance, the voucher's Accounting Period is checked, and cancelling marks
the original rows ``is_cancelled = 1`` and inserts swapped copies also flagged
``is_cancelled = 1`` (``make_reverse_gl_entries``), so balances exclude both.
Merging of similar entries, payment ledger, budgets and dimensions are not mirrored.
"""

from __future__ import annotations

from typing import Any

from frappe._stub.dictlike import _dict
from frappe.exceptions import ValidationError
from frappe.utils.data import flt, getdate


def toggle_debit_credit_if_negative(gl_map: list[_dict]) -> list[_dict]:
	debit_credit_field_map = {
		"debit": "credit",
		"debit_in_account_currency": "credit_in_account_currency",
		"debit_in_transaction_currency": "credit_in_transaction_currency",
	}
	for entry in gl_map:
		for debit_field, credit_field in debit_credit_field_map.items():
			debit = flt(entry.get(debit_field))
			credit = flt(entry.get(credit_field))
			if debit < 0 and credit < 0 and debit == credit:
				debit *= -1
				credit *= -1
			if debit < 0:
				credit = credit - debit
				debit = 0.0
			if credit < 0:
				debit = debit - credit
				credit = 0.0
			entry[debit_field] = debit
			entry[credit_field] = credit
	return gl_map


def process_gl_map(gl_map: list[_dict], merge_entries: bool = True, precision: int | None = None, from_repost: bool = False) -> list[_dict]:
	if not gl_map:
		return []
	return toggle_debit_credit_if_negative([_dict(e) for e in gl_map])


def validate_accounting_period(gl_map: list[_dict]) -> None:
	import frappe

	for entry in gl_map:
		voucher_type = entry.get("voucher_type")
		posting_date = getdate(entry.get("posting_date"))
		for period in frappe.get_all(
			"Accounting Period", fields=["name", "start_date", "end_date"], filters={"company": entry.get("company"), "disabled": 0}
		):
			if not (getdate(period.start_date) <= posting_date <= getdate(period.end_date)):
				continue
			closed = frappe.get_all(
				"Closed Document",
				filters={"parent": period.name, "parenttype": "Accounting Period", "document_type": voucher_type, "closed": 1},
			)
			if closed:
				raise ValidationError(
					f"You cannot create/edit a {voucher_type} within the closed Accounting Period {frappe.bold(period.name)}"
				)


def raise_debit_credit_not_equal_error(debit_credit_diff: float, voucher_type: str, voucher_no: str) -> None:
	raise ValidationError(f"Debit and Credit not equal for {voucher_type} #{voucher_no}. Difference is {debit_credit_diff}.")


def make_entry(args: dict[str, Any], adv_adj: bool = False, update_outstanding: str = "Yes", from_repost: bool = False) -> Any:
	import frappe

	payload = dict(args)
	payload["doctype"] = "GL Entry"
	payload.pop("name", None)
	gle = frappe.get_doc(payload)
	gle.flags.ignore_permissions = True
	gle.flags.from_repost = from_repost
	gle.insert()
	return gle


def make_gl_entries(
	gl_map: list[Any],
	cancel: bool = False,
	adv_adj: bool = False,
	merge_entries: bool = True,
	update_outstanding: str = "Yes",
	from_repost: bool = False,
) -> None:
	if not gl_map:
		return
	if cancel:
		make_reverse_gl_entries(gl_map, adv_adj=adv_adj, update_outstanding=update_outstanding)
		return
	validate_accounting_period(gl_map)
	gl_map = process_gl_map(gl_map, merge_entries, from_repost=from_repost)
	if len(gl_map) <= 1:
		raise ValidationError(
			"Incorrect number of General Ledger Entries found. You might have selected a wrong Account in the transaction."
		)
	debit = sum(flt(e.get("debit")) for e in gl_map)
	credit = sum(flt(e.get("credit")) for e in gl_map)
	diff = flt(debit - credit, 2)
	if abs(diff) > 0.005:
		raise_debit_credit_not_equal_error(diff, gl_map[0].get("voucher_type"), gl_map[0].get("voucher_no"))
	for entry in gl_map:
		make_entry(entry, adv_adj, update_outstanding, from_repost)


def make_reverse_gl_entries(
	gl_entries: list[Any] | None = None,
	voucher_type: str | None = None,
	voucher_no: str | None = None,
	adv_adj: bool = False,
	update_outstanding: str = "Yes",
	partial_cancel: bool = False,
	posting_date: Any = None,
) -> None:
	import frappe

	if not gl_entries:
		gl_entries = [
			_dict(r)
			for r in frappe.get_all(
				"GL Entry", fields=["*"], filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0}
			)
		]
	if not gl_entries:
		return
	validate_accounting_period(gl_entries)
	for entry in gl_entries:
		if entry.get("name"):
			frappe.db.set_value("GL Entry", entry["name"], "is_cancelled", 1)
	for entry in gl_entries:
		new_gle = _dict(entry)
		new_gle["name"] = None
		debit, credit = new_gle.get("debit", 0), new_gle.get("credit", 0)
		dac, cac = new_gle.get("debit_in_account_currency", 0), new_gle.get("credit_in_account_currency", 0)
		dtc, ctc = new_gle.get("debit_in_transaction_currency", 0), new_gle.get("credit_in_transaction_currency", 0)
		new_gle["debit"], new_gle["credit"] = credit, debit
		new_gle["debit_in_account_currency"], new_gle["credit_in_account_currency"] = cac, dac
		new_gle["debit_in_transaction_currency"], new_gle["credit_in_transaction_currency"] = ctc, dtc
		new_gle["remarks"] = "On cancellation of " + str(new_gle["voucher_no"])
		new_gle["is_cancelled"] = 1
		if posting_date:
			new_gle["posting_date"] = posting_date
		for key in ("creation", "modified", "owner", "modified_by", "docstatus", "idx", "_seq"):
			new_gle.pop(key, None)
		if new_gle["debit"] or new_gle["credit"]:
			make_entry(new_gle, adv_adj, "Yes")


def merge_similar_entries(gl_map: list[Any], precision: int | None = None) -> list[Any]:
	return list(gl_map)
