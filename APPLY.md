# JobHunt — How to Apply

## Daily flow

1. **9am weekdays** → Telegram briefing lands with top jobs grouped by tier
2. **Long-press a `job_id`** in Telegram → Copy
3. **In Claude Code**, type:
   ```
   /jobhunt-draft <paste>
   ```
   Produces:
   - Tailored resume PDF (auto-opens)
   - 1-paragraph cover letter (inline in chat, also saved to disk)
   - Apply URL
4. **Open the apply URL** → upload the PDF → paste the cover letter → submit
5. **Mark applied** (so it stops showing up):
   ```
   mark <job_id> as applied
   ```

## Slash commands

| Command | What it does |
|---|---|
| `/jobhunt-today` | Show top matches on demand (don't wait for 9am) |
| `/jobhunt-draft <job_id>` | Full: tailored resume PDF + cover letter |
| `/jobhunt-cover <job_id>` | Just the cover letter (faster when reusing same PDF) |
| `/jobhunt-prep <job_id>` | Interview prep notes for a role |
| `/jobhunt-referrals` | Pull contacts from your network at target companies |

## Pruning the briefing (the more you do this, the cleaner it gets)

| Tell Claude | What happens |
|---|---|
| `dismiss <job_id>` | Hide that job forever |
| `snooze <company> for 30 days` | Mute all new roles from a company for N days |
| `unsnooze <company>` | Lift the mute early |

## Coverage

Public ATS APIs we pull from (read-only, no auth, all candidate-facing endpoints):

| Source | Companies |
|---|---|
| Greenhouse | Anthropic, Stripe, Datadog, Vercel, Jump Trading, DRW |
| Lever      | OpenAI (when slug works) |
| Ashby      | Ramp, Plaid, Cursor, Linear, Notion, Perplexity |
| Amazon Jobs| Amazon, AWS |
| Workday    | NVIDIA (extensible to IBM, Adobe, Cisco, etc.) |

**Filter:** NYC-area or US-wide remote only. State-specific remote in other states (CA, WA, TX, etc.) is blocked.

**Not covered** (no clean public API as of May 2026): Apple, Google, Microsoft, Meta. These run closed SPAs requiring login.

## Where files live

```
~/.jobhunt_mcp/
├── output/
│   ├── resumes/          ← tailored PDFs
│   └── covers/           ← saved cover letters
├── tracker.sqlite        ← job state (status, posted_at, dismissed, etc.) — 0600
├── targets.yaml          ← companies to track
├── briefing.log          ← log of 9am runs
└── telegram.conf         ← bot creds — 0600
```

**Quick open:**
```bash
open "$(ls -t ~/.jobhunt_mcp/output/resumes/*.pdf | head -1)"   # most recent resume
open ~/.jobhunt_mcp/output/                                     # all output
```

Files are slugged by `{company}_{job_id}.pdf` — easy to find by company name.

## Troubleshooting

```bash
# Manually fire the briefing
python3.11 ~/.jobhunt_mcp/daily_briefing.py

# Check the schedule is loaded
launchctl list | grep jobhunt

# Recent log
tail -20 ~/.jobhunt_mcp/briefing.log
```

## Adding more Workday companies

Append to `targets.yaml`:
```yaml
- name: IBM
  ats: workday
  workday:
    host:   ibm.wd1
    tenant: ibm
    site:   IBM
```

No code change needed — the generic Workday client auto-discovers NYC location IDs per tenant.
