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
2. Order 116 was mapped to the posting patterns by two independent readers; a third
   reconciled the disagreements. A pattern is verified only where both readers (or the
   reconciler) rated the section *exact* and the integrator found the sentence verbatim in
   the saved text; *probable* readings and disagreements keep `verified: false` with the
   candidate sections in `notes`.
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

## Still open after this pass

- The standalone amending laws of 26 June 2026 (VAT, CIT, PIT, GTL) were not located on
  legalinfo (search is JavaScript-rendered); all 2027 values come from the amendment notes
  in the consolidated texts. A consolidation lag cannot be excluded.
- The adopted 2 July 2026 amendment to the Social Insurance law (own lawId not found): the
  2026 employer unemployment rate (0.5 vs 0.6) rests on the Government draft's quotation.
- Health Insurance Law (ЭМД rates), the SME Law art. 5.1 / MoF classification order, the
  Government resolution mapping occupations to accident-insurance tiers, the Ulaanbaatar
  property-tax rate annex, MoF order 135/2000 (deferred tax) — not fetched.
- Whether the 30 Dec 2025 Government bill (400M simplified regime, repeal of CIT 20.2.7,
  CIT 13.2.13 training deduction) was adopted in the autumn 2026 session.
