# Nyabo architecture and module contracts

This is the build contract. Every module is written against it; if an implementer needs
to deviate, the deviation is recorded in `docs/DECISIONS.md` with the reason.

Read first: the founder's MVP brief (Telegram + ERPNext v16 + LLM, model proposes /
code and accountant dispose, nothing posts without a human tap, corrections by reversal,
Mongolian Cyrillic UI, conservative tax defaults) and `docs/mn-rules-reference.md`
(the legal source of truth). Verified ERPNext/Frappe facts are in section 2; do not use
an API that is not listed there or in the Frappe/ERPNext version-16 source you have read.

## 1. Principles (non-negotiable)

1. **Rules are data with effective dates.** Tax parameters, tax regimes, posting
   patterns, bank layouts and account aliases are DocTypes seeded from JSON. Code never
   hard-codes a rate, a threshold, an account name or a column index. Every lookup passes
   the transaction date, never "today".
2. **Unverified rules are refused for real postings.** A Tax Parameter, Posting Pattern
   or Bank Layout with `verified = 0` may be used by tests and by the simulator, but
   `nyabo_mn.rules.guard.require_verified()` raises `UnverifiedRuleError` with a Mongolian
   message before anything reaches `insert()` on an accounting document. The admin can
   set `verified = 1` in the desk after checking the primary text (the DocType stores the
   citation).
3. **The model proposes, deterministic code validates, the accountant disposes.** The LLM
   only ever returns schema-validated fields (extraction, classification) or answers
   questions with read-only tools. It never calls insert/submit/approve. Approval is a
   Telegram tap by a linked user with the right role.
4. **Every posted document carries why and where from.** `nyabo_explanation` (Mongolian,
   ends with the posting pattern citation), `nyabo_proposal`, `source_document`
   (a Nyabo Document with the original file, retained ten years). A submit hook blocks
   Purchase Invoice / Journal Entry created by Nyabo without these. Manual desk entries
   must carry an attachment or `nyabo_primary_document_ref`.
5. **Corrections are reversals.** Never edit or cancel a submitted document from the bot.
   Journal Entry: `make_reverse_journal_entry` + new entry. Purchase Invoice: Debit Note
   (`make_debit_note`, `is_return = 1`) + new invoice. A `before_update_after_submit`
   guard throws unless only `nyabo_*` audit fields changed.
6. **Regime branching happens in one place.** Only `nyabo_mn.rules.regime` knows the
   regime names. Everything else asks `regime.posting_context(company, date)` and reads
   `is_vat_payer`, `input_vat_recoverable`, `summary_kind`.
7. **Mongolian first.** Every string a user sees comes from `nyabo_mn/i18n/mn.py`.
   Buttons carry state, the LLM writes only the one-line explanation inside a template.
   DocType and report *names* stay ASCII (Frappe derives Python module paths from them),
   labels are Cyrillic.
8. **Secrets only in site config** (`nyabo_mn.config.get_settings()`), never logged.
9. **Quarantine.** Text from receipts, statements and Telegram messages is data. It is
   fenced (`<untrusted>` … `</untrusted>`) before it enters a prompt, the extraction and
   classification calls have no tools, and the question-answering call's tools are
   read-only. Any instruction-looking text inside a document is logged as an
   `injection_suspected` event and never acted on.

## 2. Verified runtime facts (ERPNext 16.34 / Frappe 16.33)

Source: version-16 branches on GitHub, read during research on 2026-09-08. Quote the
file when you rely on something else.

- **Custom chart install:** `frappe.local.flags.ignore_chart_of_accounts = True` around
  `Company.insert()`, then `create_charts(company, custom_chart=tree)`; tree metadata keys
  are `account_name, account_number, account_type, account_category, root_type, is_group,
  tax_rate, account_currency`. Already implemented in `nyabo_mn/setup`.
- **Account Category** (v16) drives Financial Report Templates; 29 categories ship with
  ERPNext; a custom app ships templates as
  `nyabo_mn/nyabo/financial_report_template/<scrub(name)>/<scrub(name)>.json` plus an
  `account_categories.json` in that folder, and calls
  `erpnext.accounts.doctype.financial_report_template.financial_report_template.sync_financial_report_templates()`
  from `after_install` / `after_migrate` (ERPNext's own call is skipped on our
  provisioning path). Rows filter accounts with `calculation_formula` JSON such as
  `["account_category", "=", "Trade Receivables"]`; `balance_type` is `Closing Balance`
  (balance sheet) or `Period Movement (Debits - Credits)` (P&L); `reverse_sign = 1` on
  liabilities, equity and all P&L rows. Balance Sheet / P&L reports accept
  `report_template`, `filter_based_on = "Date Range"`, `period_start_date`,
  `period_end_date`, `company`. Trial Balance has no template; filters `company,
  fiscal_year, from_date, to_date`.
