# Decisions

Judgement calls made while building against `docs/ARCHITECTURE.md`. One entry per call:
what was decided, why, and what it would take to reverse it. Newest at the bottom of each
section. Agents append to their own section; the integrator merges.

## core + rules + seed (stage 1)

### D-001 Money is `Decimal` quantised to 0.01 with ROUND_HALF_UP
`money.quantize`, `vat_from_gross`, `vat_from_net` round half up, not banker's rounding.
Accountants expect 0.005 → 0.01; Python's default `ROUND_HALF_EVEN` would make a receipt
VAT differ from the printed one by a tögrög often enough to trip `vat_consistent`.
`parse_mnt` accepts spaces (including thin/no-break), commas, `₮`/`MNT`/`төг`, parentheses,
leading, unicode and trailing minus. When both `,` and `.` occur, the last one is the
decimal separator; a lone comma is a thousands separator only when every group after it has
three digits. Reverse by changing the two constants in `money.py`.

### D-002 VAT consistency tolerance is 1₮
Receipts round per line, so the total VAT may differ from `gross × r / (1 + r)` by up to a
tögrög. More than that means a non-VAT seller, another rate, or a bad extraction, and the
proposal is held for the accountant (`MSG_VAT_MATH_INCONSISTENT`). `validate_entry` and
`vat_consistent` take `tolerance` so the pipeline can widen it per company if real receipts
show larger drift.

### D-003 Tax-parameter lookups never fall back
`resolve_parameter` raises `MissingRuleError` (no row on the date), `AmbiguousRuleError`
(two rows) or `PendingRuleError` (row has `status: pending` or `value: null`). A pending row
with a null value is treated as pending even if its status says active, because a null can
only mean "not encoded". The alternative — using the last known value — is exactly how a
2026 threshold ends up on 2027 books. Every error carries a Mongolian `message_mn`.

### D-004 Regime history: latest start wins on overlap
`regime_on` refuses a date with no regime row (onboarding not done) but tolerates
overlapping rows by taking the one that started last, so a correction row added later
takes precedence; `seed_check` and the DocType validation report overlaps separately.
Only `rules_engine.regime_on` (core) and `rules.regime` (Frappe side) know regime names.

### D-005 Patterns key on two axes: VAT status and CIT regime
Reviewer verdict on the first draft: the sale/purchase patterns were keyed on the
`simplified_1pct` profile, which silently left a non-VAT company on regular CIT (or a
voluntary VAT registrant) without a pattern. `applies_to_vat` (`any | vat_payer | non_vat`)
and `applies_to_cit` (`any | regular | simplified_1pct`) are separate; `RegimeContext`
still comes from one company-level regime today, so `vat_status_of`/`cit_regime_of` derive
both axes from it. When the company model gains separate `vat_registered` and `cit_regime`
fields, only those two helpers change.

### D-006 `instantiate` decides the ERPNext document kind
A Purchase Invoice is produced only when the pattern lists it and the VAT is `withheld`
(ARCHITECTURE §5.3 step 6); every other purchase is a Journal Entry (gross to expense). The
caller may override `document_kind`. An unverified pattern always appends
`mn.WARN_UNVERIFIED_RULE` to the entry's warnings, so the card shows it even before
`rules.guard` refuses the posting.

### D-007 Optional lines vanish when their amount is missing or zero
The VAT line of a receipt from a non-VAT seller, the input-VAT line of `vat_settle` when
there is nothing to offset. A mandatory line without an amount raises
`MissingAmountError` rather than posting a zero line, because `validate_entry` would refuse
the zero line anyway and the message should name the missing amount kind.

### D-008 Statement layouts: never guess a bank's columns in the seed
The five bank layouts ship as placeholders with an empty `header_signature` and empty
`column_map`, `verified: false`. No sample export was available, and a wrong column map
silently swaps debits and credits. Detection order: specific layouts by signature (more
headers first), then the `generic_mn` keyword guess, which returns a concrete `LayoutSpec`
with `verified=False` so the bot asks the accountant to confirm the mapping and the admin
to verify (ARCHITECTURE §5.4). `seed_check` refuses a seed layout that asserts columns.

### D-009 Statement rows: signed `amount`, inflow positive, both amount styles
`BankLine.amount` is always signed (credit − debit) so matching and transfer pairing do
not care whether the export had one signed column or two. Debit/credit cells are taken as
absolute values because some exports print outflows as negatives in the debit column.
Rows without a parseable date, blank rows, and opening/closing/total rows (marker text and
no amount) are skipped rather than failing the import. Dates are parsed only with the
layout's listed formats — no dateutil guessing, so `03.04.2026` cannot flip day and month
between banks. `row_hash` = sha256 of date, amount, narrative, reference and row index: the
idempotency key for `Bank Transaction` creation.

### D-010 Matching requires a name or reference, not just amount and date
ARCHITECTURE §5.4: exact amount + date within 3 days + name similarity ≥ 0.8. The first
draft let an exact amount on the same day reach the 0.8 threshold on its own; that is a
false-match risk on round amounts. Score is now base 0.50 (exact amount within 1₮ and
date within 3 days) + 0.20 × date score (1.0 at 0–1 days, 0.5 at 2–3) + 0.30 × name
similarity when ≥ 0.8, or the full 0.30 when the voucher reference appears in the line.
A same-day exact amount with an unknown party scores 0.70 and goes to the accountant
(`MATCH_REASON_LOW_SCORE`). Two candidates with the same top score leave the line unmatched
(`MATCH_REASON_AMBIGUOUS`). Name similarity is a token-set ratio on difflib after dropping
legal forms (ХХК, LLC, …); no third-party fuzzy library.

### D-011 Own-account transfers match contiguous digit groups only
`is_own_transfer` compares each digit group in the narrative with the company's account
numbers (≥ 6 digits); it does not join all digits of the text, so a date next to an amount
cannot spell an account number. `pair_transfers` pairs equal-and-opposite lines on the same
day, each line used once, and when account numbers are known both narratives must mention
one, so a customer receipt equal to a supplier payment is not paired.

### D-012 Seed verification policy
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

### D-013 `code_roles.json` may leave V1 roles null, listed explicitly
The 40-leaf V1 draft has no SI payable, PIT payable, prepaid-expense or customer-advance
account. Rather than mapping those roles to a neighbouring account (wrong books) or
dropping them from `required_roles` (wrong for v0.3), the file lists the permitted nulls
under `null_allowed.v1`; `seed_check` refuses any other null and any null in `v03`. A null
role makes the Frappe-side resolver refuse the pattern line and mark the proposal
`needs_accountant`.

### D-014 Goods for resale are class 15, raw materials class 14
Reviewer: the trading SME (core market) keeps goods in class 15 per reference §2, and
`cogs_on_sale` credits 15; `purchase_inventory_*` therefore debit 15 (`inventory_goods`)
with class 14 (`inventory_materials`) as an alternative. Both map to V1 1410.

