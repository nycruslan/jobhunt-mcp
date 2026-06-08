"""
Netflix careers feed — Eightfold ATS public positions API.
Endpoint: https://explore.jobs.netflix.net/api/apply/v2/jobs
Public, candidate-facing. No auth.

Netflix has no Greenhouse/Lever/Ashby board; it runs on Eightfold. The list
endpoint omits the full job_description, so jobs come through with empty jd_text
(same as Workday). The scorer leans on title + company comp for these, and
Netflix's pay band makes them worth surfacing regardless.
"""
from __future__ import annotations

import logging
import time

import requests

from feeds._http import build_session, html_to_text, DEFAULT_TIMEOUT
from feeds._location import is_local_or_remote
from feeds._comp import parse_comp

log = logging.getLogger(__name__)

BASE    = "https://explore.jobs.netflix.net/api/apply/v2/jobs"
JOB_URL = "https://explore.jobs.netflix.net/careers/job"
SESSION = build_session()

# Eightfold caps results per call; a few queries cover the candidate's target roles.
_QUERIES   = ["software engineer", "machine learning", "AI"]
_PER_QUERY = 50
_JD_CAP    = 60   # max per-job description fetches per run (politeness + speed)


def _fetch_jd(raw_id: str) -> str:
    """Pull the full description from the Eightfold position-detail endpoint."""
    try:
        r = SESSION.get(f"{BASE}/{raw_id}", params={"domain": "netflix.com"},
                        timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return ""
        d = r.json()
        # Detail endpoint returns the position object directly (job_description at
        # top level); the list endpoint wraps it under positions[].
        pos = d if "job_description" in d else (d.get("positions") or [{}])[0]
        return html_to_text(pos.get("job_description", ""))
    except requests.RequestException:
        return ""


def fetch_jobs(slug: str = "", keyword: str = "") -> list[dict]:
    """Fetch NYC/remote Netflix engineering roles. slug ignored (signature parity)."""
    seen: set[str] = set()
    jobs: list[dict] = []

    for q in _QUERIES:
        params = {
            "domain":   "netflix.com",
            "query":    keyword or q,
            "location": "New York",
            "start":    0,
            "num":      _PER_QUERY,
        }
        try:
            r = SESSION.get(BASE, params=params, timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("Netflix fetch failed for '%s': %s", q, e)
            continue

        for p in r.json().get("positions", []):
            raw_id = str(p.get("id") or p.get("ats_job_id") or "")
            if not raw_id or raw_id in seen:
                continue

            # Eightfold returns a primary `location` plus a `locations` list.
            locs = p.get("locations") or []
            primary = p.get("location", "")
            if not (is_local_or_remote(primary) or any(is_local_or_remote(l) for l in locs)):
                continue
            seen.add(raw_id)

            nyc_loc = next((l for l in locs if is_local_or_remote(l)), primary)
            # List view omits the description; fetch it (capped) so these score on merit.
            jd = html_to_text(p.get("job_description", "") or "")
            if not jd and len(jobs) < _JD_CAP:
                jd = _fetch_jd(raw_id)
                time.sleep(0.3)
            jobs.append({
                "id":        f"nf_{raw_id}",
                "ats":       "netflix",
                "company":   "Netflix",
                "title":     p.get("name") or p.get("title", ""),
                "location":  nyc_loc,
                "url":       p.get("canonicalPositionUrl") or f"{JOB_URL}/{raw_id}",
                "remote":    "remote" in (primary or "").lower(),
                "jd_text":   jd,
                "comp":      parse_comp(jd),
                "posted_at": "",
            })
        time.sleep(0.5)

    log.info("Netflix: %d NYC/remote jobs", len(jobs))
    return jobs