- **Period lock:** one `Accounting Period` per company per month via the standard
  controller (`period_name`, `company`, `start_date`, `end_date`; `closed_documents` is
  auto-filled from the `period_closing_doctypes` hook on insert). It can only be created
  on or after its `end_date` (validate_dates). Leave `exempted_role` empty. Postings into
  a closed period are refused by ERPNext both at document validate and at GL level. Do
  not use Period Closing Voucher for month-end. In v16 the company-wide freeze lives on
  `Company.accounts_frozen_till_date` / `role_allowed_for_frozen_entries`. Reopening
  (disable/delete) leaves only a Version / Deleted Document trace, so Nyabo writes its
  own `Nyabo Event`.
- **Reversal:** `erpnext.accounts.doctype.journal_entry.journal_entry.make_reverse_journal_entry(source_name)`
  returns an unsaved JE with `reversal_of` set and debit/credit swapped; `posting_date`,
  `user_remark` are `no_copy`, set them. Only one submitted reversal per source; a
  reversal cannot be reversed. Purchase Invoice: `make_debit_note(source_name)` →
  `is_return = 1`, `return_against`; the original stays visible (status `Debit Note
  Issued`). Cancelling hides the invoice from the ledger by default; do not cancel.
- **Hooks:** `doc_events` per doctype: `validate, before_insert, after_insert,
  before_save, before_submit, on_submit, before_cancel, on_cancel, on_trash,
  after_delete, on_update_after_submit, before_update_after_submit`. Handler signature
  `handler(doc, method=None)`. `frappe.throw` accepts Cyrillic.
- **Change history:** Purchase Invoice, Journal Entry, Accounting Period have
  `track_changes = 1`; read with `frappe.get_all("Version", filters={"ref_doctype": …,
  "docname": …})`. `doc.add_comment("Comment", text)` adds a timeline note.
- **Files:** `frappe.get_doc({"doctype": "File", "file_name": …, "content": bytes,
  "is_private": 1, "attached_to_doctype": …, "attached_to_name": …}).insert()` writes
  the file and returns `file_url`. Deleting a parent deletes its Files; `on_trash`
  doc_events on `File` and on the parent run first and can throw. There is no
  `before_delete` event. `frappe.utils.add_years(date, n)`.
- **FX:** `Currency Exchange` records `{date, from_currency, to_currency, exchange_rate,
  for_buying = 1, for_selling = 1}`; `erpnext.setup.utils.get_exchange_rate(from, to,
  transaction_date)` reads them first; disable the external provider with
  `frappe.db.set_single_value("Currency Exchange Settings", "disabled", 1)`. ERPNext books
  realized FX differences to `Company.exchange_gain_loss_account` via a system Journal
  Entry; there is one account, not a gain/loss pair.
- **Reports and PDF:** standard Script Report at
  `nyabo_mn/nyabo/report/<scrub(name)>/<scrub(name)>.{json,py}` with ASCII `report_name`;
  `execute(filters) -> (columns, data)`; run server-side with
  `frappe.desk.query_report.run(report_name, filters=…, ignore_prepared_report=True)`
  after `frappe.set_user(user)`. `frappe.utils.pdf.get_pdf(html, options=None)` returns
  bytes (wkhtmltopdf). `frappe.utils.xlsxutils.make_xlsx(data, sheet_name)` returns a
  `BytesIO`. `frappe.render_template(html_or_path, context)`.
- **Bank reconciliation:** ERPNext `Bank Transaction` is the statement line
  (`date, deposit, withdrawal, description, reference_number, bank_account, company,
  currency, status Pending/Settled/Unreconciled/Reconciled, unallocated_amount,
  payment_entries` child rows `{payment_document, payment_entry, allocated_amount}`);
  a `Bank Account` links `bank`, `account` (GL account) and `company`. Field names are
  re-verified by the stub author (see 8.2) before use.
- **Not available:** a buyer-side ebarimt receipt verification endpoint. Only the public
  registry exists: `GET https://api.ebarimt.mn/api/info/check/getInfo?tin=<TIN>` →
  `{status, msg, data: {name, vatPayer, found, vatpayerRegisteredDate, …}}` and
  `GET …/getTinInfo?regNo=<regNo>` → `{status, msg, data: "<TIN>"}`. The receipt QR
  encodes an opaque numeric `qrData` string. `ebarimt-pos-sdk` 0.4.1 (PyPI, MIT,
  httpx + pydantic v2 + authlib) covers the seller-side POS API 3.0 only, which needs a
  locally installed PosAPI service in Mongolia; it cannot run from Frappe Cloud.

## 3. Package map and ownership

