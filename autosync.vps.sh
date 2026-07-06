#!/bin/bash
# JobHunt autosync (VPS variant) — email->pipeline sync without the claude.ai
# Gmail connector (unavailable headless). imap_fetch.py reads Gmail over IMAP,
# then Claude classifies updates and records them via the jobhunt MCP. Read-only
# on email; the ONLY write tool allowed is the gated jobhunt_record_update.
# The classification/policy prompt is shared with the local variant: autosync_prompt.md.
set -uo pipefail

MCPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
PY="$MCPDIR/.venv/bin/python"
LOG="$MCPDIR/autosync.log"
cd "$MCPDIR" || exit 1

# Log hygiene: the log accumulates inbox contents — keep only the last ~500KB and
# keep it private. cat back (not mv) so any open fd keeps the same inode.
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 500000 ]; then
  tail -c 500000 "$LOG" > "$LOG.tmp" && cat "$LOG.tmp" > "$LOG"
  rm -f "$LOG.tmp"
fi
touch "$LOG" && chmod 600 "$LOG"

# Claude auth: reuse the headless Max OAuth token from the trading deploy env,
# but export ONLY what the claude CLI needs — not that project's whole secret set.
DEPLOY_ENV="$HOME/.portfolio_copilot/deploy/.deploy.env"
if [ -f "$DEPLOY_ENV" ]; then
  for _var in CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY; do
    _val="$(grep -E "^${_var}=" "$DEPLOY_ENV" | tail -n 1 | cut -d= -f2-)"
    [ -n "$_val" ] && export "${_var}=${_val}"
  done
  unset _var _val
fi

# Failure alert via Telegram. The bot token never touches argv, the URL of a logged
# error, or the log: a python heredoc reads it through config.secret and posts.
alert() {
  "$PY" - "$1" <<'PYEOF'
import sys
try:
    import config, requests
    token = config.secret("TELEGRAM_BOT_TOKEN")
    chat  = config.secret("TELEGRAM_CHAT_ID")
    if token and chat:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": sys.argv[1]}, timeout=15)
except Exception as e:
    print(f"telegram alert failed: {type(e).__name__}", file=sys.stderr)
PYEOF
}

# The fetch must succeed AND return messages, or the agent would happily report
# "nothing to sync" against an empty inbox forever.
EMAILS="$("$PY" "$MCPDIR/imap_fetch.py" 3 2>>"$LOG")"
fetch_rc=$?
if [ "$fetch_rc" -ne 0 ] || [ -z "$EMAILS" ]; then
  echo "=== autosync $(date '+%Y-%m-%d %H:%M:%S %Z') — IMAP fetch failed (rc=$fetch_rc, ${#EMAILS} bytes), aborting ===" >> "$LOG"
  alert "JobHunt autosync (VPS): IMAP fetch failed (rc=$fetch_rc). Check autosync.log." 2>>"$LOG"
  exit 1
fi

PROMPT="You are the unattended JobHunt autosync.
Email source: recent Gmail inbox messages (READ-ONLY) are listed at the end under
=== RECENT EMAILS ===. Each includes a SENDER_DOMAIN line for step 2 below.

$(cat "$MCPDIR/autosync_prompt.md")

=== RECENT EMAILS ===
${EMAILS}"

{
  echo "=== autosync $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  "$CLAUDE" -p "$PROMPT" \
    --allowedTools \
      mcp__jobhunt__jobhunt_active_applications \
      mcp__jobhunt__jobhunt_status \
      mcp__jobhunt__jobhunt_record_update
  rc=$?
  echo "=== exit $rc at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
} >> "$LOG" 2>&1

if [ "${rc:-1}" -ne 0 ]; then
  echo "autosync: claude run failed (rc=${rc:-?}), alerting" >> "$LOG"
  alert "JobHunt autosync (VPS) failed (claude exit ${rc:-?}). Check autosync.log." 2>>"$LOG"
  exit 1
fi
