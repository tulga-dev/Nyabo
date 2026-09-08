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
