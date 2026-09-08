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

The legal source of truth is `docs/mn-rules-reference.md`. Nothing in this folder is
more certain than that document: a value the reference marks VERIFY, or takes from news
rather than a statute, ships with `verified: false`, and a value the reference does not
state at all ships as `status: pending` with `value: null`.

## Verified means

A human compared the value with the primary legal text: `source_text` names the
instrument, `article` the article, `source_url` a legalinfo.mn / parliament.mn page, and
the reference states the value without a VERIFY flag. Only the Law on Accounting rows
(retention, statement deadlines) qualify today. Every value from the June 2026 tax
package, from news sites or from agency pages is `false` until the adopted texts are
obtained (reference §6.4–6.5). An admin flips `verified` in the desk after reading the
text; `rules.seed.sync` never overwrites a row an admin has verified unless `force=True`.
`rules.guard.require_verified()` refuses an unverified Tax Parameter, Posting Pattern or
Bank Layout for a real posting (tests and the simulator may use them).

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
| `unit` | `fraction` (0.10 = 10%), `MNT` (`{amount, comparator, basis}`), `years`, `schedule` (`{basis, brackets: [{up_to, rate}]}`, last `up_to` null), `rule` (object or boolean), `deadline` (`{period, due_months_after_period_end, due_day}`, null inside = not stated) |
| `effective_from` / `effective_to` | ISO dates; `effective_to` null = open-ended. A row starting on `horizon_start` was in force before Nyabo's coverage; its legal in-force date is not asserted. |
| `status` | `active` (usable) or `pending` (known change, text not encoded: `resolve_parameter` raises `PendingRuleError`) |
| `verified` | see above |
| `source_text`, `source_url`, `article`, `note` | provenance; `note` explains every UNCONFIRMED item |

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
- `citation`: `{instrument, instrument_full, section, verified, url, quote}`. The reference
  gives no section numbers of Заавар 116, so `section` is `null` and `verified` is `false`
  on every pattern. The explanation suffix (`" — Заавар 116 (2000), <section>"`) is
  generated at runtime by `rules_engine.citation_suffix`; a null section prints
  `mn.CITATION_SECTION_PENDING`.

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
- pending rows have `value: null`; active rows have a value; verified rows cite a URL and
  an article; values match their `unit` (thresholds carry a comparator, deadlines carry the
  three fields, schedules end with `up_to: null`);
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

## Open items (from the reference §6 and the reviewers)

1. Section numbers of Заавар 116 (2000) for every pattern (needs the instrument text).
2. Final adopted texts of the June 2026 VAT/CIT/PIT/General Taxation amendments: `cit.brackets`
   2027, `pit.brackets` 2027/2028, `vat.input_deduction_categories`, the 2027 simplified
   filing deadline, `tax_debt.enforcement_split`.
3. General Law on Social Insurance art. 18: `si.employer_rate` and `si.accident_tiers`
   (both years), and whether the employee 11.5% or a contribution ceiling changed.
4. Sample statement exports from each bank to replace the placeholders.
5. The accountant's real chart to replace the v0.3 sub-account names.
