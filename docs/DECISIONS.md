# Decisions

Judgement calls made while building against `docs/ARCHITECTURE.md`. One entry per call:
what was decided, why, and what it would take to reverse it. Newest at the bottom of each
section. Agents append to their own section; the integrator merges.

Identifiers are `<SECTION>-<nn>`, numbered inside the section they belong to — `CORE`
(core + rules + seed), `INT` (integration), `RULES` (rules on the Frappe side + setup),
`PIPE` (agent pipeline + posting + ebarimt), `COMP` (compliance + reports), `BANK`
(parsers + matching), `REV` (review), `TG` (telegram review), `LLM` (model routing), `Q` (the question agent) — so an identifier names
exactly one decision and a new entry never renumbers an old one. Cite them that way in
code and in docs (REV-02).

## core + rules + seed (stage 1)

### CORE-01 Money is `Decimal` quantised to 0.01 with ROUND_HALF_UP
`money.quantize`, `vat_from_gross`, `vat_from_net` round half up, not banker's rounding.
Accountants expect 0.005 → 0.01; Python's default `ROUND_HALF_EVEN` would make a receipt
VAT differ from the printed one by a tögrög often enough to trip `vat_consistent`.
`parse_mnt` accepts spaces (including thin/no-break), commas, `₮`/`MNT`/`төг`, parentheses,
leading, unicode and trailing minus. When both `,` and `.` occur, the last one is the
decimal separator; a lone comma is a thousands separator only when every group after it has
three digits. Reverse by changing the two constants in `money.py`.

### CORE-02 VAT consistency tolerance is 1₮
Receipts round per line, so the total VAT may differ from `gross × r / (1 + r)` by up to a
tögrög. More than that means a non-VAT seller, another rate, or a bad extraction, and the
proposal is held for the accountant (`MSG_VAT_MATH_INCONSISTENT`). `validate_entry` and
`vat_consistent` take `tolerance` so the pipeline can widen it per company if real receipts
show larger drift.

### CORE-03 Tax-parameter lookups never fall back
`resolve_parameter` raises `MissingRuleError` (no row on the date), `AmbiguousRuleError`
(two rows) or `PendingRuleError` (row has `status: pending` or `value: null`). A pending row
with a null value is treated as pending even if its status says active, because a null can
only mean "not encoded". The alternative — using the last known value — is exactly how a
2026 threshold ends up on 2027 books. Every error carries a Mongolian `message_mn`.

### CORE-04 Regime history: latest start wins on overlap
`regime_on` refuses a date with no regime row (onboarding not done) but tolerates
overlapping rows by taking the one that started last, so a correction row added later
takes precedence; `seed_check` and the DocType validation report overlaps separately.
Only `rules_engine.regime_on` (core) and `rules.regime` (Frappe side) know regime names.

### CORE-05 Patterns key on two axes: VAT status and CIT regime
Reviewer verdict on the first draft: the sale/purchase patterns were keyed on the
`simplified_1pct` profile, which silently left a non-VAT company on regular CIT (or a
voluntary VAT registrant) without a pattern. `applies_to_vat` (`any | vat_payer | non_vat`)
and `applies_to_cit` (`any | regular | simplified_1pct`) are separate; `RegimeContext`
still comes from one company-level regime today, so `vat_status_of`/`cit_regime_of` derive
both axes from it. When the company model gains separate `vat_registered` and `cit_regime`
fields, only those two helpers change.

### CORE-06 `instantiate` decides the ERPNext document kind
A Purchase Invoice is produced only when the pattern lists it and the VAT is `withheld`
(ARCHITECTURE §5.3 step 6); every other purchase is a Journal Entry (gross to expense). The
caller may override `document_kind`. An unverified pattern always appends
`mn.WARN_UNVERIFIED_RULE` to the entry's warnings, so the card shows it even before
`rules.guard` refuses the posting.

### CORE-07 Optional lines vanish when their amount is missing or zero
The VAT line of a receipt from a non-VAT seller, the input-VAT line of `vat_settle` when
there is nothing to offset. A mandatory line without an amount raises
`MissingAmountError` rather than posting a zero line, because `validate_entry` would refuse
the zero line anyway and the message should name the missing amount kind.

### CORE-08 Statement layouts: never guess a bank's columns in the seed
The five bank layouts ship as placeholders with an empty `header_signature` and empty
`column_map`, `verified: false`. No sample export was available, and a wrong column map
silently swaps debits and credits. Detection order: specific layouts by signature (more
headers first), then the `generic_mn` keyword guess, which returns a concrete `LayoutSpec`
with `verified=False` so the bot asks the accountant to confirm the mapping and the admin
to verify (ARCHITECTURE §5.4). `seed_check` refuses a seed layout that asserts columns.

### CORE-09 Statement rows: signed `amount`, inflow positive, both amount styles
`BankLine.amount` is always signed (credit − debit) so matching and transfer pairing do
not care whether the export had one signed column or two. Debit/credit cells are taken as
absolute values because some exports print outflows as negatives in the debit column.
Rows without a parseable date, blank rows, and opening/closing/total rows (marker text and
no amount) are skipped rather than failing the import. Dates are parsed only with the
layout's listed formats — no dateutil guessing, so `03.04.2026` cannot flip day and month
between banks. `row_hash` = sha256 of date, amount, narrative, reference and row index: the
idempotency key for `Bank Transaction` creation.

### CORE-10 Matching requires a name or reference, not just amount and date
ARCHITECTURE §5.4: exact amount + date within 3 days + name similarity ≥ 0.8. The first
draft let an exact amount on the same day reach the 0.8 threshold on its own; that is a
false-match risk on round amounts. Score is now base 0.50 (exact amount within 1₮ and
date within 3 days) + 0.20 × date score (1.0 at 0–1 days, 0.5 at 2–3) + 0.30 × name
similarity when ≥ 0.8, or the full 0.30 when the voucher reference appears in the line as a
whole token and is long enough to identify it (≥ 4 characters, ≥ 6 for pure digits): a
handwritten `bill_no` of "5", or one that is the year, is in every narrative by accident.
A same-day exact amount with an unknown party scores 0.70 and goes to the accountant
(`MATCH_REASON_LOW_SCORE`). Two candidates with the same top score leave the line unmatched
(`MATCH_REASON_AMBIGUOUS`). Name similarity is a token-set ratio on difflib after dropping
legal forms (ХХК, LLC, …); no third-party fuzzy library.

### CORE-11 Own-account transfers match contiguous digit groups only
`is_own_transfer` compares each digit group in the narrative with the company's account
numbers (≥ 6 digits); it does not join all digits of the text, so a date next to an amount
cannot spell an account number. `pair_transfers` pairs equal-and-opposite lines on the same
day, each line used once, and when account numbers are known both narratives must mention
one, so a customer receipt equal to a supplier payment is not paired.

