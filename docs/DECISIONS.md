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
