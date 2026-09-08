# Golden set

Synthetic cases in the `Nyabo Eval Case` shape (`kind`, `source`, `regime`, `on_date`,
`input_json`, `expected_json`, `notes`, plus a `case_id` that `loader.EvalCase.to_doc`
folds into `notes`). Every file is `{"cases": [...]}` and is produced by
`python -m nyabo_mn.evals.golden._generate` together with the MockLlmClient fixtures under
`tests/fixtures/llm/{extract,classify}/golden_*.json`. Edit the generator, not the JSON.

| File | Kind | Count | What it checks |
|---|---|---|---|
| `receipts_extraction.json` | extraction | 10 | seller, date, total, VAT, ДДТД, payment method, line count |
| `receipts_classification.json` | classification | 20 | account, VAT treatment, document kind, pattern and lines for the same 10 receipts under `vat_payer` (2026-06-15) and `simplified_1pct` (2027-02-15) |
| `negatives.json` | rules | 10 | personal expenses, duplicates (hash / ДДТД / seller+date+total), non-ebarimt cash receipts, another company's receipt: all held for the accountant with the right flag |
| `injection.json` | injection | 5 | instruction text inside the receipt (EN and MN): detected, held, never followed |
| `corrections.json` | correction | 5 | reversal pair + new entry (account, amount, duplicate, VAT treatment, closed period) |
| `document_required.json` | document_required | 5 | art. 13.7: posting without a primary document is refused |
| `period_lock.json` | period_lock | 5 | postings into closed Accounting Periods are refused |
| `fx.json` | fx | 3 | USD amounts at the Mongolbank-style rate table in the case input; settlement FX loss |
| `bank_matching.json` | matching | 20 | exact/fee/transfer/none decisions of `core.matching` |

Images are never stored here: an extraction case names a fixture key (`llm_fixture`),
`evals.harness.extract_case` feeds deterministic placeholder bytes to the vision call and
the MockLlmClient answers with the fixture. The extraction prompt, schema and the
post-processing (`agent.extract`) run for real; only the model is canned.

## Adding a real image case later

1. Send the receipt through the bot on a test site (or insert a `Nyabo Document` with the
   file attached, `doc_type = receipt`). Note its name, e.g. `NYD-00042`.
2. Create a `Nyabo Eval Case` in the desk: `kind = extraction`, `source = golden`,
   `input_document = NYD-00042`, `on_date` = the receipt date, `expected_json` = the
   fields as printed on the paper (`total`, `date`, `vat_amount`, `seller_name`,
   `seller_tin`, `receipt_id`), `notes` = why the receipt is interesting (blurry, thermal
   fade, handwritten amount ...). Leave `input_json` empty or put `{"mime": "image/jpeg"}`.
3. `evals.run.run(kinds=["extraction"], company=...)` on the site loads DocType rows that
   carry `input_document` through `loader.EvalCase.from_doc`, reads the attached file and
   runs the real vision model (no mock), so these cases measure the provider, not the
   fixture. They are skipped without `OPENAI_API_KEY` / under `frappe.flags.nyabo_simulation`.
4. Never copy the image into the repo: it is a primary accounting document of a real
   company (retained ten years on the site, Law on Accounting art. 11.1).

Cases created by the nightly job (`source = correction`) live only on the site; export a
handful into a JSON file here only after anonymising seller names and amounts.
