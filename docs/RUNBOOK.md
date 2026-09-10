# Nyabo runbook (operations)

Written for the founder. Every step is one action, followed by what you should see.

A Frappe Cloud site on our plan has **no bench console** and no SSH: its Actions tab offers
migrations, backups and a SQL playground only. So every step below that shows a `bench`
command also gives the browser route, and the browser route is the one to use. It means:
log in to the site as a System Manager, press **F12**, open the **Console** tab, paste the
line and press Enter.

## 1. Deploy a new version

1. Push to `main` on `github.com/tulga-dev/Nyabo`. You should see: the push succeed.
2. Frappe Cloud → Benches → `nyabo` → **Apps** → the `nyabo_mn` row shows *Update available*.
   You should see: an **Update** / **Deploy** button at the top right.
3. Press **Deploy**. You should see: a Deploy entry with steps (Build, Upload, Pull) ending in *Success*.
4. Open the site. Frappe Cloud runs `bench migrate` automatically on deploy, which runs
   `nyabo_mn.setup.install.after_migrate` (custom fields, seed data, report templates).
   You should see: no error banner on the desk.

If a deploy fails, open the failed step's log, copy the last 30 lines and paste them to me.

## 2. Secrets (Site Config)

Site → **Site Config** → **Add Config** for each row. Values never go in the repo or in chat.

In that dialog, set **Config Name** to **Custom Key** first: it is the first entry in the
list, and until it is chosen the Key and Type fields are disabled, so the dialog looks as
though it refuses new keys. Then type the Key exactly as written below, set Type to
**String** (a custom key offers only String, Number, JSON and Boolean), paste the Value and
press **Add Key**. The site reads the new key about 30 seconds later.

The Config Name list also holds `Press Bootstrap Telegram Bot Token`. That is Frappe
Cloud's own key for its internal bot; Nyabo never reads it. The bot token goes in
`TELEGRAM_BOT_TOKEN` as a Custom Key.

| Key | Where it comes from |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather → `/mybots` → Nyabo → API Token (regenerate if it was ever pasted anywhere) |
| `TELEGRAM_WEBHOOK_SECRET` | any random string of 32+ letters and digits; you make it up |
| `ADMIN_TELEGRAM_IDS` | your numeric Telegram ID (the bot prints it with `/whoami`) |
| `OPENAI_API_KEY` | platform.openai.com → API keys |
| `OPENAI_MODEL` | optional, default `gpt-5.6-terra`; the fallback for a purpose with no model of its own (`eval`, `other`) |
| `OPENAI_MODEL_EXTRACT` | optional; the model that reads the receipt photo. Unset = `gpt-5.6-terra` |
| `OPENAI_MODEL_CLASSIFY` | optional; the model that proposes the account and the VAT treatment. Unset = `gpt-6-astra` |
| `OPENAI_MODEL_QUESTION` | optional; the model that answers free-text questions. Unset = `gpt-6-astra` |
| `ANTHROPIC_API_KEY` | optional |
| `EBARIMT_API_BASE` | `https://api.ebarimt.mn` (public registry lookups only) |

Check what is set (values are redacted):

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.config.check
```

A Frappe Cloud site has no shell on the plans Nyabo targets. From the desk instead: log in
as a System Manager, press **F12**, open the **Console** tab and paste

```javascript
frappe.call("nyabo_mn.api.config_check").then(r => console.log(r.message))
```

You should see: `missing_by_feature` empty for `telegram` and `llm`, and every secret shown
as `<set>` rather than its value. `frappe.call("nyabo_mn.api.readiness")` prints the
compliance readiness table the same way.

The same answer carries `models.by_purpose` — the model each purpose will actually run on,
resolved, with the `source` that decided it (`OPENAI_MODEL_CLASSIFY`, `purpose default`,
`OPENAI_MODEL`) and a `warning` when the id is not in the allowlist. Expect
`extract: gpt-5.6-terra` and `classify` / `question: gpt-6-astra` on a site that sets none
of the three keys. To move one purpose, add its key (Type **String**) and check here again
about 30 seconds later; no deploy is involved. The model on the next `Nyabo LLM Call` row
(desk → **Nyabo LLM Call**, sort by `creation`) is the model that actually answered, so the
intent and the call can be compared. Note that `OPENAI_MODEL` does **not** move `extract`,
`classify` or `question` — each of those has a model of its own, so set its key instead
(docs/DECISIONS.md LLM-01).

## 3. Telegram webhook

Run once after the first deploy, and again if you regenerate the bot token or the secret:

```javascript
frappe.call("nyabo_mn.api.setup_webhook").then(r => console.log(r.message))
```

(or `bench --site nyabo.s.frappe.cloud execute nyabo_mn.telegram.webhook.setup_webhook`
where a shell exists.)

You should see: an object whose `url` is `https://nyabo.s.frappe.cloud/api/method/nyabo_mn.telegram.webhook.webhook`.
Then send `/start` to the bot. You should see: the welcome message.
Send `/whoami`. You should see: `Таны Telegram ID: <number>`. That number, not your
`@username`, is what `ADMIN_TELEGRAM_IDS` wants; a username there makes every admin
command fail. `/whoami` is not in the ☰ menu on purpose (it is a diagnostic), so type it.

