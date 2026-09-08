# Нябо (Nyabo)

AI bookkeeping for Mongolian SMEs. It runs inside ERPNext v16 on Frappe Cloud and talks to
owners and accountants in Telegram. This repository is the Frappe app `nyabo_mn`.

An owner photographs a receipt and sends it to the bot. Nyabo reads it, checks the seller
against the ebarimt registry, applies the company's rules, and proposes an entry with a
one-line Mongolian explanation and the legal citation behind it. The accountant taps
**Батлах** and the document is created and submitted in ERPNext. Bank statements arrive as
Excel exports, get matched to entries, and every unmatched line comes back as a card. At
month end `/хаалт` shows what is still open, the trial balance and the VAT (or 1%) summary,
then locks the period.

**Nothing posts to the ledger without a human tap.** The model proposes, deterministic code
validates, the accountant disposes.

## Status

All modules are built and the suite is green (821 tests, no bench required).

Nyabo is deployed and running: bench `nyabo` on Frappe Cloud (Singapore) with Frappe 16.33,
ERPNext 16.34 and `nyabo_mn`, site `nyabo.s.frappe.cloud`, and the test company **Тест ХХК**
provisioned on the v0.3 chart (114 accounts, `verify()` clean). The seed is loaded: 59 tax
parameters, 44 posting patterns, 6 bank layouts.

What remains before real books: add the five Site Config keys, point the bot at the site,
verify the seed rules in the desk, and walk `docs/BETA_CHECKLIST.md`.

## What is in the repo

```
nyabo_mn/
  hooks.py                  app registration, doc_events, scheduler
  config.py                 site-config keys + validation
  log.py                    structured JSON logging (logs/nyabo.log), secrets redacted
  i18n/mn.py                every user-facing Mongolian string
  core/                     pure Python: money, dates, models, validation, rules engine,
                            statement parsing, matching, quarantine (no frappe import)
  rules/                    rules as data: parameters, regimes, patterns, guard, seed, aliases
  setup/                    charts (V1 + v0.3 + accountant CSV), taxes, banks, inventory intake,
                            custom fields, provisioning, install/migrate
  agent/                    LLM client (OpenAI + Anthropic + mock), schemas, prompts,
                            extraction, classification, questions, pipeline, posting, few-shot
  ebarimt/                  registry lookups, QR decode, mock and POS-SDK providers
  telegram/                 webhook, router, state, cards, keyboards, handlers
  parsers/ matching/        bank statement reading, layout learning, reconciliation
  compliance/               primary-document rule, no-edit-after-submit, retention,
                            reversals, period lock, policy document, readiness, FX rates
  reports/                  VAT and 1% summaries, month end, journals, exports
  evals/ simulator/         golden set, metrics, nightly job, two-regime simulator
  nyabo/                    Frappe module: 21 DocTypes, reports, print formats,
                            financial report templates, seed JSON
docs/                       ARCHITECTURE, DECISIONS, RUNBOOK, BETA_CHECKLIST,
                            mn-rules-reference, legal/ (verbatim quotes per instrument)
tests/                      821 tests; tests/frappe_stub is an in-memory Frappe
```

Read `docs/ARCHITECTURE.md` before changing anything: it is the build contract, and section 2
lists the ERPNext v16 facts that were verified against the source.

## Run the tests on your PC

1. Open PowerShell in this folder.
2. Run:

```bash
python -m pip install pytest ruff openpyxl jinja2 pydantic
```

3. Run:

```bash
python -m pytest -q
```

You should see: `821 passed`. No bench, no network, no API keys.

## Deploy to Frappe Cloud

Custom apps need your own bench. Yours is called `nyabo` (Version 16, Singapore) and already
has Frappe and ERPNext.

1. Frappe Cloud → **Benches** → `nyabo` → **Apps** → **Add App** → **Add from GitHub**.
   The dialog has two tabs, and `tulga-dev/Nyabo` is private, so choose one:
   - **Private Repository** → **Connect To GitHub**. This grants Frappe Cloud's GitHub app
     access to your repositories; only you can approve it. Pick the `tulga-dev` account and,
     when GitHub asks which repositories, select **Only select repositories → Nyabo**.
     You should see: the dialog listing your repositories.
   - or, if you would rather not grant that access, make the repository public
     (GitHub → Nyabo → Settings → General → Danger Zone → Change visibility) and use the
     **Public Repository** tab with `https://github.com/tulga-dev/Nyabo`, then **Fetch Branches**.
