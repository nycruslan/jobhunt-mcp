"""
Lever public job posting API.
Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json
Fully public, candidate-facing. No auth.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

from feeds._http import build_session, html_to_text, DEFAULT_TIMEOUT
from feeds._location import is_local_or_remote
from feeds._comp import parse_comp, comp_from_amounts

log = logging.getLogger(__name__)

BASE = "https://api.lever.co/v0/postings"
SESSION = build_session()


def _comp_from_salary_range(sr: dict) -> str:
    """Lever salaryRange: {min, max, currency, interval}. USD only."""
    if not sr or (sr.get("currency") or "USD").upper() != "USD":
        return ""
    return comp_from_amounts(sr.get("min"), sr.get("max"), sr.get("interval", ""))


def fetch_jobs(slug: str, keyword: str = "") -> list[dict]:
    """Fetch jobs from a Lever board. Returns normalized dicts."""
    try:
        r = SESSION.get(f"{BASE}/{slug}", params={"mode": "json", "limit": 250},
                        timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.warning("Lever slug not found: %s", slug)
            return []
        log.error("Lever fetch failed for %s: %s", slug, e)
        return []
    except requests.RequestException as e:
        log.error("Lever fetch failed for %s: %s", slug, e)
        return []

    jobs: list[dict] = []
    for j in r.json():
        loc = j.get("categories", {}).get("location", "")
        if not is_local_or_remote(loc):
            continue

        title = j.get("text", "")
        if keyword and keyword.lower() not in title.lower():
            continue

        # JD text — join all section "text" + cleaned bullet items
        jd_parts: list[str] = []
        for section in j.get("lists", []):
            jd_parts.append(section.get("text", ""))
            jd_parts.append(html_to_text(section.get("content", "")))
        jd_text = "\n".join(p for p in jd_parts if p).strip()

        # createdAt comes as ms-since-epoch
        created_ms = j.get("createdAt", 0)
        posted_iso = (datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
                      if created_ms else "")

        # Structured salaryRange when Lever has it (dollars), else scrape the JD.
        sr = j.get("salaryRange") or {}
        comp = _comp_from_salary_range(sr) or parse_comp(jd_text)

        jobs.append({
            "id":        f"lv_{slug}_{j['id']}",
            "ats":       "lever",
            "company":   slug.replace("-", " ").title(),
            "title":     title,
            "location":  loc,
            "url":       j.get("hostedUrl", ""),
            "remote":    "remote" in loc.lower(),
            "jd_text":   jd_text,
            "comp":      comp,
            "posted_at": posted_iso,
        })

    time.sleep(0.5)
    return jobs
