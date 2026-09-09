# Seed data (`nyabo_mn/nyabo/seed/`)

Rules are data with effective dates (ARCHITECTURE §1.1). Everything an accountant would
call "the rules" lives in these JSON files, is loaded into DocTypes by `rules.seed.sync()`
on install/migrate, and is read by the pure-Python engine in `nyabo_mn/core/`. Code never
hard-codes a rate, a threshold, an account name or a column index.

Check before committing a change:

```bash
python scripts/seed_check.py        # exit 1 and a list of problems when anything is off
python -m pytest -q tests/unit/test_seed_check.py tests/unit/test_seed_data.py
```

The legal source of truth is the primary text, tabulated per instrument in
`docs/legal/` (article → claim → verbatim quote → status). `docs/mn-rules-reference.md`
is the compiled overview it started from; where the two disagree the primary text wins
and the contradiction is recorded in the row's `note` and in `docs/legal/<instrument>.md`.
A value the text does not state ships as `status: pending` with `value: null`.

## Verified means

A human compared the value with the primary legal text: `source_text` names the
instrument, `article` the article, `source_url` the legalinfo.mn / parliament.mn page,
and the row carries the verbatim Mongolian sentence the value was read from — the quote
is stored in `citation.quote` for posting patterns and in `quote_mn` for tax parameters
(rows written before that key joined the schema keep it as the first element of `note`,
`«…» — remarks`; `nyabo_mn.nyabo.seed.tax_parameter_quote` reads either shape and
`rules.seed.sync` writes it to `Nyabo Tax Parameter.quote_mn`). A row is
verified only when the quoted sentence states the value exactly; derived numbers (sums of
printed rows, a percentage of another figure), figures from a draft law, single-reader
section mappings and values the text contradicts stay `false`. An admin flips `verified`
in the desk after reading the text; `rules.seed.sync` never overwrites a row an admin has
verified unless `force=True`. `rules.guard.require_verified()` refuses an unverified Tax
Parameter, Posting Pattern or Bank Layout for a real posting (tests and the simulator may
use them). `tests/unit/test_seed_citations.py` enforces the contract and cross-checks every
verified quote against `docs/legal/*.md`.

## Files

### `tax_parameters.json`

```json
{"schema_version": 1, "horizon_start": "2026-01-01", "verified_means": "...", "units": {...}, "rows": [...]}
```

One row per `(key, effective_from)`; DocType name is `{key}:{effective_from}`.

| Field | Meaning |
|---|---|
| `key` | dotted name, e.g. `vat.registration_threshold` |
| `value` | typed by `unit`; `null` only with `status: pending` |
| `unit` | `fraction` (0.10 = 10%), `MNT` (`{amount, comparator, basis}`), `years` (integer or object of integers), `schedule` (`{basis, brackets: [{up_to, rate}]}`, last `up_to` null), `rule` (object or boolean), `deadline` (`{period, due_months_after_period_end, due_day}`, null inside = not stated; optional `due_day_rule: last_day_of_month` explains a null day, optional `applies_to` names the taxpayer class) |
| `effective_from` / `effective_to` | ISO dates; `effective_to` null = open-ended. A row starting on `horizon_start` was in force before Nyabo's coverage; its legal in-force date is not asserted. `tax_debt.enforcement_split` starts on the package's adoption date (2026-06-26, quoted). |
| `status` | `active` (usable) or `pending` (known change, text not encoded: `resolve_parameter` raises `PendingRuleError`) |
| `verified` | see above |
| `source_text`, `source_url`, `article`, `quote_mn`, `note` | provenance; `quote_mn` (optional key, never an empty string) is the verbatim sentence the value was read from — required on a verified row, where it may still sit at the start of `note` as `«…» — ` instead; the rest of `note` explains derivations, contradictions and every UNCONFIRMED item |

Keys worth knowing: social insurance is per fund (`si.employee.pension`, `si.employer.benefit`,
`si.accident_tiers` …, General Law on Social Insurance art. 18.1) and the totals
`si.employee_rate` / `si.employer_rate` are derived and unverified; health insurance is
`emd.*` (pending, another law); CIT filing is split into `filing.cit_quarterly` (≥ 6bn taxable
income), `filing.cit_half_year`, `filing.cit_annual`, `filing.cit_payment_monthly`; PIT into
`filing.pit_withholding` (quarterly return), `filing.pit_withholding_payment` (monthly),
`filing.pit_annual`. The 2027 simplified-regime rows are pending because the 400M/quarterly
change exists only in a Government bill (docs/legal/cit_law.md).

