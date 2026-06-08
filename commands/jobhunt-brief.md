Fire the full morning briefing now and send it via the configured channel(s).

Run: `python3.11 ~/.jobhunt_mcp/daily_briefing.py`
Stream the output so the user sees progress (feed pulls, new job count, delivery confirmation).
The brief goes to Telegram and/or email per `preferences.brief_delivery`. If nothing is
configured, the script says so. Run `/jobhunt-setup` to set up delivery.
