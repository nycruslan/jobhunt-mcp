"""
LinkedIn connection matching — finds your contacts at a given company.
Reads from the official LinkedIn data export CSV (YOUR data, TOS-compliant).
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

CSV_PATH = Path(__file__).parent / "linkedin.csv"


@lru_cache(maxsize=1)
def _load_connections() -> list[dict]:
    """Load and cache all connections from the LinkedIn export CSV."""
    if not CSV_PATH.exists():
        return []

    connections = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        # LinkedIn adds a notes block before the actual CSV header — skip it
        lines = f.readlines()
        start = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("First Name"):
                start = i
                break

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
    Uses fuzzy matching to handle variants (e.g. 'JPMorgan' vs 'JPMorgan Chase').
    """
    connections = _load_connections()
    pattern = _build_pattern(company_name)
    return [c for c in connections if pattern.search(c["company"])]


def total_connections() -> int:
    return len(_load_connections())


# Generic words that must never match on their own, or "AI", "Capital", "Labs"
# style tokens would pull in dozens of unrelated employers.
_GENERIC_TOKENS = {
    "ai", "ml", "labs", "capital", "technologies", "technology", "systems",
    "solutions", "global", "group", "holdings", "partners", "ventures",
    "software", "digital", "data", "services", "tech", "studio", "studios",
}


def _build_pattern(name: str) -> re.Pattern:
    """Regex that matches a company's distinctive tokens with word boundaries.

    Requires ALL significant tokens to appear (AND, not OR) so "Scale AI" doesn't
    match every "...AI" company, and drops generic words that carry no signal."""
    clean = re.sub(r"\b(inc|llc|ltd|corp|co|&|and|the)\b", "", name, flags=re.I)
    tokens = [w for w in clean.split() if len(w) > 2 and w.lower() not in _GENERIC_TOKENS]
    if not tokens:  # name was all-generic (e.g. "AI Labs") — fall back to the raw name
        tokens = [clean.strip() or name]
    # Each token must be present as a whole word, in any order.
    body = "".join(rf"(?=.*\b{re.escape(t)}\b)" for t in tokens)
    return re.compile(body, re.IGNORECASE)
