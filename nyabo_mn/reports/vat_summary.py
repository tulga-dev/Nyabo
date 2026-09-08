"""Monthly VAT summary for a VAT-payer company (output VAT, input VAT, net) from GL Entry.

Output VAT accumulates as credits on the ``output_vat`` role account, input VAT as debits
on the ``input_vat`` role account; the month's net is the difference. Per-document rows
let the accountant tie the figure to invoices before filing the monthly return.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from nyabo_mn.core.money import quantize
from nyabo_mn.reports import accounts, gl


def compute(company: str, period: str | tuple[Any, Any]) -> dict[str, Any]:
	"""{output_vat, input_vat, net, by_document, from_date, to_date, accounts} for 'YYYY-MM'."""
	start, end = gl.range_of(period)
	output_account = accounts.role_account(company, "output_vat")
	input_account = accounts.role_account(company, "input_vat")
	rows = gl.rows(company, start, end, accounts=[output_account, input_account])
	output_vat = Decimal("0")
	input_vat = Decimal("0")
	by_document: dict[tuple[str, str], dict[str, Any]] = {}
	for row in rows:
		entry = by_document.setdefault(
			(row.voucher_type, row.voucher_no),
			{
				"voucher_type": row.voucher_type,
				"voucher_no": row.voucher_no,
				"posting_date": row.posting_date,
				"party": row.party,
				"output_vat": Decimal("0"),
				"input_vat": Decimal("0"),
			},
		)
		if row.account == output_account:
			amount = gl.money(row.credit) - gl.money(row.debit)
			output_vat += amount
			entry["output_vat"] += amount
		else:
			amount = gl.money(row.debit) - gl.money(row.credit)
			input_vat += amount
			entry["input_vat"] += amount
	documents = [
		{**d, "output_vat": quantize(d["output_vat"]), "input_vat": quantize(d["input_vat"])}
		for d in by_document.values()
	]
	return {
		"output_vat": quantize(output_vat),
		"input_vat": quantize(input_vat),
		"net": quantize(output_vat - input_vat),
		"by_document": documents,
		"from_date": start,
		"to_date": end,
		"accounts": {"output_vat": output_account, "input_vat": input_account},
	}
