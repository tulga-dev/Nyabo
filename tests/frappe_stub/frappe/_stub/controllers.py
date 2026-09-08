"""DocType -> controller class resolution.

Nyabo controllers are the real ones under ``nyabo_mn/nyabo/doctype`` (so a bug in a
``validate`` there fails a test). ERPNext / Frappe controllers are the stub's re-creations
of the version-16 behaviour the app relies on, kept at the module paths application
code imports them from. Anything else falls back to the plain ``Document``.
"""

from __future__ import annotations

import importlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from frappe.model.document import Document

STUB_CONTROLLERS: dict[str, str] = {
	"Account": "erpnext.accounts.doctype.account.account.Account",
	"Accounting Period": "erpnext.accounts.doctype.accounting_period.accounting_period.AccountingPeriod",
	"Bank Account": "erpnext.accounts.doctype.bank_account.bank_account.BankAccount",
	"Bank Transaction": "erpnext.accounts.doctype.bank_transaction.bank_transaction.BankTransaction",
	"Company": "erpnext.setup.doctype.company.company.Company",
	"Cost Center": "erpnext.accounts.doctype.cost_center.cost_center.CostCenter",
	"Currency Exchange": "erpnext.setup.doctype.currency_exchange.currency_exchange.CurrencyExchange",
	"Customer": "erpnext.selling.doctype.customer.customer.Customer",
	"GL Entry": "erpnext.accounts.doctype.gl_entry.gl_entry.GLEntry",
	"Item": "erpnext.stock.doctype.item.item.Item",
	"Item Tax Template": "erpnext.accounts.doctype.item_tax_template.item_tax_template.ItemTaxTemplate",
	"Journal Entry": "erpnext.accounts.doctype.journal_entry.journal_entry.JournalEntry",
	"Purchase Invoice": "erpnext.accounts.doctype.purchase_invoice.purchase_invoice.PurchaseInvoice",
	"Purchase Taxes and Charges Template": "erpnext.accounts.doctype.purchase_taxes_and_charges_template.purchase_taxes_and_charges_template.PurchaseTaxesandChargesTemplate",
	"Sales Invoice": "erpnext.accounts.doctype.sales_invoice.sales_invoice.SalesInvoice",
	"Sales Taxes and Charges Template": "erpnext.accounts.doctype.sales_taxes_and_charges_template.sales_taxes_and_charges_template.SalesTaxesandChargesTemplate",
	"Supplier": "erpnext.buying.doctype.supplier.supplier.Supplier",
	"Warehouse": "erpnext.stock.doctype.warehouse.warehouse.Warehouse",
	"Custom Field": "frappe.custom.doctype.custom_field.custom_field.CustomField",
	"File": "frappe.core.doctype.file.file.File",
	"Property Setter": "frappe.custom.doctype.property_setter.property_setter.PropertySetter",
	"User": "frappe.core.doctype.user.user.User",
	"Version": "frappe.core.doctype.version.version.Version",
}

_cache: dict[str, type] = {}


def scrub(name: str) -> str:
	return re.sub(r"[\s-]+", "_", name.strip()).lower()


def class_name(name: str) -> str:
	"""Same rule as scripts/gen_doctypes.py: 'Nyabo LLM Call' -> 'NyaboLlmCall'."""
	return "".join(part.capitalize() for part in re.split(r"[\s_-]+", name))


def _import_attr(path: str) -> type:
	module_name, attr = path.rsplit(".", 1)
	module = importlib.import_module(module_name)
	return getattr(module, attr)


def get_controller(doctype: str) -> type[Document]:
	from frappe.model.document import Document

	if doctype in _cache:
		return _cache[doctype]
	import frappe

	meta = frappe.get_meta(doctype)
	controller: type[Document] = Document
	if meta.app == "nyabo_mn":
		module_name = f"nyabo_mn.nyabo.doctype.{scrub(doctype)}.{scrub(doctype)}"
		try:
			module = importlib.import_module(module_name)
		except ModuleNotFoundError as exc:
			if exc.name and module_name.startswith(exc.name):
				module = None  # DocType JSON without a .py yet: plain Document
			else:
				raise
		if module is not None:
			wanted = class_name(doctype)
			found = getattr(module, wanted, None)
			if found is None:
				for value in vars(module).values():
					if (
						isinstance(value, type)
						and issubclass(value, Document)
						and value.__module__ == module_name
					):
						found = value
						break
			if found is None:
				raise ImportError(f"frappe stub: {module_name} defines no Document subclass named {wanted}")
			controller = found
	elif doctype in STUB_CONTROLLERS:
		controller = _import_attr(STUB_CONTROLLERS[doctype])
	_cache[doctype] = controller
	return controller


def clear_controller_cache() -> None:
	_cache.clear()