2. Choose `Nyabo`, branch `main`, press **Add App**. You should see: `nyabo_mn` in the Apps list.
3. Press **Deploy**. You should see: a build log ending in *Success* (10–20 minutes).
4. Create a site on this bench (**Sites → New Site**, pick bench `nyabo`, install Frappe,
   ERPNext and nyabo_mn) or move the existing site. Any site on a private bench needs the
   USD 25/month plan or higher. Run ERPNext's setup wizard with country Mongolia and currency
   MNT; the real company comes from the provisioning script below.
5. **Site → Site Config** → add the keys in *Site config keys*.
6. Point Telegram at the site:

```javascript
frappe.call("nyabo_mn.api.setup_webhook").then(r => console.log(r.message))
```

from the desk console (F12 → Console), or where a shell exists:

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.telegram.webhook.setup_webhook
```

`docs/RUNBOOK.md` has the day-to-day operations: linking people, deploys, logs, backups,
readiness and evals.

## Provision a company

Everything is idempotent: running it twice does no harm.

### From the browser (no SSH needed)

1. Log in to the site as Administrator.
2. Press **F12**, open the **Console** tab.
3. Paste and press Enter:

```javascript
frappe.call("nyabo_mn.setup.provision_company.provision",
  {company_name: "Тест ХХК", abbr: "TST", vat_registered: 0, chart_scheme: "v03"}).then(r => console.log(r.message))
```

You should see: an object with `verify.ok: true` and the account count.

### From a bench shell

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.setup.provision_company.provision_company --kwargs '{"company_name": "Тест ХХК", "abbr": "TST", "vat_registered": 0, "chart_scheme": "v03"}'
```

### Arguments

| Argument | Meaning |
|---|---|
| `chart_scheme` | `v03` (the Ministry of Finance model classes, 87 leaf accounts), `v1` (the original 40-account draft), or `accountant` (their own chart) |
| `chart_csv` | for `accountant`: rows or a CSV with `code,name,parent_code,root_type,account_type`; aliases to the v0.3 template are created automatically where names match, and unmatched codes are listed in the report |
| `bank_accounts` | `[{"bank": "Khan Bank", "currency": "MNT", "account_number": "5001234567"}, …]` creates one GL sub-account, one Bank and one Bank Account each |
| `vat_registered` | `1` writes a `vat_payer` regime row, `0` a `simplified_1pct` row, both effective from the fiscal-year start |
| `has_inventory` | enables the inventory intake flow and the stock defaults |
| `enable_perpetual_inventory` | ERPNext perpetual inventory (off by default) |

