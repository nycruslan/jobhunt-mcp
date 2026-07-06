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
from datetime import date, datetime, timezone
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

_RESULTS_PER = 25   # per search term on Indeed
_HOURS_OLD   = 48   # on weekdays; callers may override


def _search_location() -> str:
    """'City, ST' search anchor derived from profile preferences, not hardcoded."""
    import config

    p = config.preferences()
    city  = (p.get("home_terms") or ["new york"])[0].title()
    state = (p.get("home_states") or ["NY"])[0].upper()
    return f"{city}, {state}"


def _google_search_term(city: str) -> str:
    return (f"senior software engineer AI machine learning {city} remote"
            " site:jobs.google.com OR site:greenhouse.io OR site:lever.co")


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


# Query params that are pure tracking noise. Everything else stays — Indeed's
# job identity lives in the query string (viewjob?jk=<id>), so stripping it
# whole collapsed every Indeed job to one id.
_TRACKING_PARAMS = ("gclid", "fbclid", "ref", "source")


def _url_hash(url: str) -> str:
    """12-char stable hash of a URL with tracking params and fragment removed.

    Remaining params are sorted so reordering doesn't change the id."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    if not url:
        return hashlib.sha1(b"").hexdigest()[:12]
    parts = urlsplit(url)
    params = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.startswith("utm_") or k in _TRACKING_PARAMS)
    )
    canonical = urlunsplit(
        (parts.scheme, parts.netloc, parts.path.rstrip("/"), urlencode(params), "")
    )
    return hashlib.sha1(canonical.encode()).hexdigest()[:12]


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

    # Stable ID: hash the URL with tracking params + fragment stripped, so the
    # same posting stays idempotent across runs even when Indeed/Google append
    # rotating utm noise, while distinct jobs (?jk=<id>) keep distinct ids.
    job_id   = f"js_{_url_hash(url)}"

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
    }


def fetch_jobs(hours_old: int | None = None) -> list[dict]:
    """
    Scrape Indeed (and attempt Google Jobs) for NYC/remote AI-SWE roles.

    Returns a list of standard job dicts, deduped, location-filtered,
    with company name and title populated.
    """
    try:
        from jobspy import scrape_jobs  # type: ignore
    except ImportError as exc:
        # Surface as a real failure so pull() reports it instead of "0 jobs".
        raise RuntimeError(
            "python-jobspy not installed. Run: pip3.11 install python-jobspy"
        ) from exc

    from feeds._location import is_local_or_remote

    hours    = hours_old if hours_old is not None else _hours_window()
    location = _search_location()
    seen_urls: set[str] = set()
    results: list[dict] = []
    term_errors: list[Exception] = []

    # ── Indeed: multiple search terms, deduplicated ────────────────────────
    for term in _INDEED_SEARCHES:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = scrape_jobs(
                    site_name=["indeed"],
                    search_term=term,
                    location=location,
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
            term_errors.append(exc)

    # Every term failing is an outage, not an empty market — surface it.
    if term_errors and len(term_errors) == len(_INDEED_SEARCHES):
        raise term_errors[-1]

    # ── Google Jobs: best-effort, skip silently if empty/fails ────────────
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gdf = scrape_jobs(
                site_name=["google"],
                google_search_term=_google_search_term(location.split(",")[0]),
                location=location,
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
