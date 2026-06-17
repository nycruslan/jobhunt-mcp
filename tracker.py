"""
SQLite-backed job application tracker.
All state lives locally at ~/.jobhunt_mcp/tracker.sqlite
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import config

DB_PATH = Path(__file__).parent / "tracker.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    company       TEXT NOT NULL,
    title         TEXT NOT NULL,
    location      TEXT,
    url           TEXT,
    remote        INTEGER DEFAULT 0,
    jd_text       TEXT,
    ats           TEXT,
    comp          TEXT,
    score         INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'new',
    fetched_at    TEXT,
    last_seen     TEXT,
    posted_at     TEXT,
    applied_at    TEXT,
    dismissed     INTEGER DEFAULT 0,
    resume_path   TEXT,
    cover_path    TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS company_snoozes (
    company       TEXT PRIMARY KEY,
    snoozed_until TEXT NOT NULL
);
"""

VALID_STATUSES = {"new", "reviewed", "drafted", "applied", "screen", "onsite", "offer", "rejected", "withdrawn"}


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(SCHEMA)
        _migrate(con)


def _migrate(con) -> None:
    """Idempotent column adds for DBs created before a column existed."""
    have = {r["name"] for r in con.execute("PRAGMA table_info(jobs)").fetchall()}
    if "comp" not in have:
        con.execute("ALTER TABLE jobs ADD COLUMN comp TEXT")
    if "last_seen" not in have:
        con.execute("ALTER TABLE jobs ADD COLUMN last_seen TEXT")
        # Backfill so existing rows have a baseline; first refresh bumps it.
        con.execute("UPDATE jobs SET last_seen = fetched_at WHERE last_seen IS NULL")
    # Amazon ids moved off the az_ prefix (which collided with Adzuna) to amzn_.
    # The id basis is unchanged, so realign legacy rows in place — otherwise the
    # next pull's amzn_ ids look brand new and duplicate every open Amazon req.
    con.execute(
        "UPDATE OR IGNORE jobs SET id = 'amzn_' || substr(id, 4) "
        "WHERE ats = 'amazon' AND substr(id, 1, 3) = 'az_'"
    )
    # A posting can resurface under a new feed id (aggregators rotate ids). This
    # index makes the cross-run dedup lookup in pull() cheap.
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_company_title "
        "ON jobs (LOWER(company), LOWER(title))"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status)")


def upsert_job(job: dict) -> bool:
    """Insert a new job, or refresh a known one. Returns True only when the job
    was brand new (so callers can count fresh arrivals).

    On refresh: re-score and update the live fields (title/location/url/remote),
    and fill comp/jd_text/posted_at only when the new fetch actually has a value
    so a richer earlier fetch is never wiped by a thinner later one. last_seen is
    bumped every time the posting is observed; fetched_at, status, applied_at,
    dismissed, and the resume/cover paths are left alone."""
    ts = now()
    params = {
        "id":        job["id"],
        "company":   _normalize_company(job["company"]),
        "title":     job.get("title", ""),
        "location":  job.get("location", ""),
        "url":       job.get("url", ""),
        "remote":    1 if job.get("remote") else 0,
        "jd_text":   job.get("jd_text", "") or "",
        "ats":       job.get("ats", ""),
        "comp":      job.get("comp", "") or "",
        "score":     job.get("score", 0),
        "posted_at": job.get("posted_at", "") or "",
        "last_seen": ts,
    }
    with _conn() as con:
        existing = con.execute("SELECT id FROM jobs WHERE id = ?", (job["id"],)).fetchone()
        if existing:
            con.execute(
                """UPDATE jobs SET
                       title    = :title,
                       location = :location,
                       url      = :url,
                       remote   = :remote,
                       score    = :score,
                       last_seen = :last_seen,
                       jd_text   = CASE WHEN :jd_text   != '' THEN :jd_text   ELSE jd_text   END,
                       comp      = CASE WHEN :comp      != '' THEN :comp      ELSE comp      END,
                       posted_at = CASE WHEN :posted_at != '' THEN :posted_at ELSE posted_at END
                   WHERE id = :id""",
                params,
            )
            return False
        con.execute(
            """INSERT INTO jobs (id, company, title, location, url, remote, jd_text, ats, comp, score, fetched_at, last_seen, posted_at)
               VALUES (:id, :company, :title, :location, :url, :remote, :jd_text, :ats, :comp, :score, :fetched_at, :last_seen, :posted_at)""",
            {**params, "fetched_at": ts},
        )
        return True


