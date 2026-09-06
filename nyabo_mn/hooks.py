from . import __version__ as app_version  # noqa: F401  (read by bench)

app_name = "nyabo_mn"
app_title = "Nyabo"
app_publisher = "Nyabo"
app_description = "Нябо — AI bookkeeping for Mongolian SMEs (ERPNext v16 + Telegram)"
app_email = "hello@nyabo.mn"
app_license = "MIT"

# ERPNext must be installed on the site before this app.
required_apps = ["erpnext"]

# Idempotent setup: custom fields on ERPNext doctypes and a config sanity check.
after_install = "nyabo_mn.setup.install.after_install"
after_migrate = "nyabo_mn.setup.install.after_migrate"

# Phase 1 adds: doc_events, scheduler_events, override_whitelisted_methods (Telegram webhook is a
# plain whitelisted method, so no override is needed), and fixtures for roles.