```
nyabo_mn/
  core/            pure Python domain (no frappe import anywhere in this package)
    money.py       Money = Decimal quantised to 0.01; parse_mnt("85 000₮") helpers
    dates.py       Mongolian weekday names, period helpers (month bounds, quarter)
    models.py      dataclasses: Receipt, ReceiptLine, FieldConfidence, SellerInfo,
                   ReceiptVerification, Classification, ProposedLine, ProposedEntry,
                   BankLine, MatchCandidate, MatchResult, RegimeContext, Citation
    validate.py    validate_entry(entry) -> list[str]  (balanced, leaves only, VAT math)
    rules_engine.py resolve_parameter(rows, key, on_date), regime_on(history, on_date),
                   instantiate(pattern, amounts, resolver) -> ProposedEntry
    matching.py    score(bank_line, candidate) -> float; pick(bank_line, candidates)
    statements.py  parse_rows(rows, layout) -> list[BankLine]; detect_layout(rows, layouts)
    quarantine.py  fence(text) -> str; looks_like_injection(text) -> bool
  i18n/mn.py       every user-facing string; keys are UPPER_SNAKE; format() placeholders
  nyabo/           Frappe module "Nyabo": doctype/, report/, print_format/,
                   financial_report_template/, workspace/
  setup/           chart (v0.1 + v0.3), aliases, csv import, taxes, custom fields,
                   provision_company, bank sub-accounts, inventory intake
  rules/           Frappe side of rules: params.py, regime.py, patterns.py, guard.py, seed.py
  compliance/      hooks.py (document required, no-edit guard, retention, file guard),
                   reversal.py, period.py, policy_doc.py, readiness.py, events.py
  telegram/        api.py, webhook.py, router.py, state.py, cards.py, keyboards.py,
                   files.py, handlers/{start,link,menu,onboarding,receipt,statement,
                   approve,correct,close,accounts,quality,policy,question,admin}.py
  agent/           llm_client.py (base), openai_client.py, anthropic_client.py,
                   mock_client.py, schemas.py, prompts/*.md, extract.py, classify.py,
                   questions.py, few_shot.py, pipeline.py, cost.py
  ebarimt/         provider.py (Protocol), registry.py, mock.py, pos_sdk.py, qr.py
  parsers/         excel.py (openpyxl/csv -> rows), layouts.py (seed data), detect.py
  matching/        bank_import.py (rows -> Bank Transaction), match.py (ERPNext side),
                   cards.py, rules.py (fee lines, transfers)
  reports/         vat_summary.py, simplified_summary.py, month_end.py, export.py
  evals/           run.py, metrics.py, golden/*.json, corrections_job.py
  simulator/       run.py (pipeline with mock LLM + mock ebarimt, no network)
  config/faq.mn.md
tests/             pytest; tests/frappe_stub/ makes `import frappe` work without a bench
scripts/           gen_doctypes.py (spec -> DocType JSON), seed_check.py
docs/              this file, DECISIONS.md, RUNBOOK.md, BETA_CHECKLIST.md
```

Ownership for the parallel build (one agent each): `core+rules`, `telegram`, `agent`,
`ebarimt+parsers+matching`, `compliance+reports`, `setup(v0.3, aliases, csv, banks,
inventory)`, `evals+simulator`, `frappe_stub`. Shared files (`hooks.py`, `i18n/mn.py`,
`pyproject.toml`, `custom_fields.py`, `patches.txt`, seed JSON under `nyabo/seed/`) are
edited only by the integrator; agents return "integration requests" in their reports.

## 4. DocTypes (module Nyabo)

Generated from `scripts/doctype_specs.py` by `scripts/gen_doctypes.py`; the JSON files
under `nyabo_mn/nyabo/doctype/` are committed. Roles (fixtures): `Nyabo Admin`,
`Nyabo Accountant`, `Nyabo Owner`. All Nyabo DocTypes: `track_changes = 1`.