def _normalize_company(name: str) -> str:
    """Consistent company display: 'anthropic' → 'Anthropic', 'pps capital' → 'PPS Capital'.
    Sub-brand/aggregator merges come from `company_aliases` in profile.yaml. Known
    all-caps tokens (IBM, PPS) and mixed-case brands (OpenAI, xAI) survive verbatim."""
    if not name:
        return name
    name = _strip_company_noise(name)
    alias = config.company_aliases().get(name.strip().lower())
    if alias:
        return alias
    # Brands whose casing must survive verbatim — Title Case would mangle them.
    BRANDS = {
        "openai": "OpenAI", "xai": "xAI", "github": "GitHub", "gitlab": "GitLab",
        "deepmind": "DeepMind", "coreweave": "CoreWeave", "togetherai": "Together AI",
        "fireworksai": "Fireworks AI", "gleanwork": "Glean", "mongodb": "MongoDB",
        "elevenlabs": "ElevenLabs", "doordash": "DoorDash", "youtube": "YouTube",
        "nvidia": "NVIDIA", "databricks": "Databricks", "drw": "DRW",
    }
    if name.strip().lower() in BRANDS:
        return BRANDS[name.strip().lower()]
    UPPER = {"ibm", "pps", "nyc", "ai", "ml", "jpmc", "aws", "gcp", "api", "ux", "ui", "qa", "hr", "drw", "hrt"}
    parts = []
    for tok in name.split():
        if tok.lower() in UPPER:
            parts.append(tok.upper())
        elif tok.isupper() and len(tok) <= 4:
            parts.append(tok)  # keep existing acronyms
        else:
            parts.append(tok[:1].upper() + tok[1:].lower())
    return " ".join(parts)


_NOISE_SUFFIX_RE = re.compile(
    r"\s*(?:[-–—|,]\s*)?\b(careers?|jobs|hiring|talent|recruiting)\b\s*$",
    re.IGNORECASE,
)


def _strip_company_noise(name: str) -> str:
    """Drop trailing portal cruft aggregators tack on, e.g.
    'Disney ... Technology Careers' -> 'Disney ... Technology'. Iterates so a
    doubled suffix ('... Jobs Careers') collapses. Never returns empty."""
    prev = None
    out = name.strip()
    while out and out != prev:
        prev = out
        out = _NOISE_SUFFIX_RE.sub("", out).strip()
    return out or name.strip()


def get_job(job_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def update_status(job_id: str, status: str, **kwargs) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Choose from: {VALID_STATUSES}")
    fields = {"status": status}
    if status == "applied":
        fields["applied_at"] = now()
    fields.update(kwargs)
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _conn() as con:
        con.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))


def dismiss_job(job_id: str) -> bool:
    """Mark a job as dismissed (never show in briefings)."""
    with _conn() as con:
        cur = con.execute("UPDATE jobs SET dismissed = 1 WHERE id = ?", (job_id,))
        return cur.rowcount > 0


def snooze_company(company: str, days: int) -> str:
    """Hide all jobs from this company for N days. Returns the snoozed-until date."""
    until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    key = _normalize_company(company).lower()
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO company_snoozes (company, snoozed_until) VALUES (?, ?)",
            (key, until),
        )
    return until


def unsnooze_company(company: str) -> bool:
    key = _normalize_company(company).lower()
    with _conn() as con:
        cur = con.execute("DELETE FROM company_snoozes WHERE company = ?", (key,))
        return cur.rowcount > 0


def get_active_snoozes() -> dict[str, str]:
    """Returns {company_lower: snoozed_until_iso} for snoozes still in effect."""
    now_iso = now()
    with _conn() as con:
        rows = con.execute(
            "SELECT company, snoozed_until FROM company_snoozes WHERE snoozed_until > ?",
            (now_iso,),
        ).fetchall()
        return {r["company"]: r["snoozed_until"] for r in rows}


def _snooze_filter() -> tuple[str, list[str]]:
    """SQL fragment + params that exclude companies under an active snooze.
    Returns ('', []) when nothing is snoozed so the query is left untouched."""
    snoozed = list(get_active_snoozes().keys())
    if not snoozed:
        return "", []
    placeholders = ",".join("?" * len(snoozed))
    return f" AND LOWER(company) NOT IN ({placeholders})", snoozed


def get_new_since(since_iso: str, min_score: int = 0) -> list[dict]:
    """Jobs fetched since `since_iso` that are still 'new', not dismissed, not in snoozed companies."""
    snooze_sql, snooze_params = _snooze_filter()
    with _conn() as con:
        rows = con.execute(
            f"""SELECT * FROM jobs
               WHERE status = 'new'
               AND dismissed = 0
               AND score >= ?
               AND fetched_at >= ?{snooze_sql}
               ORDER BY score DESC, fetched_at DESC""",
            (min_score, since_iso, *snooze_params),
        ).fetchall()
        return [dict(r) for r in rows]


