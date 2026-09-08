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
