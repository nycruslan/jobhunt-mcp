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

from feeds import greenhouse, lever, ashby, amazon, workday, netflix
from feeds import jobspy as jobspy_feed

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
    score_fn: Callable[[str, str, str], int],
    upsert_fn: Callable[[dict], bool],
    include_jobspy: bool,
) -> tuple[int, list[tuple[str, str]], list[tuple[str, str]]]:
    """Pull every company (+ optional JobSpy), score, and upsert each job.

    Everything fetched is stored so nothing is lost at ingest; callers filter by
    score at display time. Returns (new_count, errors, skipped) where errors and
    skipped are lists of (name, detail) for the caller to report however it likes.
    """
    new_count = 0
    errors: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []

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
            j["score"] = score_fn(j.get("title", ""), j.get("jd_text", ""), name)
            if upsert_fn(j):
                new_count += 1
        log.info("Fetched %s: %d jobs", name, len(jobs))

    if include_jobspy:
        try:
            for j in jobspy_feed.fetch_jobs():
                j["score"] = score_fn(j.get("title", ""), j.get("jd_text", ""), j.get("company", ""))
                if upsert_fn(j):
                    new_count += 1
        except Exception as e:
            log.warning("JobSpy feed error: %s", e)
            errors.append(("JobSpy (Indeed)", str(e)))

    return new_count, errors, skipped
