"""
Amazon Jobs public search API.
Endpoint: https://www.amazon.jobs/en/search.json
Public, candidate-facing. No auth. Cap is 100 results per request; paginated
via `offset`. Note: the API silently ignores `country[]` — the working US
filter is `normalized_country_code[]=USA` (live-verified).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from feeds._http import build_session, DEFAULT_TIMEOUT
from feeds._location import is_local_or_remote
from feeds._comp import parse_comp

log = logging.getLogger(__name__)

BASE         = "https://www.amazon.jobs/en/search.json"
JOB_URL_BASE = "https://www.amazon.jobs"
PAGE_LIMIT   = 100  # Amazon's per-request max
MAX_PAGES    = 3
SESSION      = build_session()


def fetch_jobs() -> list[dict]:
    """Fetch recent US Amazon software roles, NYC-filtered.

    Request errors propagate to the caller (feeds.pull records them per company).
    """
    jobs: list[dict] = []
    for page in range(MAX_PAGES):
        if page:
            time.sleep(0.5)  # polite pause between pages
        params: dict = {
            "result_limit":                PAGE_LIMIT,
            "offset":                      page * PAGE_LIMIT,
            "sort":                        "recent",
            "normalized_country_code[]":   "USA",
            "category[]":                  "software-development",
        }
        r = SESSION.get(BASE, params=params, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()

        page_jobs = r.json().get("jobs", [])
        for j in page_jobs:
            loc = j.get("location") or j.get("normalized_location") or ""
            if not is_local_or_remote(loc):
                continue

            # Stable ID: prefer icims, fall back to internal id. Truthy check avoids 0 collision.
            # Prefix is amzn_ (not az_) so it never shares a namespace with Adzuna.
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
                "id":        f"amzn_{raw_id}",
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

        if len(page_jobs) < PAGE_LIMIT:
            break

    return jobs


def _parse_posted(s: str) -> str:
    """'May 21, 2026' → ISO. Empty on failure."""
    if not s:
        return ""
    try:
        return datetime.strptime(s, "%B %d, %Y").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return ""
