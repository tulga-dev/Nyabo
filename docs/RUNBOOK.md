# Nyabo runbook (operations)

Written for the founder. Every step is one action, followed by what you should see.
Commands marked `bench` run in the Frappe Cloud bench console (Site → Actions → Bench
Console, or SSH) or in the browser console as noted.

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

Site → **Site Config** → **Add key** for each row. Values never go in the repo or in chat.

| Key | Where it comes from |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather → `/mybots` → Nyabo → API Token (regenerate if it was ever pasted anywhere) |
| `TELEGRAM_WEBHOOK_SECRET` | any random string of 32+ letters and digits; you make it up |
| `ADMIN_TELEGRAM_IDS` | your numeric Telegram ID (the bot prints it with `/whoami`) |
| `OPENAI_API_KEY` | platform.openai.com → API keys |
| `OPENAI_MODEL` | optional, default `gpt-5.6-terra` |
| `ANTHROPIC_API_KEY` | optional |
| `EBARIMT_API_BASE` | `https://api.ebarimt.mn` (public registry lookups only) |

Check what is set (values are redacted):

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.config.check
```

## 3. Telegram webhook

Run once after the first deploy, and again if you regenerate the bot token or the secret:

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.telegram.webhook.setup_webhook
```

You should see: `{"ok": true, "url": "https://<site>/api/method/nyabo_mn.telegram.webhook.webhook"}`.
Then send `/start` to the bot. You should see: the welcome message and your Telegram ID.

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
inventory yes/no with an Excel or text list, accountant of record. You should see: the
summary card `✅ Тохиргоо дууслаа` and, in the desk, a Nyabo Company Settings record.

## 6. Daily operation

- Receipts: the owner sends a photo; the accountant gets the card and taps Батлах.
- Bank statements: the accountant sends the bank's Excel export; unmatched lines come back as cards.
- Month end: `/хаалт 2026-09` → checklist → summaries as PDF → **Хаах**.
- Corrections: on a posted entry's card, **Засах** → reason → reversal + new proposal.
- Questions: type a sentence; the answer comes from the books, read-only.

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

```bash
bench --site nyabo.s.frappe.cloud execute nyabo_mn.compliance.readiness.run
```

You should see: a table with one line per requirement, ТЭНЦСЭН or ДУТУУ, and a note.

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
| Card says ⚠️ Дүрэм баталгаажаагүй | posting pattern not verified | desk → Nyabo Posting Pattern → check citation → tick Баталгаажсан |
| `Site config is missing OPENAI_API_KEY` | secret missing | step 2 |
| Statement import asks for columns | bank layout unknown | answer the column questions once; an admin then verifies the Nyabo Bank Layout |
| `/хаалт` refuses | month not ended, or unverified rules used | wait for month end; verify rules |
