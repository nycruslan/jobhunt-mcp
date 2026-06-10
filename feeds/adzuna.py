"""
Adzuna public job-search API — broad US market coverage beyond the curated
targets.yaml list. Needs a free developer key (app_id + app_key) from
https://developer.adzuna.com; returns [] when it isn't configured.

READ-ONLY: search only. One request per target role, home-area, recent postings.
"""
from __future__ import annotations

import hashlib
import logging

import requests

import config
from feeds._http import build_session, html_to_text, DEFAULT_TIMEOUT
from feeds._location import is_local_or_remote
from feeds._comp import comp_from_amounts

log = logging.getLogger(__name__)

BASE = "https://api.adzuna.com/v1/api/jobs/us/search/1"
SESSION = build_session()
MAX_ROLES = 4
RESULTS_PER = 50
MAX_DAYS_OLD = 4


def fetch_jobs() -> list[dict]:
    app_id = config.secret("ADZUNA_APP_ID")
    app_key = config.secret("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []

    prefs = config.preferences()
    where = (prefs.get("home_terms") or ["New York"])[0]
    roles = config.profile().get("target_roles") or ["software engineer"]

    seen: set[str] = set()
    out: list[dict] = []
    for role in roles[:MAX_ROLES]:
        try:
            r = SESSION.get(
                BASE,
                params={
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": role,
                    "where": where,
                    "results_per_page": RESULTS_PER,
                    "max_days_old": MAX_DAYS_OLD,
                },
                timeout=DEFAULT_TIMEOUT,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("Adzuna '%s' failed: %s", role, e)
            continue

        for j in r.json().get("results", []):
            url = j.get("redirect_url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            title = html_to_text(j.get("title", ""))
            company = ((j.get("company") or {}).get("display_name") or "").strip()
            loc = ((j.get("location") or {}).get("display_name") or "").strip()
            if not title or not company or not is_local_or_remote(loc):
                continue
            out.append({
                "id":        f"az_{hashlib.sha1(url.encode()).hexdigest()[:12]}",
                "ats":       "adzuna",
                "company":   company,
                "title":     title,
                "location":  loc,
                "url":       url,
                "remote":    "remote" in loc.lower(),
                "jd_text":   html_to_text(j.get("description", "")),
                "comp":      comp_from_amounts(j.get("salary_min"), j.get("salary_max")),
                "posted_at": j.get("created", "") or "",
            })

    log.info("Adzuna fetched %d jobs", len(out))
    return out