| DocType | Naming | Purpose and key fields |
|---|---|---|
| Nyabo Company Settings | `field:company` | per Company: `owner_telegram_id`, `accountant_telegram_id`, `accountant_user` (Link User), `auto_approve_policy` (none/owner_simple), `auto_approve_max_amount`, `auto_approve_accounts` (Small Text, codes), `default_expense_code` (Data, default 6910 / 7010), `has_inventory`, `inventory_method` (FIFO/Weighted Average), `depreciation_method`, `fx_policy` (Data, default "Монголбанкны албан ханш"), `accountant_of_record_name`, `accountant_micpa_permit`, `chart_scheme` (v1/v03/accountant), `few_shot_refreshed_at`, tables `regimes` (Nyabo Tax Regime Period), `bank_accounts` (Nyabo Bank Account Row), `onboarding_state` (Data), `onboarding_completed` |
| Nyabo Tax Regime Period | child | `regime` (vat_payer / simplified_1pct), `effective_from`, `effective_to`, `note` |
| Nyabo Bank Account Row | child | `bank` (Khan Bank / TDB / Golomt Bank / Trans Bank / XacBank), `currency`, `account_number`, `gl_account` (Link Account), `erpnext_bank_account` (Link Bank Account) |
| Nyabo User Link | `field:telegram_id` | `telegram_id` (Data, unique), `telegram_username`, `first_name`, `user` (Link User), `role` (Owner/Accountant/Admin), `status` (active/blocked), `linked_at`, table `companies` (Nyabo User Company: `company`, `role`) — the row role wins over the link role for that company (TG-04) |
| Nyabo Link Code | `field:code` | `code` (6 digits), `role`, `company`, `issued_by`, `expires_at`, `used_by_telegram_id`, `used_at`, `status` (open/used/expired) |
| Nyabo Chat State | `field:chat_id` | `chat_id`, `telegram_id`, `state` (Data), `payload` (JSON), `updated_at`, `link_attempts`, `link_blocked_until` — the conversation state machine storage and the link-code attempt cap (TG-05) |
| Nyabo Document | `NYD-.#####` | `file` (Attach), `file_hash` (sha256, indexed), `doc_type` (receipt/sales_ebarimt/bank_statement/inventory/other), `company`, `sender_telegram_id`, `sender_user`, `telegram_file_id`, `telegram_chat_id`, `telegram_message_id`, `status` (received/extracted/proposed/approved/rejected/posted/failed), `retain_until` (Date), `posted_doctype`, `posted_name`, `error` (Small Text), `mime_type`, `size_bytes` |
| Nyabo Proposal | `NYP-.#####` | `document` (Link), `company`, `kind` (receipt/bank_line/inventory), `extracted_json` (JSON), `verification_json` (JSON), `entry_json` (JSON: ProposedEntry), `confidence_json` (JSON), `warnings_json` (JSON), `supplier` (Link Supplier), `supplier_is_new`, `posting_date`, `total` (Currency), `vat_amount` (Currency), `vat_treatment` (withheld/in_expense/exempt/zero/none), `account` (Link Account), `account_code` (Data), `posting_pattern` (Link Nyabo Posting Pattern), `rule_applied` (Link Nyabo Rule), `explanation` (Small Text ≤ 200), `citation` (Data), `prompt_version`, `model`, `tokens_in`, `tokens_out`, `latency_ms`, `needs_accountant` (Check), `status` (proposed/approved/rejected/posted/failed), `approved_by` (Link User), `approved_telegram_id`, `rejection_reason`, `posted_doctype`, `posted_name`, `card_chat_id`, `card_message_id`, `bank_transaction` (Link Bank Transaction) |
| Nyabo Correction | `NYC-.#####` | `proposal` (Link), `company`, `field` (account_code/vat_treatment/supplier/total/posting_date/rejected/reversed), `proposed_value`, `corrected_value`, `corrected_by` (Link User), `corrected_telegram_id`, `reason` (Data), `reason_text` (Small Text), `source` (edit/reversal/rejection), `posted_doctype`, `posted_name`, `reversal_name` |
| Nyabo Rule | `NYR-.#####` | `company`, `match_type` (supplier_register_no/supplier_name_pattern/description_pattern/amount_band), `match_value` (Data), `amount_min`, `amount_max`, `target_account_code`, `vat_treatment`, `posting_pattern`, `source` (accountant/learned/seed), `status` (active/pending_confirmation/disabled), `hit_count`, `last_hit`, `created_from_corrections` (Small Text) |
| Nyabo LLM Call | `NYL-.######` | `purpose` (extract/classify/question/eval), `provider`, `model`, `prompt_version`, `tokens_in`, `tokens_out`, `latency_ms`, `ok`, `error_class`, `cost_usd`, `company`, `proposal` (Link) — never content |
| Nyabo Eval Case | `NYE-.#####` | `kind` (extraction/classification/vat/matching/rules/injection/correction/period_lock/fx/document_required), `company`, `input_document` (Link Nyabo Document), `input_json` (JSON), `expected_json` (JSON), `source` (golden/correction/synthetic), `regime`, `on_date`, `notes` |
| Nyabo Tax Parameter | `format:{key}:{effective_from}` | `key`, `value_json` (JSON), `unit` (fraction/MNT/years/schedule/rule), `effective_from`, `effective_to`, `status` (active/pending), `source_text`, `source_url`, `article`, `verified` (Check), `note` |
| Nyabo Posting Pattern | `field:pattern_id` | `pattern_id`, `name_mn`, `document_types` (Small Text, comma list), `applies_to_vat` (any/vat_payer/non_vat), `applies_to_cit` (any/regular/simplified_1pct), `conditions`, table `lines` (Nyabo Posting Pattern Line: `side` debit/credit, `account_class` (Data, "70"), `class_name_mn`, `sub_account_mn`, `amount_kind` (net/vat/gross/…), `alternatives_json`, `optional`), `primary_document_mn`, `citation_instrument`, `citation_section`, `citation_quote`, `verified`, `notes` |
| Nyabo Account Alias | `format:{company}:{scheme}:{alias_code}` | `company`, `scheme` (v1/accountant/mof), `alias_code`, `target_code`, `target_account` (Link Account), `note` |
| Nyabo Bank Layout | `field:layout_id` | `layout_id`, `bank`, `header_signature_json` (JSON list of header cell texts), `column_map_json` (JSON: date/description/debit/credit/amount/balance/reference/currency → column index or header text), `date_formats` (Small Text), `amount_style` (separate_debit_credit/signed_amount), `header_row_hint`, `verified`, `sample_file` (Attach, private), `notes` |
| Nyabo Event | `NYEV-.######` | append-only audit: `event_type`, `company`, `actor_user`, `actor_telegram_id`, `ref_doctype`, `ref_name`, `reason`, `payload_json`; `on_trash` throws |
| Nyabo Inventory Intake | `NYI-.#####` | `company`, `source` (excel/text), `file` (Attach), `posting_date`, `status` (draft/confirmed/posted), table `items` (Nyabo Inventory Intake Item: `item_name`, `qty`, `uom`, `rate`, `amount`, `item_code` (Link Item), `warehouse`), `created_docs_json`, `confirmed_by` |
| Nyabo Reconciliation Note | not needed; use Bank Transaction fields | |

