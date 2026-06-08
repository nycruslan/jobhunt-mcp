# JobHunt MCP

A read-only job search assistant. It pulls openings from target companies, scores them against your resume, tracks the pipeline in SQLite, drafts tailored resumes and cover letters, and sends a daily Telegram brief. It never submits applications. Every apply is human-in-the-loop.

Self-host and config-driven: drop in your own `profile.yaml` and `targets.yaml`, connect it to your Claude, and it's yours. Nothing personal is hardcoded.

## How it fits together

```
targets.yaml ──► feeds/ ──► score.py ──► tracker.sqlite
                  (ATS + JobSpy)            │
                                            ├──► server.py      (MCP tools for Claude Code)
                                            └──► daily_briefing.py (launchd → Telegram)
```

- **feeds/** — one module per source. ATS boards (Greenhouse, Lever, Ashby, Amazon, Netflix, Workday) hit clean public JSON APIs; `jobspy.py` scrapes Indeed/Google for companies without one. `feeds/__init__.py` (`fetch_for_company`, `pull`) is the single dispatch point used by both the server and the briefing. `_comp.py` extracts real posted salary; `_location.py` is the configurable home/remote filter (driven by `preferences` in `profile.yaml`); `_http.py` is the shared session + HTML stripper.
- **score.py** — JD-relative fit: skill match + role title + AI signal + company comp band. `display_comp()` prefers a posting's real salary over the static company band.
- **tracker.py** — SQLite store. `upsert_job` inserts new jobs and refreshes score/comp on known ones. Maintenance: `backfill_comp`, `renormalize_companies`, idempotent `_migrate`.
- **server.py** — the MCP server. Tools: `jobhunt_today`, `jobhunt_search`, `jobhunt_draft`, `jobhunt_save_cover`, `jobhunt_applied`, `jobhunt_active_applications`, `jobhunt_set_status`, `jobhunt_followup`, `jobhunt_referrals`, `jobhunt_prep`, `jobhunt_dismiss`, snooze/unsnooze, `jobhunt_pull_feed`, `jobhunt_status`, `jobhunt_stats`. Email sync is the `/jobhunt-sync` command: it reads your inbox (read-only) for recruiter replies and proposes status changes you confirm.
- **daily_briefing.py** — launchd job. Pulls every feed, then sends an HTML-formatted Telegram brief. Logs rotate at 1MB; keeps the 2 newest DB backups.
- **resume/**, **cover/** — generate a tailored PDF + cover letter. Use the Anthropic API when `ANTHROPIC_API_KEY` is set, otherwise hand structured context to Claude in the chat.

## Setup (use it yourself)

Self-host tool. Your résumé and job data never leave your machine. There's no
hardcoded identity, location, or company list. Everything comes from your own
`profile.yaml` and `targets.yaml`.

> **Fastest path:** do step 1, then run `/jobhunt-setup` in Claude and answer the
> questions. It builds `profile.yaml` from your existing resume, picks targets, wires
> up the optional brief, and installs the slash commands. Steps 2-6 are what it
> automates, kept here for reference and manual setup.

**1. Install**

```bash
git clone <repo> ~/.jobhunt_mcp && cd ~/.jobhunt_mcp
pipx install -e .          # or: pip install -e .  (add [ai] for API tailoring)
```

**2. Add your profile** — one file holds your résumé, contact, location, and
tuning. It is git-ignored, so your real data is never committed.

```bash
cp resume/profile.example.yaml resume/profile.yaml
$EDITOR resume/profile.yaml
```

`preferences` in that file drives the location filter (`home_terms`,
`home_states`, `remote_scope`), the tailoring model, and the daily brief.
`scoring.category_weights` rebalances which skills matter for your field.

**3. Pick your targets** — edit `targets.yaml` (companies, ATS slugs, comp bands).

**4. Connect it to Claude**

```bash
# Claude Code
claude mcp add jobhunt -- jobhunt-mcp
# (no install) claude mcp add jobhunt -- python3.11 ~/.jobhunt_mcp/server.py
```

Claude Desktop — add to `claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/`). Desktop is a GUI app and does NOT inherit
your shell `PATH`, so use **absolute paths**. A bare `jobhunt-mcp` usually fails there.

```json
{ "mcpServers": { "jobhunt": {
    "command": "/usr/local/bin/python3.11",
    "args": ["/Users/you/.jobhunt_mcp/server.py"]
} } }
```

Find your interpreter with `which python3.11`, then restart Desktop. The server
exposes its commands as MCP prompts, so they appear as slash commands in Desktop
automatically — the `cp` step below is only for Claude Code.

Install the slash commands so `/jobhunt-*` works in Claude Code:

```bash
cp commands/*.md ~/.claude/commands/
```

**5. (Optional) Daily brief** — Telegram, email, or both. Copy `briefing.conf.example`
to `briefing.conf`, fill the section(s) you want, and set `preferences.brief_delivery`
(`auto` uses whatever is configured). Email sends by SMTP from the cron job, so it works
headless (Gmail: `smtp.gmail.com:587` + an App Password). `/jobhunt-setup` does this for you.

**6. (Optional) API tailoring** — `export ANTHROPIC_API_KEY='sk-ant-...'` to have
résumés and cover letters drafted through the API. Without it, Claude tailors
them inline in chat. Pick the model with `preferences.tailor_model`.

## Scheduling

The optional daily brief runs via launchd at `~/Library/LaunchAgents/com.jobhunt.briefing.plist` (weekday mornings). `/jobhunt-setup` generates it from `com.jobhunt.briefing.plist.example`. It runs in a fresh process, so code changes are picked up automatically. **The MCP server must be restarted** for code changes to reach the `jobhunt_*` tools.

## Notes

- Read-only by policy. No feed is ever POSTed to.
- Referral data comes from your own LinkedIn export (`referrals/linkedin.csv`), not scraping.
- Comp shown as `$X` is the real posted range; `~$X` is the static company band estimate.