### CORE-12 Seed verification policy
Only rows compared with a primary text (Law on Accounting art. 9–11, legalinfo URL and
article) ship `verified: true`; every tax value from the June 2026 package, news sites or
agency pages is `false`; values the reference marks VERIFY without stating a number ship
as `status: pending`, `value: null` (CIT brackets 2027, PIT brackets 2027/2028, employer SI
rate and accident tiers both years, 2027 input-VAT deduction categories, the 2027 "not
VAT-registered" condition, the tax-debt 70/30 rule whose in-force date is unconfirmed).
`effective_from: 2026-01-01` on a tax row means "in force before Nyabo's horizon", not a
legal date; the Law on Accounting rows carry their real date (2016-01-01). Reviewer verdicts
in the scratchpad `result_4`, `result_7`, `result_11` were applied to the seed files;
`seed_check` and `tests/unit/test_seed_data.py` pin them.

### CORE-13 `code_roles.json` may leave V1 roles null, listed explicitly
The 40-leaf V1 draft has no SI payable, PIT payable, prepaid-expense or customer-advance
account. Rather than mapping those roles to a neighbouring account (wrong books) or
dropping them from `required_roles` (wrong for v0.3), the file lists the permitted nulls
under `null_allowed.v1`; `seed_check` refuses any other null and any null in `v03`. A null
role makes the Frappe-side resolver refuse the pattern line and mark the proposal
`needs_accountant`.

### CORE-14 Goods for resale are class 15, raw materials class 14
Reviewer: the trading SME (core market) keeps goods in class 15 per reference §2, and
`cogs_on_sale` credits 15; `purchase_inventory_*` therefore debit 15 (`inventory_goods`)
with class 14 (`inventory_materials`) as an alternative. Both map to V1 1410.

### CORE-15 `Nyabo Posting Pattern Line` has no `role`, `code`, `v1_code_hint`, `class_assumed` columns
The DocType child table (scripts/doctype_specs.py) carries `side, account_class,
class_name_mn, sub_account_mn, amount_kind, optional, alternatives_json`. The core
`PatternLine` reads the extra seed keys when present and works without them; until the
integrator adds columns, `rules.seed.sync` should serialise `role`, `v1_code_hint`,
`v1_code_range` and `class_assumed` into `alternatives_json` alongside the alternatives or
into the pattern's `notes`. Integration request filed in the stage-1 report.

### CORE-16 Test data, not fixtures files
Core tests build rows inline (statement rows, receipts, candidates) instead of reading
xlsx fixtures, so a failure shows the input next to the assertion and no binary files
enter the repo. Real bank exports, once obtained, go under `tests/fixtures/statements/`
with the layout they verify.

## integration (stage 1 → stage 2)

### INT-01 One company-level regime for the MVP, two derived axes
The founder's onboarding asks one question ("НӨАТ төлөгч үү?"). `Nyabo Company Settings.regimes`
therefore stores `vat_payer` or `simplified_1pct`; `RegimeContext` derives `is_vat_payer` and the
CIT axis from it. A non-VAT company on regular CIT is not representable yet; when such a client
appears, add `cit_regime` to the settings and to `regime_on` (CORE-05 keeps the pattern axes
separate, so no pattern changes are needed).

### INT-02 Matching threshold stays 0.8 with name-or-reference required
CORE-10 stands. If real statements (Phase 3 checkpoint) show narratives without counterparty
names pushing auto-match below 80%, the fix is a per-company threshold on Nyabo Company
Settings, not a weaker default.

### INT-03 v0.3 is the production chart scheme; v1 stays for the test company
`code_roles.json` nulls under `v1` (CORE-13) are accepted: the v1 draft is only used by the
Phase 0 test company. New companies are provisioned with `chart_scheme = v03` unless the
accountant supplies a CSV chart.

### INT-04 Pattern line columns added to the DocType
`role`, `v1_code_hint`, `v1_code_range`, `class_assumed` on Nyabo Posting Pattern Line and
`family`, `reference_bullet`, `citation_instrument_full` on Nyabo Posting Pattern were added
(supersedes CORE-15). `rules.seed.sync` writes them directly.

### INT-05 Placeholders keep hooks importable during parallel builds
`nyabo_mn/compliance/{hooks,events,period}.py`, `evals/corrections_job.py`, `agent/few_shot.py`
and `telegram/state.py` exist as no-op placeholders named in hooks.py, so every stage-2 worktree
imports cleanly; the owning agents replace them. A placeholder that survives to a release is a
bug; `compliance.readiness` must report it.
## rules (Frappe side) + setup (stage 2)

### RULES-01 A code that exists in the installed chart is never treated as an alias
V1 and v0.3 reuse numbers with different meanings (V1 `6110` is salaries, v0.3 `6110` is
the stock adjustment). `rules.aliases.resolve_code` therefore checks the company's chart
first and only consults `Nyabo Account Alias` for codes the chart does not have; an alias
hop stops as soon as its target is a chart account, so `7003 -> 5101` on an accountant's
chart is not re-read as the v0.3 `5101` and hopped again. Roles resolve straight through
`code_roles.json` for v1/v0.3; only the accountant scheme hops through the `mof` aliases
(v0.3 template code -> accountant code) that CSV import creates from name matches.

### RULES-02 `provision_company` defaults to the V1 chart until the integrator flips it
`chart_scheme="v1"` keeps Phase 0 behaviour, the README instructions and the shared
`company` fixture (58 accounts, code 6210) identical while the other stage-2 modules are
built against them. `COMPANY_DEFAULTS_BY_CODE` is now derived from `code_roles.json`
(`company_defaults_by_code("v1")`) and pinned by a test to the Phase 0 literal table.
Switching the default to v0.3 is one constant (`DEFAULT_SCHEME`) plus that test.

### RULES-03 Tax parameters fall back to the seed *file* (not to another period) when the DocType is empty
A site whose install hook has not run yet has no `Nyabo Tax Parameter` rows;
`rules.params.load_rows` then reads `seed/tax_parameters.json` and logs
`rules.params.seed_fallback`. The data is identical and every row is unverified, so the
guard still refuses real postings; provisioning needs `vat.rate` for the templates and
must not hard-code 10%. The engine's date rules (CORE-03) are unchanged: no period fallback.

### RULES-04 Opening stock reconciliation uses the temporary-opening account
`stock_reconciliation.py` (version-16) refuses a Profit and Loss difference account on an
"Opening Stock" reconciliation, so `inventory_intake.post_intake` sets `expense_account`
to the `temporary_opening` role (`Temporary` account type) rather than ERPNext's default
`stock_adjustment_account`. Without perpetual inventory the opening entry is a submitted
Journal Entry Дт `inventory_goods` — Кт `temporary_opening` carrying `nyabo_explanation`
and `nyabo_primary_document_ref = <intake name>` so the document-required hook passes.

### RULES-05 Bank sub-accounts: next free sub-code under the bank role's parent group
The scheme's `bank` role is a leaf (1101 / 1120), so the per-bank accounts sit next to it
under its parent group ("11 Банкинд байгаа мөнгө" on v0.3, "1100 Мөнгөн хөрөнгө" on V1)
with the next free code of that prefix (1103, 1104 / 1121, 1122). The leaf stays the
Company default bank account; per-bank balances come from the sub-accounts and the ERPNext
`Bank Account` rows that link to them. Names are "<Bank MN> <currency> <last 4 digits>".
## agent pipeline + posting + ebarimt (stage 2)

### PIPE-01 The pipeline bridges to `nyabo_mn.rules` and falls back to the core engine on the same rows
`nyabo_mn.rules` (regime, patterns, guard) was not in the tree when the pipeline was
written. `agent.pipeline.regime_context` uses `rules.regime.posting_context` and
`agent.pipeline.require_verified` uses `rules.guard.require_verified` / `UnverifiedRuleError`
when they are importable (the names ARCHITECTURE §1 fixes); otherwise the same DocType
rows (`Nyabo Company Settings.regimes`, `Nyabo Posting Pattern`, `Nyabo Tax Parameter`,
seed JSON when a table is empty) are fed to `core.rules_engine`. There is no second rule
set to drift. Reverse by deleting the fallback branches once the rules package lands.

### PIPE-02 VAT treatment is decided by code, the model only suggests
`decide_vat_treatment`: a non-VAT company never withholds; no printed VAT means nothing
to withhold; a seller the registry marks as non-VAT-payer keeps the printed VAT in the
expense with `WARN_SELLER_NOT_VAT_PAYER`; a VAT payer with printed VAT from a VAT-payer
seller withholds even when the model said `in_expense`, because the non-deductible
categories are a pending 2027 parameter (`vat.input_deduction_categories`), not a model
judgement. Only `exempt` / `zero` survive from the model.

### PIPE-03 A cash receipt credits cash; card / QPay / transfer keep the payable
The bank statement flow settles the payable through ERPNext, so crediting the bank
account directly on a card/QPay/transfer receipt would double count when the statement
line arrives. A cash receipt (`payment_method == "cash"`) has no statement line to wait
for, so it credits the cash role whatever the document kind
(`make_resolver(overrides={"payable": "cash"})`): a Journal Entry credits cash directly,
and a Purchase Invoice (input VAT withheld) is posted as ERPNext's paid invoice —
`agent.post.build_purchase_invoice` sets `is_paid = 1`, `cash_bank_account` and
`paid_amount` from that credit line, so `make_payment_gl_entries` nets the payable to
zero and credits cash. Amended after review: crediting the payable on a cash purchase
left an open supplier balance that nothing in the product could ever settle.

What settles the payable is now written down, because "the bank statement flow settles it"
was a promise nothing kept: a cash receipt credits cash at posting time through ERPNext's
`is_paid` invoice, while a card / QPay / transfer receipt keeps the payable open until its
statement line arrives, and that line is settled by a Payment Entry
(`matching.match.settle`) created on the accountant's tap — never by allocating the invoice
to the Bank Transaction, which posts nothing.

### PIPE-04 The classified account replaces the pattern's primary debit line
A pattern's first debit line carrying `net`/`gross` (the class-70 line, or the
`inventory_goods` / `fixed_asset` role) is resolved to the account the rule or the model
chose; the family (`purchase_expense` / `purchase_inventory` / `fixed_asset_acquire`) is
derived from that account's ERPNext `account_type` (`Stock`, `Fixed Asset`, `Capital Work
in Progress`), never from the model's words. Other roles resolve through
`code_roles.json` for the settings' scheme; when the settings say `v03` but the chart is
the V1 draft (provisioning today), `chart_scheme` picks the scheme whose payable role
exists in the chart rather than posting to a code the chart does not have.

### PIPE-05 Supplier matching: identifiers first, names at 0.9 with an exact-name tie-break
`tin` / `tax_id` / `register_no` decide before names. The token-set ratio scores a subset
("Петровис" vs "Петровис Ойл ХХК") as 1.0, so ties are broken by exact normalised
equality and then the plain character ratio. New suppliers carry
`nyabo_pending_confirmation = 1` and the registry answer (`ebarimt_vat_payer`,
`ebarimt_checked_at`, 30-day cache) when the seller was found.

### PIPE-06 Learned rules key on the supplier's register number, then its name, then the description
Two `Nyabo Correction(field=account_code)` rows agreeing on the target for the same
supplier create one `Nyabo Rule(source=learned, status=pending_confirmation)` listing the
corrections; an existing active/pending rule for the same key blocks duplicates. A pending
rule never matches (`match_rule` reads `status = active` only) until `confirm_rule`.

### PIPE-07 LLM call rows are written after the proposal exists, with its name
`Nyabo LLM Call` needs the proposal link, which does not exist while the model runs, so
the pipeline buffers `CallRecord`s and flushes them with the proposal name (or without
one when the pipeline fails). An injected client without a recorder (tests, simulator)
gets the pipeline's recorder, so "every call writes" holds there too.

### PIPE-08 ebarimt: registry only, receipt verification "unsupported", POS SDK refuses to start
No buyer-side verification endpoint exists (ARCHITECTURE §2), so every provider answers
`ReceiptVerification(status="unsupported", reason=VERIFICATION_RECEIPT_UNCHECKED)` and
the card never shows `ebarimt ✓`. `RegistryProvider` treats any non-200, non-JSON or
off-shape body as "not found" and never raises into the pipeline. `PosSdkProvider` raises
`NotConfigured` at construction: PosAPI 3.0 is merchant-side and needs a local service in
Mongolia. `qr.decode` tries pyzbar then zxing-cpp and logs `qr_decoder_missing` once.
## compliance + reports (stage 2)

### COMP-01 Retention years are a tax parameter, read from the table or the seed
`compliance.hooks.retention_years()` resolves `retention.years` (Law on Accounting art.
11.1, the one row shipped `verified: true`) through `core.rules_engine.resolve_parameter`
on the Nyabo Tax Parameter table and falls back to `seed/tax_parameters.json` only while
the table has no row for the key, so a document received before the first seed sync still
gets a date. No constant `10` exists in the code; reverse by seeding another row.

### COMP-02 The no-edit guard compares field by field, system code may opt out
`guard_no_edit_after_submit` diffs `get_doc_before_save()` against the document (child
tables row by row) and lets only `nyabo_*` fields and `remarks` change. ERPNext saves
submitted documents itself in a few flows (hold/release, clearance); those go through
`db_set` today, but a future flow that calls `save()` can set
`frappe.flags.nyabo_allow_submit_edit`. The Nyabo audit fields still need
`allow_on_submit = 1` in `setup/custom_fields.py` for Frappe's own check to let them
through — integration request filed.

### COMP-03 A period locked through Nyabo cannot be deleted; reopen is `disabled = 1`
The lock/reopen events point at the Accounting Period with a Dynamic Link, which makes
Frappe's link check refuse a delete anyway; `log_period_delete` turns that into a
Mongolian refusal before the misleading "deleted" event would be written. Manual desk
periods keep the name in the event payload instead of a link so they stay deletable
(and logged). Reopening is ERPNext's `disabled = 1`, never a delete.

### COMP-04 Reversal helpers run as the session user; the approver is a field
`make_reverse_journal_entry` / `make_debit_note` check read permission on the source
under the current session, then the reversal is inserted with `ignore_permissions`. The
Telegram approver is recorded in `nyabo_approved_by`, Nyabo Correction and the event;
bot jobs therefore run under a service session that can read the ledger (Administrator
or an Accounts User), not under the approver's login.

### COMP-05 Report accounts come from roles, and the scheme is checked against the chart
`reports.accounts` maps role -> code through `seed/code_roles.json` for the company's
`chart_scheme`, then to the Account by `account_number`. The settings field defaults to
v0.3 while Phase-0 companies run the V1 chart, so the configured scheme is trusted only
when its cash-role code exists in the chart; otherwise v1 then v03 are tried. The
`accountant` scheme goes through Nyabo Account Alias rows. When `nyabo_mn.rules.aliases`
lands, `role_account` delegates to it (signatures unchanged).

### COMP-06 Simplified 1% summary refuses an unverified rate unless simulated
`simplified_summary.compute` resolves `simplified.rate` on the quarter's last day and
raises `UnverifiedRuleError` when the row is unverified, exactly like the posting guard,
because the number goes on a tax return. `simulation=True` (the report's Simulation
filter, tests, the simulator) shows the figure labelled `LBL_SIMULATION`. The error class
is imported from `nyabo_mn.rules.guard` when that package exists (`reports.rules_bridge`).

### COMP-07 Financial report templates: two shipped, two not
Balance sheet and income statement ship as Financial Report Templates keyed on the 29
ERPNext account categories only (no account-number tests except the 70/71 split of
operating expenses), so they render on the V1 and the v0.3 chart. Both open with a
`ТҮР ЗАГВАР` row. The engine's `report_type` options are `Profit and Loss Statement`,
`Balance Sheet`, `Cash Flow`, `Custom Financial Statement`
(erpnext/accounts/doctype/financial_report_template/financial_report_template.py,
version-16); how a `Cash Flow` template maps rows to cash-flow activities and whether a
`Custom Financial Statement` can express the MN statement of changes in equity was not
verified from the engine source, so `nyabo_sme_equity_statement` and `nyabo_sme_cash_flow`
are not shipped and the readiness checklist reports the four-statement item as failed.
Known category mismatches in the v0.3 chart (7012 bank fees as Finance Costs, 8703/8790
as Operating Expenses) are listed as an integration request rather than patched here.

### COMP-08 Print-format labels come through a whitelisted call, not literal Cyrillic
Print formats are Jinja files that cannot import `i18n/mn.py`. Frappe's print Jinja
environment exposes `frappe.call` (safe_exec `get_safe_globals`), so every template
starts with `{% set L = frappe.call("nyabo_mn.reports.labels.print_labels") %}`. A
`jinja` hook method would be cleaner; requested from the integrator.

### COMP-09 Mongolbank fetch is off by default and undocumented
The rate endpoint (`POST /en/currency-rates/data?startDate&endDate`) is the website's
internal XHR, not a documented API. `fx_rates.fetch_mongolbank` exists behind the site
config flag `MONGOLBANK_FETCH_ENABLED`, is marked UNVERIFIED and is never called from
tests; `import_csv` is the supported path. Rows land in ERPNext's Currency Exchange table
and the pipeline reads them through `get_exchange_rate`.

### COMP-10 A Payment Entry is a posting, so it carries the guards — except the reversal
The settlement tap introduced a fourth ledger-posting DocType, and the first attempt left it
outside every Nyabo guard: no `doc_events`, none of the `nyabo_*` custom fields, no Mongolian
explanation, no link back to the statement, no retention date, editable after submit and
deletable after cancel — with ERPNext's English boilerplate as its only narrative. Payment
Entry is now in `hooks.doc_events` with the same four handlers, in
`setup.custom_fields.TRANSACTION_DOCTYPES`, in `RETAINED_PARENTS` and in
`PRIMARY_DOCUMENT_DOCTYPES`; `match.settle` stamps `nyabo_explanation` (which payable this
credit closed and which bank account it left), `nyabo_approved_by`, `source_document` (the
Nyabo Document of the statement import) and `nyabo_primary_document_ref` (the invoice).
`block_delete_of_posted` used to ask for `nyabo_proposal` alone, which a settlement has not
got; it now fires on any Nyabo trail — the proposal, the source document or the explanation.

`PRIMARY_DOCUMENT_DOCTYPES` is the one of the four that cannot be applied flat. Nyabo did not
put Payment Entry on the site: ERPNext submits its own from the desk, from the Bank
Reconciliation Tool (`bank_reconciliation_tool.create_payment_entry_bts` builds
`frappe.new_doc("Payment Entry")` and calls `pe.insert(); pe.submit()`) and from a Payment
Request, and none of them can name a primary document. Journal Entry survives that because
`system_generated_source` recognises ERPNext's own entries, and it answers `None` for every
other doctype — so the first attempt refused *every* Payment Entry the company made, in
Mongolian, including the ones ERPNext's own features depend on. `require_primary_document`
therefore asks art. 13.7 of a Payment Entry only when it carries a Nyabo trail
(`has_nyabo_trail`, the same `NYABO_TRAIL_FIELDS` the delete guard reads). The guarantee is
unchanged where it matters: `match.settle` stamps `source_document`, `nyabo_explanation` and
`nyabo_primary_document_ref` together, so a settlement that lost its source document is still
refused, and a Payment Entry with no Nyabo field on it is not Nyabo's to refuse. Purchase
Invoice and Journal Entry keep the flat rule: a person filing a purchase or a journal by hand
is exactly whom art. 13.7 addresses.

The reversal path is deliberately *not* extended. Every DocType in `reversal.SUPPORTED` has an
ERPNext constructor that builds a counter-document leaving the original in place
(`make_reverse_journal_entry`, `make_debit_note`). A Payment Entry has none: ERPNext undoes one
by cancelling it, which is what re-opens the invoice through the Payment Ledger and, through
`remove_from_bank_transaction`, releases the statement line. A hand-built reversing Journal
Entry would move the bank and the payable back while `outstanding_amount` still said "Paid" —
a worse book than the mistake. A mis-tapped settlement is therefore corrected by cancelling the
Payment Entry (the line returns to Unreconciled and can be settled again) or, when the invoice
itself was wrong, by reversing the invoice, which this module does support. Reverse this
decision the day ERPNext grows a `make_reverse_payment_entry`, or the day Nyabo models the
Payment Ledger well enough to restore an outstanding amount by hand.

## parsers + matching (stage 2)

### BANK-01 Candidates come from the GL, not from each DocType's amount fields
`matching.match.candidates_for` reads GL Entry rows on the bank GL account (submitted
Purchase Invoice with `is_paid`, Sales Invoice POS payments, Journal Entry, Payment Entry,
no `clearance_date`, allocation already made by other Bank Transactions subtracted) and
hands `core.matching.pick` a signed movement per voucher. That is the same row ERPNext's
`allocate_payment_entries` looks at (`get_related_bank_gl_entries`), so a match the core
accepts can always be allocated; an unpaid invoice (payable only) is never a candidate,
which is also what ERPNext's reconciliation tool queries. Direction is enforced: a
withdrawal only sees outflow vouchers. Reverse by switching to per-DocType queries.

### BANK-02 Bank Transactions are inserted and submitted; reconciliation mirrors the tool
ERPNext's Bank Statement Import submits what it creates (`submit_after_import` defaults to
1, hidden), and the reconciliation queries filter `docstatus = 1`, so `bank_import` does the
same. `match.reconcile` runs exactly the `reconcile_vouchers` sequence of
`bank_reconciliation_tool.py` (version-16): `add_payment_entries` →
`validate_duplicate_references` → `allocate_payment_entries` → `update_allocated_amount` →
`set_status` → `save`, with vouchers shaped `{payment_doctype, payment_name, amount}`.

### BANK-03 Two idempotency keys per statement row
The core `row_hash` (includes the row index) goes into `Bank Transaction.transaction_id`;
a second fingerprint (bank account + date + deposit + withdrawal + normalised narrative)
catches the same line re-exported at another row position (next month's overlapping
statement). Either hit counts as `dup`. The import writes one `statement_imported` Nyabo
Event with the created names, all row hashes and the closing balance column, which is
what `/данс` reports as the statement balance.

### BANK-04 The account number is only searched in the title block
`resolve_bank_row` matches a configured account number only in rows above the detected
header. A transfer narrative in the data rows names the *other* account and, before this
rule, redirected a whole TDB statement into the Khan Bank account.

### BANK-05 Chart scheme is probed, not trusted
`Nyabo Company Settings.chart_scheme` defaults to v0.3 while provisioning still installs
the V1 tree, so `matching.rules.chart_scheme` checks that the scheme's `bank` and
`receivable` role codes exist in the company's accounts before using its role table, and
falls through to the other scheme otherwise. Codes are then resolved with
`setup.chart_db.account_for_code`; the alias resolver in `nyabo_mn.rules` is not in this
worktree (integration request filed).

### BANK-06 Unmatched inflows are proposed to the receivable role, outflows are classified
Fee lines follow the company's `bank_fee` Nyabo Rule (seed row fallback). Other outflows
are classified by the model (`agent.classify`, mock under `frappe.flags.nyabo_simulation`),
inflows are proposed as Дт bank / Кт receivable with `needs_accountant = 1` because the
classification prompt is receipt-shaped. Every bank-line proposal cites an unverified
pattern today, so all carry `WARN_UNVERIFIED_RULE` and need the accountant. All four ids
(`bank_fee_expense`, `receivable_collect`, `bank_line_expense`, `bank_transfer_internal`)
are seed rows with `citation.section = null` and `verified = false`: approval therefore
ends in `UnverifiedRuleError` («Дүрэм баталгаажаагүй») and an admin can clear it by
verifying the row, instead of failing with «загвар олдсонгүй» on an id that exists nowhere.

### BANK-07 Synthetic statement fixtures are committed, clearly labelled
Unlike CORE-16, the import tests need real file containers (xlsx zip, cp1251 bytes), so
`tests/fixtures/statements/` holds files generated by `make_fixtures.py` from inline data;
the tests import the builders, never the files, so a stale file cannot change a result.
The README states they are scaffolds, not claims about any bank's format.

### BANK-08 An unpaid invoice is settled by a Payment Entry, never by an allocation
`Bank Transaction.add_payment_entries` and `allocate_payment_entries` (version-16) only
append a link row and stamp `clearance_date`; they post nothing. Allocating an invoice that
still owes money therefore left the supplier payable open and the bank balance overstated
for good — one phantom payable per card / QPay / transfer purchase, growing every month.
ERPNext says the same in `bank_reconciliation_tool.get_pi_matching_query`, which offers
Purchase Invoices only with `docstatus = 1 AND is_paid = 1 AND clearance_date IS NULL`: the
supported route for an unpaid invoice is a Payment Entry. So `match.reconcile` refuses a
voucher that `settlement_needed` flags (submitted invoice, `outstanding_amount > 0`), and
`match.settle` builds ERPNext's own Payment Entry
(`payment_entry.get_payment_entry(dt, dn, bank_account=<the bank GL account>)` — that
parameter reaches `get_default_bank_cash_account(..., account=...)`, so it is a GL Account
name, not a Bank Account row, which goes on `pe.bank_account` as
`create_payment_entry_bts` sets `company_bank_account`), dates it on the statement line,
allocates the smaller of the line and the outstanding amount, submits it and reconciles the
line against *that*. A line larger than what the invoice owes is refused rather than parked
as an advance on the supplier: the accountant splits it or picks another document.
`match.run` never settles — a Payment Entry reaches the ledger, and ARCHITECTURE §1.3 keeps
posting behind a human tap, so the line stays unmatched and its card carries
[Төлбөр бүртгэх]. Reverse by deleting `settle` and the button; the refusal in `reconcile`
must stay either way, because the allocation it refuses does not do what it looks like.

### BANK-09 What `settle` refuses, and why every one of those refusals is a book entry saved
Two independent reviews reproduced eighteen problems with the first settlement branch, six
of which corrupted the books. `settle` now checks everything it can before it writes
anything, and each check is here because a probe produced a wrong ledger without it:

- **The invoice's company must be the statement line's.** The voucher name arrives in
  callback data, and `frappe.db.exists` is a global question. Without the check
  `get_payment_entry` built a Payment Entry in the *other* company's books with this
  company's bank account on it; only `submit` noticed, in English, and a docstatus-1
  document with no GL behind it was left in the other company's ledger — one more per retry.
- **The direction must agree**: only a withdrawal pays a Purchase Invoice, only a deposit
  collects a Sales Invoice, and the `payment_type` ERPNext derives is asserted as well
  (`Pay` for an outflow, `Receive` for an inflow). The wrong pairing produced a `Receive`
  that DEBITED the bank for a line where money left it, and then marked the line Reconciled:
  double the overstatement this change exists to remove.
- **A line a Nyabo Proposal already explains may not also be settled.** `existing_proposal`
  asked for status `proposed` only, so a *posted* bank-line proposal made the line look
  untouched: `run` re-carded it, the button was offered, and 187,000₮ of bank credit came
  out of one 93,500₮ statement line. The lookup now covers `proposed`, `approved` and
  `posted` — every state that means the line is spoken for — and `settle`, `run`, the card
  text and the button all ask the same question.
- **The currencies must agree** (invoice, party account, bank account, statement line).
  `outstanding_amount` is in the invoice's currency and `unallocated_amount` in the bank's,
  so the over-allocation guard and the allocated amount compared and wrote across
  currencies: a 93,500 USD invoice was offered for a 93,500₮ withdrawal. Supporting it
  properly means writing `paid_amount`, `received_amount` and `allocated_amount` in three
  currencies through `conversion_rate`; until that is built and tested against a real bench
  the tap is refused and the accountant posts by hand.
- **A reversed invoice is not a candidate**: `is_return`, a status of Return / Debit Note
  Issued / Credit Note Issued / Cancelled / Closed, or a submitted return naming it. ERPNext's
  repost normally zeroes the outstanding too, but nothing here may depend on that having
  happened — settling a voided invoice credits the bank against a payable that already nets
  to zero and leaves a phantom prepayment on the supplier.
- **A closed period is refused with `MSG_POSTING_IN_CLOSED_PERIOD`**, the message every other
  posting path gives (`post.refuse_if_closed`). ERPNext refuses it too, in English, which
  reached the accountant as the generic "error, admin notified".
- **A bank account with no GL account is refused.** `get_payment_entry` silently falls back
  to `Company.default_bank_account`, so an empty mapping credited a bank the statement line
  never touched.
- **Nothing partial survives a failure.** `insert` + `submit` + `reconcile` run inside one
  `frappe.db.savepoint`; the rollback is what a site relies on, and an explicit cancel +
  delete of the Payment Entry makes the invariant observable in the harness, which has no
  real transaction. Before, a `reconcile` that threw left a *submitted* Payment Entry, the
  invoice at zero outstanding and the line Unreconciled — and, because `settlement_needed`
  was then false, every retry was refused, so the accountant could neither settle nor
  reconcile the line from Telegram.

Authorisation: `check_can_settle` asks `access.require_company` and `post.approver_kind`, and
the Payment Entry is then inserted with `ignore_permissions`, as every other Nyabo posting
path does (`agent.post.post_proposal`). The alternative — posting as the tapping user and
relying on ERPNext's own role — was rejected: a linked accountant does get `Accounts User`
at link time (TG-05), but making the tap depend on a role a site's admin can revoke turns a
posting Nyabo has already authorised into a dead button. `MSG_BANK_SETTLE_ERPNEXT_PERMISSION`
stays as the Mongolian answer for the paths that still reach a `PermissionError`.

Cost: the candidate scan used to be O(open invoices) round trips per line, per card and per
[Буцах] tap — a 300-line statement against 200 open invoices was ~60,000 `get_value` calls
per import. `open_invoice_candidates` now fetches the party and reference columns in the same
`get_all` (no `voucher_details` per row) plus one query for the returns that void them, and
`run` builds the list once per (direction, currency) instead of once per line. The card's
settlement hint and the button both catch broadly: the hint is decoration, and decoration
must never suppress a card.

## integration (stage 2 seams: rules + compliance + reports)

### INT-06 The reports side reads rules through the rules package, no second reader
`reports.rules_bridge` now delegates to `rules.params.get` / `rules.guard.require_verified`
(same `UnverifiedRuleError`), `reports.accounts.role_code` to `rules.aliases.role_code` +
`alias_target` (alias scheme `mof` for the accountant's chart, as `rules.aliases` defines
it), and `reports.month_end.regime_history` to `rules.regime.history`. The report-side
signatures (`parameter_on` throws Mongolian, `require_verified(row, simulation=...)`,
`role_account`) and the chart probe of COMP-05 stay. Reverse by re-inlining the
readers, which is how the two sides drifted in the first place.

### INT-07 Verified seed rows pass the guard, also from the seed-file fallback
After the legal-citation pass 46 tax parameters and 28 patterns ship `verified: true` with
their quote; `rules.seed.sync` writes `citation.{section,quote,url}` to `citation_*` and
the tax-parameter quote (`quote_mn`, else the `«…» —` prefix of `note`) to `quote_mn`.
RULES-03 said "every seed row is unverified, so the fallback is safe"; the fallback
now carries the same human verification the synced rows would, which is the point of
verifying the file. Tests that need an unverified rule pick one that ships unverified
(`si.employee_rate`, `bank_fee_expense`, `payable_pay`) or insert their own row.

## integration review (post-merge)

### REV-01 The simulator and the golden set must mirror `agent.pipeline`, not their own rules
`evals.harness` swapped the credit line to the bank for card, QPay and transfer receipts,
while `agent.pipeline` follows the pipeline decision "a Purchase Invoice always credits the
payable; a Journal Entry credits cash only for a cash receipt". The simulator therefore
printed an entry the system would never post, and the golden set scored that entry as
correct. `_conditions` now returns only `paid_in_cash`, the generator's `expected_lines`
uses the same rule, and `test_both_regimes_credit_the_payable_like_the_pipeline` pins it.
Whenever the two disagree, the pipeline is the authority: it is what reaches the ledger.

### REV-02 Decision identifiers are unique per section, not per agent
Seven agents each numbered their decisions from `D-017`, so the log held five different
`D-017`s and a citation in code named a number that matched several entries. Every entry
now carries its section's prefix and a number that runs inside that section
(`CORE-01`, `RULES-03`, `PIPE-03`, …), so an identifier names exactly one decision and a
new entry is appended to its section without touching any other. The file also held two
stale copies of itself from a bad merge; they are collapsed into one, keeping the newer
text of each entry (the reference-token rule in `CORE-10`, the amended `PIPE-03`, the
four seed pattern ids in `BANK-06`). The post-merge review sections were renumbered with
the rest: `D-I01`/`D-I02` are `REV-01`/`REV-02`, `D-R01`…`D-R06` are `REV-03`…`REV-08`,
`D-I03` is `REV-09`, and the telegram review's `D-T01`…`D-T06` are `TG-01`…`TG-06`. Every
citation in `nyabo_mn`, `tests` and `docs` was rewritten to the new identifiers in the same
commit; `D-0…`, `D-I…`, `D-R…` and `D-T…` no longer appear anywhere.

## review fixes (compliance + reports)

### REV-03 The 1% summary resolves the regime's conditions, not only its rate
`simplified_summary.compute` now resolves `simplified.requires_not_vat_registered`
(CIT art. 29.3.1) and `simplified.revenue_threshold` (art. 29.1) on the quarter's last day
before it computes anything, so the deliberately pending 2027 rows raise `PendingRuleError`
instead of letting the verified open-ended rate print 1% of a quarter whose regime terms
nobody knows. A company that is a VAT withholding payer on that date is refused
(`MSG_SIMPLIFIED_NOT_ELIGIBLE_VAT`). The threshold is only *raised*: art. 29.1 rests on the
confirmed prior-year return, which Nyabo does not hold, so the company's own prior-year
revenue sets `needs_accountant` and a warning line instead of deciding eligibility.

### REV-04 ERPNext's own Journal Entries carry a stamped primary document
`require_primary_document` refused every entry ERPNext generates itself (depreciation —
a daily scheduler job — asset disposal, exchange-rate revaluation, the gain/loss entry,
opening entries, reversals), which have no Nyabo Document, no reference and no attachment.
They are now stamped with `MSG_PRIMARY_DOCUMENT_SYSTEM_GENERATED` naming what produced
them rather than skipped silently, so art. 13.7's trail stays on the document.

### REV-05 The period lock reads the pattern from the entry, not only from the link
`posting_pattern` is a Link, so it stays empty for a pattern that exists only in the seed
file (a site whose rows were never synced) or was renamed. `unverified_proposals` now takes
the id from `entry_json` when the link is empty and asks `rules.guard` the same question the
posting guard asked (DocType row first, seed second); an id that resolves to nothing counts
as unverified, because refusing is the safe default.

### REV-06 A reversal is never reversed, and the refusal is Mongolian
`reversal.is_reversal` refuses a document that already carries `reversal_of`, `is_return`
or `nyabo_corrects` with `MSG_CORRECTION_IS_REVERSAL`; ERPNext refused it too, in English,
which reached the accountant as the generic "error, admin notified".

### REV-07 The month-end trial balance falls back on any report failure
The documented fallback caught `DoesNotExistError` only, while the realistic failures are
`frappe.PermissionError` (the Telegram user holds `Nyabo Accountant`, not `Accounts User`),
a disabled report (`ValidationError`) and `FiscalYearError`. `trial_balance` now logs and
falls back to the GL aggregation on any exception: `/хаалт` must not die on a report the
app does not need.

### REV-08 The readiness checklist cites no instrument it has not read
`readiness.py` claimed conformity with numbered items of "MoF Order 47/2018 annex 1", an
instrument absent from `docs/legal/` and from `docs/mn-rules-reference.md`, whose §6.1 lists
the certification procedure «Нягтлан бодох бүртгэлийн программ хангамжид хяналт тавих журам»
as still to obtain. The requirement column, the item-number map, the invented annex module
list and the order named in the report footers are gone; the table is labelled Nyabo's own
internal readiness list (`READINESS_SOURCE_PENDING`) and reports with no MoF form behind them
are footed `FORM_SOURCE_INTERNAL`. When the procedure text is fetched, the rows are mapped to
it with the verbatim quotes `docs/legal/README.md` requires.

### REV-09 Company scoping is enforced in two layers, not only in the handlers
The DocType permission tables gave `Nyabo Accountant` read and write on every row of
every Nyabo DocType, and the app declared no `permission_query_conditions`. One missed
company check in a handler was therefore a full cross-tenant read of another client's
proposals and the private URLs of their receipt photos (review finding SEC-06).
`nyabo_mn/permissions.py` now narrows every list, report and `get_doc` on a Nyabo DocType
to the caller's linked companies, and `consume_link_code` writes a Frappe `User Permission`
(Company) per link so ERPNext's own documents are scoped by the standard mechanism too.
Admins (`System Manager`, `Nyabo Admin`, the Administrator) stay unrestricted, and a row
with no company stays visible. Telegram users keep `user_type: "System User"` because the
reversal and journal-export paths need ERPNext's own roles; the User Permission rows, not
the user type, are what confine them.

## telegram review (post-merge)

### TG-01 `_deps` names the module that owns the function, not the one in the contract
ARCHITECTURE §5.3 step 6 calls the posting entry point `agent.pipeline.post_proposal`, but
posting landed in `agent/post.py` and `pipeline.py` cannot re-export it (post.py imports
pipeline, so the re-export would be circular). The six shims - `post_proposal`,
`change_account`, `reject`, `top_accounts`, `search_accounts`,
`make_correction_proposal` - therefore resolve `nyabo_mn.agent.post`.
`tests/unit/test_telegram_deps.py` imports every `_call` target so a shim can never again
name a function that does not exist.

### TG-02 The rejection reason travels as a code, the free text beside it
`post.reject` takes `reason_code` (a key of `mn.REJECT_REASONS`) and now an explicit
`reason_text` for the "other" case. The handler renders the label for the card and the
proposal's `rejection_reason`, but `Nyabo Correction.reason` keeps the code, because the
corrections job and `learn_from_correction` read the code, not the Mongolian label.

### TG-03 Company scoping lives in `nyabo_mn/access.py`, next to every entry point
Callback data is attacker-chosen and ERPNext document names are a global sequence, so a
name alone never authorises anything: `correct`, `bank`, `compliance.reversal`,
`matching.match` and `compliance.period` all re-check the document's company against the
caller's `Nyabo User Company` rows. The handlers check it *and* the functions do, so a new
caller cannot reintroduce the hole.

### TG-04 The link role is per company
`Nyabo User Company` carries a `role`; `Ctx.role` and `agent.post.approver_kind` resolve it
for the active company and fall back to the link-level role (which is what a link with no
company carries, and what rows written before this field fall back to, so nothing needs
migrating). One person is often the owner of their own company and the bookkeeper of
another; the old site-wide role let an Accountant code for one company make them an
accountant everywhere. `approver_kind` asks the link before the site-wide Frappe roles for
the same reason.

### TG-05 A linked accountant gets ERPNext roles, and guessing link codes is capped
`ensure_frappe_user` adds `Accounts User` for an Accountant link and `Accounts Manager` for
an Admin link (an Owner gets neither: an owner only taps cards). Without them ERPNext
refuses `make_reverse_journal_entry`, `make_debit_note` and `query_report.run` for the
session the bot runs as, which is the approver's. The roles are site-wide, so the company
boundary is TG-03's, not ERPNext's. Separately, five wrong link codes block a chat for an
hour (`Nyabo Chat State.link_attempts` / `link_blocked_until`) and raise a Nyabo Event:
a six-digit code is the only credential guarding a company's books.

### TG-06 The bot token never reaches an error string
A `requests` transport failure embeds the request URL, and the request URL contains the
token, so `api.call` / `api.download` log and raise only the exception's class name.
`log.scrub` masks anything token-shaped in any logged value, in the desk Error Log
traceback and in the admin notice, as a backstop for paths that repr an exception.

## bot UX review (post-merge, the founder's first live session)

### UX-14 An escape button carries the step it was drawn for, not only the flow
§5.1 lists callback data by prefix; the escape row added `e:<scope>:<verb>` and it is now
`e:<scope>:<verb>:<step>`, the two halves of the conversation state the prompt belongs to.
The scope alone could only catch a tap that crossed flows. Steps answered by typing
(`acc_name`, `acct`, `micpa`, `cur_other`, `inv_wait`) are never edited when they are
answered, so their escape row stays live above the question that followed, and a tap on it
moved the wizard from a step it was not drawn for. A datum with no step is a card drawn
before this change and still gets the old flow-level check, because a card lives in the chat
across a deploy. The longest state name leaves the 64-byte datum less than half used
(`tests/unit/test_telegram_escape_words.py`).

### UX-15 `Nyabo Inventory Intake.status` gains `cancelled`
§4 lists `draft/confirmed/posted` (the code already had `failed`). The draft is inserted
when the confirmation card is drawn, so every way out of that step — Алгасах, Цуцлах, Буцах,
the card's own [Цуцлах] — left one behind. `post_intake` refuses anything but a confirmed
intake, so none of them could reach the ledger, but a draft nobody explained is a row an
auditor has to ask about. It is cancelled by status and never deleted: this app corrects by
reversal and keeps its trail (principle 5). A posted intake is never cancelled.

### UX-16 A bank layout is not saved unless a statement can be read through it
§5.4 has the accountant map the columns and saves the answer with `verified = 0`. That is
now conditional: `core.statements.parse_rows` skips a row whose date cell does not parse and
a row with no amount, so a mapping without a date column, or without one of
`amount`/`debit`/`credit`, reads zero lines. Answering «Ашиглахгүй» to every column (by
button or by Алгасах) used to save exactly that mapping, keyed on the header signature, and
ask an admin to verify it — after which every later import of that bank's export would find
it and read nothing. The last column now refuses to complete the mapping instead, in
Mongolian, with the question left standing.

## model routing (one model per purpose)

### LLM-01 A purpose's own model outranks `OPENAI_MODEL`
`resolve_model` reads the purpose's key first (`OPENAI_MODEL_CLASSIFY`), then the model
chosen for that purpose in `OPENAI_PURPOSE_MODELS`, and only then `OPENAI_MODEL`. The other
order was tempting — one key that moves everything — but the live site already sets
`OPENAI_MODEL`, so under it the founder's routing would have applied to nothing until three
keys were added, and «use Astra for chat» would have shipped as a no-op. `eval` and `other`
have no model of their own and are exactly what `OPENAI_MODEL` says, so the fallback still
means something. The cost is that pinning `OPENAI_MODEL` no longer moves extraction,
classification or questions: `api.config_check` prints each purpose's model *and* the
`source` that decided it so that is visible without reading code, and `llm_client.pin_models`
(used by the eval sweep) sets every key at once when a caller really does mean "this model,
everywhere". Reverse by swapping the two branches in `resolve_model`.

### LLM-02 Classification runs on Astra, not on Terra — the judgement call in this task
The founder said «Astra for reasoning and chat, terra for receipt parsing». Extraction is
plainly parsing: a photograph in, the printed fields out, and Terra was picked for exactly
that. Classification is not parsing. By the time it runs, the receipt is already text; it
proposes the expense account and the VAT treatment *with a reason*, against a chart of
accounts and a regime, and its answer is what the accountant taps «Зөв» on. It is the last
model step before the ledger, and principle 3 (a human taps) is a review of that proposal,
not a substitute for it: a plausible wrong account with a fluent Mongolian reason is the
failure this app can least afford. So classification is read as reasoning and routed to
`gpt-6-astra`. Against it: «receipt parsing» could fairly mean the whole receipt pipeline,
and Astra is 5× Terra's price ($10/$50 vs $2/$12 per 1M tokens in `agent.cost`) — though
classification sends text only, while extraction carries the image tokens, so the bill moves
less than the ratio suggests. If the founder meant the pipeline, one key flips it back:
`OPENAI_MODEL_CLASSIFY = gpt-5.6-terra` in Site Config, effective in about 30 seconds with
no deploy. The eval sweep now covers every routed model, so the two can be compared on the
golden set before deciding.

### LLM-03 Separate keys, not one JSON map
`OPENAI_MODEL_EXTRACT`, `OPENAI_MODEL_CLASSIFY`, `OPENAI_MODEL_QUESTION` rather than a
single `OPENAI_MODELS` JSON blob. Frappe Cloud's Site Config is the founder's only door
(no shell), it adds one key at a time as a String, and a JSON value is edited as a whole —
a typo in the blob would break every purpose at once instead of one. Separate keys also
grep, and each appears in `config.check` on its own line with `<missing>` when unset.
Purposes with no key (`eval`, `other`) are deliberate: they are not something the founder
tunes. Reverse by parsing one JSON key in `resolve_model`; `KEY_SPECS` and
`OPENAI_PURPOSE_MODELS` are the only two places that name the keys, and a test keeps them
in step.

### LLM-04 The model is chosen per call, not once per client
`get_client` returns a `PurposeRouter` holding one adapter per distinct model id and
dispatching on the `purpose` every call already carries. A client is built once and used
for several purposes — `agent.pipeline` extracts and then classifies through the same
object — so a model fixed at construction could not honour a per-purpose routing without
rewriting every caller. Routing per call keeps `pipeline`, `matching.rules` and `evals`
exactly as they were, and each adapter records its own calls, so `Nyabo LLM Call.model` is
the model that actually answered and the intent in `config_check` can be checked against
it. `get_client(..., purpose="question")` still returns a single pinned adapter for a caller
that makes only one kind of call. Reverse by giving the adapters a per-call model argument
instead, which is a change in all three adapters.

## interactive questions (§5.7 widened)

### Q-01 Conversation memory keeps the subject, never the figures
`Nyabo Chat State.payload_json["question_memory"]` carries one turn: the previous question
(capped at 160 characters) and the subject the *handler* resolved — account code, period,
supplier, date, document. It expires after twenty minutes, it is stamped with the company
and dropped on a mismatch, and `set_state` / `clear_state` take it with them, so leaving a
question for a receipt ends the exchange it belonged to. §5.7 said nothing about context;
this is the smallest thing that makes «мөн өнгөрсөн сард?» work.

Figures are deliberately not remembered and never enter the prompt. A number in the context
is a number the model can repeat as if it were this turn's answer, and a receipt approved
between two questions changes it — a bookkeeping bot that silently answers last month's
figure is worse than one that asks again. The follow-up therefore always calls a handler.
The other half of that trade is visibility: the answer card prints the subject it read
(`📒 6210 · 2026 оны 8-р сар`), which is how an accountant catches a context carried forward
wrongly instead of trusting it.

### Q-02 A number the model wrote and no handler returned never reaches the user
`questions.unverified_numbers` compares every number in the model's sentence against the
figures the handlers *computed*, the question and the clock (thousands separators
normalised, a rounded tögrög figure and a month written out of an ISO period accepted). One
that matches nothing replaces the whole sentence with the last handler's own Mongolian text
— or, when there is none, with `MSG_QUESTION_CANNOT` — and writes a
`question_number_unverified` Nyabo Event.

What counts as computed is the narrow part, and it took three passes to get right. Each
books handler returns `computed_numbers` (`questions.COMPUTED_NUMBERS_FIELD`): the amounts
and counts it worked out, the posting dates, voucher names, account and supplier name the
ledger gave back, and the month and day of the coordinate it read. Nothing else — and in
particular not a result's rendered `text`, which is where two leaks lived: `answer_faq`
returns product prose quoting worked examples («85 000₮-ийн шатахууны и-баримт»), and every
not-found answer renders the model's own argument (`SUPPLIER_NOT_FOUND_ANSWER.format(...)`),
so a figure the model invented came home through the sentence saying the books never found
it. A rendered string is not a computation, whoever wrote it. The year of a period is not
vouched for either: the read runs for whatever month it is given, so the year comes from the
clock (`_clock_years`) and a model cannot ask about «9999 оны 12-р сар» to license «9 999₮».
The stricter set is walked against all ten query kinds in the flow tests, because the way
this fails is not a leak but correct sentences quietly being replaced for ever.
"The model writes sentences, deterministic code writes numbers" was a rule the prompt asked
for politely; this is the same rule enforced. The shared question fixture is what proved it:
its sentence says "3 unmatched lines" against a ledger with none, and the user now reads the
handler's "0".

### Q-03 A follow-up button carries its whole query, and runs without a model
Callback data is `q:<verb>[:<arg>…]` where the verb is a three-letter query kind and the
arguments are the ones that kind reads, in `questions.QUERY_ARGS` order. The tap runs
`pipeline.books_answer` — the model's own dispatcher and pydantic validation, no LLM call —
so a button's answer is always a figure the books produced, and it arrives in one round trip
instead of two. Nothing is looked up in the chat state, so a tap still works on a card
opened tomorrow, after a deploy, with the memory long expired; `bank_candidates` may use an
index precisely because its taps follow immediately, and this one may not.

The company is *not* in the datum: callback data is attacker-chosen (TG-03), so the handler
answers about the caller's own active company and re-checks it against their `Nyabo User
Company` rows first. A datum that cannot be encoded (a supplier name past 64 bytes, or one
carrying the separator) drops that button and logs, exactly as `keyboards.settle_row` does —
losing a button is a nuisance, losing the answer is not.

### Q-04 Ten read-only query kinds, and `explain_entry` reads the proposal
§5.7 named four. Added: `account_entries` (the entries behind a spend figure — the
«Юунаас бүрдэв?» button), `supplier_total`, `vat_position`, `top_spend_accounts`,
`unmatched_lines` and `explain_entry`. All are reads and all are filtered by company, so a
document name typed into a question or arriving in callback data comes back "not found"
rather than "not permitted" when it belongs to another client (SEC-06: existence is
information too).

`supplier_total` reports purchases and payments as two figures instead of netting them:
the net answers «how much do we still owe them», which is a different question from «how
much did we buy from them», and the accountant asking the second must not be handed the
first under the same words. `explain_entry` reads the `Nyabo Proposal` (§1.4 — the record
of the decision) and answers a document Nyabo did not propose with its own figures plus a
plain "there is no Nyabo explanation", because writing one after the fact is what principle
4 forbids.

### Q-05 The question prompt is v2, and the widening is why
`question.v2.md` describes the ten kinds, adds the `{{MEMORY}}` slot, and says three things
the model would otherwise get wrong: the previous turn is for resolving what a follow-up
refers to and carries no figures; a figure it did not receive from a tool is removed before
the user sees it; and it must not list next steps in prose, because the buttons under the
answer already are that list. `tests/unit/test_agent_prompts.py` now pins a version per
prompt instead of asserting 1 for all of them, so a bump has to be deliberate.
