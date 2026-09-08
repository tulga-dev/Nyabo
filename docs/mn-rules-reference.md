# Nyabo — Mongolian accounting rules and chart of accounts reference

*Compiled 8 September 2026 from primary sources (legalinfo.mn, parliament.mn, mof.gov.mn, mta.gov.mn, standards.mn). Items marked VERIFY were not confirmed from a primary text and must be checked before they go into a rule table.*

## 0. What this changes in the build (read first)

1. **The rule tables need effective dates.** The tax package adopted by parliament on 18–19 June 2026 takes effect **1 January 2027** (a few provisions earlier). Nyabo will run 2026 rules for the current books and 2027 rules from January. Every tax parameter below must be stored as `(value, effective_from, effective_to, source)`, never as a constant.
2. **From 2027 most of Nyabo's target market is outside VAT.** The VAT withholding-payer threshold rises from 50M₮ to 400M₮ annual revenue, and businesses under 400M₮ can use a simplified 1% regime with quarterly filing. Micro and small clients will need a *smaller* chart and *no* VAT logic; VAT-registered clients (above 400M₮, or voluntarily registered) need the full one. Model this as a company-level `tax_regime` with two profiles: `vat_payer` and `simplified_1pct`.
3. **Software certification is a market-entry requirement.** The Accounting Law (art. 17.1.11) has the Ministry of Finance publish the list of accounting software permitted for bookkeeping in Mongolia; the ministry publishes that list, and certification is granted for two years by order of the MoF State Secretary after an examination commission review, under the "Нягтлан бодох бүртгэлийн программ хангамжид хяналт тавих журам". Nyabo (ERPNext + `nyabo_mn`) will need this certificate for clients to use it as their statutory ledger. Get the procedure text and requirement list now; it also defines what journals, ledgers and forms the software must produce.
4. **Books must be kept by a professional or certified accountant** (art. 18.3), and contracted accountants or firms need a permit from the Institute (MICPA) (art. 18.4, 18.9). Nyabo is software; the accountant of record signs. Never position Nyabo as the bookkeeper of record, and check that partner accountants hold the permit.
5. **The official model chart is two-digit classes plus two-digit sub-accounts.** Accountants' real charts are built on the 2000 model (e.g. 10 Касс, 11 Банк, 12 Авлага, 31 Дансны өглөг, 51 Борлуулалт, 61 ББӨ, 70/71 зардал). The Tooroi V1 draft uses different 4-digit codes. Re-base the default template on the model classes (section 2) and keep V1 codes as aliases; the accountant's own chart overrides both.
6. **Audit-trail rules are law, not preference:** primary document required for every entry (13.7), documents retained ≥ 10 years (11.1), corrections documented with reason and method and signed (15.1), errors corrected in the period they occurred (15.2), e-signature on electronic primary documents and statements (13.5, 8.4, 9.5).

## 1. Legal framework

### 1.1 Law on Accounting (revised 19 June 2015, in force 1 Jan 2016, amended through 2024)
Source: https://legalinfo.mn/mn/detail/11191

- **Standards (art. 4):** IFRS for public-interest entities (listed, licensed financial, state-owned, utilities, banks, VASPs…); **IFRS for SMEs** for entities meeting the SME Law criteria; IPSAS for budget entities. The Ministry of Finance classification order (4 Feb 2016) treats entities as SMEs when both revenue < 1.5bn₮ and total assets < 0.5bn₮. IFRS for SMEs (2015) is officially translated by MICPA. An e-reporting standard for SME statements exists at standards.mn.
- **Basis (art. 6):** accrual. **Language and currency (art. 7):** Mongolian, tögrög; foreign-currency bookkeeping only with MoF consent, statements still in MNT.
- **Statements (art. 8.1):** statement of financial position, statement of comprehensive income, statement of changes in equity, cash flow statement, notes. Signed and stamped by executive management and chief accountant; e-signature when electronic (8.4).
- **Filing (art. 9–10):** electronically to the relevant financial agency (district/aimag finance department, MoF e-balance). Fiscal year = calendar year. IFRS entities: half-year by 20 July, annual by 10 February. **All others (SMEs): annual by 10 February.** Consolidated by 1 March.
- **Retention (art. 11.1):** accounting documents and statements ≥ 10 years.
- **Inventory count (art. 12.2):** mandatory before annual statements, on change of custodian, suspected loss, disaster, reorganisation/liquidation.
- **Primary documents (art. 13):** forms and method approved by MoF; document valid when signed and stamped by preparer/approver, or e-signed; **recording a transaction without a primary document is prohibited (13.7)**.
- **Processing order (art. 14.3):** primary document → journal → detailed and general ledger → transaction reports → statements. Double entry mandatory (14.2).
- **Error correction (art. 15):** based on a document stating the reason and method, signed by the approver and the person correcting; reflected in the statements of the period in which the error occurred.
- **Who keeps the books (art. 18):** a professional or certified accountant; the CEO may do it for non-IFRS entities if they are one (18.7); contracted accountants and consulting firms need an Institute permit (18.9–18.10).
- **Chief accountant duties (art. 20.2):** review payables/receivables and settlements, verify transactions before they are made, check tax calculations, keep the accounting policy document.
- **Approved software (art. 17.1.11):** MoF publishes the permitted list.