### D-015 `Nyabo Posting Pattern Line` has no `role`, `code`, `v1_code_hint`, `class_assumed` columns
The DocType child table (scripts/doctype_specs.py) carries `side, account_class,
class_name_mn, sub_account_mn, amount_kind, optional, alternatives_json`. The core
`PatternLine` reads the extra seed keys when present and works without them; until the
integrator adds columns, `rules.seed.sync` should serialise `role`, `v1_code_hint`,
`v1_code_range` and `class_assumed` into `alternatives_json` alongside the alternatives or
into the pattern's `notes`. Integration request filed in the stage-1 report.

### D-016 Test data, not fixtures files
Core tests build rows inline (statement rows, receipts, candidates) instead of reading
xlsx fixtures, so a failure shows the input next to the assertion and no binary files
enter the repo. Real bank exports, once obtained, go under `tests/fixtures/statements/`
with the layout they verify.

## integration (stage 1 → stage 2)

### D-017 One company-level regime for the MVP, two derived axes
The founder's onboarding asks one question ("НӨАТ төлөгч үү?"). `Nyabo Company Settings.regimes`
therefore stores `vat_payer` or `simplified_1pct`; `RegimeContext` derives `is_vat_payer` and the
CIT axis from it. A non-VAT company on regular CIT is not representable yet; when such a client
appears, add `cit_regime` to the settings and to `regime_on` (D-005 keeps the pattern axes
separate, so no pattern changes are needed).

### D-018 Matching threshold stays 0.8 with name-or-reference required
D-010 stands. If real statements (Phase 3 checkpoint) show narratives without counterparty
names pushing auto-match below 80%, the fix is a per-company threshold on Nyabo Company
Settings, not a weaker default.

### D-019 v0.3 is the production chart scheme; v1 stays for the test company
`code_roles.json` nulls under `v1` (D-013) are accepted: the v1 draft is only used by the
Phase 0 test company. New companies are provisioned with `chart_scheme = v03` unless the
accountant supplies a CSV chart.

### D-020 Pattern line columns added to the DocType
`role`, `v1_code_hint`, `v1_code_range`, `class_assumed` on Nyabo Posting Pattern Line and
`family`, `reference_bullet`, `citation_instrument_full` on Nyabo Posting Pattern were added
(supersedes D-015). `rules.seed.sync` writes them directly.

### D-021 Placeholders keep hooks importable during parallel builds
`nyabo_mn/compliance/{hooks,events,period}.py`, `evals/corrections_job.py`, `agent/few_shot.py`
and `telegram/state.py` exist as no-op placeholders named in hooks.py, so every stage-2 worktree
imports cleanly; the owning agents replace them. A placeholder that survives to a release is a
bug; `compliance.readiness` must report it.
## rules (Frappe side) + setup (stage 2)

### D-017 A code that exists in the installed chart is never treated as an alias
V1 and v0.3 reuse numbers with different meanings (V1 `6110` is salaries, v0.3 `6110` is
the stock adjustment). `rules.aliases.resolve_code` therefore checks the company's chart
first and only consults `Nyabo Account Alias` for codes the chart does not have; an alias
hop stops as soon as its target is a chart account, so `7003 -> 5101` on an accountant's
chart is not re-read as the v0.3 `5101` and hopped again. Roles resolve straight through
`code_roles.json` for v1/v0.3; only the accountant scheme hops through the `mof` aliases
(v0.3 template code -> accountant code) that CSV import creates from name matches.

### D-018 `provision_company` defaults to the V1 chart until the integrator flips it
`chart_scheme="v1"` keeps Phase 0 behaviour, the README instructions and the shared
`company` fixture (58 accounts, code 6210) identical while the other stage-2 modules are
built against them. `COMPANY_DEFAULTS_BY_CODE` is now derived from `code_roles.json`
(`company_defaults_by_code("v1")`) and pinned by a test to the Phase 0 literal table.
Switching the default to v0.3 is one constant (`DEFAULT_SCHEME`) plus that test.

### D-019 Tax parameters fall back to the seed *file* (not to another period) when the DocType is empty
A site whose install hook has not run yet has no `Nyabo Tax Parameter` rows;
`rules.params.load_rows` then reads `seed/tax_parameters.json` and logs
`rules.params.seed_fallback`. The data is identical and every row is unverified, so the
guard still refuses real postings; provisioning needs `vat.rate` for the templates and
must not hard-code 10%. The engine's date rules (D-003) are unchanged: no period fallback.

### D-020 Opening stock reconciliation uses the temporary-opening account
`stock_reconciliation.py` (version-16) refuses a Profit and Loss difference account on an
"Opening Stock" reconciliation, so `inventory_intake.post_intake` sets `expense_account`
to the `temporary_opening` role (`Temporary` account type) rather than ERPNext's default
`stock_adjustment_account`. Without perpetual inventory the opening entry is a submitted
Journal Entry Дт `inventory_goods` — Кт `temporary_opening` carrying `nyabo_explanation`
and `nyabo_primary_document_ref = <intake name>` so the document-required hook passes.

### D-021 Bank sub-accounts: next free sub-code under the bank role's parent group
The scheme's `bank` role is a leaf (1101 / 1120), so the per-bank accounts sit next to it
under its parent group ("11 Банкинд байгаа мөнгө" on v0.3, "1100 Мөнгөн хөрөнгө" on V1)
with the next free code of that prefix (1103, 1104 / 1121, 1122). The leaf stays the
Company default bank account; per-bank balances come from the sub-accounts and the ERPNext
`Bank Account` rows that link to them. Names are "<Bank MN> <currency> <last 4 digits>".
## agent pipeline + posting + ebarimt (stage 2)

### D-017 The pipeline bridges to `nyabo_mn.rules` and falls back to the core engine on the same rows
`nyabo_mn.rules` (regime, patterns, guard) was not in the tree when the pipeline was
written. `agent.pipeline.regime_context` uses `rules.regime.posting_context` and
`agent.pipeline.require_verified` uses `rules.guard.require_verified` / `UnverifiedRuleError`
when they are importable (the names ARCHITECTURE §1 fixes); otherwise the same DocType
rows (`Nyabo Company Settings.regimes`, `Nyabo Posting Pattern`, `Nyabo Tax Parameter`,
seed JSON when a table is empty) are fed to `core.rules_engine`. There is no second rule
set to drift. Reverse by deleting the fallback branches once the rules package lands.

### D-018 VAT treatment is decided by code, the model only suggests
`decide_vat_treatment`: a non-VAT company never withholds; no printed VAT means nothing
to withhold; a seller the registry marks as non-VAT-payer keeps the printed VAT in the
expense with `WARN_SELLER_NOT_VAT_PAYER`; a VAT payer with printed VAT from a VAT-payer
seller withholds even when the model said `in_expense`, because the non-deductible
categories are a pending 2027 parameter (`vat.input_deduction_categories`), not a model
judgement. Only `exempt` / `zero` survive from the model.

### D-019 A cash receipt credits cash; card / QPay / transfer keep the payable
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

