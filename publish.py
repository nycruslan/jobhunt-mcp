"""
Publish a dashboard snapshot of the jobhunt pipeline to Turso, for the web admin
at ruslanshulga.com/admin. Read-only mirror: the local SQLite stays the source of
truth; this pushes one JSON row the Astro site reads.

Publishing is opt-in (preferences.publish) and needs Turso creds (env or
briefing.conf). It never raises into the caller — a failed publish must not break
the feed pull or any tool.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import config
import tracker
import score as scorer
from referrals.match import find_contacts

log = logging.getLogger("jobhunt_mcp")
MCP_DIR = Path(__file__).parent


def _creds() -> tuple[str, str]:
    """Turso URL + token from environment, falling back to briefing.conf."""
    import os

    url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    tok = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    if url and tok:
        return url, tok

    conf = MCP_DIR / "briefing.conf"
    if conf.exists():
        for line in conf.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k == "TURSO_DATABASE_URL" and not url:
                url = v
            elif k == "TURSO_AUTH_TOKEN" and not tok:
                tok = v
    return url, tok


def build_snapshot() -> dict:
    """Assemble the dashboard payload from the tracker (pure read, no network)."""
    today = []
    for j in tracker.get_today_new(min_score=60)[:25]:
        comp, actual = scorer.display_comp(j)
        comp_str = (f"${comp}" if actual else f"~${comp}") if comp else ""
        today.append({
            "company":  j["company"],
            "title":    j["title"],
            "score":    j["score"],
            "comp":     comp_str,
            "url":      j.get("url", "") or "",
            "location": j.get("location") or "",
            "contacts": len(find_contacts(j["company"])),
        })

    applications = [
        {
            "id":         j["id"],
            "company":    j["company"],
            "title":      j["title"],
            "status":     j["status"],
            "applied_at": j.get("applied_at"),
            "url":        j.get("url", "") or "",
        }
        for j in tracker.active_applications()
    ]

    now = datetime.now(timezone.utc)
    followups = []
    for j in tracker.get_followups(days=5):
        days = 0
        try:
            days = (now - datetime.fromisoformat(j["applied_at"])).days
        except (ValueError, TypeError):
            pass
        followups.append({
            "company": j["company"],
            "title":   j["title"],
            "applied_days_ago": days,
        })

    return {
        "generated_at": tracker.now(),
        "pipeline":     tracker.pipeline_counts(),
        "funnel":       tracker.funnel_stats(),
        "today":        today,
        "applications": applications,
        "followups":    followups,
    }


def publish() -> bool:
    """Write the snapshot to Turso. Returns False if creds are missing."""
    url, tok = _creds()
    if not url or not tok:
        return False

    import libsql

    payload = json.dumps(build_snapshot())
    conn = libsql.connect(database=url, auth_token=tok)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS jobhunt_snapshot "
        "(id INTEGER PRIMARY KEY, data TEXT, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO jobhunt_snapshot (id, data, updated_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
        (payload, tracker.now()),
    )
    conn.commit()
    log.info("Published jobhunt snapshot to Turso")
    return True


def publish_safe() -> None:
    """Publish if enabled and configured. Never raises."""
    if not config.preferences().get("publish"):
        return
    try:
        if not publish():
            log.info("Snapshot publish skipped: Turso creds not set")
    except Exception as e:  # ImportError, network, auth — never break the tool
        log.warning("Snapshot publish failed: %s", e)
