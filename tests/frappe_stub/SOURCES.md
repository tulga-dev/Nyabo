# Sources for the Frappe test stub

Everything in `erpnext_meta.json` and every ERPNext behaviour the stub mirrors was read
from the `version-16` branches on 2026-09-08. Regenerate the meta file by re-fetching the
URLs below and reducing each DocType JSON to
`{autoname, istable, is_submittable, track_changes, permissions, fields[...]}` where a
field keeps `fieldname, fieldtype, options, reqd, default, read_only` plus, only when
truthy, `allow_on_submit` (edits after submit), `no_copy` (reversal / return mapping),
`label` (error messages), `precision`, `unique`, `is_virtual`. `permissions` keeps
`role` and the truthy `read/write/create/delete/submit/cancel/amend` flags of permlevel 0.
The extra keys are the minimum the stub needs to honour ERPNext semantics; the task
asked for the first six only, the rest is documented here so nobody mistakes it for
invented data.

## DocType JSON (erpnext_meta.json)

ERPNext base: `https://raw.githubusercontent.com/frappe/erpnext/version-16/`

| DocType | Path |
|---|---|
| Purchase Invoice | erpnext/accounts/doctype/purchase_invoice/purchase_invoice.json |
| Purchase Invoice Item | erpnext/accounts/doctype/purchase_invoice_item/purchase_invoice_item.json |
| Purchase Taxes and Charges | erpnext/accounts/doctype/purchase_taxes_and_charges/purchase_taxes_and_charges.json |
| Sales Invoice | erpnext/accounts/doctype/sales_invoice/sales_invoice.json |
| Sales Invoice Item | erpnext/accounts/doctype/sales_invoice_item/sales_invoice_item.json |
| Sales Invoice Payment | erpnext/accounts/doctype/sales_invoice_payment/sales_invoice_payment.json |
| Sales Taxes and Charges | erpnext/accounts/doctype/sales_taxes_and_charges/sales_taxes_and_charges.json |
| Journal Entry | erpnext/accounts/doctype/journal_entry/journal_entry.json |
| Journal Entry Account | erpnext/accounts/doctype/journal_entry_account/journal_entry_account.json |
| Payment Entry | erpnext/accounts/doctype/payment_entry/payment_entry.json |
| Supplier | erpnext/buying/doctype/supplier/supplier.json |
| Customer | erpnext/selling/doctype/customer/customer.json |
| Item | erpnext/stock/doctype/item/item.json |
| Item Tax Template | erpnext/accounts/doctype/item_tax_template/item_tax_template.json |
| Item Tax Template Detail | erpnext/accounts/doctype/item_tax_template_detail/item_tax_template_detail.json |
| Sales Taxes and Charges Template | erpnext/accounts/doctype/sales_taxes_and_charges_template/sales_taxes_and_charges_template.json |
| Purchase Taxes and Charges Template | erpnext/accounts/doctype/purchase_taxes_and_charges_template/purchase_taxes_and_charges_template.json |
| Bank | erpnext/accounts/doctype/bank/bank.json |
| Bank Account | erpnext/accounts/doctype/bank_account/bank_account.json |
| Bank Transaction | erpnext/accounts/doctype/bank_transaction/bank_transaction.json |
| Bank Transaction Payments | erpnext/accounts/doctype/bank_transaction_payments/bank_transaction_payments.json |
| Account | erpnext/accounts/doctype/account/account.json |
| Company | erpnext/setup/doctype/company/company.json |
| Cost Center | erpnext/accounts/doctype/cost_center/cost_center.json |
| Fiscal Year | erpnext/accounts/doctype/fiscal_year/fiscal_year.json |
| Accounting Period | erpnext/accounts/doctype/accounting_period/accounting_period.json |
| Closed Document | erpnext/accounts/doctype/closed_document/closed_document.json |
| Currency Exchange | erpnext/setup/doctype/currency_exchange/currency_exchange.json |
| Warehouse | erpnext/stock/doctype/warehouse/warehouse.json |
| Stock Reconciliation | erpnext/stock/doctype/stock_reconciliation/stock_reconciliation.json |
| Stock Reconciliation Item | erpnext/stock/doctype/stock_reconciliation_item/stock_reconciliation_item.json |
| GL Entry | erpnext/accounts/doctype/gl_entry/gl_entry.json |
| Mode of Payment | erpnext/accounts/doctype/mode_of_payment/mode_of_payment.json |
| Financial Report Template | erpnext/accounts/doctype/financial_report_template/financial_report_template.json |
| Financial Report Row | erpnext/accounts/doctype/financial_report_row/financial_report_row.json |
| Account Category | erpnext/accounts/doctype/account_category/account_category.json |
| Item Group | erpnext/setup/doctype/item_group/item_group.json |
| UOM | erpnext/setup/doctype/uom/uom.json (added by the setup/inventory author, read 2026-09-08) |
| Supplier Group | erpnext/setup/doctype/supplier_group/supplier_group.json |

Frappe base: `https://raw.githubusercontent.com/frappe/frappe/version-16/`

