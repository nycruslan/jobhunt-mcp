"""
Shared location filter — used by every feed module.

Driven by `preferences` in profile.yaml so it works for any home base, not just
NYC:
  home_terms    city/borough strings that always pass ("austin", "remote hub")
  home_states   2-letter codes that count as local (e.g. ["NY"] or ["CA","WA"])
  allow_remote  whether remote roles are acceptable at all
  remote_scope  "us"       → US-wide remote passes, state-locked remote elsewhere blocked
                "anywhere" → any remote passes
                "none"     → remote never passes

Policy:
  ✓ A home term appears (wins even inside a multi-location string)
  ✓ Remote within the configured scope
  ✗ State-specific role/remote in a non-home state
  ✗ Multi-state listings that exclude every home state
"""
from __future__ import annotations

import re

from config import preferences

# Remote indicators
REMOTE_TERMS = (
    "remote", "wfh", "work from home", "virtual", "telecommute", "anywhere",
)

# "US, CA, X" / "US-CA-X" / "US CA X" — captures the 2-letter state code
_STATE_CODE_RE = re.compile(r"\bus[,\s\-]+([a-z]{2})\b", re.IGNORECASE)

# Word-boundary US anchor
_US_ANCHOR_RE = re.compile(
    r"\b(us|usa|u\.s\.a?|united\s+states|america|north\s+america)\b",
    re.IGNORECASE,
)

# 2-letter code → full lower-cased name, for blocking non-home states by name.
_STATE_NAMES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas",
    "CA": "california", "CO": "colorado", "CT": "connecticut", "DE": "delaware",
    "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
    "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
    "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
    "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska",
    "NV": "nevada", "NH": "new hampshire", "NJ": "new jersey",
    "NM": "new mexico", "NY": "new york", "NC": "north carolina",
    "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon",
    "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina",
    "SD": "south dakota", "TN": "tennessee", "TX": "texas", "UT": "utah",
    "VT": "vermont", "VA": "virginia", "WA": "washington",
    "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming",
}


def is_local_or_remote(loc: str) -> bool:
    """True if `loc` is in the configured home area or acceptable remote."""
    if not loc:
        return False

    p            = preferences()
    loc_lower    = loc.lower()
    home_terms   = [t.lower() for t in p["home_terms"]]
    home_states  = {s.upper() for s in p["home_states"]}

    # Step 1: home tokens always win, even in multi-location strings
    if any(t in loc_lower for t in home_terms):
        return True

    # Step 2: block explicit non-home state codes (e.g. "US, CA, Remote")
    code_match = _STATE_CODE_RE.search(loc)
    if code_match and code_match.group(1).upper() not in home_states:
        return False

    # Step 3: block listings that name only non-home states
    home_names = {_STATE_NAMES[s] for s in home_states if s in _STATE_NAMES}
    if any(name not in home_names and name in loc_lower for name in _STATE_NAMES.values()):
        return False

    # Step 4: remote, within the configured scope
    if p["allow_remote"] and any(t in loc_lower for t in REMOTE_TERMS):
        scope = p["remote_scope"]
        if scope == "anywhere":
            return True
        if scope == "us":
            return bool(_US_ANCHOR_RE.search(loc_lower))
        return False  # scope == "none"

    return False
