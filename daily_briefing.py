#!/usr/bin/env python3.11
"""
JobHunt Daily Briefing
Fired by launchd at 9am EDT on weekdays.

Pulls fresh feed, builds a punchy Telegram message, sends it.

Config (set once, never commit):
  ~/.jobhunt_mcp/telegram.conf
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_CHAT_ID=...
"""
from __future__ import annotations

import html
import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

MCP_DIR = Path(__file__).parent
sys.path.insert(0, str(MCP_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        RotatingFileHandler(MCP_DIR / "briefing.log", maxBytes=1_000_000, backupCount=2),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("briefing")


# ── Config ────────────────────────────────────────────────────────────────────

# Every setting the briefing understands: Telegram for chat, SMTP for email.
_CONF_KEYS = (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "EMAIL_TO", "EMAIL_FROM",
)


def _load_conf() -> dict[str, str]:
    """Load briefing delivery settings (Telegram and/or SMTP email).
    Order: environment variables, then briefing.conf, then telegram.conf (legacy).
    """
    conf: dict[str, str] = {}

    for key in _CONF_KEYS:
        val = os.environ.get(key, "").strip()
        if val:
            conf[key] = val

    for fname in ("briefing.conf", "telegram.conf"):
        path = MCP_DIR / fname
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k in _CONF_KEYS and v and k not in conf:
                conf[k] = v

    return conf


def _resolve_delivery(conf: dict) -> str:
    """Where the brief goes: telegram | email | both | none.
    Combines `preferences.brief_delivery` (auto by default) with what's configured."""
    import config

    has_tg    = bool(conf.get("TELEGRAM_BOT_TOKEN") and conf.get("TELEGRAM_CHAT_ID"))
    has_email = bool(conf.get("SMTP_HOST") and conf.get("SMTP_USER")
                     and conf.get("SMTP_PASS") and conf.get("EMAIL_TO"))
    pref = (config.preferences().get("brief_delivery") or "auto").lower()

    want_tg    = has_tg    and pref in ("auto", "telegram", "both")
    want_email = has_email and pref in ("auto", "email", "both")

    if want_tg and want_email:
        return "both"
    if want_tg:
        return "telegram"
    if want_email:
        return "email"
    return "none"


# ── Feed pull ─────────────────────────────────────────────────────────────────

def _pull_all_feeds() -> int:
    """Pull all ATS feeds + JobSpy supplemental feed. Returns count of new jobs added."""
    import yaml
    import config
    import tracker
    import score as scorer
    import feeds

    tracker.init_db()
    data = yaml.safe_load((MCP_DIR / "targets.yaml").read_text())
    companies = [co for tier in data.values() for co in tier.get("companies", [])]

    new_count, errors, _skipped = feeds.pull(
        companies,
        score_fn=scorer.score_job,
        upsert_fn=tracker.upsert_job,
        include_jobspy=config.preferences()["enable_jobspy"],
    )
    for name, detail in errors:
        log.warning("Feed error: %s — %s", name, detail)
    return new_count


def _prune_backups(keep: int = 2) -> None:
    """Keep only the newest `keep` tracker.sqlite.bak-* files."""
    backups = sorted(MCP_DIR.glob("tracker.sqlite.bak-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in backups[keep:]:
        try:
            stale.unlink()
            log.info("Pruned old backup: %s", stale.name)
        except OSError as e:
            log.warning("Could not prune %s: %s", stale.name, e)


# ── Briefing builder ──────────────────────────────────────────────────────────

# Single source of truth for the briefing score threshold.
# Post-2026 scorer: strong target-company matches land 75-95, off-list firms cap ~73.
MIN_SCORE_BRIEFING = 60

# Max jobs shown in the brief body, and per-company cap before the "+N more" roll-up.
MAX_SHOWN = 12
MAX_PER_COMPANY = 2


def esc(text: str) -> str:
    """Escape untrusted text for Telegram HTML parse_mode (& < > only)."""
    return html.escape(str(text or "").strip(), quote=False)


def _tier(score: int) -> str:
    """Quality tier for grouping. Calibrated to the 2026 scorer (targets 75-95)."""
    if score >= 80:
        return "fire"
    if score >= 68:
        return "strong"
    return "look"


_TIER_HEADERS = {
    "fire":   "🔥 <b>Top picks</b>",
    "strong": "⭐ <b>Strong matches</b>",
    "look":   "📌 <b>Worth a look</b>",
}


def _compress_location(job: dict) -> str:
    """Squash long location strings into compact, NYC-prioritized form."""
    loc = (job.get("location") or "").strip()
    if not loc:
        return "Remote" if job.get("remote") else "NYC"

    # Split on pipe or comma-separated city groups
    parts = [p.strip() for p in loc.replace(" | ", "|").split("|")]

    short_map = {
        "new york city, ny": "NYC", "new york, ny": "NYC", "new york": "NYC",
        "san francisco, ca": "SF", "san francisco": "SF",
        "seattle, wa": "Sea", "seattle": "Sea",
        "los angeles, ca": "LA", "los angeles": "LA",
        "austin, tx": "Austin",
        "boston, ma": "Boston",
        "chicago, il": "Chicago",
        "remote - united states": "Remote-US",
        "remote - united states / remote": "Remote-US",
        "remote": "Remote",
        "united states": "US",
    }

    shortened = []
    nyc_first = []
    for p in parts:
        key = p.lower()
        short = short_map.get(key, p.split(",")[0])
        if "nyc" in short.lower() or "new york" in key:
            nyc_first.append("NYC")
        else:
            shortened.append(short)

    ordered = nyc_first + shortened
    seen = set()
    deduped = [x for x in ordered if not (x in seen or seen.add(x))]

    if len(deduped) > 3:
        return f"{' · '.join(deduped[:2])} +{len(deduped)-2}"
    return " · ".join(deduped) or "NYC"


def _format_age(posted_at: str) -> str:
    """Return 'today' / '2d ago' / '3w ago' / '' if unknown."""
    if not posted_at:
        return ""
    try:
        dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - dt).days
        if days <= 0:
            return "today"
        if days == 1:
            return "1d ago"
        if days < 14:
            return f"{days}d ago"
        return f"{days // 7}w ago"
    except Exception:
        return ""


def _diversify(jobs: list[dict], max_per_company: int = 2) -> tuple[list[dict], dict]:
    """Cap N per company in the displayed list; return (shown, leftover_count_by_company)."""
    shown: list[dict] = []
    counts: dict[str, int] = defaultdict(int)
    leftover: dict[str, int] = defaultdict(int)
    for j in jobs:
        c = j["company"]
        if counts[c] < max_per_company:
            shown.append(j)
            counts[c] += 1
        else:
            leftover[c] += 1
    return shown, dict(leftover)


def _since_window() -> tuple[datetime, str]:
    """Return (cutoff_dt, label) for new-matches window — handles Mon catch-up."""
    now_dt = datetime.now(timezone.utc)
    weekday = now_dt.weekday()  # Monday=0
    if weekday == 0:  # Monday — catch up since last Friday morning
        cutoff = (now_dt - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
        return cutoff, "since Friday"
    cutoff = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return cutoff, "today"


def _job_block(job: dict, scorer, applied_history: dict) -> str:
    """One job rendered as a 3-line HTML block."""
    comp, is_actual = scorer.display_comp(job)
    comp_str = ""
    if comp:
        comp_str = f" · 💰 ${esc(comp)}" if is_actual else f" · 💰 ~${esc(comp)}"

    age = _format_age(job.get("posted_at", ""))
    age_str = f" · {age}" if age else ""
    loc_str = esc(_compress_location(job))

    history_str = ""
    n_active = applied_history.get(job["company"], 0)
    if n_active > 0:
        history_str = f"\n   ↳ you have {n_active} active here"

    return (
        f"<b>{esc(job['company'])}</b> — {esc(job['title'])}\n"
        f"   {loc_str} · {job['score']}%{comp_str}{age_str}\n"
        f'   <a href="{esc(job["url"])}">Apply →</a> · <code>{esc(job["id"])}</code>{history_str}'
    )


def build_message(new_count: int) -> str:
    import tracker
    import score as scorer
    from referrals.match import find_contacts

    today = date.today().strftime("%A, %b %-d")
    lines: list[str] = [f"☀️ <b>JobHunt Morning Brief — {esc(today)}</b>", ""]

    # ── Pipeline snapshot — actionable stats only ─────────────────────────────
    counts       = tracker.pipeline_counts()
    applied_week = sum(tracker.applied_count_by_company(days=7).values())
    cutoff_dt, window_label = _since_window()
    today_new = tracker.get_new_since(cutoff_dt.isoformat(), min_score=MIN_SCORE_BRIEFING)

    pipeline_parts = [f"<b>{len(today_new)}</b> new {window_label}"]
    if applied_week:          pipeline_parts.append(f"{applied_week} applied this week")
    if counts.get("drafted"): pipeline_parts.append(f"{counts['drafted']} drafted")
    if counts.get("screen"):  pipeline_parts.append(f"{counts['screen']} in screen")
    if counts.get("onsite"):  pipeline_parts.append(f"{counts['onsite']} onsite")
    if counts.get("offer"):   pipeline_parts.append(f"🎉 {counts['offer']} offer!")

    lines.append("📊 " + " · ".join(pipeline_parts))
    lines.append("")

    # ── New matches — tiered + diversified ────────────────────────────────────
    if not today_new:
        lines.append(f"🆕 No new matches {window_label}.")
        if new_count > 0:
            lines.append(f"   ({new_count} fetched, all scored below {MIN_SCORE_BRIEFING}%)")
        lines.append("")
        lines.append("💬 Good day to follow up on past applications or prep for interviews.")
        return "\n".join(lines)

    shown, leftover = _diversify(today_new, max_per_company=MAX_PER_COMPANY)
    shown = shown[:MAX_SHOWN]

    by_tier: dict[str, list[dict]] = {"fire": [], "strong": [], "look": []}
    for j in shown:
        by_tier[_tier(j["score"])].append(j)

    applied_history = tracker.applied_count_by_company(days=7)

    for tier_key in ("fire", "strong", "look"):
        tier_jobs = by_tier[tier_key]
        if not tier_jobs:
            continue
        lines.append(_TIER_HEADERS[tier_key])
        lines.append("")
        for job in tier_jobs:
            lines.append(_job_block(job, scorer, applied_history))
            lines.append("")

    # Leftover summary (companies capped out)
    if leftover:
        more = [f"+{n} more {esc(co)}" for co, n in sorted(leftover.items(), key=lambda x: -x[1])[:5]]
        lines.append("➕ " + ", ".join(more))
        lines.append("   Run /jobhunt-search for the full list.")
        lines.append("")

    # ── Follow-ups ────────────────────────────────────────────────────────────
    followups = tracker.get_followups(days=5)
    if followups:
        lines.append(f"⏰ <b>{len(followups)} follow-up{'s' if len(followups) != 1 else ''} due</b>")
        for job in followups[:4]:
            applied_str = ""
            if job.get("applied_at"):
                try:
                    delta = (datetime.now(timezone.utc) - datetime.fromisoformat(job["applied_at"])).days
                    applied_str = f" · applied {delta}d ago"
                except Exception:
                    pass
            lines.append(f"   • <b>{esc(job['company'])}</b> — {esc(job['title'])}{applied_str}")
        lines.append("")

    # ── Warm intros ───────────────────────────────────────────────────────────
    warm_new = [j for j in shown if find_contacts(j["company"])]
    if warm_new:
        lines.append("🤝 <b>Warm intros available</b>")
        seen_cos: set[str] = set()
        for job in warm_new[:4]:
            if job["company"] in seen_cos:
                continue
            seen_cos.add(job["company"])
            contacts = find_contacts(job["company"])
            first = contacts[0]
            name  = esc(first.get("name", "?"))
            pos   = esc(first.get("position", ""))
            extra = f" (+{len(contacts) - 1} more)" if len(contacts) > 1 else ""
            lines.append(f"   • {esc(job['company'])}: {name}{', ' + pos if pos else ''}{extra}")
        lines.append("")

    # ── How-to footer ─────────────────────────────────────────────────────────
    lines.append("───────────────")
    lines.append("📋 <b>How to use</b>")
    lines.append("• Apply → tap a job id to copy, then in Claude Code: <code>/jobhunt-draft</code> paste")
    lines.append("• Not interested → tell Claude: dismiss JOB_ID")
    lines.append("• Mute a company → tell Claude: snooze COMPANY for 30 days")

    return "\n".join(lines)


# ── Telegram sender ───────────────────────────────────────────────────────────

def send_telegram(token: str, chat_id: str, text: str) -> None:
    import requests

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    log.info("Telegram sent OK (message_id=%s)", resp.json()["result"]["message_id"])


# ── Email sender (SMTP) ───────────────────────────────────────────────────────

def _to_email_html(message: str) -> str:
    """The brief is built with inline HTML tags and bare newlines (Telegram style).
    Email clients ignore bare newlines, so turn them into <br> and wrap the body."""
    body = message.replace("\n", "<br>\n")
    return (
        "<html><body style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
        "font-size:15px;line-height:1.5;color:#111\">"
        f"{body}</body></html>"
    )


def send_email(conf: dict, subject: str, message: str) -> None:
    import smtplib
    import ssl
    from email.message import EmailMessage

    port   = int(conf.get("SMTP_PORT") or 587)
    sender = conf.get("EMAIL_FROM") or conf["SMTP_USER"]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = conf["EMAIL_TO"]
    msg.set_content("This briefing is HTML. Open it in an HTML-capable mail client.")
    msg.add_alternative(_to_email_html(message), subtype="html")

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(conf["SMTP_HOST"], port, context=ctx) as s:
            s.login(conf["SMTP_USER"], conf["SMTP_PASS"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(conf["SMTP_HOST"], port) as s:
            s.starttls(context=ctx)
            s.login(conf["SMTP_USER"], conf["SMTP_PASS"])
            s.send_message(msg)
    log.info("Email sent OK to %s", conf["EMAIL_TO"])


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    conf = _load_conf()
    delivery = _resolve_delivery(conf)
    if delivery == "none":
        log.error(
            "No briefing delivery configured. Add Telegram and/or SMTP settings to "
            "~/.jobhunt_mcp/briefing.conf (see briefing.conf.example), or run /jobhunt-setup."
        )
        sys.exit(1)

    log.info("Pulling feeds…")
    new_count = _pull_all_feeds()
    log.info("Feed pull complete — %d new jobs", new_count)

    message = build_message(new_count)
    subject = f"JobHunt Brief — {date.today().strftime('%a %b %-d')} ({new_count} new)"

    log.info("Sending briefing via %s…", delivery)
    if delivery in ("telegram", "both"):
        send_telegram(conf["TELEGRAM_BOT_TOKEN"], conf["TELEGRAM_CHAT_ID"], message)
    if delivery in ("email", "both"):
        send_email(conf, subject, message)

    _prune_backups(keep=2)
    log.info("Done.")


if __name__ == "__main__":
    main()