Engine behaviour (`nyabo_mn.core.rules_engine.resolve_parameter`): the single row of the
key covering the transaction date is returned; no row raises `MissingRuleError`, two rows
raise `AmbiguousRuleError`, a pending row raises `PendingRuleError`. There is never a
fallback to the previous period — that is how a 2027 threshold ends up on 2026 books.

Rates are fractions. ERPNext tax templates want percent; `setup/taxes.py` converts at
that boundary.

### `posting_patterns.json`

`{"schema_version", "reference", "conventions", "rows"}`. One row per entry shape from
reference §3 (Order 116/2000 posting instruction). Fields mirror `Nyabo Posting Pattern`:

- `pattern_id`, `name_mn`, `family` (what `select_pattern(hints={"family": ...})` filters on),
  `document_types` (ERPNext DocTypes the pattern may produce or explain).
- `applies_to_vat` (`any | vat_payer | non_vat`) and `applies_to_cit`
  (`any | regular | simplified_1pct`): two axes on purpose. VAT status decides the input-VAT
  split; only the `income_tax` family keys on the CIT regime. The most specific matching
  pattern wins; ties keep file order.
- `lines[]`: `side`, `account_class` (two-digit model class, must exist as a group in
  `chart_v03.json`), `class_name_mn`, `sub_account_mn` (a plain name, no conditions),
  `role` (resolved through `code_roles.json`; `null` on class 70/71 lines means the
  classified expense account), `amount_kind` (`net`, `vat`, `gross`, `gross_salary`, ...),
  `optional` (dropped when the amount is missing or zero, e.g. the VAT line of a receipt
  from a non-VAT seller), `alternatives[]` (`{account_class, role, when, when_mn}` — the
  pipeline picks by hint or the accountant taps), `v1_code_hint` / `v1_code_range`,
  `class_assumed` (the reference does not name the class; confirm with the accountant).
- `primary_document_mn`: the primary document Law on Accounting art. 13.7 requires.
- `citation`: `{instrument, instrument_full, section, verified, url, quote}`. Sections of
  Заавар 116 come from two independent readings of the instrument reconciled by a third,
  plus a second reading on 2026-09-09 (`docs/legal/order116.md`): where a reader pair, the
  reconciler or the second reading rated the section exact and the sentence was found
  verbatim, `section` and `quote` are set and `verified` is `true` (35 patterns);
  otherwise `section` and `quote` are `null`, `verified` is `false` and `notes` says
  whether the instrument prints no such entry at all or prints only part of it, and what an
  admin would be vouching for if they ticked the box anyway. A `section` may name more than
  one label, joined with `; `, when the entry is a composite of printed sentences (the
  amount from one, the accounts from another) — `tests/unit/test_seed_citations.py` checks
  every label against the instrument's own numbering. The explanation suffix
  (`" — Заавар 116 (2000), <section>"`) is generated at runtime by
  `rules_engine.citation_suffix`; a null section prints `mn.CITATION_SECTION_PENDING`.

Split patterns: `sale_*`, `purchase_*`, `fixed_asset_acquire_*`,
`customer_prepayment_recognize_*` exist per VAT status; `fixed_asset_dispose_gain`,
`fixed_asset_dispose_loss`, `fixed_asset_scrap` replace one pattern with exclusive lines.
Settlement patterns (`receivable_collect`, `payable_pay`, `vat_settle`, `income_tax_pay`,
`payroll_pay`) are the Payment Entry / Bank Transaction shapes; invoice patterns claim only
the invoice. Payroll has four legs (`payroll_accrue`, `payroll_withhold_pit`,
`payroll_withhold_employee_si`, `payroll_employer_si`); whether the SI deduction reduces
the PIT base is UNCONFIRMED (pattern notes).

### `chart_v03.json` and `aliases_v1_to_v03.json`

`chart_v03.json` is the ERPNext tree for "Монгол - ЖДҮ v0.3 (Nyabo)": five roots, two-digit
class groups from reference §2, four-digit `CCSS` leaves (87). It loads through
`nyabo_mn.setup.chart.load_chart` exactly like the V1 draft (`_comment` keys stripped,
`account_category` overlay applied). Class names are verbatim from the reference;
sub-account names are Nyabo drafts to be reconciled with the accountant's real chart.
Class 92 sits under Equity because ERPNext's Period Closing Voucher needs a
Liability/Equity closing account.

`aliases_v1_to_v03.json` maps every one of the 40 V1 leaves to a v0.3 leaf so pipeline
code that addresses accounts by V1 code keeps working; the accountant's own chart
overrides both via `Nyabo Account Alias` rows. `unmapped` must stay `[]`.

### `code_roles.json`

