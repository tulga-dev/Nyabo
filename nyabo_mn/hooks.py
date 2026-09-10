from . import __version__ as app_version  # noqa: F401  (read by bench)

app_name = "nyabo_mn"
app_title = "Nyabo"
app_publisher = "Nyabo"
app_description = "Нябо — AI bookkeeping for Mongolian SMEs (ERPNext v16 + Telegram)"
app_email = "hello@nyabo.mn"
app_license = "MIT"

# ERPNext must be installed on the site before this app.
required_apps = ["erpnext"]

# Idempotent setup: custom fields, roles, seed data, financial report templates.
after_install = "nyabo_mn.setup.install.after_install"
after_migrate = "nyabo_mn.setup.install.after_migrate"

# Company scoping (SEC-06): a linked accountant sees only their own clients' rows, in the
# desk, in reports and through the REST API. nyabo_mn/permissions.py explains both layers.
_SCOPED_DOCTYPES = (
	"Nyabo Document",
	"Nyabo Proposal",
	"Nyabo Correction",
	"Nyabo Event",
	"Nyabo Rule",
	"Nyabo Account Alias",
	"Nyabo Rule Acceptance",
	"Nyabo Inventory Intake",
	"Nyabo Eval Case",
	"Nyabo LLM Call",
	"Nyabo Company Settings",
)
permission_query_conditions = {dt: "nyabo_mn.permissions.query_conditions" for dt in _SCOPED_DOCTYPES}
has_permission = {dt: "nyabo_mn.permissions.has_permission" for dt in _SCOPED_DOCTYPES}

fixtures = [
	{"dt": "Role", "filters": [["name", "in", ["Nyabo Admin", "Nyabo Accountant", "Nyabo Owner"]]]},
]

# Compliance constraints (docs/ARCHITECTURE.md §1 and §5). Handler signature: (doc, method=None).
doc_events = {
	"Purchase Invoice": {
		"validate": "nyabo_mn.compliance.hooks.validate_accounting_document",
		"before_submit": "nyabo_mn.compliance.hooks.require_primary_document",
		"before_update_after_submit": "nyabo_mn.compliance.hooks.guard_no_edit_after_submit",
		"on_trash": "nyabo_mn.compliance.hooks.block_delete_of_posted",
	},
	"Journal Entry": {
		"validate": "nyabo_mn.compliance.hooks.validate_accounting_document",
		"before_submit": "nyabo_mn.compliance.hooks.require_primary_document",
		"before_update_after_submit": "nyabo_mn.compliance.hooks.guard_no_edit_after_submit",
		"on_trash": "nyabo_mn.compliance.hooks.block_delete_of_posted",
	},
	"Sales Invoice": {
		"validate": "nyabo_mn.compliance.hooks.validate_accounting_document",
		"before_update_after_submit": "nyabo_mn.compliance.hooks.guard_no_edit_after_submit",
		"on_trash": "nyabo_mn.compliance.hooks.block_delete_of_posted",
	},
	# A settlement (matching.match.settle) posts to the ledger like any other Nyabo document,
	# so it carries the same four guards and the same nyabo_* trail (COMP-10 / BANK-09).
	"Payment Entry": {
		"validate": "nyabo_mn.compliance.hooks.validate_accounting_document",
		"before_submit": "nyabo_mn.compliance.hooks.require_primary_document",
		"before_update_after_submit": "nyabo_mn.compliance.hooks.guard_no_edit_after_submit",
		"on_trash": "nyabo_mn.compliance.hooks.block_delete_of_posted",
	},
	"File": {
		"on_trash": "nyabo_mn.compliance.hooks.block_retained_file_delete",
	},
	"Nyabo Document": {
		"before_insert": "nyabo_mn.compliance.hooks.stamp_retention",
		"on_trash": "nyabo_mn.compliance.hooks.block_retained_document_delete",
	},
	"Nyabo Event": {
		"before_save": "nyabo_mn.compliance.events.enforce_append_only",
		"on_trash": "nyabo_mn.compliance.events.block_delete",
	},
	"Accounting Period": {
		"on_update": "nyabo_mn.compliance.period.log_period_change",
		"on_trash": "nyabo_mn.compliance.period.log_period_delete",
	},
}

# A Nyabo Event points at its document with a Dynamic Link and can never be deleted, so
# without this every document an event has ever named would be undeletable for ever - drafts,
# rejected proposals, test data (F11). This is the hook Frappe reads when *deleting*
# (frappe/model/delete_doc.py, get_linked_docs: `if method == "Delete":
# ignored_doctypes.update(frappe.get_hooks("ignore_links_on_delete"))`; the document-level
# `ignore_linked_doctypes` attribute is consulted only for Cancel). It removes the referential
# veto, nothing else: events stay append-only and undeletable, still naming the document, and
# what may be deleted at all is decided by the on_trash guards above.
ignore_links_on_delete = ["Nyabo Event"]

scheduler_events = {
	"daily": [
		"nyabo_mn.evals.corrections_job.run_nightly",
		"nyabo_mn.agent.few_shot.refresh_all",
		"nyabo_mn.telegram.state.expire_link_codes",
	],
}

# Telegram webhook: nyabo_mn.telegram.webhook.webhook is a guest-allowed whitelisted method
# reachable at /api/method/nyabo_mn.telegram.webhook.webhook; no override needed.

# Month-end period locks add nothing here: ERPNext's own period_closing_doctypes hook already
# covers Purchase Invoice, Journal Entry, Sales Invoice, Payment Entry and the rest.
