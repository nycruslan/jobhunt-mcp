"""
Remotive public API — remote jobs, free and key-less (https://remotive.com/api).
Adds remote roles beyond the curated list. Filtered to the user's remote scope.

READ-ONLY: search only. Remotive blocks >2 requests/min and asks for at most
~4 calls/day, so this makes exactly ONE unfiltered request per pull and does
the role matching client-side.
"""
from __future__ import annotations

import logging

import config
from feeds._http import build_session, html_to_text, DEFAULT_TIMEOUT
from feeds._comp import parse_comp

log = logging.getLogger(__name__)

BASE = "https://remotive.com/api/remote-jobs"
SESSION = build_session()
MAX_ROLES = 3
LIMIT = 200  # one request replaces the old per-role queries, so fetch deep

# Remotive's candidate_required_location strings that are workable from the US.
_US_HINTS = (
    "usa", "united states", "us only", "us-", "u.s", "north america",
    "worldwide", "anywhere", "americas",
)


def _remote_ok(loc: str, prefs: dict) -> bool:
    scope = prefs.get("remote_scope", "us")
    if not prefs.get("allow_remote") or scope == "none":
        return False
    if scope == "anywhere":
        return True
    l = loc.lower().strip()
    return l in ("", "us") or any(h in l for h in _US_HINTS)


def _matches_roles(text: str, roles: list[str]) -> bool:
    """Client-side stand-in for Remotive's `search` param: a role matches when
    all of its words appear in the job's searchable text."""
    return any(all(w in text for w in role.split()) for role in roles)


def fetch_jobs() -> list[dict]:
    """One unfiltered request, role-filtered client-side.

    Request errors propagate to the caller (feeds.pull records them)."""
    prefs = config.preferences()
    if not prefs.get("allow_remote") or prefs.get("remote_scope") == "none":
        return []
    roles = [r.lower() for r in (config.profile().get("target_roles") or [])[:MAX_ROLES]]

    r = SESSION.get(BASE, params={"limit": LIMIT}, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()

    seen: set[str] = set()
    out: list[dict] = []
    for j in r.json().get("jobs", []):
        url = j.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        cand = (j.get("candidate_required_location") or "").strip()
        if not _remote_ok(cand, prefs):
            continue
        title = (j.get("title") or "").strip()
        company = (j.get("company_name") or "").strip()
        if not title or not company:
            continue
        jd_text = html_to_text(j.get("description", ""))
        searchable = " ".join((title, j.get("category") or "", jd_text)).lower()
        if roles and not _matches_roles(searchable, roles):
            continue
        out.append({
            "id":        f"rmtv_{j.get('id')}",
            "ats":       "remotive",
            "company":   company,
            "title":     title,
            "location":  f"Remote · {cand}" if cand else "Remote",
            "url":       url,
            "remote":    True,
            "jd_text":   jd_text,
            "comp":      parse_comp(j.get("salary", "") or ""),
            "posted_at": j.get("publication_date", "") or "",
        })

    log.info("Remotive fetched %d jobs", len(out))
    return out