Register the command menu (the ☰ button next to the message box) at the same time, and
again whenever a command is added or renamed:

```javascript
frappe.call("nyabo_mn.api.setup_commands").then(r => console.log(r.message))
```

Telegram accepts only lowercase Latin command names, so the menu shows `/bank`, `/close`,
`/setup` with a Mongolian description naming the Cyrillic command; both spellings work.

## 4. Link people

In your own chat with the bot (you must be in `ADMIN_TELEGRAM_IDS`):

```
/link нягтлан Тест ХХК
```

You should see: a 6-digit code valid for 30 minutes. The accountant sends the code to the
bot and sees `✅ Холбогдлоо`. Owners: `/link эзэмшигч <company>`.

## 5. Onboard a company

Either provision from the desk console (see README) or let the accountant run `/эхлэх`
in Telegram: VAT payer yes/no, banks (Khan, TDB, Golomt, Trans, Xac) and currencies,
inventory yes/no with an Excel or text list, accountant of record. The wizard is one card
(`Тохиргоо · <company>`, step strip 1/7 … 7/7, the answers so far folded under «Хариулсан»)
that is redrawn in place while the accountant taps; a typed answer gets a fresh card below
it. You should see: the `Тохиргоо дууслаа` card with the summary and a [Самбар] button, and,
in the desk, a Nyabo Company Settings record.

### Demo figures for a test company

An empty test ledger shows «Энэ сард бичилт алга» on every card. To see the dashboard with
numbers, seed six months of demo vouchers (sales into the bank, rent, salaries, supplies, a
phone bill; two unmatched bank deposits when a bank account is configured; a small opening
stock when the company keeps stock) from the desk console (`/app/system-console`):

```js
frappe.call("nyabo_mn.api.seed_demo", {company: "Тест ХХК"}).then(r => console.log(r.message))
```

Every voucher carries `nyabo_primary_document_ref` = «ДЕМО: …», so nothing pretends to a
paper document. The call refuses a company whose ledger already holds a posting and answers
`already: true` on a second run — it can never double a real ledger.

## 6. Daily operation

- Receipts: the owner sends a photo; the accountant gets the card and taps Батлах.
- Bank statements: the accountant sends the bank's Excel export; unmatched lines come back as cards.
  - A card that names an unpaid invoice («Төлөгдөөгүй баримт: …») carries **Төлбөр бүртгэх**.
    Tapping it records the payment (a Payment Entry dated on the statement line), which closes
    the supplier payable and credits the bank; the line then shows as reconciled. Nothing posts
    until that tap. **Баримт хайх** onto an unpaid invoice offers the same button.
  - If the line is bigger than what the invoice still owes, the tap is refused: split it or pick
    another document. A smaller line pays part of the invoice and leaves the rest outstanding.
  - A foreign-currency invoice, a reversed one, a line that already carries a Nyabo proposal and
    a closed period are each refused in Mongolian; the answer says which.
  - Undo a mis-tapped settlement by cancelling the Payment Entry in the desk: the invoice goes
    back to Unpaid and the statement line back to Unreconciled, ready to settle again.
- Month end: `/хаалт 2026-09` → checklist → summaries as PDF → **Хаах**.
- Corrections: on a posted entry's card, **Засах** → reason → reversal + new proposal.
- Questions: type a sentence; the answer comes from the books, read-only. While the model
  works the chat shows a streamed «Бодож байна…» draft (Bot API `sendRichMessageDraft`); the
  answer card carries the handler's rows as a table and the next reads as buttons.
