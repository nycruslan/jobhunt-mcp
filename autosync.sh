#!/bin/bash
# JobHunt autosync — scheduled, unattended email→pipeline sync via headless Claude.
#
# Run by launchd (com.jobhunt.autosync) on your always-on mac. A cloud
# routine can't reach the local jobhunt SQLite, so this runs locally where both the
# jobhunt MCP server and the Gmail MCP are reachable.
#
# Safety: --allowedTools restricts the run to reading Gmail, reading the pipeline,
# and the gated jobhunt_record_update. It cannot draft, send mail, or call
# set_status. record_update auto-applies only low-stakes signals and logs the rest.
# The classification/policy prompt is shared with the VPS variant: autosync_prompt.md.
set -uo pipefail

MCPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
PY="$(command -v python3.11 || command -v python3 || echo python3)"
LOG="$MCPDIR/autosync.log"
cd "$MCPDIR" || exit 1

# Log hygiene: the log accumulates inbox contents — keep only the last ~500KB and
# keep it private. cat back (not mv) so launchd's open fd keeps the same inode.
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 500000 ]; then
  tail -c 500000 "$LOG" > "$LOG.tmp" && cat "$LOG.tmp" > "$LOG"
  rm -f "$LOG.tmp"
fi
touch "$LOG" && chmod 600 "$LOG"

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

PROMPT="You are the unattended JobHunt autosync.
Email source: search the connected Gmail (READ-ONLY) over the last 3 days for messages
about your in-flight companies — application receipts (\"thanks for applying\") and
recruiter replies. Note each message's sender domain for step 2 below.

$(cat "$MCPDIR/autosync_prompt.md")"

{
  echo "=== autosync $(date '+%Y-%m-%d %H:%M:%S') ==="
  "$CLAUDE" -p "$PROMPT" \
    --allowedTools \
      mcp__jobhunt__jobhunt_active_applications \
      mcp__jobhunt__jobhunt_status \
      mcp__jobhunt__jobhunt_record_update \
      mcp__claude_ai_Gmail__search_threads \
      mcp__claude_ai_Gmail__get_thread
  rc=$?
  echo ""
  echo "=== exit $rc at $(date '+%Y-%m-%d %H:%M:%S') ==="
} >> "$LOG" 2>&1

if [ "${rc:-1}" -ne 0 ]; then
  echo "autosync: claude run failed (rc=${rc:-?}), alerting" >> "$LOG"
  alert "JobHunt autosync failed (claude exit ${rc:-?}). Check autosync.log." 2>>"$LOG"
  exit 1
fi