Custom fields added to ERPNext doctypes (integrator): existing ebarimt/nyabo set on
Purchase Invoice, Sales Invoice, Journal Entry, plus `nyabo_correction_reason`,
`nyabo_corrects` (Link to same doctype), `nyabo_approved_by` (Link User),
`nyabo_primary_document_ref` (Data) on Purchase Invoice and Journal Entry;
`nyabo_retain_until` (Date) on Purchase Invoice, Journal Entry, Sales Invoice;
`register_no`, `tin`, `ebarimt_vat_payer` (Check), `ebarimt_checked_at` on Supplier.

## 5. Flows and state machines

### 5.1 Telegram update routing

`webhook()` (guest, verifies `X-Telegram-Bot-Api-Secret-Token` against
`TELEGRAM_WEBHOOK_SECRET`, rejects otherwise with 403, always returns 200 after that so
Telegram does not retry) stores nothing itself: it enqueues
`nyabo_mn.telegram.router.handle_update(update)` on the `short` queue and returns.
Dedup on `update_id` (Nyabo Chat State keeps `last_update_id`).

`handle_update`: resolve the sender (`Nyabo User Link` by `telegram_id`). Unlinked users
get `MSG_NOT_LINKED` unless the message is a 6-digit code (link flow) or `/start`.
Then dispatch in this order: callback query → command → conversation state (Nyabo Chat
State) → content type (photo/document/text). Commands: `/start`, `/меню`, `/тусламж`,
`/хаалт`, `/данс`, `/чанар`, `/бодлого`, `/link` (admin), `/компани` (switch active
company when a user has several), `/эхлэх` (onboarding). Every handler returns quickly;
LLM work is enqueued (`long` queue) and replies later by editing or sending a card.

Callback data (≤ 64 bytes): `p:<NYP-name>:ap|ch|rj`, `p:<name>:acc:<code>`,
`p:<name>:rr:<personal|dup|company|other>`, `b:<bank txn name>:find|exp|later`,
`b:<name>:acc:<code>`, `c:<period>:confirm|cancel`, `x:<posted doctype short>:<name>:rev`
(reversal), `x:<name>:reason:<code>`, `o:<step>:<value>` (onboarding), `i:<NYI>:confirm`.

### 5.2 Onboarding (`/эхлэх`, also triggered on first accountant link for a company without settings)

