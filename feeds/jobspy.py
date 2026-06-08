"""
JobSpy supplemental feed — scrapes Indeed (+ Google Jobs when available).

Catches roles from companies without public ATS APIs (Meta, Google, Apple,
Microsoft, DoorDash, Zoom, Snowflake, Coinbase, etc.) by scraping the
aggregator boards they all post to.

Design rules:
- READ-ONLY: we only scrape, never interact with job boards on the candidate's behalf.
- Indeed only by default; google site attempted but silently skipped if empty.
- Deduplication by URL across both sites and across multiple search terms.
- All results run through the shared NYC/remote location filter.
- ID prefix "js_" distinguishes these from ATS-sourced jobs.
"""
from __future__ import annotations

import hashlib
import logging
import warnings
from datetime import date, datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

# Search terms that cover senior SWE + AI/ML roles
_INDEED_SEARCHES = [
    "senior software engineer AI machine learning",
    "staff software engineer AI",
    "principal engineer machine learning",
    "senior backend engineer",
    "senior ML engineer",
]

_GOOGLE_SEARCH_TERM = (
    "senior software engineer AI machine learning New York NYC remote site:jobs.google.com OR"
    " site:greenhouse.io OR site:lever.co"
)

_LOCATION    = "New York, NY"
_RESULTS_PER = 25   # per search term on Indeed
_HOURS_OLD   = 48   # on weekdays; callers may override


def _hours_window() -> int:
    """72h on Mondays (catch weekend posts), 48h otherwise."""
    return 72 if datetime.now(timezone.utc).weekday() == 0 else _HOURS_OLD


def _to_iso(d: Any) -> str:
    """Convert date / datetime / string to ISO-8601 UTC string."""
    if d is None:
        return ""
    if isinstance(d, datetime):
        return d.replace(tzinfo=timezone.utc).isoformat()
    if isinstance(d, date):
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()
    if isinstance(d, str) and d:
        try:
            return datetime.fromisoformat(d.replace("Z", "+00:00")).isoformat()
        except ValueError:
            pass
    return ""


def _safe_str(val: Any) -> str:
    import math
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip()


def _comp_from_row(row: Any, jd_text: str) -> str:
    """Prefer JobSpy's structured salary columns, fall back to scraping the JD."""
    from feeds._comp import comp_from_amounts, parse_comp

    currency = _safe_str(row.get("currency")) or "USD"
    if currency.upper() == "USD":
        band = comp_from_amounts(
            _num(row.get("min_amount")),
            _num(row.get("max_amount")),
            _safe_str(row.get("interval")),
        )
        if band:
            return band
    return parse_comp(jd_text)


def _num(val: Any):
    """Coerce a possibly-NaN/blank DataFrame cell to float or None."""
    import math
    if val is None or val == "":
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _job_from_row(row: Any) -> dict:
    """Map a JobSpy DataFrame row to the standard job dict."""
    url        = _safe_str(row.get("job_url"))
    direct_url = _safe_str(row.get("job_url_direct"))
    apply_url  = direct_url or url

    # Stable ID: hash of the canonical URL so the same posting is idempotent
    url_hash = hashlib.sha1(url.encode()).hexdigest()[:12]
    job_id   = f"js_{url_hash}"

    jd_text = _safe_str(row.get("description"))

    return {
        "id":        job_id,
        "title":     _safe_str(row.get("title")),
        "company":   _safe_str(row.get("company")),
        "location":  _safe_str(row.get("location")),
        "url":       apply_url,
        "jd_text":   jd_text,
        "comp":      _comp_from_row(row, jd_text),
        "posted_at": _to_iso(row.get("date_posted")),
        "remote":    bool(row.get("is_remote")),
        "source":    "jobspy",
    }


def fetch_jobs(hours_old: int | None = None) -> list[dict]:
    """
    Scrape Indeed (and attempt Google Jobs) for NYC/remote AI-SWE roles.

    Returns a list of standard job dicts, deduped, location-filtered,
    with company name and title populated.
    """
    try:
        from jobspy import scrape_jobs  # type: ignore
        import pandas as pd
    except ImportError:
        log.error("python-jobspy not installed. Run: pip3.11 install python-jobspy")
        return []

    from feeds._location import is_local_or_remote

    hours = hours_old if hours_old is not None else _hours_window()
    seen_urls: set[str] = set()
    results: list[dict] = []

    # ── Indeed: multiple search terms, deduplicated ────────────────────────
    for term in _INDEED_SEARCHES:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = scrape_jobs(
                    site_name=["indeed"],
                    search_term=term,
                    location=_LOCATION,
                    results_wanted=_RESULTS_PER,
                    hours_old=hours,
                    country_indeed="usa",
                    verbose=0,
                )
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                url = _safe_str(row.get("job_url"))
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                job = _job_from_row(row)
                if not job["title"] or not job["company"]:
                    continue
                if is_local_or_remote(job["location"]):
                    results.append(job)
        except Exception as exc:
            log.warning("JobSpy/Indeed error for term '%s': %s", term, exc)

    # ── Google Jobs: best-effort, skip silently if empty/fails ────────────
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gdf = scrape_jobs(
                site_name=["google"],
                google_search_term=_GOOGLE_SEARCH_TERM,
                location=_LOCATION,
                results_wanted=20,
                hours_old=hours,
                verbose=0,
            )
        if gdf is not None and not gdf.empty:
            for _, row in gdf.iterrows():
                url = _safe_str(row.get("job_url"))
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                job = _job_from_row(row)
                if not job["title"] or not job["company"]:
                    continue
                if is_local_or_remote(job["location"]):
                    results.append(job)
    except Exception as exc:
        log.debug("JobSpy/Google skipped: %s", exc)

    log.info("JobSpy fetched %d unique NYC/remote jobs (window: %dh)", len(results), hours)
    return results
