"""
Generic Workday Career Site (CXS) JSON client.

Endpoint pattern: https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

Public, candidate-facing. No auth. Workday exposes location facets we use
for server-side NYC filtering.

Add a Workday company in targets.yaml with:
    ats: workday
    workday: { host: nvidia.wd5, tenant: nvidia, site: NVIDIAExternalCareerSite }
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from feeds._http import build_session, html_to_text, DEFAULT_TIMEOUT
from feeds._location import is_local_or_remote
from feeds._comp import parse_comp

log = logging.getLogger(__name__)

SESSION    = build_session(content_type_json=True)
PAGE_LIMIT = 20  # Workday's per-request cap
MAX_PAGES  = 3   # up to 60 NYC-filtered roles per tenant — plenty, and every one gets its JD

_DIGIT_RE = re.compile(r"(\d+)")


def fetch_jobs(host: str, tenant: str, site: str, company_name: str = "") -> list[dict]:
    """Fetch NYC-relevant jobs from a Workday tenant."""
    base_url = f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    display  = company_name or tenant.title()

    location_ids = _discover_nyc_location_ids(base_url)
    if not location_ids:
        log.warning("Workday %s: no NYC/US-Remote location facets found", tenant)
        return []

    jobs: list[dict] = []
    for page in range(MAX_PAGES):
        body = {
            "appliedFacets": {"locations": location_ids},
            "limit":         PAGE_LIMIT,
            "offset":        page * PAGE_LIMIT,
            "searchText":    "",
        }
        try:
            r = SESSION.post(base_url, json=body, timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("Workday %s page %d failed: %s", tenant, page, e)
            break

        page_jobs = r.json().get("jobPostings", [])
        if not page_jobs:
            break

        for j in page_jobs:
            normalized = _normalize(j, host, tenant, site, display)
            if not normalized:
                continue
            # Backfill the description from the job-detail endpoint so Workday
            # roles score on real content, not just their title.
            path = j.get("externalPath") or ""
            if path:
                normalized["jd_text"] = _fetch_jd(base_url, path)
                normalized["comp"] = parse_comp(normalized["jd_text"])
                time.sleep(0.3)
            jobs.append(normalized)

        if len(page_jobs) < PAGE_LIMIT:
            break
        time.sleep(0.5)

    log.info("Workday %s: %d jobs after NYC filter", tenant, len(jobs))
    return jobs


def _fetch_jd(base_url: str, external_path: str) -> str:
    """GET the Workday job-detail endpoint and return cleaned description text."""
    try:
        r = SESSION.get(base_url.rsplit("/jobs", 1)[0] + external_path, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return ""
        info = r.json().get("jobPostingInfo", {})
        return html_to_text(info.get("jobDescription", ""))
    except requests.RequestException:
        return ""


# ── Internals ─────────────────────────────────────────────────────────────────

def _discover_nyc_location_ids(base_url: str) -> list[str]:
    """One call with no filter to get the location facet tree, then extract IDs."""
    try:
        r = SESSION.post(base_url, json={"limit": 1, "offset": 0, "searchText": ""},
                         timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("Workday facet discovery failed for %s: %s", base_url, e)
        return []

    ids: list[str] = []
    for facet in r.json().get("facets", []):
        _collect_nyc_ids(facet, ids)
    return ids


def _collect_nyc_ids(node: dict, out: list[str]) -> None:
    """Recursively walk Workday's nested facet tree, picking NYC/US-Remote IDs."""
    if node.get("facetParameter") == "locations":
        for v in node.get("values", []):
            if is_local_or_remote(v.get("descriptor", "")) and v.get("id"):
                out.append(v["id"])
        return
    for v in node.get("values", []):
        if isinstance(v, dict) and v.get("values") is not None:
            _collect_nyc_ids(v, out)


def _normalize(j: dict, host: str, tenant: str, site: str, company_name: str) -> Optional[dict]:
    """Convert one Workday jobPosting into our standard job dict.

    Server-side facets guarantee every result is NYC-available, even if the
    primary externalPath city is elsewhere.
    """
    path  = j.get("externalPath") or ""
    title = j.get("title", "")
    if not path or not title:
        return None

    loc_raw      = (j.get("locationsText") or "").strip()
    primary_city = _city_from_path(path)

    if "Location" in loc_raw:  # "2 Locations" / "5 Locations"
        loc_text = (f"NYC + {primary_city}"
                    if primary_city and "ny" not in primary_city.lower()
                    else "NYC")
    else:
        loc_text = loc_raw or primary_city or "NYC"

    job_id = (j.get("bulletFields") or [path.rsplit("_", 1)[-1]])[0]

    return {
        "id":        f"wd_{tenant}_{job_id}",
        "ats":       "workday",
        "company":   company_name,
        "title":     title,
        "location":  loc_text,
        # Candidate-facing URL uses the SITE path, not the tenant (the tenant
        # only appears in the internal /wday/cxs/ data endpoint). Using the
        # tenant here 404s. externalPath already begins with "/job/...".
        "url":       f"https://{host}.myworkdayjobs.com/{site}{path}",
        "remote":    "remote" in loc_text.lower(),
        "jd_text":   "",  # filled by fetch_jobs from the job-detail endpoint
        "posted_at": _parse_workday_date(j.get("postedOn", "")),
    }


def _city_from_path(path: str) -> str:
    """Extract city from `/job/US-CA-Santa-Clara/Title_JR123` style paths."""
    parts = path.split("/")
    if len(parts) < 3:
        return ""
    chunks = parts[2].split("-")
    # Drop "US" + 2-letter state when present
    if len(chunks) >= 3 and chunks[0].upper() == "US" and len(chunks[1]) == 2:
        return " ".join(chunks[2:])
    return parts[2].replace("-", " ")


def _parse_workday_date(s: str) -> str:
    """'Posted Today' / 'Posted 5 Days Ago' / 'Posted 30+ Days Ago' → ISO."""
    if not s:
        return ""
    s_lower = s.lower().strip()
    if "today" in s_lower:
        days = 0
    elif "yesterday" in s_lower:
        days = 1
    elif "30+" in s_lower:
        days = 30
    else:
        m = _DIGIT_RE.search(s_lower)
        days = int(m.group(1)) if m else 0
    posted = datetime.now(timezone.utc) - timedelta(days=days)
    return posted.isoformat()
