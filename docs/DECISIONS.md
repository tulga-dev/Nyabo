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
