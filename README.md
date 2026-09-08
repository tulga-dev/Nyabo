# Нябо (Nyabo)

AI bookkeeping for Mongolian SMEs. Runs inside ERPNext v16 on Frappe Cloud, talks to
owners and accountants in Telegram. This repository is the Frappe app `nyabo_mn`.

**Status: Phase 0** (localisation + provisioning). Phases 1–5 add the agent DocTypes,
the Telegram bot, the receipt flow, bank statements, month-end and evals.

## What is in the repo

```
nyabo_mn/
  hooks.py                 app registration, install/migrate hooks
  config.py                site-config keys + validation (bench execute nyabo_mn.config.check)
  log.py                   structured JSON logging (logs/nyabo.log)
  i18n/mn.py               every user-facing Mongolian string
  translations/mn.csv      Cyrillic names for our own DocTypes
  setup/
    data/mn_sme_coa.json   the draft chart of accounts (copy of mn_sme_coa_erpnext_draft.json)
    chart.py               loads/normalises/validates the chart (pure Python, unit-tested)
    chart_db.py            installs the chart, resolves V1 code -> ERPNext account
    taxes.py               VAT templates (НӨАТ 10%, Татан суутгах НӨАТ 10%, exempt, zero-rated)
    custom_fields.py       ebarimt / Nyabo fields on invoices, journal entries, suppliers, customers
    provision_company.py   creates a company end to end; verify() checks it
    install.py             after_install / after_migrate
tests/                     pytest, no Frappe site needed
.github/workflows/ci.yml   ruff + pytest on every push
```

## Run the tests on your PC

1. Open PowerShell in this folder.
2. Run:

```bash
python -m pip install pytest ruff
```

3. Run:

```bash
python -m pytest
```

You should see: `28 passed`.

## Deploy to Frappe Cloud

Custom apps need your own bench (Frappe Cloud calls it a *Bench* or *Bench Group*).
Your trial site `nyabo.s.frappe.cloud` currently sits on a shared bench, which cannot
take custom apps.

1. Push this repository to GitHub. It must be its own repository with `pyproject.toml`
   at the root (Frappe Cloud reads the app from the repo root). It lives at `https://github.com/tulga-dev/Nyabo` (branch `main`).
2. In Frappe Cloud open **Benches** in the left menu, press **Continue Onboarding** and
   finish it. You should see: a **New Bench** button. If it asks for a billing method,
   that is required for private benches. I am not sure of the exact plan name; pick the
   lowest site plan whose feature list mentions *custom apps* or *private bench*, and tell me what you saw.
3. **New Bench** → name `nyabo`, region **Singapore** (same as the site), version **Version 16**,
   apps **Frappe** and **ERPNext**. You should see: the bench page with an **Apps** tab.
4. **Apps → Add App → your GitHub account** → authorise the GitHub app for `tulga-dev` →
   choose the `Nyabo` repository, branch `main`. You should see: `nyabo_mn` listed with the other apps.
5. **Deploy** (button on the bench page; it may say *Update available*). You should see: a
   build log ending in *Success*, roughly 10–20 minutes.
6. Either move the site (**Site → Actions**, look for *Change bench*; I am not sure it is
   offered for trial sites) or create a new site on this bench (**Sites → New Site** → pick
   bench `nyabo` → install Frappe, ERPNext, nyabo_mn). If you create a new site, run the
   ERPNext setup wizard with country Mongolia, currency MNT, and any company name; the
   real company is created by the provisioning script below.
7. **Site → Site Config → Add key** for each secret when a phase needs it (see *Site config keys*).

## Provision a company

Everything below is idempotent: running it twice does no harm.

### From the browser (no SSH needed)

1. Log in to the site as Administrator (or any System Manager).
2. Press **F12**, open the **Console** tab.
3. Paste and press Enter (change the name, abbreviation and VAT flag):

```javascript
frappe.call("nyabo_mn.setup.provision_company.provision",
  {company_name: "Тест ХХК", abbr: "TST", vat_registered: 0}).then(r => console.log(r.message))
```

You should see: an object with `verify.ok: true`, `created.accounts: 58`, and any `warnings`.

### From a bench shell (SSH)

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.setup.provision_company.provision_company --kwargs '{"company_name": "Тест ХХК", "abbr": "TST", "vat_registered": 0}'
```

Check later:

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.setup.provision_company.verify --kwargs '{"company": "Тест ХХК"}'
```

### What provisioning sets