Check a company later:

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.setup.provision_company.verify --kwargs '{"company": "Тест ХХК"}'
```

The accountant can also do all of this from Telegram with `/эхлэх`: VAT payer yes or no,
which banks and currencies, inventory with an Excel or typed list, and the accountant of
record.

## Verify it yourself

1. Send `/start` to the bot. You should see: the welcome message and your Telegram ID.
2. In your admin chat run `/link нягтлан Тест ХХК`. You should see: a 6-digit code. Send that
   code from the accountant's Telegram. You should see: `✅ Холбогдлоо`.
3. Run `/эхлэх` and answer the questions. You should see: `✅ Тохиргоо дууслаа` and a
   Nyabo Company Settings record in the desk.
4. Photograph a receipt and send it. You should see: a card with seller, date, money line,
   proposed account and the reason, within about 15 seconds.
5. Tap **Батлах**. You should see: `✅ Бүртгэлээ: …` and, in ERPNext, a submitted document
   whose *Нябо · И-баримт* section links the source document and carries the explanation.
6. Send a bank statement as an Excel file. You should see: an import summary, and cards for
   the lines that did not match.
7. Run `/хаалт 2026-08` as the accountant. You should see: the checklist, the trial balance,
   the VAT or 1% summary as a PDF, and a **Хаах** button.

`docs/BETA_CHECKLIST.md` is the full list to tick before real client data.

## Bot commands

| Command | Who | What |
|---|---|---|
| `/start`, `/whoami` | anyone | welcome, your Telegram ID |
| `/меню`, `/тусламж` | linked | menu and help |
| `/эхлэх` | owner, accountant | company onboarding |
| `/компани` | linked | switch the active company |
| `/данс` | linked | bank reconciliation status |
| `/хаалт YYYY-MM` | accountant | month-end checklist, summaries, lock |
| `/чанар` | accountant | accuracy, auto-match rate, cost per document |
| `/бодлого` | accountant | the accounting policy document as a PDF |
| `/link`, `/status` | admin | issue a link code, system status |

Photos are receipts, Excel and CSV files are bank statements, and free text is a question
answered read-only from the books.

## Rules are data

No rate, threshold, account code or column index is hard-coded. They live in DocTypes seeded
from `nyabo_mn/nyabo/seed/`:

| Seed | Rows | Verified |
|---|---|---|
| Tax parameters (VAT, CIT, PIT, social insurance, filing deadlines, retention) | 59 | 46 |
| Posting patterns (the entries Order 116 prescribes) | 42 | 28 |
| Bank layouts (five banks + a generic keyword layout) | 6 | 0 |

`verified` means a human compared the value with the primary legal text and the row carries
the article and a verbatim quote (see `docs/legal/`). **An unverified rule cannot be used for
a real posting**; the card shows ⚠️ and the admin verifies it in the desk after reading the
citation. Every lookup passes the transaction date, so a 2026 receipt and a 2027 receipt get
different answers. Bank layouts ship empty on purpose: nobody has guessed a bank's column
order, so the accountant maps the columns once and an admin verifies that layout.

## Site config keys

| Key | Needed for | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram | from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Telegram | random string; Telegram returns it on every call |
| `ADMIN_TELEGRAM_IDS` | Telegram | comma-separated numeric admin IDs |
| `OPENAI_API_KEY` | the model | vision extraction and classification |
| `OPENAI_MODEL` | optional | default `gpt-5.6-terra` |
| `OPENAI_SWEEP_MODEL` | optional | second model for eval sweeps |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | optional | enables the Anthropic adapter |
| `EBARIMT_API_BASE` | ebarimt | `https://api.ebarimt.mn` (public registry lookups) |
| `EBARIMT_PROVIDER` | optional | `registry` (default), `mock`, `pos` |

Missing keys never block a deploy; the feature that needs them fails with a message naming
the key. Check with:

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.config.check
```

Without a bench shell, do the same from the desk: log in as a System Manager, press **F12**,
open the **Console** tab and paste

```javascript
frappe.call("nyabo_mn.api.config_check").then(r => console.log(r.message))
```

You should see: an object whose `missing_by_feature.telegram` and `.llm` are empty, with
every secret shown as `<set>`.

Secrets are never committed and never logged. A GitHub Actions secret is not visible to
Frappe Cloud; the key has to be in Site Config.

## What Nyabo does not do

- **It does not verify a purchase receipt against the tax authority.** No buyer-side ebarimt
  API exists in any published documentation. Nyabo checks the *seller* in the public registry
  (`getInfo?tin=`) and says `Баримт шалгагдаагүй` about the receipt itself.
- **It does not issue ebarimt receipts.** The POS API 3.0 needs a service installed on a
  machine inside Mongolia; the adapter exists behind an optional extra.
- **It does not compute payroll** or file anything with the tax office. It classifies salary
  payments seen on bank statements and produces the numbers the accountant files.
- **It is not the bookkeeper of record.** A professional or certified accountant signs
  (Law on Accounting art. 18.3); their name and MICPA permit are in Company Settings.

## Decisions and deviations

`docs/DECISIONS.md` records every judgement call with its reason. The ones worth knowing:

- The chart is installed by the provisioning script, not chosen in the Company form: ERPNext
  v16 only discovers charts inside its own package and offers no hook for other apps.
- Corrections never edit a posted document. A Journal Entry is reversed with ERPNext's own
  reversal, a Purchase Invoice with a Debit Note, both dated in the original period when it
  is still open, with the reason and the approver recorded (art. 15).
- Documents and images are never deleted: `retain_until` is the posting date plus ten years
  and the delete hooks refuse (art. 11.1).
- Statement matching needs a name or a reference on top of an exact amount and date; amount
  and date alone go to the accountant.
- Month end uses ERPNext's Accounting Period, not the Period Closing Voucher.