def get_today_new(min_score: int = 0) -> list[dict]:
    """Jobs fetched today not yet reviewed. Excludes dismissed and snoozed companies."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return get_new_since(f"{today}T00:00:00+00:00", min_score=min_score)


def search_jobs(
    query: str = "",
    company: str = "",
    min_score: int = 70,
    status: str = "new",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    Search all tracked jobs with optional keyword, company, and score filters.
    Returns (jobs, total_matching_count) for pagination.
    """
    conditions = ["dismissed = 0", "score >= ?"]
    params: list = [min_score]

    if status:
        conditions.append("status = ?")
        params.append(status)

    if company:
        conditions.append("LOWER(company) LIKE ?")
        params.append(f"%{company.lower()}%")

    if query:
        conditions.append("(LOWER(title) LIKE ? OR LOWER(jd_text) LIKE ?)")
        params.extend([f"%{query.lower()}%", f"%{query.lower()}%"])

    where = " AND ".join(conditions)
    snooze_sql, snooze_params = _snooze_filter()
    where += snooze_sql
    params += snooze_params

    with _conn() as con:
        total: int = con.execute(
            f"SELECT COUNT(*) FROM jobs WHERE {where}", params
        ).fetchone()[0]

        rows = con.execute(
            f"SELECT * FROM jobs WHERE {where} ORDER BY score DESC, fetched_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return [dict(r) for r in rows], total


def get_followups(days: int = 5) -> list[dict]:
    """Applied jobs with no update after N days."""
    with _conn() as con:
        rows = con.execute(
            """SELECT * FROM jobs
               WHERE status = 'applied'
               AND applied_at IS NOT NULL
               AND CAST((julianday('now') - julianday(applied_at)) AS INTEGER) >= ?
               ORDER BY applied_at ASC""",
            (days,)
        ).fetchall()
        return [dict(r) for r in rows]


def pipeline_counts() -> dict:
    """Return counts by status, ignoring dismissed jobs."""
    with _conn() as con:
        rows = con.execute(
            "SELECT status, COUNT(*) as cnt FROM jobs WHERE dismissed = 0 GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}


def funnel_stats() -> dict:
    """Application conversion metrics from current statuses.

    `responded` counts everything past 'applied' (a recruiter moved it, either
    forward or to a rejection). Time-to-response isn't tracked: we only store
    applied_at, not per-transition timestamps."""
    counts = pipeline_counts()
    responded     = sum(counts.get(s, 0) for s in ("screen", "onsite", "offer", "rejected"))
    applied_total = responded + counts.get("applied", 0)
    return {
        "counts":        counts,
        "applied_total": applied_total,
        "responded":     responded,
        "response_rate": round(responded / applied_total * 100) if applied_total else 0,
        "offers":        counts.get("offer", 0),
    }


def find_jobs_by_status(statuses: tuple[str, ...]) -> list[dict]:
    """All non-dismissed jobs in any of `statuses`. Used by the automation matcher
    to find which application a recruiter email or confirmation refers to."""
    if not statuses:
        return []
    placeholders = ",".join("?" * len(statuses))
    with _conn() as con:
        rows = con.execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders}) AND dismissed = 0",
            tuple(statuses),
        ).fetchall()
        return [dict(r) for r in rows]


def active_applications() -> list[dict]:
    """Jobs in an active application stage (applied/screen/onsite), newest first.
    This is what an email-sync pass checks for recruiter updates."""
    with _conn() as con:
        rows = con.execute(
            """SELECT * FROM jobs
               WHERE status IN ('applied', 'screen', 'onsite')
               AND dismissed = 0
               ORDER BY applied_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]


def applied_count_by_company(days: int = 7) -> dict[str, int]:
    """How many roles applied to per company in the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as con:
        rows = con.execute(
            """SELECT company, COUNT(*) as cnt FROM jobs
               WHERE status IN ('applied','screen','onsite','offer')
               AND applied_at >= ?
               GROUP BY company""",
            (cutoff,),
        ).fetchall()
        return {r["company"]: r["cnt"] for r in rows}


def backup_db(dest) -> None:
    """Write a consistent snapshot of the DB to `dest` via SQLite's backup API
    (WAL-safe, unlike a plain file copy). Used before the destructive stale purge."""
    with _conn() as con:
        dst = sqlite3.connect(str(dest))
        try:
            con.backup(dst)
        finally:
            dst.close()


def purge_stale_jobs(days: int = 21) -> int:
    """Delete untouched 'new' postings not seen by any feed in `days` days.

    Only removes rows the user never acted on (status still 'new', not applied,
    drafted, reviewed, etc.). Anything in the pipeline is kept regardless of age,
    so application history is never lost. Returns the number of rows removed."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as con:
        cur = con.execute(
            """DELETE FROM jobs
               WHERE status = 'new'
               AND COALESCE(last_seen, fetched_at) < ?""",
            (cutoff,),
        )
        return cur.rowcount


def now() -> str:
    return datetime.now(timezone.utc).isoformat()
