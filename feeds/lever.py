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
PAGE_LIMIT = 250  # Lever's per-request max
MAX_PAGES  = 4


def _comp_from_salary_range(sr: dict) -> str:
    """Lever salaryRange: {min, max, currency, interval}. USD only."""
    if not sr or (sr.get("currency") or "USD").upper() != "USD":
        return ""
    return comp_from_amounts(sr.get("min"), sr.get("max"), sr.get("interval", ""))


def fetch_jobs(slug: str) -> list[dict]:
    """Fetch jobs from a Lever board, paginated via `skip`. Returns normalized dicts.

    Request errors propagate to the caller (feeds.pull records them per company);
    only a 404 — dead slug — is handled here as a warning + empty list.
    """
    postings: list[dict] = []
    for page in range(MAX_PAGES):
        if page:
            time.sleep(0.5)  # polite pause between pages
        r = SESSION.get(
            f"{BASE}/{slug}",
            params={"mode": "json", "limit": PAGE_LIMIT, "skip": page * PAGE_LIMIT},
            timeout=DEFAULT_TIMEOUT,
        )
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                log.warning("Lever slug not found: %s", slug)
                return []
            raise
        batch = r.json()
        postings.extend(batch)
        if len(batch) < PAGE_LIMIT:
            break

    if not postings:
        # 200 with an empty board usually means the company left Lever
        # (plaid/voleon rotted this way) — worth flagging, not an error.
        log.warning("Lever board %s returned 0 postings — dead slug?", slug)

    jobs: list[dict] = []
    for j in postings:
        loc = j.get("categories", {}).get("location", "")
        if not is_local_or_remote(loc):
            continue

        title = j.get("text", "")

        # JD text — the pay-transparency block lives in descriptionPlain (and
        # sometimes additionalPlain), not in the lists[] sections.
        jd_parts: list[str] = [j.get("descriptionPlain", "")]
        for section in j.get("lists", []):
            jd_parts.append(section.get("text", ""))
            jd_parts.append(html_to_text(section.get("content", "")))
        jd_parts.append(j.get("additionalPlain", ""))
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

    return jobs