| Company field | Account |
|---|---|
| Cash / Bank | 1110 Касс / 1120 Банкны харилцах данс |
| Receivable / Payable | 1310 / 2110 |
| Income / Expense default | 4110 / 6910 |
| Round off / Write off / Exchange gain-loss | 6920 / 6940 / 6930 |
| Depreciation / Accumulated / CWIP | 6530 / 1519 / 1530 |
| Stock / Received-not-billed / Adjustment / Valuation | 1410 / 2120 / 5120 / 5130 |

Tax templates: **НӨАТ 10%** (sales → 2210), **Татан суутгах НӨАТ 10%** (purchase → 1810),
item tax templates **НӨАТ-аас чөлөөлөгдсөн** and **Тэг хувийн НӨАТ** (0%). For a company
that is not a VAT payer none of them is default, so VAT is only applied when chosen.

## Verify Phase 0 yourself

1. Open **Accounting → Chart of Accounts**, choose the new company. You should see: five
   Mongolian roots (Хөрөнгө, Өр төлбөр, Эзэмшигчийн өмч, Орлого, Зардал) with numbered leaves.
2. Open **Buying → Purchase Invoice → New**. Company = the new company, any supplier, item
   row: description "Тест", quantity 1, rate 100 000, expense account `6210 - Шатахуун - TST`.
3. In **Taxes and Charges** choose **Татан суутгах НӨАТ 10% - TST**. You should see: a tax
   row of 10 000 and grand total 110 000.
4. **Save**, then **Submit**.
5. Open **Accounting → General Ledger**, filter by this invoice. You should see:
   `6210` debit 100 000, `1810` debit 10 000, `2110` credit 110 000.
6. Scroll to the bottom of the invoice. You should see: a collapsed section
   **Нябо · И-баримт** with the ebarimt fields.

## Site config keys

| Key | Needed from | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Phase 1 | from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Phase 1 | random string; Telegram sends it back on every webhook call |
| `ADMIN_TELEGRAM_IDS` | Phase 1 | comma-separated numeric Telegram IDs of admins |
| `OPENAI_API_KEY` | Phase 2 | vision extraction and classification |
| `OPENAI_MODEL` | optional | default `gpt-5.6-terra` |
| `ANTHROPIC_API_KEY` | optional | enables the Anthropic adapter and eval sweeps |
| `EBARIMT_API_BASE` | Phase 2 | ebarimt lookup base URL |

Missing keys never block a deploy; the feature that needs them fails with a message
naming the key. `bench --site <site> execute nyabo_mn.config.check` prints the status.
Secrets are never committed. A GitHub Actions secret is not read by Frappe Cloud;
the key has to be in Site Config.

## Backups

Frappe Cloud takes daily backups (Site → Backups). Before a risky operation take a manual
one: **Site → Backups → Backup Now**, or from a bench shell:

```bash
bench --site nyabo.s.frappe.cloud backup --with-files
```

## Decisions and deviations (Phase 0)

- **The chart is not selectable in the Company form.** ERPNext v16 discovers charts only
  from files inside the erpnext package; there is no hook for other apps. Provisioning
  installs the chart through the same `create_charts(custom_chart=...)` call that ERPNext's
  Chart of Accounts Importer uses, after switching off ERPNext's own chart creation with
  the flag the importer uses. Companies created by hand in the UI get the Standard chart.
- **Range codes dropped on three groups.** The draft numbers `Эргэлтийн хөрөнгө` as
  `1100-1800`, `Богино хугацаат өр төлбөр` as `2100-2300` and `Зардал` as `5000-9000`; ERPNext would put that text in the account
  name, so those three groups carry no number. Every leaf keeps its V1 code.
- **Account categories added.** ERPNext v16 builds financial statements from Account
  Categories. The draft has none, so `chart.py` maps codes to ERPNext's categories.
  Trial Balance and General Ledger do not depend on this. Whether the Balance Sheet and
  P&L render correctly with them is verified in Phase 4.
- **Perpetual inventory off by default** (`enable_perpetual_inventory: 1` to switch on).
  The first company sells services; stock accounts exist but are unused.
- **Default expense account is 6910** (other operating expenses), not ERPNext's cost of
  goods sold, because Nyabo assigns the expense account explicitly on every entry.
- **Expense Claim fields** are only created when HRMS is installed; your site has no HRMS.
- **Non-VAT company:** purchase VAT stays in the expense, no template is default.
- The site also has `email_delivery_service` and `myinvois_erpgulf` (Malaysian e-invoicing)
  installed. They do not interfere, but the second one is unnecessary.