### 1.2 Model chart of accounts and posting instructions
Source: Order 116 (2000) of the Minister of Finance and Economy, "Аж ахуйн нэгж, байгууллагад мөрдөх нягтлан бодох бүртгэлийн дансны үлгэрчилсэн заавар", still listed as in force: https://legalinfo.mn/mn/detail?lawId=205201

Applies to all entities except banks. Principles stated: accrual, double entry, MNT, historical cost, revenue recognition, matching, full disclosure. Each entity prepares its own chart "based on" the model (section 2). Inventory cost: FIFO or weighted average. Depreciation: straight-line, units of production, double-declining, sum-of-years. Foreign currency: Mongolbank official rate on transaction date, remeasured at reporting date. Journal forms: MoF order 100 (2018) defines the general journal ("ЕЖ") and cash journal and the correction/adjustment entry rules (http://igovernment.mn/docs/313).

### 1.3 Tax laws — parameters (2026, and 2027 after the June 2026 package)

| Parameter | 2026 (current) | From 1 Jan 2027 | Source |
|---|---|---|---|
| VAT rate | 10% | 10% | VAT Law |
| VAT withholding-payer registration threshold | 50M₮ annual revenue | **400M₮** | ikon.mn 26 Jun 2026; parliament.mn 18 Jun 2026 |
| VAT payment timing | due with monthly return | deferral up to 2 months depending on compliance rating; import VAT after sale | ikon.mn 26 Jun 2026 |
| VAT deductions widened | — | training and employee-need expenses, fixed-asset purchases, non-resident services, cash purchases without receipt deemed VAT-inclusive (VERIFY final text) | ikon.mn 24 Dec 2025 |
| Simplified regime (1% of revenue) | revenue < 50M₮, not VAT-registered, annual filing by 10 Feb | revenue < **400M₮**, quarterly | mta.gov.mn; arslan.mn 13 Mar 2026 |
| 90% CIT credit ("1% effective") threshold | 1.5bn₮ revenue | **2.5bn₮** | parliament.mn 76435 |
| CIT brackets | 10% up to 6bn₮ taxable income, 25% above | new **15%** middle bracket for non-mining companies (thresholds VERIFY) | parliament.mn 18 Jun 2026 |
| PIT (employment) | 10% flat | 0% up to 792,000₮/month (2027); 1% for 792,000–2,000,000₮ (from 2028); higher bracket above (VERIFY) | parliament.mn 18 Jun 2026 |
| Tax debt enforcement | account freeze | 70% of inflows to tax debt, 30% left to the business (in force on adoption) | parliament.mn 18 Jun 2026 |
| Immovable property tax | 0.6% of value (per 2000 instruction; VERIFY current) | — | legalinfo 205201 |
| Social insurance | employee 11.5%; employer ≈12.5–14.5% by accident-insurance tier (VERIFY exact current split in art. 18 of the General Law on Social Insurance) | accident-insurance tiers change (0.5/1.5/2.5 → 0.3/1.2/2.2) from 1 Jan 2027 per 2 Jul 2026 amendment | legalinfo lawId=16760148379551 |
| Tax depreciation lives (CIT law art. 15) | buildings 40y, machinery 10y, computers/software 3y, other 10y (VERIFY) | — | CIT Law |

Filing calendar (VERIFY each against the current law/MTA notices before encoding): VAT return monthly by the 10th; CIT quarterly by the 20th of the month after the quarter and annual by 10 February; PIT withholding quarterly; social insurance monthly.

## 2. Model chart of accounts (Order 116/2000) and mapping

The model gives classes; entities add sub-accounts "01..". This is what accountants' real charts descend from.

| Class | Name (Mongolian) | Model guidance for sub-accounts | Tooroi V1 code(s) |
|---|---|---|---|
| 10 | Кассад байгаа бэлэн мөнгө | by currency, cashier, purpose | 1110 |
| 11 | Банкинд байгаа мөнгө | by bank, MNT/FX | 1120 |
| 12 | Авлага (дансны, бусад) | customers, staff advances, interest, tax receivable, bad-debt allowance | 1310 (+ VAT receivable 1810) |
| 13 | Богино хугацаат хөрөнгө оруулалт | deposits, securities | — |
| 14 | Түүхий эд, материал | by custodian | 1410 |
| 15 | Дуусаагүй үйлдвэрлэл, бэлэн бүтээгдэхүүн, бараа, сав баглаа, түлш шатахуун, сэлбэг, мал, ажлын хувцас | by type/custodian | 1410 |
| 18 | Урьдчилж төлсөн зардал/тооцоо | by type | — |
| 20 | Үндсэн хөрөнгө / элэгдэл | land, buildings, equipment, furniture, vehicles; depreciation per class | 1510 / 1519 |
| 21 | Биет бус хөрөнгө | by type | — |
| 22 | Хөрөнгө оруулалт (урт хугацаат) | by type | — |
| 31 | Дансны өглөг | suppliers, social insurance, salaries, taxes payable | 2110, 2210, 2220, 2310 |
| 32 | Бусад өглөг, урьдчилан төлөгдсөн орлого | customer prepayments, long-term debt | — |
| 41 | Эзэмшигчдийн өмч | shares, additional paid-in, retained earnings, current-year profit, donated, revaluation | 3110, 3120, 3210 |
| 51 | Борлуулалт | by product/service, domestic/export | 4110, 4120 |
| 52 | Борлуулалтын хөнгөлөлт, буцаалт | contra to sales | — |
| 61 | Борлуулсан бүтээгдэхүүний өртөг | by product | 5110 |
| 70 | Удирдлагын зардал | salaries, bonuses, social insurance, travel, comms, utilities, depreciation… | 6110–6940 |
| 71 | Борлуулалтын зардал | sales staff, marketing, delivery | (split needed) |
| 84 | Үндсэн бус үйл ажиллагааны ашиг (олз) | interest, dividends, FX gains, asset disposal gains | — |
| 87 | Үндсэн бус үйл ажиллагааны алдагдал (гарз) | interest expense, FX losses, disposal losses | — |
| 91 | Орлогын албан татварын зардал | | 9110 |
| 92 | Орлого, зарлагын нэгдсэн данс | closing account | — |

Recommendation: default template v0.3 = classes above with 4-digit codes `CCSS` (class + sub), Mongolian names verbatim; keep a `code_alias` table mapping V1 codes so nothing in the pipeline changes when the accountant's chart replaces the template. Add 71 (selling expenses), 84/87 (non-operating), 18 (prepaid), 32 (customer prepayments), 13 (deposits) — SMEs hit all of these within a year.

## 3. Posting patterns from the model instruction (rules as data)

These are the entries the instruction prescribes; Nyabo's proposal engine should choose among them, never invent others.

- **Cash sale / credit sale:** Дт Мөнгө / Дансны авлага — Кт Борлуулалт (+ Кт НӨАТ өглөг for VAT payers).
- **Purchase of goods/services (VAT payer):** Дт Бараа материал / Зардал, Дт НӨАТ авлага — Кт Мөнгө / Дансны өглөг.
- **Purchase (not VAT-registered):** VAT is included in cost: Дт Бараа материал / Зардал (gross) — Кт Мөнгө / Өглөг. *This is the default for simplified-regime clients.*
- **Petty cash:** establish Дт Жижиг мөнгөн сан — Кт Мөнгө; replenish Дт зардлын дансууд — Кт Мөнгө; the fund account itself is not touched by expenses.
- **Payroll:** Дт Цалингийн зардал — Кт Цалингийн өглөг; withholding Дт Цалингийн өглөг — Кт ХХОАТ өглөг; social insurance Дт зардал — Кт НДШ өглөг; payment Дт өглөг — Кт Мөнгө.
- **Prepaid expenses (rent, insurance):** Дт Урьдчилж төлсөн зардал — Кт Мөнгө; monthly Дт Зардал — Кт Урьдчилж төлсөн зардал.
- **Customer prepayment:** Дт Мөнгө — Кт Урьдчилан төлөгдсөн орлого; recognise on delivery.
- **Fixed asset purchase:** Дт Үндсэн хөрөнгө (cost incl. transport, customs, installation, less cash discounts) — Кт Мөнгө/Өглөг; depreciation Дт Элэгдлийн зардал — Кт Хуримтлагдсан элэгдэл; disposal closes cost and accumulated depreciation with gain/loss.
- **Inventory issue:** Дт Зардал/Дуусаагүй үйлдвэрлэл — Кт Бараа материал; COGS on sale Дт ББӨ — Кт Бараа/Бэлэн бүтээгдэхүүн.
- **Bad debts:** allowance Дт Найдваргүй авлагын зардал — Кт Найдваргүй авлагын хасагдуулга; write-off Дт хасагдуулга — Кт Дансны авлага.
- **Foreign currency:** record at Mongolbank official rate on the transaction date; settlement/remeasurement differences to FX gain (84) / loss (87).
- **Income tax:** Дт Орлогын татварын зардал — Кт Орлогын татварын өглөг (+ deferred tax per MoF order 135/2000 where relevant).
- **Property tax:** Дт Хөрөнгийн татварын зардал — Кт Хөрөнгийн татварын өглөг.
- **Accrued expenses (utilities, rent not yet invoiced):** Дт Зардал — Кт холбогдох өглөг.
- **Sales discounts/returns:** Дт Борлуулалтын хөнгөлөлт/буцаалт — Кт Дансны авлага (contra-revenue, class 52).

## 4. Documents, journals, controls

- Primary document forms and compilation method: approved by MoF (art. 13.2); entities may add internal forms approved by their governing body (13.3). Cash journal is kept from bank statements and cash reports with attached originals (MoF order 100/2018).
- Every entry must reference its primary document; an ebarimt receipt, invoice, contract or payment slip is the document. A photo of a receipt plus the ebarimt verification record satisfies "electronic primary document" only if the e-signature requirement is met — VERIFY how the MoF forms order treats scanned receipts, and keep the original image in any case.
- Accounting policy document ("НББ-ийн бодлогын баримт бичиг") is mandatory per entity (art. 18.2, 20.2.2). Nyabo should generate a template per client from its configuration (chart, inventory method, depreciation method, VAT status).
- Corrections: reversal entry with a stated reason, approver recorded (art. 15.1); never edit a posted document.

## 5. Ebarimt and other APIs

- Ebarimt POS API 3.0 (issuing receipts, merchant side): official docs at developer.itc.gov.mn (Ebarimt API section); an async Python SDK `ebarimt-pos-sdk` (Pydantic v2, OAuth2 + local POS REST) exists and is a reasonable starting point for `nyabo_mn/ebarimt/`.
- Receipt lookup/verification by QR for purchases (buyer side) uses the public info endpoints under api.ebarimt.mn (e.g. branch and TIN lookups are documented there); confirm the receipt-check endpoint and payload in the same developer portal before implementing `lookup.py`.
- MoF financial statement e-filing (e-balance) and the SME e-reporting standard: standards.mn/standard/zhdaan lists the standard; obtain the current XML/format spec from MoF's Accounting Policy Department.

## 6. Still to obtain (in priority order)

1. **"Нягтлан бодох бүртгэлийн программ хангамжид хяналт тавих журам"** — the software certification procedure and the current approved-software list (mof.gov.mn/article/entry/12-20, published 3 Sep 2024). Determines what Nyabo must produce to be legal software.
2. **Your accountant's real chart** and one month of statements and GL (already requested) — replaces the template.
3. **MoF-approved primary document forms** (art. 13.2 order) — the templates Nyabo must be able to print/export (кассын орлого/зарлагын ордер, нэхэмжлэх, төлбөрийн даалгавар…).
4. **Final adopted texts** of the June 2026 VAT, CIT, PIT and General Taxation Law amendments from legalinfo.mn, to encode the 2027 rule set exactly (thresholds, brackets, effective dates).
5. **General Law on Social Insurance art. 18** current and 2027 rates.
6. **IFRS for SMEs (2015, Mongolian)** from MICPA, for the recognition rules the agent should cite in explanations.
7. **SME financial statement layouts** (MoF e-balance forms) for the report templates.