`role -> account code` per scheme (`v1`, `v03`). Pattern lines name roles, not codes, so
the same pattern serves both charts and the accountant's chart (mapped by alias rows).
`required_roles` must resolve to a leaf in `v03`; `null_allowed.<scheme>` lists the roles
a scheme may leave null because its chart has no such account (V1 has no SI/PIT payable,
prepaid or customer-advance leaf). A null role makes the resolver refuse the line and the
proposal is marked `needs_accountant` — never a guessed account.

### `bank_layouts.json`

Five bank placeholders (`khan_bank_xlsx`, `tdb_xlsx`, `golomt_bank_xlsx`, `trans_bank_xlsx`,
`xacbank_xlsx`) with an EMPTY `header_signature` and `column_map` and `verified: false`,
plus `generic_mn`. No sample export of any bank was available, so no column layout is
asserted: an empty signature never matches (`statements.detect_layout`), the first import
falls back to the keyword guess (`statements.guess_layout`, always `verified=False`), the
accountant confirms the mapping in the bot, and the result is saved as a new layout for
the admin to verify against the sample file. `seed_check` refuses any seed layout that
asserts columns without that process.

### `rules_default.json`

Company-independent `Nyabo Rule` rows seeded per scheme at provisioning: today the bank-fee
rule (`match_value` is the keyword alternation of `core.matching.FEE_KEYWORDS`,
`target_account_code` the scheme's `bank_fee` role, pattern `bank_fee_expense`).

## What `scripts/seed_check.py` enforces

- every file is valid JSON with the documented top-level shape and no unknown keys;
- unique `pattern_id`, `layout_id`, `rule_id`; no overlapping periods per tax-parameter key;
- pending rows have `value: null`; active rows have a value; verified rows cite a URL, an
  article and the verbatim quote (`quote_mn`, or the `«…» — ` prefix of `note`); a `quote_mn`
  key is never an empty string; values match their `unit` (thresholds carry a comparator,
  deadlines carry the three fields, schedules end with `up_to: null`);
- both charts load through `nyabo_mn.setup.chart.load_chart` without warnings; v0.3 groups
  are two-digit classes and leaves four-digit `CCSS` codes under their class;
- aliases cover all 40 V1 leaves and point at v0.3 leaves;
- every role resolves to a leaf of its chart, nulls only where `null_allowed` says so and
  never in `v03`;
- pattern lines use classes that exist in v0.3, roles that exist in `code_roles`, V1 hints
  that are V1 leaves, alternatives with a stated condition; a pattern is never `verified`
  without a citation section;
- bank layouts ship unverified and without guessed columns, one placeholder per bank plus
  `generic_mn`;
- default rules target leaves of their scheme and existing patterns.

## Open items (after the legal-citation pass; details in `docs/legal/README.md`)

1. **Closed on 2026-09-09** by the second reading of Заавар 116 (docs/legal/order116.md §3):
   the second reader confirmed `receivable_collect`, `payable_pay` and `income_tax_pay`, and
   `purchase_expense_non_vat`, `bank_line_expense`, `bank_fee_expense` and
   `sale_credit_vat_payer` are verified as composites of printed sentences. 35 of 44
   patterns are verified and the everyday path posts without a human tick. What remains is
   NOT a reading task: `purchase_expense_vat_payer`, `fixed_asset_acquire_vat_payer`,
   `vat_settle`, `income_tax_accrue`, `payroll_withhold_employee_si`,
   `simplified_tax_accrue`, `customer_prepayment_recognize_*` and `bank_transfer_internal`
   need a different instrument (VAT Law art. 14 and 14.1.5, MoF order 135/2000, the General
   Law on Social Insurance, IFRS for SMEs s.23) or an accountant vouching for mechanics no
   order prescribes. Each row's `notes` says which.
2. The standalone amending laws of 26 June 2026 (their legalinfo lawIds were not found) to
   rule out a consolidation lag; the fate of the 30 Dec 2025 Government bill (400M
   simplified regime) before the pending 2027 `simplified.*` rows are encoded.
3. The adopted 2 July 2026 Social Insurance amendment (2026 employer unemployment 0.5 vs
   0.6), the Health Insurance Law (`emd.*`), the Government resolution mapping occupations
   to accident tiers, the Ulaanbaatar property-tax rate annex (`property_tax.rate`).
4. Move the tax-parameter quotes from `note` into the `quote_mn` key (`scripts/seed_check.py`
   and `rules.seed.sync` accept both shapes now; `tests/unit/test_seed_citations.py` still
   reads the note prefix and moves with the data).
5. Reconcile the v0.3 class names with the instrument's own table (mismatches listed in
   `docs/legal/order116.md` §2) when the accountant's real chart arrives; sample statement
   exports from each bank to replace the placeholders.
