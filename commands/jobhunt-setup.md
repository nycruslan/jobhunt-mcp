Set up JobHunt end to end, conversationally. Do NOT make the user hand-edit YAML.

Install dir is `~/.jobhunt_mcp` (adjust if they cloned elsewhere). Walk these steps,
confirming as you go. Skip any step the user declines.

**1. Profile (required)**
- If `~/.jobhunt_mcp/resume/profile.yaml` already exists, ask whether to reconfigure or keep it.
- Read `~/.jobhunt_mcp/resume/profile.example.yaml` first to learn the exact schema.
- Ask for their resume: paste the text, a path to a PDF/DOCX, or a LinkedIn export. Read/parse whatever they give.
- Write `~/.jobhunt_mcp/resume/profile.yaml` from their real details: contact, summary, target_roles, experience (with bullets), education, skills (same category keys as the example), and all_skills_flat. Only include what they actually have.
- When you author the summary and bullets, follow the human-voice rules: no em dashes, no rule-of-three triplets, vary sentence length, plain verbs, no buzzwords.

**2. Preferences**
- Ask where they're based and whether they want remote. Set `home_terms`, `home_states` (2-letter codes), `allow_remote`, `remote_scope` (us | anywhere | none).
- Set `tailor_model` (default `claude-haiku-4-5`) and `enable_jobspy` (default false; explain it's a noisy Indeed/Google scrape with heavy deps).
- Optionally tune `scoring.category_weights` to their field (backend-heavy vs AI-heavy, etc.).

**3. Targets**
- Show the tiers in `~/.jobhunt_mcp/targets.yaml`. Help them trim to companies they care about or keep the defaults. To add one they need `ats` + `slug`.

**4. Referrals (optional)**
- If they have a LinkedIn connections export, copy it to `~/.jobhunt_mcp/referrals/linkedin.csv`.

**5. Daily brief (optional) — Telegram, email, or both**
- Ask how they want it delivered: Telegram, email, both, or skip. Set `preferences.brief_delivery` in profile.yaml accordingly (or leave `auto`, which uses whatever is configured).
- Copy `~/.jobhunt_mcp/briefing.conf.example` to `briefing.conf`, fill only the section(s) they chose, then `chmod 600` it:
  - Telegram: create a bot with @BotFather, message it once, read the chat id from the getUpdates URL. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
  - Email: SMTP host/port/user/pass and EMAIL_TO. For Gmail use smtp.gmail.com:587 and an App Password (not the login). Note: the brief is sent by SMTP from the cron job, NOT by Claude's email connector (connectors only run inside a Claude session and can't send mail).
- Schedule it. On macOS, fill `~/.jobhunt_mcp/com.jobhunt.briefing.plist.example` with their python path, install dir, and home, write it to `~/Library/LaunchAgents/com.jobhunt.briefing.plist`, and load it with `launchctl load`.
- Offer to test now: run `python3.11 ~/.jobhunt_mcp/daily_briefing.py` and confirm the message arrives.

**6. API tailoring (optional)**
- Mention `ANTHROPIC_API_KEY`: with it, resumes and covers are drafted via the API; without it, you tailor them inline in chat. Either is fine.

**7. Register + install commands**
- Register the server: `claude mcp add jobhunt -- jobhunt-mcp` (or `python3.11 ~/.jobhunt_mcp/server.py`).
- Copy `~/.jobhunt_mcp/commands/*.md` to `~/.claude/commands/` so every `/jobhunt-*` command works.

**8. Smoke test**
- Run `jobhunt_pull_feed(company="<one of their targets>")`, then `jobhunt_today()`, to confirm jobs flow in.
- Summarize the daily flow: brief → `/jobhunt-draft <id>` → apply → `/jobhunt-applied <id>`.
