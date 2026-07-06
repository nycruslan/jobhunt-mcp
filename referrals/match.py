"""
LinkedIn connection matching — finds your contacts at a given company.
Reads from the official LinkedIn data export CSV (YOUR data, TOS-compliant).
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

import config

CSV_PATH = Path(__file__).parent / "linkedin.csv"


@config.mtime_cached(CSV_PATH)
def _load_connections() -> list[dict]:
    """Load all connections from the LinkedIn export CSV. Cached until the
    file's mtime changes, so replacing linkedin.csv takes effect without an
    MCP server restart."""
    if not CSV_PATH.exists():
        return []

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        # LinkedIn adds a notes block before the actual CSV header — skip it
        lines = f.readlines()
        start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("First Name"):
                start = i
                break
        if start is None:
            raise ValueError(
                f"{CSV_PATH} doesn't look like a LinkedIn connections export: "
                "no 'First Name,Last Name,...' header row found. Re-export your "
                "connections from LinkedIn (Settings > Data privacy > Get a copy "
                "of your data) and copy the Connections.csv here unmodified."
            )

        connections = []
        reader = csv.DictReader(lines[start:])
        for row in reader:
            company = (row.get("Company") or "").strip()
            if not company:
                continue
            connections.append({
                "first_name":  (row.get("First Name") or "").strip(),
                "last_name":   (row.get("Last Name") or "").strip(),
                "name":        f"{row.get('First Name', '').strip()} {row.get('Last Name', '').strip()}".strip(),
                "position":    (row.get("Position") or "").strip(),
                "company":     company,
                "profile_url": (row.get("URL") or "").strip(),
                "connected_on":(row.get("Connected On") or "").strip(),
            })
    return connections


def find_contacts(company_name: str) -> list[dict]:
    """
    Find LinkedIn connections who work at company_name.
    Uses fuzzy token matching to handle variants: a query of 'JPMorgan Chase'
    matches a CSV entry of 'JPMorgan' (and vice versa) because one side's
    significant tokens are a subset of the other's.
    """
    query = _tokens(company_name)
    if not query:
        return []
    matches = []
    for c in _load_connections():
        toks = _tokens(c["company"])
        if toks and (query <= toks or toks <= query):
            matches.append(c)
    return matches


def total_connections() -> int:
    return len(_load_connections())


# Generic words that must never match on their own, or "AI", "Capital", "Labs"
# style tokens would pull in dozens of unrelated employers.
_GENERIC_TOKENS = {
    "ai", "ml", "labs", "capital", "technologies", "technology", "systems",
    "solutions", "global", "group", "holdings", "partners", "ventures",
    "software", "digital", "data", "services", "tech", "studio", "studios",
}

_LEGAL_SUFFIXES = re.compile(r"\b(inc|llc|ltd|corp|co|and|the)\b", re.I)


@lru_cache(maxsize=4096)
def _tokens(name: str) -> frozenset[str]:
    """A company name's significant tokens, lower-cased.

    '&' and other punctuation separate tokens (so "AT&T" -> {"at", "t"} and
    "H&M" -> {"h", "m"} instead of being mangled). Legal suffixes and generic
    words are dropped, as are tokens of <= 2 chars — unless that filter would
    empty the set (e.g. "HP", "EA", "AT&T"), in which case every word is kept
    so short names stay matchable."""
    clean = _LEGAL_SUFFIXES.sub(" ", name)
    words = [w.lower() for w in re.findall(r"[a-z0-9']+", clean, re.I)]
    toks = [w for w in words if len(w) > 2 and w not in _GENERIC_TOKENS]
    if not toks:  # name was all-short or all-generic — fall back to every word
        toks = words
    return frozenset(toks)
