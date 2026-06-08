"""
Amazon Jobs public search API.
Endpoint: https://www.amazon.jobs/en/search.json
Public, candidate-facing. No auth. Cap is 100 results per request.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

from feeds._http import build_session, DEFAULT_TIMEOUT
from feeds._location import is_local_or_remote
from feeds._comp import parse_comp

log = logging.getLogger(__name__)

BASE         = "https://www.amazon.jobs/en/search.json"
JOB_URL_BASE = "https://www.amazon.jobs"
RESULT_LIMIT = 100  # Amazon's per-request max
SESSION      = build_session()


def fetch_jobs(slug: str = "", keyword: str = "") -> list[dict]:
    """Fetch recent Amazon software roles, NYC-filtered.

    Args:
        slug:    Ignored (signature consistency with other feeds).
        keyword: Optional title keyword filter applied server-side.
    """
    params: dict = {
        "result_limit": RESULT_LIMIT,
        "offset":       0,
        "sort":         "recent",
        "country[]":    "US",
        "category[]":   "software-development",
    }
    if keyword:
        params["base_query"] = keyword

    try:
        r = SESSION.get(BASE, params=params, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("Amazon Jobs fetch failed: %s", e)
        return []

    jobs: list[dict] = []
    for j in r.json().get("jobs", []):
        loc = j.get("location") or j.get("normalized_location") or ""
        if not is_local_or_remote(loc):
            continue

        # Stable ID: prefer icims, fall back to internal id. Truthy check avoids 0 collision.
        raw_id = j.get("id_icims") or j.get("id")
        if not raw_id:
            continue

        path = j.get("job_path") or ""
        url  = f"{JOB_URL_BASE}{path}" if path.startswith("/") else path

        jd_text = " ".join(filter(None, [
            j.get("description"),
            j.get("basic_qualifications"),
            j.get("preferred_qualifications"),
        ])).strip()

        jobs.append({
            "id":        f"az_{raw_id}",
            "ats":       "amazon",
            "company":   "Amazon",
            "title":     j.get("title", ""),
            "location":  loc,
            "url":       url,
            "remote":    "remote" in loc.lower() or "virtual" in loc.lower(),
            "jd_text":   jd_text,
            "comp":      parse_comp(jd_text),
            "posted_at": _parse_posted(j.get("posted_date", "")),
        })

    time.sleep(0.5)
    return jobs


def _parse_posted(s: str) -> str:
    """'May 21, 2026' → ISO. Empty on failure."""
    if not s:
        return ""
    try:
        return datetime.strptime(s, "%B %d, %Y").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return ""
