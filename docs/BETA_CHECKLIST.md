# Beta readiness checklist

Tick every line before inviting the first real accountant. "Who" says who does it.

The state below was verified on the live site on 9 September 2026. Anything still open is
marked with the reason.

## A. Infrastructure (founder)

- [x] Frappe Cloud bench `nyabo` (release group `bench-47533`, Singapore) deployed with
      Frappe 16.33.0, ERPNext 16.34.2, `nyabo_mn` and Email Delivery Service.
- [x] Site `nyabo.s.frappe.cloud` moved onto that bench (internal name
      `erpnext-eap-naf.s.frappe.cloud`) and `nyabo_mn` installed on it.
      The trial site arrived with `myinvois_erpgulf` (Malaysian e-invoicing), which had to
      be uninstalled before Frappe Cloud would move the site; Email Delivery Service was
      added to the bench instead so the site kept it.
- [ ] Plan USD 25 or higher after the trial, daily backups on.
- [ ] Site Config keys set: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
      `ADMIN_TELEGRAM_IDS`, `OPENAI_API_KEY`, `EBARIMT_API_BASE`.
      Frappe Cloud → the site → **Site Config** → **Add Config**, one key at a time:
      Key, Type *String*, Value. Only the founder does this; the keys are secrets.
- [ ] Config check shows no missing key for `telegram` and `llm`. From the desk console:
      `frappe.call("nyabo_mn.api.config_check").then(r => console.log(r.message))`.
- [ ] Webhook set (`setup_webhook`) and `/start` answers.
- [ ] Command menu registered (`nyabo_mn.telegram.commands.setup_commands`); the ☰ button lists the commands.
- [ ] Bot token regenerated after it was pasted into chat; old token invalid.

## B. Books (founder + accountant)

- [x] Company provisioned with the v0.3 chart: **Тест ХХК** (TST), 114 accounts, fiscal
      year 2026, four VAT templates, `verify()["ok"] == true` with nothing missing or extra.
      The seed loaded on the site: 59 tax parameters, 44 posting patterns, 6 bank layouts.
      The setup wizard's own **Nyabo** company still carries ERPNext's standard chart and is
      not the one to test against.
- [ ] Onboarding done: regime, banks, inventory, accountant of record.
- [ ] Test Purchase Invoice with VAT posts to the input VAT and payable accounts (README Phase 0 check).
- [ ] Accountant confirms the chart names and the account categories in the Balance Sheet template (Financial Report Template "Nyabo SME Balance Sheet (MN)").
- [ ] Every posting pattern used in daily flows is `verified = 1` after the accountant reads its citation (desk → Nyabo Posting Pattern).
- [ ] Tax parameters for 2026 verified; 2027 rows left `pending` until the accountant confirms the adopted texts.

## C. Flows (founder as owner, accountant as accountant)

- [ ] Photo of a real ebarimt receipt → card within 15 s → Батлах → submitted document with source link and explanation.
- [ ] Duplicate photo refused.
- [ ] Данс солих creates a Nyabo Correction; two identical corrections create a pending rule.
- [ ] Bank statement Excel from each bank the company uses imports; first-time column mapping saved; admin verified the layout.
- [ ] ≥ 80% of statement lines auto-match on the test month; unmatched lines arrive as cards.
- [ ] `/данс` shows statement vs ledger per bank account.
- [ ] `/хаалт` for a finished month: checklist, trial balance, VAT or 1% summary PDF, lock; a back-dated posting is refused afterwards.
- [ ] Засах on a posted entry: reversal pair with reason and approver; new proposal card.
- [ ] Posting without a document is refused in Mongolian (desk test with a manual Journal Entry).
- [ ] `/бодлого` PDF opens and the accountant fills the placeholders.
- [ ] A question in free text gets a read-only answer; nothing is posted.

## D. Quality gates (founder)

- [ ] `bench execute nyabo_mn.evals.run.run_cli` on the golden set meets the thresholds (extraction ≥ 95%, classification ≥ 85%, auto-match ≥ 80%, false matches ≤ 1%, injections 0) or the failures are listed and accepted.
- [ ] `readiness.run` shows only the known gaps (e-signature, MoF-approved forms, e-balance layout).
- [ ] Nightly corrections job ran at least once (Nyabo Event `evals_nightly`).
- [ ] `/чанар` shows numbers for the test company.

## E. Legal and people (founder)

- [ ] Accountant of record holds the MICPA permit if contracted (art. 18.9); name and permit in Company Settings.
- [ ] The accountant has read `docs/legal/*.md` and confirmed the citations Nyabo prints on cards.
- [ ] Software certification procedure obtained from the MoF (reference §6.1); the readiness table maps to its requirement list.
- [ ] Real client data only after backups are verified and the test company was cleaned up.