Steps, each a card with buttons, stored in Nyabo Chat State:
1. Company (pick from the user's companies or admin-provided).
2. VAT: `НӨАТ төлөгч үү?` → [Тийм] [Үгүй] → creates the `regimes` row (`vat_payer` or
   `simplified_1pct`) effective from the fiscal-year start; a second question asks whether
   the company expects to stay under 400M₮ in 2027 → if VAT payer and yes, a note is
   stored (no automatic regime change; the accountant decides in December).
3. Banks: multi-select toggle buttons Khan Bank / TDB / Golomt Bank / Trans Bank /
   XacBank, then currency per bank (MNT / USD / other, multi-select), then optional
   account number → `bank_accounts` rows; provisioning creates one GL sub-account per
   row under class 11 (v0.3) or 1120 (v1) and an ERPNext Bank Account.
4. Inventory: `Бараа материалын үлдэгдэл бий юу?` → [Тийм] [Үгүй]. Yes →
   "Excel файл (нэр, тоо, нэгж үнэ) илгээх эсвэл мөр бүрт `нэр, тоо, үнэ` бичнэ үү" →
   Nyabo Inventory Intake (rows parsed from xlsx/csv or text), confirmation card with
   the total, [Батлах] → Items created, opening Stock Reconciliation (perpetual on) or
   opening Journal Entry Дт 14/15 — Кт Түр нээлтийн данс (perpetual off).
5. Accountant of record: name, MICPA permit (optional), confirm.
6. Summary card and `onboarding_completed = 1`.

### 5.3 Receipt

Photo → `Nyabo Document` (sha256 dedup per company → `MSG_DUPLICATE_DOCUMENT`) → enqueue
`agent.pipeline.process_receipt(doc)`:
1. QR decode (`ebarimt.qr.decode`, returns opaque `qrData` or None).
2. Vision extraction (`agent.extract.receipt`) → `Receipt` with per-field confidence.
3. Seller check: `ebarimt.registry.lookup(tin or register_no)` → `SellerInfo(vat_payer)`;
   Supplier matched by `tin`/`register_no`/name, else created with
   `nyabo_pending_confirmation = 1` (custom field) and the card marks ⚠️ new supplier.
4. Regime context → rules (`Nyabo Rule` by supplier register_no, name pattern,
   description pattern, amount band, in that order) → else classification call with the
   chart's leaf accounts and the last 20 approved entries as examples.
5. Posting pattern selection: purchase expense / inventory / fixed asset variant by VAT
   status; `rules_engine.instantiate` builds the `ProposedEntry`; `core.validate` checks;
   `rules.guard.require_verified` decides `needs_accountant` and blocks approval when
   the pattern is unverified (card shows ⚠️ `Дүрэм баталгаажаагүй`).
6. Card. Approve → `agent.pipeline.post_proposal`: Purchase Invoice when the seller is a
   VAT payer and the company recovers input VAT (`vat_treatment = withheld`, `is_paid`
   from the cash account when the receipt was paid in cash), otherwise
   Journal Entry (`Дт expense (gross) / Кт 2110 or cash`), both with custom fields,
   `submit()`, Nyabo Document status `posted`, reply `MSG_POSTED`.
7. Confidence < 0.7 on `total`, `date` or `vat_amount`, a QR/vision disagreement, a new
   supplier, or an unverified rule → `needs_accountant = 1`; an Owner tap on
   [Батлах] gets `MSG_ACCOUNTANT_ONLY`.

### 5.4 Bank statement

Document (xlsx/csv) → `Nyabo Document(bank_statement)` → `parsers.excel.read_rows` →
`core.statements.detect_layout` against `Nyabo Bank Layout` rows. Unknown → the bot
shows the first three rows and asks the accountant to map columns (buttons per column
role); the answer is saved as a new Bank Layout with `verified = 0` and a card asks the
admin to verify. Known → `matching.bank_import.create_bank_transactions` (idempotent on
`bank_account + date + amount + reference + row hash`) → `matching.match.run`:
exact amount + date within 3 days + name similarity ≥ 0.8 → reconcile via ERPNext
(`Bank Transaction.add_payment_entries` or the reconciliation tool API the stub author
verifies); fee lines → rule `bank_fee` auto-proposal (still approved by a tap unless
`auto_approve_policy` allows); transfers between own accounts matched pairwise. Unmatched
lines → cards with [Баримт хайх] [Зардал бүртгэх] [Дараа]. `/данс` prints per bank
account: statement balance vs ledger balance, unmatched count.

A cash receipt credits cash at posting time through ERPNext's `is_paid` invoice; a card /
QPay / transfer receipt keeps the payable open and is settled by a Payment Entry
(`matching.match.settle`) created on the accountant's tap when the statement line arrives.
A line whose only candidate is such an unpaid invoice therefore stays unmatched and its
card carries [Төлбөр бүртгэх]: `Bank Transaction.add_payment_entries` /
`allocate_payment_entries` only record a link and a clearance date, so allocating an unpaid
invoice would leave the payable open and the bank overstated (ERPNext's own
`get_pi_matching_query` offers Purchase Invoices only with `is_paid = 1`). `run` never
settles — a Payment Entry posts, and §1.3 keeps posting behind a human tap. The tap is
refused unless the invoice belongs to the line's company, the direction agrees (a
withdrawal pays a Purchase Invoice, a deposit collects a Sales Invoice), the invoice is
live (not returned or reversed), the three currencies agree, the line carries no Nyabo
Proposal already, the period is open and the line is no bigger than the outstanding
amount. The Payment Entry it creates is a Nyabo posting like any other: `doc_events`
guards, the `nyabo_*` audit fields, the Mongolian explanation and the statement as its
source document.