- Dashboard: `/меню` (or [Самбар] on any card) draws the month's revenue/expense/profit
  against last month, the bank balances with their reconciliation state, and what waits on a
  tap. Its buttons open the transactions of a month, the bank balances, the reports menu
  (trial balance with PDF/Excel, revenue and expense, revenue trend, biggest cost, stock,
  unmatched lines) and the pending proposals; every card edits itself in place and pages by
  month. Every figure is read from the ledger on the tap — nothing is cached.

### Rich cards and old clients

Cards are Bot API 10.3 rich messages (`sendRichMessage`, HTML body: headings, tables,
`details`, styled `<tg-button>` rows). Every card also has a plain-text twin, and the bot
sends that instead when Telegram refuses the rich one: a 404 (a bot server older than
10.1) is learned once per process and logged as `telegram.rich.unsupported`; a 400 is our
own HTML being refused, logged as `telegram.rich.rejected` with Telegram's description —
that card goes out plain, the next one is tried rich again. Grep `nyabo.log` for
`telegram.rich.` after a deploy.

## 7. Logs and errors

- Structured log: Site → Logs → `nyabo.log` (one JSON line per event, no secrets).
- Desk: **Error Log** list for exceptions; **Nyabo Event** list for the audit trail
  (postings, reversals, period locks, injections suspected, imports).
- Background jobs: Site → **Jobs**; failed jobs show the traceback. The receipt pipeline
  runs on the `long` queue, the webhook on `short`.

## 8. Backups

Frappe Cloud takes daily backups (Site → Backups). Before a risky operation:
Site → Backups → **Backup Now**, or:

```bash
bench --site nyabo.s.frappe.cloud backup --with-files
```

Files (receipt images, statements, PDFs) are private Frappe files and are included with
`--with-files`. Retention is ten years; the app refuses to delete them.

## 9. Certification readiness

```javascript
frappe.call("nyabo_mn.api.readiness").then(r => console.table(r.message))
```

You should see: a table with one line per checklist item, ТЭНЦСЭН or ДУТУУ, a note per item,
and the closing line saying the list is Nyabo's own — the MoF certification procedure text has
not been obtained yet (reference §6.1), so no requirement numbers are claimed.

## 10. Evals

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.evals.run.run_cli
bench --site nyabo.s.frappe.cloud execute nyabo_mn.evals.run.run_cli --kwargs '{"rules": 1}'
bench --site nyabo.s.frappe.cloud execute nyabo_mn.evals.run.run_cli --kwargs '{"sweep": 1}'
```

The simulator shows one receipt under both regimes without touching real books:

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.simulator.run.run --kwargs '{"case": "petrovis_fuel"}'
```

## 11. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Bot silent after `/start` | webhook not set or secret mismatch | run step 3; check Site Config keys |
| Cards arrive as plain text with buttons underneath | Telegram refused the rich message | `nyabo.log`: `telegram.rich.unsupported` (bot server predates Bot API 10.1: nothing to fix on our side) or `telegram.rich.rejected` (our HTML; the `description` names the tag) |
| Card says ⚠️ Дүрэм баталгаажаагүй | the rule is uncited and this company has not accepted it | the accountant runs `/дүрэм`, reads the rule and taps [Манай компанид хамаарна] — it clears that company only, and the refused [Батлах] finishes itself (ACC-01). A site admin in `ADMIN_TELEGRAM_IDS` may instead tap [Сайт даяар баталгаажуулах] once a citation is found (VER-08); nobody needs the desk. |
| Card still says ⚠️ after the accountant accepted | a deploy rewrote the rule's posting lines, so the acceptance no longer covers them | expected: the chat shows both versions and asks for the new one. `Nyabo Event` filtered to `rule_changed_after_acceptance` says when it moved and whose name was on the old content. |
| `Site config is missing OPENAI_API_KEY` | secret missing | step 2 |
| Statement import asks for columns | bank layout unknown | answer the column questions once, then confirm the mapping on the card that follows — the accountant who read the file confirms it for their own company and the stored statement is re-read on the spot (ACC-02). Ticking Баталгаажсан on the Nyabo Bank Layout row in the desk is the separate, site-wide act. |
| `/хаалт` refuses | month not ended, or rules this company has not cleared were used | wait for month end; the accountant answers them with `/дүрэм` (ACC-01) |