| DocType | Path |
|---|---|
| Currency | frappe/geo/doctype/currency/currency.json |
| File | frappe/core/doctype/file/file.json |
| User | frappe/core/doctype/user/user.json |
| Has Role | frappe/core/doctype/has_role/has_role.json |
| Role | frappe/core/doctype/role/role.json |
| Version | frappe/core/doctype/version/version.json |
| Deleted Document | frappe/core/doctype/deleted_document/deleted_document.json |
| Error Log | frappe/core/doctype/error_log/error_log.json |
| Report | frappe/core/doctype/report/report.json |
| Print Format | frappe/printing/doctype/print_format/print_format.json |
| Comment | frappe/core/doctype/comment/comment.json |
| Custom Field | frappe/custom/doctype/custom_field/custom_field.json |
| Property Setter | frappe/custom/doctype/property_setter/property_setter.json |

Seed data: the 29 standard Account Categories come from
`erpnext/accounts/financial_report_template/account_categories.json`
(copied to `tests/frappe_stub/account_categories.json`).

## Behaviour mirrored from source (same bases as above)

| Stub feature | Source file |
|---|---|
| `create_charts` (name building, `is_group` detection, report_type, suffix on duplicates) | erpnext/accounts/doctype/account/chart_of_accounts/chart_of_accounts.py |
| Account autoname `<number> - <name> - <abbr>` | erpnext/accounts/utils.py (`get_autoname_with_number`) |
| Bank Account autoname `<account_name> - <bank>` | erpnext/accounts/doctype/bank_account/bank_account.py |
| Warehouse autoname `<warehouse_name> - <abbr>` | erpnext/stock/doctype/warehouse/warehouse.py |
| Tax template autoname `<title> - <abbr>` | erpnext/accounts/doctype/{sales,purchase}_taxes_and_charges_template/*.py, item_tax_template.py |
| Currency Exchange autoname `<yyyy-MM-dd>-<from>-<to>[-<purpose>]` | erpnext/setup/doctype/currency_exchange/currency_exchange.py |
| Supplier / Customer named by `supplier_name` / `customer_name` (master name setting default) | erpnext/buying/doctype/supplier/supplier.py |
| Company: `validate_abbr`, `create_default_warehouses`, cost centre names, `ignore_chart_of_accounts` flag | erpnext/setup/doctype/company/company.py |
| Accounting Period: autoname, `validate_dates`, `validate_overlap`, `bootstrap_doctypes_for_closing`, `validate_accounting_period_on_doc_save` message | erpnext/accounts/doctype/accounting_period/accounting_period.py |
| `period_closing_doctypes` list | erpnext/hooks.py |
| `make_reverse_journal_entry` (guards, field_map swapping debit/credit, `reversal_of`) | erpnext/accounts/doctype/journal_entry/journal_entry.py |
| `make_debit_note` -> `make_return_doc` (`is_return`, `return_against`, negated qty) | erpnext/accounts/doctype/purchase_invoice/purchase_invoice.py, erpnext/controllers/sales_and_purchase_return.py |
| Bank Transaction `add_payment_entries`, `update_allocated_amount`, `set_status`, `allocate_payment_entries` | erpnext/accounts/doctype/bank_transaction/bank_transaction.py |
| `get_exchange_rate` (Currency Exchange lookup, `Currency Exchange Settings.disabled`) | erpnext/setup/utils.py |
| `get_balance_on` signature | erpnext/accounts/utils.py |
| `sync_financial_report_templates` signature | erpnext/accounts/doctype/financial_report_template/financial_report_template.py |
| Group-account GL refusal message | erpnext/accounts/doctype/gl_entry/gl_entry.py (`validate_account_details`) |
| Naming: `field:`, `naming_series:`, `format:`, `.####`, `hash`, `YYYY/YY/MM/DD` parts | frappe/model/naming.py |
| Insert / save order of controller and hook methods, `_action` transitions | frappe/model/document.py |
| `_validate_update_after_submit`, mandatory and link checks | frappe/model/base_document.py |
| `default_fields`, `table_fields`, `numeric_fieldtypes` | frappe/model/__init__.py |
| `get_mapped_doc` no_copy handling | frappe/model/mapper.py |
| Delete order (`on_trash` -> link check -> row delete -> `after_delete` -> attached Files -> Deleted Document) | frappe/model/delete_doc.py |
| Version `data` layout (`changed`, `added`, `removed`, `row_changed`), no Version on plain insert | frappe/core/doctype/version/version.py |
| File: `content` written on insert, `get_content()` | frappe/core/doctype/file/file.py |
| Exception hierarchy | frappe/exceptions.py |

What is deliberately *not* mirrored raises `NotImplementedError` with a message
(`frappe.db.sql`, SQL-ish aggregate fields, `descendants of` filters, ERPNext's external
exchange-rate provider, item tax templates on invoice rows, "On Previous Row" charges,
"Valuation" purchase taxes, the Standard chart of accounts, ...).

## Bank Transaction: the version-16 source the stub follows

`erpnext/accounts/doctype/bank_transaction/bank_transaction.py`, read 2026-09-08. The
stub keeps the method bodies; only the two SQL helpers (`get_total_allocated_amount`,
`get_related_bank_gl_entries`) are re-expressed as loops over the in-memory tables.
(Plain fence on purpose: ruff formats ```python blocks in Markdown and this is a quote.)

```
def add_payment_entries(self, vouchers, is_new_voucher: bool = False):
	"""
	Add the vouchers with zero allocation. Save() will perform the allocations and clearance

	is_new_voucher - is used to set the reonciliation type - whether the voucher was added as a result of "Matching" or a new voucher was created.
	Used in bank reconciliation
	"""
	if 0.0 >= self.unallocated_amount:
		frappe.throw(_("Bank Transaction {0} is already fully reconciled").format(self.name))

	for voucher in vouchers:
		self.append(
			"payment_entries",
			{
				"payment_document": voucher["payment_doctype"],
				"payment_entry": voucher["payment_name"],
				"allocated_amount": 0.0,  # Temporary
				"reconciliation_type": "Voucher Created" if is_new_voucher else "Matched",
			},
		)

def before_update_after_submit(self):
	self.validate_duplicate_references()
	self.update_allocated_amount()
	self.delink_old_payment_entries()
	self.allocate_payment_entries()
	self.set_status()

def update_allocated_amount(self):
	allocated_amount = (
		sum(p.allocated_amount for p in self.payment_entries) if self.payment_entries else 0.0
	)
	unallocated_amount = abs(flt(self.withdrawal) - flt(self.deposit)) - allocated_amount

	self.allocated_amount = flt(allocated_amount, self.precision("allocated_amount"))
	self.unallocated_amount = flt(unallocated_amount, self.precision("unallocated_amount"))

def set_status(self):
	if self.docstatus == 2:
		self.db_set("status", "Cancelled")
	elif self.docstatus == 1:
		if self.unallocated_amount > 0:
			self.db_set("status", "Unreconciled")
		elif self.unallocated_amount <= 0:
			self.db_set("status", "Reconciled")
```

`allocate_payment_entries`, `get_clearance_details`, `clear_linked_payment_entry`,
`update_linked_bank_transaction`, `remove_payment_entry`, `delink_payment_entry`,
`validate_duplicate_references`, `validate_currency` and `validate_included_fee` are in
the stub module with the same bodies. `delink_old_payment_entries` (rows removed from the
table since the last save) and `auto_set_party` (Accounts Settings party matching) are
not mirrored: the first is a no-op in the stub, the second is skipped.

## Stub-only behaviour (deviations, all deliberate)

| Where | What differs from a bench and why |
|---|---|
| `Document.__setattr__` | An unknown field raises `frappe.ValidationError`; Frappe keeps the attribute and drops it on save. Typos must fail tests. Private (`_x`) names, the standard fields and a controller's `_stub_extra_fields` are exempt. |
| Link validation | Checked only when the target table has rows, or always with `frappe.flags.stub_strict_links = True` (a target without meta then raises `DoesNotExistError`). Links to `DocType` are checked only in strict mode because the stub's DocType table is a partial view of a site. |
| `save_version` | Versions are written in tests (Frappe sets `ignore_version = frappe.in_test`), so audit-trail assertions work. `docstatus` changes are listed under `changed`. |
| `frappe.enqueue` | Runs the job inline (also with `enqueue_after_commit`) and records it in `frappe.enqueued`. |
| `get_pdf` | Returns the HTML encoded as bytes and records the call; wkhtmltopdf is not run. |
| `make_xlsx` | openpyxl instead of xlsxwriter; same data layout, bold header row. |
| Invoice totals | Single currency, `Actual` / `On Net Total` charges only, no rounding adjustment (`rounded_total = grand_total`), no discounts, no stock GL (`update_stock` raises). |
| `get_balance_on` | Descendants of a group account are found by walking `parent_account`; `lft`/`rgt` are not maintained. `cost_center` / `finance_book` filters raise. |
| Custom fields | `nyabo_mn.setup.custom_fields.get_custom_fields()` is merged into the metas at `reset()` (as on a migrated site); `create_custom_fields` then creates the Custom Field rows without duplicating fields. |
| Hooks | `frappe._stub.hooks.temporary_hooks(...)` layers extra hooks or drops an app's hooks for one block; a missing handler module raises `ImportError` naming the dotted path. |
| `sync_financial_report_templates` | Records the call and imports only `nyabo_mn/nyabo/financial_report_template/*` when the folder exists. |
| `frappe.desk.query_report.run` | Runs Nyabo Script Reports (`nyabo_mn.nyabo.report.<scrub>.<scrub>.execute`); ERPNext's reports raise `DoesNotExistError`. |
| `delete_doc` | Deletes attached Files, Comments and Versions and writes a Deleted Document (`delete_dynamic_links` in frappe/model/delete_doc.py). |
| `Company.on_update` | Raises `NotImplementedError` instead of creating the Standard chart unless `frappe.local.flags.ignore_chart_of_accounts` is set; `create_default_cost_center` runs like on a site. |
| `Accounts Settings.allow_stale` | Unset in the stub means 1 (the field default in ERPNext); set it to 0 to test stale-rate refusal. |