### 5.5 Month-end `/хаалт YYYY-MM` (accountant only)

Checklist: open proposals, unmatched bank lines, receipts without seller verification,
suppliers pending confirmation, unverified rules used in the month (must be zero),
December → inventory count item (art. 12.2.1). Then Trial Balance numbers in chat, VAT
summary (output 2210 / input 1810 / net) for `vat_payer`, or the quarterly 1% summary
for `simplified_1pct`, both as PDF (Telegram `sendDocument`) and numbers. [Хаах] →
`compliance.period.lock(company, period)` creates the Accounting Period and a Nyabo
Event; refuses if today < end of month with `MSG_PERIOD_NOT_ENDED`.

### 5.6 Corrections `Засах` on a posted entry

Card with reasons [Буруу данс] [Буруу дүн] [Давхардсан] [Бусад…] → `compliance.reversal`
creates the reversal (JE reverse / PI debit note) dated in the original period if it is
still open, else dated today with a card telling the accountant the original period;
then, unless the reason is `duplicate`, a new proposal card pre-filled from the original
for the corrected values. Nyabo Correction rows record every changed field; two identical
corrections for a supplier create a `Nyabo Rule(status = pending_confirmation)`.

### 5.7 Questions

Free text outside a state → `agent.questions.answer(user, company, text)`: one model
call with tools `answer_from_books(query_kind, args)` (account balance on date, spend by
account this month, last entries for a supplier, unmatched count), `answer_faq(question)`
(from `config/faq.mn.md`), `escalate_to_admin(summary)`. Read-only; results are
formatted by code, the model writes the sentence.

## 6. LLM contract

```python
class LlmClient(Protocol):
    provider: str
    model: str
    def structured(self, *, purpose: str, system: str, user: list[Part], schema: dict,
                   schema_name: str, temperature: float = 0) -> LlmResult: ...
    def with_tools(self, *, purpose: str, system: str, user: list[Part], tools: list[ToolSpec],
                   handler: Callable[[str, dict], dict], max_turns: int = 4) -> LlmResult: ...

Part = TextPart(text) | ImagePart(bytes, mime)
LlmResult(data: dict | None, text: str | None, tokens_in, tokens_out, latency_ms,
          model, provider, prompt_version, raw_id)
```

Prompts are Markdown files `agent/prompts/<name>.v<N>.md` with a front-matter line
`version: N`; `agent.prompts.load(name)` returns `(text, version)`. Static instructions
first, the fenced untrusted content and the timestamp at the end of the user message.
Schemas come from pydantic v2 models in `agent/schemas.py`
(`model_json_schema()`, `additionalProperties: false`, all fields required for OpenAI
strict mode). OpenAI: Responses API, `text.format = {"type": "json_schema", "strict":
true, …}`, image as `input_image` data URL. Anthropic: Messages API with a single forced
tool whose input schema is the output schema (`tool_choice = {"type": "tool", "name":
…}`). Model names are per purpose: `get_client` returns a `PurposeRouter` that picks the
adapter from the `purpose` of each call, so one client can extract on one model and
classify on another and `Nyabo LLM Call.model` is the model that answered.
`OPENAI_PURPOSE_MODELS` holds the routing (`extract` → `gpt-5.6-terra`, `classify` and
`question` → `gpt-6-astra`, `eval` / `other` → `OPENAI_MODEL`) and `resolve_model` the
precedence: the purpose's own key, then that default, then `OPENAI_MODEL`. The ids were
given by the founder and are not verified against the provider's model list; `agent.cost`
prices are a table with `verified = false` until the founder confirms. Every call writes a
`Nyabo LLM Call`.

`MockLlmClient` returns canned results keyed by purpose + a hash of the user parts; the
simulator and tests use it.

As built (stage 1): `agent.extract.extract_receipt(client, image_bytes, mime, *, company_context, now)`
returns `(core.models.Receipt, LlmResult)`; `extract_receipt_full(...)` returns an `ExtractOutcome` whose
`warnings` carry `seller_name_missing`, `line_amount_missing`, `injection_suspected` (the pipeline sets
`needs_accountant` and writes a `Nyabo Event injection_suspected` with `injection_fragment`).
`agent.frappe_log.recorder(company=…, proposal=…)` is the `record_call` callback that writes `Nyabo LLM Call`.
Settings: `OPENAI_MODEL`, `OPENAI_MODEL_EXTRACT`, `OPENAI_MODEL_CLASSIFY`,
`OPENAI_MODEL_QUESTION`, `OPENAI_SWEEP_MODEL`, `ANTHROPIC_MODEL`;
`nyabo_mn.api.config_check` answers the routing resolved.

## 7. Ebarimt contract

