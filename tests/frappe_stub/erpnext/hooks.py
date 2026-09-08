"""The ERPNext hooks the stub honours (erpnext/hooks.py, version-16, quoted in SOURCES.md)."""

from __future__ import annotations

app_name = "erpnext"

period_closing_doctypes = [
	"Sales Invoice",
	"Purchase Invoice",
	"Journal Entry",
	"Bank Clearance",
	"Stock Entry",
	"Dunning",
	"Invoice Discounting",
	"Payment Entry",
	"Period Closing Voucher",
	"Process Deferred Accounting",
	"Asset",
	"Asset Capitalization",
	"Asset Repair",
	"Delivery Note",
	"Landed Cost Voucher",
	"Purchase Receipt",
	"Stock Reconciliation",
	"Subcontracting Receipt",
]

doc_events = {
	tuple(period_closing_doctypes): {
		"validate": "erpnext.accounts.doctype.accounting_period.accounting_period.validate_accounting_period_on_doc_save",
	},
}

bank_reconciliation_doctypes = [
	"Payment Entry",
	"Journal Entry",
	"Purchase Invoice",
	"Sales Invoice",
	"Bank Transaction",
]
