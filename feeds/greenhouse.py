"""
Greenhouse public job board API.
Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Fully public, candidate-facing. No auth.
"""
from __future__ import annotations

import logging
import time

import requests

from feeds._http import build_session, html_to_text, DEFAULT_TIMEOUT
from feeds._location import is_local_or_remote
from feeds._comp import comp_from_cents, parse_comp

log = logging.getLogger(__name__)

BASE = "https://boards-api.greenhouse.io/v1/boards"
SESSION = build_session()


def _comp_from_pay_ranges(ranges: list) -> str:
    """First USD annual range in Greenhouse's pay_input_ranges, as a band string."""
    for r in ranges or []:
        band = comp_from_cents(
            r.get("min_cents"), r.get("max_cents"), r.get("currency_type", "USD")
        )
        if band:
            return band
    return ""


def fetch_jobs(slug: str, keyword: str = "") -> list[dict]:
    """Fetch jobs from a Greenhouse board. Returns normalized dicts."""
    params = {"content": "true", "pay_transparency": "true"}
    if keyword:
        params["q"] = keyword

    try:
        r = SESSION.get(f"{BASE}/{slug}/jobs", params=params, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.warning("Greenhouse slug not found: %s", slug)
            return []
        log.error("Greenhouse fetch failed for %s: %s", slug, e)
        return []
    except requests.RequestException as e:
        log.error("Greenhouse fetch failed for %s: %s", slug, e)
        return []

    raw = r.json()
    company = raw.get("company", {}).get("name", slug)
    jobs: list[dict] = []

    for j in raw.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        if not is_local_or_remote(loc):
            continue

        jd_text = html_to_text(j.get("content", ""))
        comp = _comp_from_pay_ranges(j.get("pay_input_ranges")) or parse_comp(jd_text)

        jobs.append({
            "id":        f"gh_{slug}_{j['id']}",
            "ats":       "greenhouse",
            "company":   company,
            "title":     j.get("title", ""),
            "location":  loc,
            "url":       j.get("absolute_url", ""),
            "remote":    "remote" in loc.lower(),
            "jd_text":   jd_text,
            "comp":      comp,
            "posted_at": j.get("updated_at", "") or j.get("first_published", ""),
        })

    time.sleep(0.5)  # polite pause
    return jobs