```python
class EbarimtProvider(Protocol):
	name: str

	def lookup_seller(self, *, tin: str | None = None, register_no: str | None = None) -> SellerInfo: ...
	def verify_receipt(self, *, qr_data: str | None, receipt_id: str | None) -> ReceiptVerification: ...
```
`RegistryProvider` implements `lookup_seller` with the two public endpoints (requests,
5 s timeout, results cached on Supplier for 30 days) and returns
`ReceiptVerification(status="unsupported", reason=MSG_EBARIMT_VERIFY_UNAVAILABLE)`.
`MockProvider` returns fixtures. `PosSdkProvider` wraps `ebarimt-pos-sdk` (optional
extra `nyabo_mn[pos]`) for future seller-side use and raises `NotConfigured` on Frappe
Cloud. `qr.decode(image_bytes)` uses `pyzbar` if importable, else `zxing-cpp`, else
returns None with a logged `qr_decoder_missing` event. Card wording: `ebarimt ✓` is
never shown; instead `Худалдагч ✓ (ТТД)` when the seller was found in the registry and
`Баримт шалгагдаагүй` for the receipt itself.

## 8. Testing

### 8.1 Layers
- `tests/unit`: core, rules engine, parsers, matching, quarantine, i18n coverage
  (every `MSG_*`/`BTN_*` referenced in code exists), seed data validity.
- `tests/flows`: pipeline and Telegram handlers against the frappe stub with
  `MockLlmClient` and `MockProvider`; includes the two-regime receipt test, the
  unverified-rule refusal, post-without-document refusal, period-lock refusal, reversal
  pair, injection cases.
- `nyabo_mn/nyabo/doctype/*/test_*.py`: bench tests for a real site (run in Frappe
  Cloud's bench console or a local bench); CI does not run them.

### 8.2 `tests/frappe_stub`
A minimal in-memory Frappe: `frappe._`, `throw`, `msgprint`, exceptions, `get_doc`
(dict or doctype+name), `new_doc`, `Document` with `insert/save/submit/cancel/reload/
db_set/append/get/set/as_dict/flags/run_method`, `frappe.db.{get_value,set_value,exists,
count,get_all,get_list,get_single_value,set_single_value,commit,rollback,sql (raises)}`,
`frappe.get_all` (filters `=, !=, in, not in, >, >=, <, <=, like, between, is`,
`fields`, `order_by`, `limit`, `pluck`), `get_meta` (from our DocType JSON files and
`tests/frappe_stub/erpnext_meta.json` for ERPNext doctypes), `get_doc_hooks`/`get_hooks`
(reads `nyabo_mn/hooks.py`), `enqueue` (runs inline, records calls), `conf`, `local`,
`flags`, `session`, `set_user`, `get_roles`, `has_permission` (role table from
DocType JSON), `only_for`, `whitelist`, `request`/`response` objects for the webhook,
`logger`, `log_error`, `get_traceback`, `utils` (dates, flt/cint/cstr, fmt_money,
random_string, add_to_date family, file_manager.save_file), `utils.pdf.get_pdf`
(returns html bytes), `render_template` (Jinja2), `utils.xlsxutils.make_xlsx` (openpyxl).
`erpnext` stub: `make_reverse_journal_entry`, `make_debit_note`, `get_balance_on`
(sums GL Entry rows the stub records on submit of JE/PI/SI), `get_exchange_rate`,
`create_charts` (reuses our loader logic), `query_report.run` (calls our report modules).
Submitting a Purchase Invoice / Journal Entry in the stub writes simplified `GL Entry`
rows so balance assertions work. The stub validates that every field set on a document
exists in its meta, so typos in field names fail tests.

Stub-only knobs: `frappe.flags.stub_strict_links`, `frappe._stub.hooks.temporary_hooks(replace=…, without_apps=…, **hooks)`
(the `frappe_hooks` fixture), `frappe._stub.calls(name)` (recorded side effects). Fixtures in `tests/conftest.py`:
`site`, `company` (provisions Тест ХХК through the real provisioning code), `as_user`, `frappe_flags`, `frappe_hooks`.

## 9. Seed data

`nyabo_mn/nyabo/seed/`: `tax_parameters.json`, `posting_patterns.json`,
`bank_layouts.json`, `rules_default.json`, `chart_v03.json`, `aliases_v1_to_v03.json`,
`faq.mn.md`. `rules.seed.sync()` upserts by name on install/migrate and never overwrites
a row an admin has marked `verified = 1` unless `force = True`.

## 10. Style

Python 3.10+, tabs, type hints, ruff clean, docstrings that say *why*. No bare `except`.
No network in tests. Every public function that a Telegram handler calls has a unit or
flow test. Mongolian strings only in `i18n/mn.py`. Commit messages in English, one
feature per commit.
