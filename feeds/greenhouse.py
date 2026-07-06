"""
Greenhouse public job board API.
Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Fully public, candidate-facing. No auth.
"""
from __future__ import annotations

import logging

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


def fetch_jobs(slug: str) -> list[dict]:
    """Fetch jobs from a Greenhouse board. Returns normalized dicts.

    Request errors propagate to the caller (feeds.pull records them per company);
    only a 404 — dead slug — is handled here as a warning + empty list.
    """
    # The list endpoint honors pay_transparency (verified); a `q` keyword param
    # is silently ignored, so we don't send one.
    params = {"content": "true", "pay_transparency": "true"}

    r = SESSION.get(f"{BASE}/{slug}/jobs", params=params, timeout=DEFAULT_TIMEOUT)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.warning("Greenhouse slug not found: %s", slug)
            return []
        raise

    raw = r.json()
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
            # The board payload has no top-level company; each job carries it.
            "company":   j.get("company_name") or slug,
            "title":     j.get("title", ""),
            "location":  loc,
            "url":       j.get("absolute_url", ""),
            "remote":    "remote" in loc.lower(),
            "jd_text":   jd_text,
            "comp":      comp,
            # first_published is when candidates first saw it; updated_at moves
            # on any edit and inflates freshness.
            "posted_at": j.get("first_published", "") or j.get("updated_at", ""),
        })

    return jobs
