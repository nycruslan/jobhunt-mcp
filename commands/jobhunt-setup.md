Set up JobHunt end to end, conversationally. Do NOT make the user hand-edit YAML or
config files — YOU do the edits, they just answer questions. Confirm as you go and skip
any optional step they decline. Install dir is `~/.jobhunt_mcp` (adjust if cloned elsewhere).

Say up front: **no API keys are required.** Out of the box it pulls from public ATS boards
plus Remotive (free, no key), and drafts resumes and cover letters here in Claude for free.
Everything below with a key is optional and only adds reach.

**1. Install**
- Check `python3.11`, `git`, and `pipx` exist. If `pipx` or `python3.11` is missing, install
  them (macOS: `brew install python@3.11 pipx && pipx ensurepath`).
- From the repo: `cd ~/.jobhunt_mcp && pipx install -e .`

**2. Profile (required)**
- If `resume/profile.yaml` already exists, ask whether to redo it. Read
  `resume/profile.example.yaml` first for the exact schema.
- Ask for their resume: paste text, a PDF/DOCX path, or a LinkedIn export. Parse it and write
  `resume/profile.yaml`: contact, summary, target_roles, experience, education, skills (same
  category keys as the example), all_skills_flat. Only what they actually have.
- Author the summary and bullets in a human voice: no em dashes, no rule-of-three triplets,
  varied sentence length, plain verbs, no buzzwords.

**3. Preferences**
- Ask their city and whether they want remote. Set `home_terms`, `home_states` (2-letter
  codes), `allow_remote`, `remote_scope` (us | anywhere | none).
- If their field isn't software/AI (e.g. a designer), tune `scoring.category_weights` to their
  field AND adjust the role patterns in `score.py` so their titles aren't penalized.

**4. Job sources — this controls how many jobs come in**
- None are required. Explain the tiers and set the flags in `preferences`:
  - Public ATS boards + **Remotive**: free, no key. Set `enable_remotive: true`.
  - **Adzuna (recommended, free):** broadens to the whole market. Offer to set it up now —
    have them register at https://developer.adzuna.com (instant, free), then paste their
    Application ID and Application Key. Write them to `~/.jobhunt_mcp/briefing.conf` as
    `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` (then `chmod 600` it) and set `enable_adzuna: true`.
    If they skip it, leave `enable_adzuna: false`; everything still works.
  - **JobSpy** (Indeed/Google scrape): optional and heavier. Only if they want it, set
    `enable_jobspy: true` and run `pipx inject jobhunt-mcp python-jobspy pandas`.

**5. Targets**
- Show the tiers in `targets.yaml`. Help them keep or trim companies they care about. Adding
  one needs a valid `ats` + `slug`.

**6. Referrals (optional)**
- If they have a LinkedIn connections export, copy it to `referrals/linkedin.csv`.

**7. Daily brief (optional) — Telegram, email, or both**
- Ask how, or skip. Set `preferences.brief_delivery` (auto | telegram | email | both | none).
- Copy `briefing.conf.example` to `briefing.conf`, fill only the chosen section, `chmod 600`:
  - Telegram: create a bot with @BotFather, message it once, read the chat id from the
    getUpdates URL → `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. (You can fetch that URL and
    pull the chat id for them.)
  - Email: SMTP host/port/user/pass + `EMAIL_TO`. Gmail = `smtp.gmail.com:587` + an App Password.
- Schedule it (macOS): fill `com.jobhunt.briefing.plist.example` with their python path,
  install dir, and home; write it to `~/Library/LaunchAgents/com.jobhunt.briefing.plist`;
  `launchctl load` it. Offer a test run: `python3.11 ~/.jobhunt_mcp/daily_briefing.py`.

**8. Connect to Claude**
- Register: `claude mcp add jobhunt -s user -- jobhunt-mcp`
  (fallback if `jobhunt-mcp` isn't on PATH: `claude mcp add jobhunt -s user -- python3.11 ~/.jobhunt_mcp/server.py`).
- Install the commands: `cp ~/.jobhunt_mcp/commands/*.md ~/.claude/commands/`
- Verify it loaded: `claude mcp get jobhunt` should report Connected.

**9. Finish**
- Tell them to restart Claude Code so the jobhunt tools and `/jobhunt-*` commands attach (MCP
  servers connect at session start, so they aren't live in this session yet).
- Then the daily flow is: `/jobhunt-today` to see matches → `/jobhunt-draft <id>` for the
  resume PDF + a custom cover letter → apply → `/jobhunt-applied <id>`.
