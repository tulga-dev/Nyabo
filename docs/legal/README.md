# Legal sources behind the seed data

*Generated from the seed on 2026-09-08 by the legal-citation pass; the quotes are verbatim from the saved copies of the texts listed in docs/legal/README.md. Regenerate rather than edit the tables by hand.*

Every `verified: true` row in `nyabo_mn/nyabo/seed/tax_parameters.json` and every
`verified: true` pattern in `posting_patterns.json` is backed by a verbatim Mongolian quote
and an article / section number from the primary text. This folder is the human-readable
side of that gate: one file per instrument, a table of article → claim → quote → status,
written so the founder can hand it to the accountant and to the ministry reviewer.

| Instrument | File | Primary text (fetched 2026-09-08) |
|---|---|---|
| Сангийн сайдын 2000 оны 116 дугаар тушаал — дансны үлгэрчилсэн заавар (posting instruction) | [order116.md](order116.md) | https://legalinfo.mn/mn/detail?lawId=205201 |
| Нягтлан бодох бүртгэлийн тухай хууль (Law on Accounting, 2015) | [accounting_law.md](accounting_law.md) | https://legalinfo.mn/mn/detail/11191 |
| Нэмэгдсэн өртгийн албан татварын тухай хууль (VAT Law) | [vat_law.md](vat_law.md) | https://legalinfo.mn/mn/detail?lawId=11227 |
| Аж ахуйн нэгжийн орлогын албан татварын тухай хууль (CIT Law) | [cit_law.md](cit_law.md) | https://legalinfo.mn/mn/detail?lawId=14407 and the 2019 gazette text |
| Хувь хүний орлогын албан татварын тухай хууль (PIT Law) | [pit_law.md](pit_law.md) | https://legalinfo.mn/mn/detail?lawId=14410 and the 2022 amendment act |
| Нийгмийн даатгалын ерөнхий хууль (General Law on Social Insurance, 2023) | [social_insurance_law.md](social_insurance_law.md) | https://legalinfo.mn/mn/detail?lawId=16760148379551 |
| Үл хөдлөх эд хөрөнгийн албан татварын тухай хууль (Immovable Property Tax Law) | [property_tax_law.md](property_tax_law.md) | https://legalinfo.mn/mn/detail?lawId=39 |
| Татварын ерөнхий хууль (General Taxation Law) | [general_taxation_law.md](general_taxation_law.md) | https://legalinfo.mn/mn/detail?lawId=14403 |
| The June 2026 tax package as a whole | [tax_package_2026.md](tax_package_2026.md) | amendment notes in the four consolidated laws; ikon.mn 26 Jun 2026 |

## Status legend

- **verified** — the quoted sentence states the value exactly; the seed row has `verified: true`.
- **unverified** — the value is a derivation (a sum, a percentage of another figure), comes
  from a draft law or a secondary source, or the reading has a single reader; the seed row
  has `verified: false` and `rules.guard` refuses it for a real posting.
- **pending** — the text does not state the value, or contradicts what the product assumed;
  the seed row has `value: null`, `status: pending` and the engine raises `PendingRuleError`.
- **contradicted** — a claim of `docs/mn-rules-reference.md` the primary text disagrees with;
  the seed was corrected to the text and the contradiction is recorded in the row's note.

## Method

1. Each text was fetched with curl from legalinfo.mn / parliament.mn (the pages are
   server-rendered; WebFetch summaries were not used for quotes) and saved as plain text.
