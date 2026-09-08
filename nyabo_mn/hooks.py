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
