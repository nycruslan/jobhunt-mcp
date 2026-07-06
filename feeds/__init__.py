"""
Feed orchestration — one place that knows how to pull a company's jobs.

Both the MCP server and the daily briefing used to carry their own copy of the
"if ats == greenhouse / lever / ashby / ..." switch. They now share these two
helpers, so adding a feed or changing dispatch happens in exactly one spot.

Layering: this module depends on the individual feed modules only. Scoring and
storage are passed in as callables so feeds never import tracker or score.
"""
from __future__ import annotations

import logging
from typing import Callable

import config
from feeds import greenhouse, lever, ashby, amazon, workday, netflix
from feeds import jobspy as jobspy_feed
from feeds import adzuna as adzuna_feed
from feeds import remotive as remotive_feed
from feeds._filters import is_agency

log = logging.getLogger(__name__)


class FeedConfigError(ValueError):
    """A target is misconfigured (e.g. Workday missing host/tenant/site)."""


def fetch_for_company(co: dict) -> list[dict]:
    """Fetch normalized job dicts for one targets.yaml company entry.

    Returns [] for manual-apply or unknown ATS. Raises FeedConfigError when a
    Workday entry is missing required config. The company name from targets.yaml
    is stamped onto every job so it stays canonical across feeds.
    """
    ats  = (co.get("ats") or "").strip()
    name = co["name"]
    slug = co.get("slug", "")

    if ats == "greenhouse" and slug:
        jobs = greenhouse.fetch_jobs(slug)
    elif ats == "lever" and slug:
        jobs = lever.fetch_jobs(slug)
    elif ats == "ashby" and slug:
        jobs = ashby.fetch_jobs(slug)
    elif ats == "amazon":
        jobs = amazon.fetch_jobs()
    elif ats == "netflix":
        jobs = netflix.fetch_jobs()
    elif ats == "workday":
        wd = co.get("workday") or {}
        if not (wd.get("host") and wd.get("tenant") and wd.get("site")):
            raise FeedConfigError("workday config missing host/tenant/site")
        jobs = workday.fetch_jobs(
            host=wd["host"], tenant=wd["tenant"], site=wd["site"], company_name=name,
        )
    else:
        return []  # manual-apply or unknown ATS — no public API

    for j in jobs:
        j["company"] = name
    return jobs


def pull(
    companies: list[dict],
    *,
    score_fn: Callable[..., int],
    upsert_fn: Callable[[dict], bool],
    include_jobspy: bool = False,
    include_adzuna: bool = False,
    include_remotive: bool = False,
) -> tuple[int, list[tuple[str, str]], list[tuple[str, str]]]:
    """Pull every target company plus any enabled aggregator feed, score, upsert.

    The ATS feeds are the curated, high-signal core. Aggregators (Adzuna, Remotive,
    JobSpy) add market breadth and are deduped against the ATS results and each
    other by (canonical company, title, location) — company runs through
    company_aliases() so alias spellings collapse, and location keeps the same
    title in different cities distinct. Everything fetched is stored; callers
    filter by score at display time. Returns (new_count, errors, skipped).
    """
    new_count = 0
    errors: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    aliases = config.company_aliases()

    def _key(j: dict) -> tuple[str, str, str]:
        co = (j.get("company") or "").strip().lower()
        co = str(aliases.get(co, co)).strip().lower()
        return (co,
                (j.get("title") or "").strip().lower(),
                config.slugify(j.get("location") or ""))

    def _store(j: dict, company: str) -> None:
        nonlocal new_count
        try:
            j["score"] = score_fn(j.get("title", ""), j.get("jd_text", ""), company, j.get("comp", ""))
            if upsert_fn(j):
                new_count += 1
        except Exception as e:  # one bad row never sinks the batch
            log.warning("Store failed for %s — %s: %s", company, j.get("title", ""), e)
            errors.append((company, f"store failed: {e}"))

    # ── Curated ATS feeds (high-signal core) ──────────────────────────────────
    for co in companies:
        name = co["name"]
        ats  = (co.get("ats") or "").strip()

        if ats == "manual":
            skipped.append((name, co.get("url", "career site")))
            continue

        try:
            jobs = fetch_for_company(co)
        except FeedConfigError as e:
            skipped.append((name, str(e)))
            continue
        except Exception as e:  # one bad feed never sinks the whole run
            log.warning("Feed error for %s (%s): %s", name, ats, e)
            errors.append((name, str(e)))
            continue

        for j in jobs:
            _store(j, name)
            seen.add(_key(j))
        log.info("Fetched %s: %d jobs", name, len(jobs))

    # ── Aggregators (market breadth), deduped against the ATS core + each other ─
    aggregators = []
    if include_adzuna:
        aggregators.append(("Adzuna", adzuna_feed))
    if include_remotive:
        aggregators.append(("Remotive", remotive_feed))
    if include_jobspy:
        aggregators.append(("JobSpy (Indeed)", jobspy_feed))

    for label, mod in aggregators:
        try:
            fetched = mod.fetch_jobs()
        except Exception as e:  # a flaky aggregator never sinks the run
            log.warning("%s feed error: %s", label, e)
            errors.append((label, str(e)))
            continue
        kept = 0
        for j in fetched:
            if is_agency(j.get("company", "")):
                continue  # staffing/recruiting reposters, not the real employer
            k = _key(j)
            if k in seen:
                continue
            seen.add(k)
            _store(j, j.get("company", ""))
            kept += 1
        log.info("%s: %d new after dedup (of %d fetched)", label, kept, len(fetched))

    return new_count, errors, skipped