### D-020 The classified account replaces the pattern's primary debit line
A pattern's first debit line carrying `net`/`gross` (the class-70 line, or the
`inventory_goods` / `fixed_asset` role) is resolved to the account the rule or the model
chose; the family (`purchase_expense` / `purchase_inventory` / `fixed_asset_acquire`) is
derived from that account's ERPNext `account_type` (`Stock`, `Fixed Asset`, `Capital Work
in Progress`), never from the model's words. Other roles resolve through
`code_roles.json` for the settings' scheme; when the settings say `v03` but the chart is
the V1 draft (provisioning today), `chart_scheme` picks the scheme whose payable role
exists in the chart rather than posting to a code the chart does not have.

### D-021 Supplier matching: identifiers first, names at 0.9 with an exact-name tie-break
`tin` / `tax_id` / `register_no` decide before names. The token-set ratio scores a subset
("Петровис" vs "Петровис Ойл ХХК") as 1.0, so ties are broken by exact normalised
equality and then the plain character ratio. New suppliers carry
`nyabo_pending_confirmation = 1` and the registry answer (`ebarimt_vat_payer`,
`ebarimt_checked_at`, 30-day cache) when the seller was found.

### D-022 Learned rules key on the supplier's register number, then its name, then the description
Two `Nyabo Correction(field=account_code)` rows agreeing on the target for the same
supplier create one `Nyabo Rule(source=learned, status=pending_confirmation)` listing the
corrections; an existing active/pending rule for the same key blocks duplicates. A pending
rule never matches (`match_rule` reads `status = active` only) until `confirm_rule`.

### D-023 LLM call rows are written after the proposal exists, with its name
`Nyabo LLM Call` needs the proposal link, which does not exist while the model runs, so
the pipeline buffers `CallRecord`s and flushes them with the proposal name (or without
one when the pipeline fails). An injected client without a recorder (tests, simulator)
gets the pipeline's recorder, so "every call writes" holds there too.

### D-024 ebarimt: registry only, receipt verification "unsupported", POS SDK refuses to start
No buyer-side verification endpoint exists (ARCHITECTURE §2), so every provider answers
`ReceiptVerification(status="unsupported", reason=VERIFICATION_RECEIPT_UNCHECKED)` and
the card never shows `ebarimt ✓`. `RegistryProvider` treats any non-200, non-JSON or
off-shape body as "not found" and never raises into the pipeline. `PosSdkProvider` raises
`NotConfigured` at construction: PosAPI 3.0 is merchant-side and needs a local service in
Mongolia. `qr.decode` tries pyzbar then zxing-cpp and logs `qr_decoder_missing` once.
## compliance + reports (stage 2)

### D-017 Retention years are a tax parameter, read from the table or the seed
`compliance.hooks.retention_years()` resolves `retention.years` (Law on Accounting art.
11.1, the one row shipped `verified: true`) through `core.rules_engine.resolve_parameter`
on the Nyabo Tax Parameter table and falls back to `seed/tax_parameters.json` only while
the table has no row for the key, so a document received before the first seed sync still
gets a date. No constant `10` exists in the code; reverse by seeding another row.

### D-018 The no-edit guard compares field by field, system code may opt out
`guard_no_edit_after_submit` diffs `get_doc_before_save()` against the document (child
tables row by row) and lets only `nyabo_*` fields and `remarks` change. ERPNext saves
submitted documents itself in a few flows (hold/release, clearance); those go through
`db_set` today, but a future flow that calls `save()` can set
`frappe.flags.nyabo_allow_submit_edit`. The Nyabo audit fields still need
`allow_on_submit = 1` in `setup/custom_fields.py` for Frappe's own check to let them
through — integration request filed.

### D-019 A period locked through Nyabo cannot be deleted; reopen is `disabled = 1`
The lock/reopen events point at the Accounting Period with a Dynamic Link, which makes
Frappe's link check refuse a delete anyway; `log_period_delete` turns that into a
Mongolian refusal before the misleading "deleted" event would be written. Manual desk
periods keep the name in the event payload instead of a link so they stay deletable
(and logged). Reopening is ERPNext's `disabled = 1`, never a delete.

### D-020 Reversal helpers run as the session user; the approver is a field
`make_reverse_journal_entry` / `make_debit_note` check read permission on the source
under the current session, then the reversal is inserted with `ignore_permissions`. The
Telegram approver is recorded in `nyabo_approved_by`, Nyabo Correction and the event;
bot jobs therefore run under a service session that can read the ledger (Administrator
or an Accounts User), not under the approver's login.

### D-021 Report accounts come from roles, and the scheme is checked against the chart
`reports.accounts` maps role -> code through `seed/code_roles.json` for the company's
`chart_scheme`, then to the Account by `account_number`. The settings field defaults to
v0.3 while Phase-0 companies run the V1 chart, so the configured scheme is trusted only
when its cash-role code exists in the chart; otherwise v1 then v03 are tried. The
`accountant` scheme goes through Nyabo Account Alias rows. When `nyabo_mn.rules.aliases`
lands, `role_account` delegates to it (signatures unchanged).

### D-022 Simplified 1% summary refuses an unverified rate unless simulated
`simplified_summary.compute` resolves `simplified.rate` on the quarter's last day and
raises `UnverifiedRuleError` when the row is unverified, exactly like the posting guard,
because the number goes on a tax return. `simulation=True` (the report's Simulation
filter, tests, the simulator) shows the figure labelled `LBL_SIMULATION`. The error class
is imported from `nyabo_mn.rules.guard` when that package exists (`reports.rules_bridge`).

### D-023 Financial report templates: two shipped, two not
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

### D-024 Print-format labels come through a whitelisted call, not literal Cyrillic
Print formats are Jinja files that cannot import `i18n/mn.py`. Frappe's print Jinja
environment exposes `frappe.call` (safe_exec `get_safe_globals`), so every template
starts with `{% set L = frappe.call("nyabo_mn.reports.labels.print_labels") %}`. A
`jinja` hook method would be cleaner; requested from the integrator.

### D-025 Mongolbank fetch is off by default and undocumented
The rate endpoint (`POST /en/currency-rates/data?startDate&endDate`) is the website's
internal XHR, not a documented API. `fx_rates.fetch_mongolbank` exists behind the site
config flag `MONGOLBANK_FETCH_ENABLED`, is marked UNVERIFIED and is never called from
tests; `import_csv` is the supported path. Rows land in ERPNext's Currency Exchange table
and the pipeline reads them through `get_exchange_rate`.
# Decisions

Judgement calls made while building against `docs/ARCHITECTURE.md`. One entry per call:
what was decided, why, and what it would take to reverse it. Newest at the bottom of each
section. Agents append to their own section; the integrator merges.

## parsers + matching (stage 2)

### D-017 Candidates come from the GL, not from each DocType's amount fields
`matching.match.candidates_for` reads GL Entry rows on the bank GL account (submitted
Purchase Invoice with `is_paid`, Sales Invoice POS payments, Journal Entry, Payment Entry,
no `clearance_date`, allocation already made by other Bank Transactions subtracted) and
hands `core.matching.pick` a signed movement per voucher. That is the same row ERPNext's
`allocate_payment_entries` looks at (`get_related_bank_gl_entries`), so a match the core
accepts can always be allocated; an unpaid invoice (payable only) is never a candidate,
which is also what ERPNext's reconciliation tool queries. Direction is enforced: a
withdrawal only sees outflow vouchers. Reverse by switching to per-DocType queries.

### D-018 Bank Transactions are inserted and submitted; reconciliation mirrors the tool
ERPNext's Bank Statement Import submits what it creates (`submit_after_import` defaults to
1, hidden), and the reconciliation queries filter `docstatus = 1`, so `bank_import` does the
same. `match.reconcile` runs exactly the `reconcile_vouchers` sequence of
`bank_reconciliation_tool.py` (version-16): `add_payment_entries` →
`validate_duplicate_references` → `allocate_payment_entries` → `update_allocated_amount` →
`set_status` → `save`, with vouchers shaped `{payment_doctype, payment_name, amount}`.

### D-019 Two idempotency keys per statement row
The core `row_hash` (includes the row index) goes into `Bank Transaction.transaction_id`;
a second fingerprint (bank account + date + deposit + withdrawal + normalised narrative)
catches the same line re-exported at another row position (next month's overlapping
statement). Either hit counts as `dup`. The import writes one `statement_imported` Nyabo
Event with the created names, all row hashes and the closing balance column, which is
what `/данс` reports as the statement balance.

### D-020 The account number is only searched in the title block
`resolve_bank_row` matches a configured account number only in rows above the detected
header. A transfer narrative in the data rows names the *other* account and, before this
rule, redirected a whole TDB statement into the Khan Bank account.

### D-021 Chart scheme is probed, not trusted
`Nyabo Company Settings.chart_scheme` defaults to v0.3 while provisioning still installs
the V1 tree, so `matching.rules.chart_scheme` checks that the scheme's `bank` and
`receivable` role codes exist in the company's accounts before using its role table, and
falls through to the other scheme otherwise. Codes are then resolved with
`setup.chart_db.account_for_code`; the alias resolver in `nyabo_mn.rules` is not in this
worktree (integration request filed).

### D-022 Unmatched inflows are proposed to the receivable role, outflows are classified
Fee lines follow the company's `bank_fee` Nyabo Rule (seed row fallback). Other outflows
are classified by the model (`agent.classify`, mock under `frappe.flags.nyabo_simulation`),
inflows are proposed as Дт bank / Кт receivable with `needs_accountant = 1` because the
classification prompt is receipt-shaped. Every bank-line proposal cites an unverified
pattern today, so all carry `WARN_UNVERIFIED_RULE` and need the accountant; the two
pattern ids without a seed row (`bank_line_expense`, `bank_transfer_internal`) leave
`posting_pattern` empty until the seed gains them.

### D-023 Synthetic statement fixtures are committed, clearly labelled
Unlike D-016, the import tests need real file containers (xlsx zip, cp1251 bytes), so
`tests/fixtures/statements/` holds files generated by `make_fixtures.py` from inline data;
the tests import the builders, never the files, so a stale file cannot change a result.
The README states they are scaffolds, not claims about any bank's format.

## integration (stage 2 seams: rules + compliance + reports)

### D-024 The reports side reads rules through the rules package, no second reader
`reports.rules_bridge` now delegates to `rules.params.get` / `rules.guard.require_verified`
(same `UnverifiedRuleError`), `reports.accounts.role_code` to `rules.aliases.role_code` +
`alias_target` (alias scheme `mof` for the accountant's chart, as `rules.aliases` defines
it), and `reports.month_end.regime_history` to `rules.regime.history`. The report-side
signatures (`parameter_on` throws Mongolian, `require_verified(row, simulation=...)`,
`role_account`) and the chart probe of D-021 (reports) stay. Reverse by re-inlining the
readers, which is how the two sides drifted in the first place.

### D-025 Verified seed rows pass the guard, also from the seed-file fallback
After the legal-citation pass 46 tax parameters and 28 patterns ship `verified: true` with
their quote; `rules.seed.sync` writes `citation.{section,quote,url}` to `citation_*` and
the tax-parameter quote (`quote_mn`, else the `«…» —` prefix of `note`) to `quote_mn`.
D-019 (rules) said "every seed row is unverified, so the fallback is safe"; the fallback
now carries the same human verification the synced rows would, which is the point of
verifying the file. Tests that need an unverified rule pick one that ships unverified
(`si.employee_rate`, `bank_fee_expense`, `payable_pay`) or insert their own row.

## integration review (post-merge)

### D-I01 The simulator and the golden set must mirror `agent.pipeline`, not their own rules
`evals.harness` swapped the credit line to the bank for card, QPay and transfer receipts,
while `agent.pipeline` follows the pipeline decision "a Purchase Invoice always credits the
payable; a Journal Entry credits cash only for a cash receipt". The simulator therefore
printed an entry the system would never post, and the golden set scored that entry as
correct. `_conditions` now returns only `paid_in_cash`, the generator's `expected_lines`
uses the same rule, and `test_both_regimes_credit_the_payable_like_the_pipeline` pins it.
Whenever the two disagree, the pipeline is the authority: it is what reaches the ledger.

### D-I02 Decision identifiers are unique per section, not per agent
Seven agents each numbered their decisions from D-017, so the log holds five different
D-017s. Section headings disambiguate them for now; a citation in code or on a card must
name the section as well as the number until they are renumbered.
# Decisions

Judgement calls made while building against `docs/ARCHITECTURE.md`. One entry per call:
what was decided, why, and what it would take to reverse it. Newest at the bottom of each
section. Agents append to their own section; the integrator merges.

## core + rules + seed (stage 1)

### D-001 Money is `Decimal` quantised to 0.01 with ROUND_HALF_UP
`money.quantize`, `vat_from_gross`, `vat_from_net` round half up, not banker's rounding.
Accountants expect 0.005 → 0.01; Python's default `ROUND_HALF_EVEN` would make a receipt
VAT differ from the printed one by a tögrög often enough to trip `vat_consistent`.
`parse_mnt` accepts spaces (including thin/no-break), commas, `₮`/`MNT`/`төг`, parentheses,
leading, unicode and trailing minus. When both `,` and `.` occur, the last one is the
decimal separator; a lone comma is a thousands separator only when every group after it has
three digits. Reverse by changing the two constants in `money.py`.

### D-002 VAT consistency tolerance is 1₮
Receipts round per line, so the total VAT may differ from `gross × r / (1 + r)` by up to a
tögrög. More than that means a non-VAT seller, another rate, or a bad extraction, and the
proposal is held for the accountant (`MSG_VAT_MATH_INCONSISTENT`). `validate_entry` and
`vat_consistent` take `tolerance` so the pipeline can widen it per company if real receipts
show larger drift.

### D-003 Tax-parameter lookups never fall back
`resolve_parameter` raises `MissingRuleError` (no row on the date), `AmbiguousRuleError`
(two rows) or `PendingRuleError` (row has `status: pending` or `value: null`). A pending row
with a null value is treated as pending even if its status says active, because a null can
only mean "not encoded". The alternative — using the last known value — is exactly how a
2026 threshold ends up on 2027 books. Every error carries a Mongolian `message_mn`.

### D-004 Regime history: latest start wins on overlap
`regime_on` refuses a date with no regime row (onboarding not done) but tolerates
overlapping rows by taking the one that started last, so a correction row added later
takes precedence; `seed_check` and the DocType validation report overlaps separately.
Only `rules_engine.regime_on` (core) and `rules.regime` (Frappe side) know regime names.

### D-005 Patterns key on two axes: VAT status and CIT regime
Reviewer verdict on the first draft: the sale/purchase patterns were keyed on the
`simplified_1pct` profile, which silently left a non-VAT company on regular CIT (or a
voluntary VAT registrant) without a pattern. `applies_to_vat` (`any | vat_payer | non_vat`)
and `applies_to_cit` (`any | regular | simplified_1pct`) are separate; `RegimeContext`
still comes from one company-level regime today, so `vat_status_of`/`cit_regime_of` derive
both axes from it. When the company model gains separate `vat_registered` and `cit_regime`
fields, only those two helpers change.

### D-006 `instantiate` decides the ERPNext document kind
A Purchase Invoice is produced only when the pattern lists it and the VAT is `withheld`
(ARCHITECTURE §5.3 step 6); every other purchase is a Journal Entry (gross to expense). The
caller may override `document_kind`. An unverified pattern always appends
`mn.WARN_UNVERIFIED_RULE` to the entry's warnings, so the card shows it even before
`rules.guard` refuses the posting.

### D-007 Optional lines vanish when their amount is missing or zero
The VAT line of a receipt from a non-VAT seller, the input-VAT line of `vat_settle` when
there is nothing to offset. A mandatory line without an amount raises
`MissingAmountError` rather than posting a zero line, because `validate_entry` would refuse
the zero line anyway and the message should name the missing amount kind.

### D-008 Statement layouts: never guess a bank's columns in the seed
The five bank layouts ship as placeholders with an empty `header_signature` and empty
`column_map`, `verified: false`. No sample export was available, and a wrong column map
silently swaps debits and credits. Detection order: specific layouts by signature (more
headers first), then the `generic_mn` keyword guess, which returns a concrete `LayoutSpec`
with `verified=False` so the bot asks the accountant to confirm the mapping and the admin
to verify (ARCHITECTURE §5.4). `seed_check` refuses a seed layout that asserts columns.

### D-009 Statement rows: signed `amount`, inflow positive, both amount styles
`BankLine.amount` is always signed (credit − debit) so matching and transfer pairing do
not care whether the export had one signed column or two. Debit/credit cells are taken as
absolute values because some exports print outflows as negatives in the debit column.
Rows without a parseable date, blank rows, and opening/closing/total rows (marker text and
no amount) are skipped rather than failing the import. Dates are parsed only with the
layout's listed formats — no dateutil guessing, so `03.04.2026` cannot flip day and month
between banks. `row_hash` = sha256 of date, amount, narrative, reference and row index: the
idempotency key for `Bank Transaction` creation.

### D-010 Matching requires a name or reference, not just amount and date
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

### D-011 Own-account transfers match contiguous digit groups only
`is_own_transfer` compares each digit group in the narrative with the company's account
numbers (≥ 6 digits); it does not join all digits of the text, so a date next to an amount
cannot spell an account number. `pair_transfers` pairs equal-and-opposite lines on the same
day, each line used once, and when account numbers are known both narratives must mention
one, so a customer receipt equal to a supplier payment is not paired.

### D-012 Seed verification policy
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

### D-013 `code_roles.json` may leave V1 roles null, listed explicitly
The 40-leaf V1 draft has no SI payable, PIT payable, prepaid-expense or customer-advance
account. Rather than mapping those roles to a neighbouring account (wrong books) or
dropping them from `required_roles` (wrong for v0.3), the file lists the permitted nulls
under `null_allowed.v1`; `seed_check` refuses any other null and any null in `v03`. A null
role makes the Frappe-side resolver refuse the pattern line and mark the proposal
`needs_accountant`.

### D-014 Goods for resale are class 15, raw materials class 14
Reviewer: the trading SME (core market) keeps goods in class 15 per reference §2, and
`cogs_on_sale` credits 15; `purchase_inventory_*` therefore debit 15 (`inventory_goods`)
with class 14 (`inventory_materials`) as an alternative. Both map to V1 1410.

### D-015 `Nyabo Posting Pattern Line` has no `role`, `code`, `v1_code_hint`, `class_assumed` columns
The DocType child table (scripts/doctype_specs.py) carries `side, account_class,
class_name_mn, sub_account_mn, amount_kind, optional, alternatives_json`. The core
`PatternLine` reads the extra seed keys when present and works without them; until the
integrator adds columns, `rules.seed.sync` should serialise `role`, `v1_code_hint`,
`v1_code_range` and `class_assumed` into `alternatives_json` alongside the alternatives or
into the pattern's `notes`. Integration request filed in the stage-1 report.

### D-016 Test data, not fixtures files
Core tests build rows inline (statement rows, receipts, candidates) instead of reading
xlsx fixtures, so a failure shows the input next to the assertion and no binary files
enter the repo. Real bank exports, once obtained, go under `tests/fixtures/statements/`
with the layout they verify.

## integration (stage 1 → stage 2)

### D-017 One company-level regime for the MVP, two derived axes
The founder's onboarding asks one question ("НӨАТ төлөгч үү?"). `Nyabo Company Settings.regimes`
therefore stores `vat_payer` or `simplified_1pct`; `RegimeContext` derives `is_vat_payer` and the
CIT axis from it. A non-VAT company on regular CIT is not representable yet; when such a client
appears, add `cit_regime` to the settings and to `regime_on` (D-005 keeps the pattern axes
separate, so no pattern changes are needed).

### D-018 Matching threshold stays 0.8 with name-or-reference required
D-010 stands. If real statements (Phase 3 checkpoint) show narratives without counterparty
names pushing auto-match below 80%, the fix is a per-company threshold on Nyabo Company
Settings, not a weaker default.

### D-019 v0.3 is the production chart scheme; v1 stays for the test company
`code_roles.json` nulls under `v1` (D-013) are accepted: the v1 draft is only used by the
Phase 0 test company. New companies are provisioned with `chart_scheme = v03` unless the
accountant supplies a CSV chart.

### D-020 Pattern line columns added to the DocType
`role`, `v1_code_hint`, `v1_code_range`, `class_assumed` on Nyabo Posting Pattern Line and
`family`, `reference_bullet`, `citation_instrument_full` on Nyabo Posting Pattern were added
(supersedes D-015). `rules.seed.sync` writes them directly.

### D-021 Placeholders keep hooks importable during parallel builds
`nyabo_mn/compliance/{hooks,events,period}.py`, `evals/corrections_job.py`, `agent/few_shot.py`
and `telegram/state.py` exist as no-op placeholders named in hooks.py, so every stage-2 worktree
imports cleanly; the owning agents replace them. A placeholder that survives to a release is a
bug; `compliance.readiness` must report it.
## rules (Frappe side) + setup (stage 2)

### D-017 A code that exists in the installed chart is never treated as an alias
V1 and v0.3 reuse numbers with different meanings (V1 `6110` is salaries, v0.3 `6110` is
the stock adjustment). `rules.aliases.resolve_code` therefore checks the company's chart
first and only consults `Nyabo Account Alias` for codes the chart does not have; an alias
hop stops as soon as its target is a chart account, so `7003 -> 5101` on an accountant's
chart is not re-read as the v0.3 `5101` and hopped again. Roles resolve straight through
`code_roles.json` for v1/v0.3; only the accountant scheme hops through the `mof` aliases
(v0.3 template code -> accountant code) that CSV import creates from name matches.

### D-018 `provision_company` defaults to the V1 chart until the integrator flips it
`chart_scheme="v1"` keeps Phase 0 behaviour, the README instructions and the shared
`company` fixture (58 accounts, code 6210) identical while the other stage-2 modules are
built against them. `COMPANY_DEFAULTS_BY_CODE` is now derived from `code_roles.json`
(`company_defaults_by_code("v1")`) and pinned by a test to the Phase 0 literal table.
Switching the default to v0.3 is one constant (`DEFAULT_SCHEME`) plus that test.

### D-019 Tax parameters fall back to the seed *file* (not to another period) when the DocType is empty
A site whose install hook has not run yet has no `Nyabo Tax Parameter` rows;
`rules.params.load_rows` then reads `seed/tax_parameters.json` and logs
`rules.params.seed_fallback`. The data is identical and every row is unverified, so the
guard still refuses real postings; provisioning needs `vat.rate` for the templates and
must not hard-code 10%. The engine's date rules (D-003) are unchanged: no period fallback.

### D-020 Opening stock reconciliation uses the temporary-opening account
`stock_reconciliation.py` (version-16) refuses a Profit and Loss difference account on an
"Opening Stock" reconciliation, so `inventory_intake.post_intake` sets `expense_account`
to the `temporary_opening` role (`Temporary` account type) rather than ERPNext's default
`stock_adjustment_account`. Without perpetual inventory the opening entry is a submitted
Journal Entry Дт `inventory_goods` — Кт `temporary_opening` carrying `nyabo_explanation`
and `nyabo_primary_document_ref = <intake name>` so the document-required hook passes.

### D-021 Bank sub-accounts: next free sub-code under the bank role's parent group
The scheme's `bank` role is a leaf (1101 / 1120), so the per-bank accounts sit next to it
under its parent group ("11 Банкинд байгаа мөнгө" on v0.3, "1100 Мөнгөн хөрөнгө" on V1)
with the next free code of that prefix (1103, 1104 / 1121, 1122). The leaf stays the
Company default bank account; per-bank balances come from the sub-accounts and the ERPNext
`Bank Account` rows that link to them. Names are "<Bank MN> <currency> <last 4 digits>".
## agent pipeline + posting + ebarimt (stage 2)

### D-017 The pipeline bridges to `nyabo_mn.rules` and falls back to the core engine on the same rows
`nyabo_mn.rules` (regime, patterns, guard) was not in the tree when the pipeline was
written. `agent.pipeline.regime_context` uses `rules.regime.posting_context` and
`agent.pipeline.require_verified` uses `rules.guard.require_verified` / `UnverifiedRuleError`
when they are importable (the names ARCHITECTURE §1 fixes); otherwise the same DocType
rows (`Nyabo Company Settings.regimes`, `Nyabo Posting Pattern`, `Nyabo Tax Parameter`,
seed JSON when a table is empty) are fed to `core.rules_engine`. There is no second rule
set to drift. Reverse by deleting the fallback branches once the rules package lands.

### D-018 VAT treatment is decided by code, the model only suggests
`decide_vat_treatment`: a non-VAT company never withholds; no printed VAT means nothing
to withhold; a seller the registry marks as non-VAT-payer keeps the printed VAT in the
expense with `WARN_SELLER_NOT_VAT_PAYER`; a VAT payer with printed VAT from a VAT-payer
seller withholds even when the model said `in_expense`, because the non-deductible
categories are a pending 2027 parameter (`vat.input_deduction_categories`), not a model
judgement. Only `exempt` / `zero` survive from the model.

### D-019 Purchase Invoice always credits the payable; a Journal Entry credits cash only for cash
The bank statement flow settles the payable through ERPNext, so crediting the bank
account directly on a card/QPay/transfer receipt would double count when the statement
line arrives. Cash receipts (`payment_method == "cash"`) booked as a Journal Entry credit
the cash role instead (`make_resolver(overrides={"payable": "cash"})`).

### D-020 The classified account replaces the pattern's primary debit line
A pattern's first debit line carrying `net`/`gross` (the class-70 line, or the
`inventory_goods` / `fixed_asset` role) is resolved to the account the rule or the model
chose; the family (`purchase_expense` / `purchase_inventory` / `fixed_asset_acquire`) is
derived from that account's ERPNext `account_type` (`Stock`, `Fixed Asset`, `Capital Work
in Progress`), never from the model's words. Other roles resolve through
`code_roles.json` for the settings' scheme; when the settings say `v03` but the chart is
the V1 draft (provisioning today), `chart_scheme` picks the scheme whose payable role
exists in the chart rather than posting to a code the chart does not have.

### D-021 Supplier matching: identifiers first, names at 0.9 with an exact-name tie-break
`tin` / `tax_id` / `register_no` decide before names. The token-set ratio scores a subset
("Петровис" vs "Петровис Ойл ХХК") as 1.0, so ties are broken by exact normalised
equality and then the plain character ratio. New suppliers carry
`nyabo_pending_confirmation = 1` and the registry answer (`ebarimt_vat_payer`,
`ebarimt_checked_at`, 30-day cache) when the seller was found.

### D-022 Learned rules key on the supplier's register number, then its name, then the description
Two `Nyabo Correction(field=account_code)` rows agreeing on the target for the same
supplier create one `Nyabo Rule(source=learned, status=pending_confirmation)` listing the
corrections; an existing active/pending rule for the same key blocks duplicates. A pending
rule never matches (`match_rule` reads `status = active` only) until `confirm_rule`.

### D-023 LLM call rows are written after the proposal exists, with its name
`Nyabo LLM Call` needs the proposal link, which does not exist while the model runs, so
the pipeline buffers `CallRecord`s and flushes them with the proposal name (or without
one when the pipeline fails). An injected client without a recorder (tests, simulator)
gets the pipeline's recorder, so "every call writes" holds there too.

### D-024 ebarimt: registry only, receipt verification "unsupported", POS SDK refuses to start
No buyer-side verification endpoint exists (ARCHITECTURE §2), so every provider answers
`ReceiptVerification(status="unsupported", reason=VERIFICATION_RECEIPT_UNCHECKED)` and
the card never shows `ebarimt ✓`. `RegistryProvider` treats any non-200, non-JSON or
off-shape body as "not found" and never raises into the pipeline. `PosSdkProvider` raises
`NotConfigured` at construction: PosAPI 3.0 is merchant-side and needs a local service in
Mongolia. `qr.decode` tries pyzbar then zxing-cpp and logs `qr_decoder_missing` once.
## compliance + reports (stage 2)

### D-017 Retention years are a tax parameter, read from the table or the seed
`compliance.hooks.retention_years()` resolves `retention.years` (Law on Accounting art.
11.1, the one row shipped `verified: true`) through `core.rules_engine.resolve_parameter`
on the Nyabo Tax Parameter table and falls back to `seed/tax_parameters.json` only while
the table has no row for the key, so a document received before the first seed sync still
gets a date. No constant `10` exists in the code; reverse by seeding another row.

### D-018 The no-edit guard compares field by field, system code may opt out
`guard_no_edit_after_submit` diffs `get_doc_before_save()` against the document (child
tables row by row) and lets only `nyabo_*` fields and `remarks` change. ERPNext saves
submitted documents itself in a few flows (hold/release, clearance); those go through
`db_set` today, but a future flow that calls `save()` can set
`frappe.flags.nyabo_allow_submit_edit`. The Nyabo audit fields still need
`allow_on_submit = 1` in `setup/custom_fields.py` for Frappe's own check to let them
through — integration request filed.

### D-019 A period locked through Nyabo cannot be deleted; reopen is `disabled = 1`
The lock/reopen events point at the Accounting Period with a Dynamic Link, which makes
Frappe's link check refuse a delete anyway; `log_period_delete` turns that into a
Mongolian refusal before the misleading "deleted" event would be written. Manual desk
periods keep the name in the event payload instead of a link so they stay deletable
(and logged). Reopening is ERPNext's `disabled = 1`, never a delete.

### D-020 Reversal helpers run as the session user; the approver is a field
`make_reverse_journal_entry` / `make_debit_note` check read permission on the source
under the current session, then the reversal is inserted with `ignore_permissions`. The
Telegram approver is recorded in `nyabo_approved_by`, Nyabo Correction and the event;
bot jobs therefore run under a service session that can read the ledger (Administrator
or an Accounts User), not under the approver's login.

### D-021 Report accounts come from roles, and the scheme is checked against the chart
`reports.accounts` maps role -> code through `seed/code_roles.json` for the company's
`chart_scheme`, then to the Account by `account_number`. The settings field defaults to
v0.3 while Phase-0 companies run the V1 chart, so the configured scheme is trusted only
when its cash-role code exists in the chart; otherwise v1 then v03 are tried. The
`accountant` scheme goes through Nyabo Account Alias rows. When `nyabo_mn.rules.aliases`
lands, `role_account` delegates to it (signatures unchanged).

### D-022 Simplified 1% summary refuses an unverified rate unless simulated
`simplified_summary.compute` resolves `simplified.rate` on the quarter's last day and
raises `UnverifiedRuleError` when the row is unverified, exactly like the posting guard,
because the number goes on a tax return. `simulation=True` (the report's Simulation
filter, tests, the simulator) shows the figure labelled `LBL_SIMULATION`. The error class
is imported from `nyabo_mn.rules.guard` when that package exists (`reports.rules_bridge`).

### D-023 Financial report templates: two shipped, two not
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

### D-024 Print-format labels come through a whitelisted call, not literal Cyrillic
Print formats are Jinja files that cannot import `i18n/mn.py`. Frappe's print Jinja
environment exposes `frappe.call` (safe_exec `get_safe_globals`), so every template
starts with `{% set L = frappe.call("nyabo_mn.reports.labels.print_labels") %}`. A
`jinja` hook method would be cleaner; requested from the integrator.

### D-025 Mongolbank fetch is off by default and undocumented
The rate endpoint (`POST /en/currency-rates/data?startDate&endDate`) is the website's
internal XHR, not a documented API. `fx_rates.fetch_mongolbank` exists behind the site
config flag `MONGOLBANK_FETCH_ENABLED`, is marked UNVERIFIED and is never called from
tests; `import_csv` is the supported path. Rows land in ERPNext's Currency Exchange table
and the pipeline reads them through `get_exchange_rate`.
# Decisions

Judgement calls made while building against `docs/ARCHITECTURE.md`. One entry per call:
what was decided, why, and what it would take to reverse it. Newest at the bottom of each
section. Agents append to their own section; the integrator merges.

## parsers + matching (stage 2)

### D-017 Candidates come from the GL, not from each DocType's amount fields
`matching.match.candidates_for` reads GL Entry rows on the bank GL account (submitted
Purchase Invoice with `is_paid`, Sales Invoice POS payments, Journal Entry, Payment Entry,
no `clearance_date`, allocation already made by other Bank Transactions subtracted) and
hands `core.matching.pick` a signed movement per voucher. That is the same row ERPNext's
`allocate_payment_entries` looks at (`get_related_bank_gl_entries`), so a match the core
accepts can always be allocated; an unpaid invoice (payable only) is never a candidate,
which is also what ERPNext's reconciliation tool queries. Direction is enforced: a
withdrawal only sees outflow vouchers. Reverse by switching to per-DocType queries.

### D-018 Bank Transactions are inserted and submitted; reconciliation mirrors the tool
ERPNext's Bank Statement Import submits what it creates (`submit_after_import` defaults to
1, hidden), and the reconciliation queries filter `docstatus = 1`, so `bank_import` does the
same. `match.reconcile` runs exactly the `reconcile_vouchers` sequence of
`bank_reconciliation_tool.py` (version-16): `add_payment_entries` →
`validate_duplicate_references` → `allocate_payment_entries` → `update_allocated_amount` →
`set_status` → `save`, with vouchers shaped `{payment_doctype, payment_name, amount}`.

### D-019 Two idempotency keys per statement row
The core `row_hash` (includes the row index) goes into `Bank Transaction.transaction_id`;
a second fingerprint (bank account + date + deposit + withdrawal + normalised narrative)
catches the same line re-exported at another row position (next month's overlapping
statement). Either hit counts as `dup`. The import writes one `statement_imported` Nyabo
Event with the created names, all row hashes and the closing balance column, which is
what `/данс` reports as the statement balance.

### D-020 The account number is only searched in the title block
`resolve_bank_row` matches a configured account number only in rows above the detected
header. A transfer narrative in the data rows names the *other* account and, before this
rule, redirected a whole TDB statement into the Khan Bank account.

### D-021 Chart scheme is probed, not trusted
`Nyabo Company Settings.chart_scheme` defaults to v0.3 while provisioning still installs
the V1 tree, so `matching.rules.chart_scheme` checks that the scheme's `bank` and
`receivable` role codes exist in the company's accounts before using its role table, and
falls through to the other scheme otherwise. Codes are then resolved with
`setup.chart_db.account_for_code`; the alias resolver in `nyabo_mn.rules` is not in this
worktree (integration request filed).

### D-022 Unmatched inflows are proposed to the receivable role, outflows are classified
Fee lines follow the company's `bank_fee` Nyabo Rule (seed row fallback). Other outflows
are classified by the model (`agent.classify`, mock under `frappe.flags.nyabo_simulation`),
inflows are proposed as Дт bank / Кт receivable with `needs_accountant = 1` because the
classification prompt is receipt-shaped. Every bank-line proposal cites an unverified
pattern today, so all carry `WARN_UNVERIFIED_RULE` and need the accountant. All four ids
(`bank_fee_expense`, `receivable_collect`, `bank_line_expense`, `bank_transfer_internal`)
are seed rows with `citation.section = null` and `verified = false`: approval therefore
ends in `UnverifiedRuleError` («Дүрэм баталгаажаагүй») and an admin can clear it by
verifying the row, instead of failing with «загвар олдсонгүй» on an id that exists nowhere.

### D-023 Synthetic statement fixtures are committed, clearly labelled
Unlike D-016, the import tests need real file containers (xlsx zip, cp1251 bytes), so
`tests/fixtures/statements/` holds files generated by `make_fixtures.py` from inline data;
the tests import the builders, never the files, so a stale file cannot change a result.
The README states they are scaffolds, not claims about any bank's format.

## integration (stage 2 seams: rules + compliance + reports)

### D-024 The reports side reads rules through the rules package, no second reader
`reports.rules_bridge` now delegates to `rules.params.get` / `rules.guard.require_verified`
(same `UnverifiedRuleError`), `reports.accounts.role_code` to `rules.aliases.role_code` +
`alias_target` (alias scheme `mof` for the accountant's chart, as `rules.aliases` defines
it), and `reports.month_end.regime_history` to `rules.regime.history`. The report-side
signatures (`parameter_on` throws Mongolian, `require_verified(row, simulation=...)`,
`role_account`) and the chart probe of D-021 (reports) stay. Reverse by re-inlining the
readers, which is how the two sides drifted in the first place.

### D-025 Verified seed rows pass the guard, also from the seed-file fallback
After the legal-citation pass 46 tax parameters and 28 patterns ship `verified: true` with
their quote; `rules.seed.sync` writes `citation.{section,quote,url}` to `citation_*` and
the tax-parameter quote (`quote_mn`, else the `«…» —` prefix of `note`) to `quote_mn`.
D-019 (rules) said "every seed row is unverified, so the fallback is safe"; the fallback
now carries the same human verification the synced rows would, which is the point of
verifying the file. Tests that need an unverified rule pick one that ships unverified
(`si.employee_rate`, `bank_fee_expense`, `payable_pay`) or insert their own row.

## integration review (post-merge)

### D-I01 The simulator and the golden set must mirror `agent.pipeline`, not their own rules
`evals.harness` swapped the credit line to the bank for card, QPay and transfer receipts,
while `agent.pipeline` follows the pipeline decision "a Purchase Invoice always credits the
payable; a Journal Entry credits cash only for a cash receipt". The simulator therefore
printed an entry the system would never post, and the golden set scored that entry as
correct. `_conditions` now returns only `paid_in_cash`, the generator's `expected_lines`
uses the same rule, and `test_both_regimes_credit_the_payable_like_the_pipeline` pins it.
Whenever the two disagree, the pipeline is the authority: it is what reaches the ledger.

### D-I02 Decision identifiers are unique per section, not per agent
Seven agents each numbered their decisions from D-017, so the log holds five different
D-017s. Section headings disambiguate them for now; a citation in code or on a card must
name the section as well as the number until they are renumbered.

## review fixes (compliance + reports)

### D-R01 The 1% summary resolves the regime's conditions, not only its rate
`simplified_summary.compute` now resolves `simplified.requires_not_vat_registered`
(CIT art. 29.3.1) and `simplified.revenue_threshold` (art. 29.1) on the quarter's last day
before it computes anything, so the deliberately pending 2027 rows raise `PendingRuleError`
instead of letting the verified open-ended rate print 1% of a quarter whose regime terms
nobody knows. A company that is a VAT withholding payer on that date is refused
(`MSG_SIMPLIFIED_NOT_ELIGIBLE_VAT`). The threshold is only *raised*: art. 29.1 rests on the
confirmed prior-year return, which Nyabo does not hold, so the company's own prior-year
revenue sets `needs_accountant` and a warning line instead of deciding eligibility.

### D-R02 ERPNext's own Journal Entries carry a stamped primary document
`require_primary_document` refused every entry ERPNext generates itself (depreciation —
a daily scheduler job — asset disposal, exchange-rate revaluation, the gain/loss entry,
opening entries, reversals), which have no Nyabo Document, no reference and no attachment.
They are now stamped with `MSG_PRIMARY_DOCUMENT_SYSTEM_GENERATED` naming what produced
them rather than skipped silently, so art. 13.7's trail stays on the document.

### D-R03 The period lock reads the pattern from the entry, not only from the link
`posting_pattern` is a Link, so it stays empty for a pattern that exists only in the seed
file (a site whose rows were never synced) or was renamed. `unverified_proposals` now takes
the id from `entry_json` when the link is empty and asks `rules.guard` the same question the
posting guard asked (DocType row first, seed second); an id that resolves to nothing counts
as unverified, because refusing is the safe default.

### D-R04 A reversal is never reversed, and the refusal is Mongolian
`reversal.is_reversal` refuses a document that already carries `reversal_of`, `is_return`
or `nyabo_corrects` with `MSG_CORRECTION_IS_REVERSAL`; ERPNext refused it too, in English,
which reached the accountant as the generic "error, admin notified".

### D-R05 The month-end trial balance falls back on any report failure
The documented fallback caught `DoesNotExistError` only, while the realistic failures are
`frappe.PermissionError` (the Telegram user holds `Nyabo Accountant`, not `Accounts User`),
a disabled report (`ValidationError`) and `FiscalYearError`. `trial_balance` now logs and
falls back to the GL aggregation on any exception: `/хаалт` must not die on a report the
app does not need.

### D-R06 The readiness checklist cites no instrument it has not read
`readiness.py` claimed conformity with numbered items of "MoF Order 47/2018 annex 1", an
instrument absent from `docs/legal/` and from `docs/mn-rules-reference.md`, whose §6.1 lists
the certification procedure «Нягтлан бодох бүртгэлийн программ хангамжид хяналт тавих журам»
as still to obtain. The requirement column, the item-number map, the invented annex module
list and the order named in the report footers are gone; the table is labelled Nyabo's own
internal readiness list (`READINESS_SOURCE_PENDING`) and reports with no MoF form behind them
are footed `FORM_SOURCE_INTERNAL`. When the procedure text is fetched, the rows are mapped to
it with the verbatim quotes `docs/legal/README.md` requires.

### D-I03 Company scoping is enforced in two layers, not only in the handlers
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