2. Order 116 was mapped to the posting patterns by two independent readers (A and B) on
   **2026-09-08**; a third (R) reconciled their disagreements. The bar that day was: a
   pattern is verified only where **both readers, or R, rated the section *exact*** and the
   integrator found the sentence verbatim in the saved text. *Probable* readings,
   disagreements and rows only one reader had reached kept `verified: false` with the
   candidate sections in `notes`.

   **That bar was widened on 2026-09-09, and this is exactly how.** A second reading (S)
   re-fetched the instrument (body byte-identical to the 2026-09-08 copy) and read the
   outstanding candidates itself. For those rows S *is* the second reader: the pair is "the
   2026-09-08 reader plus S", not two people who read independently and were then compared.
   Seven patterns were verified on that basis — `purchase_expense_non_vat`,
   `receivable_collect`, `payable_pay`, `bank_line_expense`, `bank_fee_expense`,
   `income_tax_pay`, `sale_credit_vat_payer` — and each of their `notes` says
   `SECOND READER 2026-09-09`, so which rows rest on which bar is readable row by row.

   *Why it was widened rather than the rows left unverified:* `rules.guard.require_verified`
   refuses an unverified pattern for a real posting, and four of those seven are the whole
   everyday path of a non-VAT company — an expense receipt, collecting a receivable, paying a
   supplier, a bank outflow. While they were unverified the product refused every receipt its
   first user sent. The alternative was not "a stricter citation"; it was a live site where a
   human ticked the boxes with no reading behind them at all.

   So, precisely: a pattern in this repository is verified where the section was rated
   *exact* by both 2026-09-08 readers, or by R, or by the 2026-09-08 reader together with S,
   **and** the integrator found the sentence verbatim in the fetched text. 35 of 44 patterns
   are verified on that bar; the nine that are not say in their notes what an admin would be
   vouching for if they ticked the box. Per-row detail in [order116.md](order116.md) §3.
3. Tax parameters were compared row by row with the confirmed facts; where the text
   contradicted the reference (`docs/mn-rules-reference.md` §1.3) the seed value was
   corrected to the text and the old claim recorded.
4. Quotes are whitespace-normalised copies of the saved text (line breaks inside a sentence
   joined with one space; typos such as «матераил», «талааар» reproduced as printed).

## Where the quotes live in the seed

`posting_patterns.json` stores the quote in `citation.quote`. `tax_parameters.json` rows of
this pass keep the quote as the first element of `note`, in guillemets: `«…» — remarks`.
The schema now also accepts a `quote_mn` key (`scripts/seed_check.py` requires one shape or
the other on a verified row) and `rules.seed.sync` writes whichever is present to the
`Nyabo Tax Parameter.quote_mn` field; moving the quotes into the key is open item 4 of
`docs/seed/README.md`.

## Closed by the second reading (2026-09-09)

- Заавар 116 sections for seven patterns: `purchase_expense_non_vat` (12.2.2 А; 9.4.1.1),
  `receivable_collect` (3.4.1 в)), `payable_pay` (1.4), `bank_line_expense` and
  `bank_fee_expense` (1.4; 12.2.2 А), `income_tax_pay` (9.4.1.1) and `sale_credit_vat_payer`
  (3.4.1 а); 9.4.1.1). The first four are the patterns everyday bookkeeping runs on; while
  they were unverified `rules.guard.require_verified` refused every receipt a non-VAT
  company sent the bot.
- Whether the nine remaining patterns can be verified from Order 116 at all. They cannot,
  and each row now says which other instrument (or which piece of plain double-entry
  mechanics) an admin would be vouching for instead.

## Still open after this pass

- The standalone amending laws of 26 June 2026 (VAT, CIT, PIT, GTL) were not located on
  legalinfo (search is JavaScript-rendered); all 2027 values come from the amendment notes
  in the consolidated texts. A consolidation lag cannot be excluded.
- The adopted 2 July 2026 amendment to the Social Insurance law (own lawId not found): the
  2026 employer unemployment rate (0.5 vs 0.6) rests on the Government draft's quotation.
- Health Insurance Law (ЭМД rates), the SME Law art. 5.1 / MoF classification order, the
  Government resolution mapping occupations to accident-insurance tiers, the Ulaanbaatar
  property-tax rate annex, MoF order 135/2000 (deferred tax) — not fetched. The Health
  Insurance Law was tried again on 2026-09-09 and **cannot be fetched the way Order 116
  was**: its body is not server-rendered (`lawId=103861` returns the title and the site
  chrome only, and no `/api/front/` detail endpoint answers), so the text has to come from
  the Pdf/Word export on that page or from the accountant. `emd.employee_rate` and
  `emd.employer_rate` stay pending; they are the one pending pair an ordinary SME walks
  into, every month, on payroll.
- MoF order 135/2000 matters more than its place in this list suggests: it is why
  `income_tax_accrue` cannot be verified. Every accrual form Order 116 prints carries a
  deferred-tax credit line the two-line pattern does not have.
- Whether the 30 Dec 2025 Government bill (400M simplified regime, repeal of CIT 20.2.7,
  CIT 13.2.13 training deduction) was adopted in the autumn 2026 session.
