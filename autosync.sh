#!/bin/bash
# JobHunt autosync — scheduled, unattended email→pipeline sync via headless Claude.
#
# Run by launchd (com.ruslan.jobhunt-autosync) on your always-on mac. A cloud
# routine can't reach the local jobhunt SQLite, so this runs locally where both the
# jobhunt MCP server and the Gmail MCP are reachable.
#
# Safety: --allowedTools restricts the run to reading Gmail, reading the pipeline,
# and the gated jobhunt_record_update. It cannot draft, send mail, or call
# set_status. record_update auto-applies only low-stakes signals and logs the rest.
set -uo pipefail

MCPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
LOG="$MCPDIR/autosync.log"
cd "$MCPDIR" || exit 1

PROMPT='You are the unattended JobHunt autosync. Work only through the allowed tools.
1. Call jobhunt_active_applications and jobhunt_status to see in-flight and drafted roles.
2. Search the connected Gmail (READ-ONLY) over the last 3 days for messages about those
   companies: application receipts ("thanks for applying") and recruiter replies.
3. Classify each relevant message as one signal: application_received, rejected,
   interview, onsite, or offer. Skip anything ambiguous or unrelated.
4. For each, call jobhunt_record_update(company, signal, evidence="<subject/short quote>").
   Do not call any other write tool. Let the tool decide auto-apply vs confirm.
5. Print a short summary: what was auto-applied, and what needs confirmation.
Never send any email or message. Read-only on Gmail.'

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
