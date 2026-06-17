"""
Quality filters shared by the market-wide aggregator feeds (Adzuna, Remotive,
JobSpy). The curated ATS feeds are already high-signal and skip these.

`is_agency` drops staffing / recruiting reposters whose "company" is really a
middleman, so the tracker stays a list of actual employers.
"""
from __future__ import annotations

import re

# Whole-word cues that a "company" is a staffing agency, recruiter, or job-mill
# repost rather than the real employer. Word-boundary matched so "Consulting" as
# a standalone token fires but substrings inside a real name do not.
_AGENCY_RE = re.compile(
    r"\b(staffing|recruit\w*|recruitment|consult\w*|search\s*&\s*selection"
    r"|talent|headhunt\w*|placement|staffing solutions|workforce|resourcing"
    r"|outsourc\w*|manpower|temp agency|contract\w* agency)\b",
    re.IGNORECASE,
)


def is_agency(company: str) -> bool:
    """True when the company name looks like a staffing/recruiting reposter."""
    return bool(company) and bool(_AGENCY_RE.search(company))
