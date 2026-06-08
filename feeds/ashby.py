"""
Ashby public job board API.
Endpoint: https://api.ashbyhq.com/posting-api/job-board/{slug}
Fully public, candidate-facing. No auth.

Ashby returns one of two shapes depending on the board's API version:
  • "jobPostings" — locationName (string), jobUrl, descriptionHtml
  • "jobs"        — location (string) + secondaryLocations (list), jobUrl, descriptionHtml

Either way a role may list its NYC availability only in a SECONDARY location
(OpenAI tags most NYC roles "San Francisco" primary, "New York City" secondary),
so we check every location, not just the primary.
"""
from __future__ import annotations

import logging
import time

import requests

from feeds._http import build_session, html_to_text, DEFAULT_TIMEOUT
from feeds._location import is_local_or_remote
from feeds._comp import parse_comp

log = logging.getLogger(__name__)

BASE = "https://api.ashbyhq.com/posting-api/job-board"
SESSION = build_session()


def _all_locations(posting: dict) -> list[str]:
    """Every location string on a posting, primary + secondary, both shapes."""
    locs = [
        posting.get("locationName", ""),
        posting.get("location", ""),
    ]
    for sec in posting.get("secondaryLocations") or []:
        if isinstance(sec, dict):
            locs.append(sec.get("location", ""))
            addr = (sec.get("address") or {}).get("postalAddress") or {}
            locs.append(addr.get("addressLocality", ""))
            locs.append(addr.get("addressRegion", ""))
        elif isinstance(sec, str):
            locs.append(sec)
    return [l for l in locs if l]


def fetch_jobs(slug: str, keyword: str = "") -> list[dict]:
    """Fetch jobs from an Ashby board. Returns normalized dicts."""
    try:
        r = SESSION.get(f"{BASE}/{slug}", timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.warning("Ashby slug not found: %s", slug)
            return []
        log.error("Ashby fetch failed for %s: %s", slug, e)
        return []
    except requests.RequestException as e:
        log.error("Ashby fetch failed for %s: %s", slug, e)
        return []

    data = r.json()
    company = data.get("organization", {}).get("name", "") or slug.replace("-", " ").title()
    postings = data.get("jobPostings") or data.get("jobs") or []
    jobs: list[dict] = []

    for j in postings:
        locations = _all_locations(j)
        nyc_loc = next((l for l in locations if is_local_or_remote(l)), "")
        if not nyc_loc:
            continue

        title = j.get("title", "")
        if keyword and keyword.lower() not in title.lower():
            continue

        jd_text = html_to_text(j.get("descriptionHtml") or j.get("description", ""))
        # descriptionPlain (when present) is already clean text — better to scan.
        comp = parse_comp(j.get("descriptionPlain") or jd_text)

        jobs.append({
            "id":        f"ab_{slug}_{j['id']}",
            "ats":       "ashby",
            "company":   company,
            "title":     title,
            "location":  nyc_loc,
            "url":       j.get("jobUrl", "") or j.get("applyUrl", ""),
            "remote":    bool(j.get("isRemote")) or "remote" in nyc_loc.lower(),
            "jd_text":   jd_text,
            "comp":      comp,
            "posted_at": j.get("publishedDate", "") or j.get("publishedAt", ""),
        })

    time.sleep(0.5)
    return jobs
