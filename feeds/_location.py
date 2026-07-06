"""
Shared location filter — used by every feed module.

Driven by `preferences` in profile.yaml so it works for any home base, not just
NYC:
  home_terms    city/borough strings that always pass ("austin", "remote hub")
  home_states   2-letter codes that count as local (e.g. ["NY"] or ["CA","WA"])
  allow_remote  whether remote roles are acceptable at all
  remote_scope  "us"       → US-wide remote passes, foreign-anchored remote blocked
                "anywhere" → any remote passes
                "none"     → remote never passes

Policy:
  ✓ A home term appears (wins even inside a multi-location string)
  ✓ A home state appears anywhere — code or full name ("Port Washington, NY")
  ✓ Remote within the configured scope; bare "Remote" counts as US-scope remote
    unless the string carries a foreign geography signal
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

# Foreign geography signals that make a bare "Remote" NOT a US remote under
# scope "us". Countries plus the foreign hub cities ATS multi-location strings
# actually carry ("Remote - Denmark; Stockholm, Sweden"). "Worldwide" and
# "global" stay acceptable — they include the US.
_FOREIGN_RE = re.compile(
    r"\b(canada|uk|united\s+kingdom|great\s+britain|england|scotland|wales"
    r"|ireland|germany|france|poland|netherlands|spain|portugal|italy"
    r"|sweden|norway|denmark|finland|iceland|switzerland|austria|belgium"
    r"|luxembourg|czechia|czech\s+republic|slovakia|hungary|romania|bulgaria"
    r"|greece|serbia|croatia|slovenia|estonia|latvia|lithuania|ukraine"
    r"|turkey|israel|india|pakistan|bangladesh|sri\s+lanka|china|hong\s+kong"
    r"|taiwan|japan|korea|singapore|malaysia|indonesia|thailand|vietnam"
    r"|philippines|australia|new\s+zealand|mexico|brazil|argentina|colombia"
    r"|chile|peru|uruguay|costa\s+rica|guatemala|ecuador|egypt|nigeria|kenya"
    r"|ghana|south\s+africa|morocco|uae|dubai|saudi\s+arabia|qatar"
    r"|emea|europe|european|apac|latam"
    r"|london|dublin|berlin|munich|paris|amsterdam|madrid|barcelona|lisbon"
    r"|zurich|stockholm|copenhagen|oslo|helsinki|warsaw|prague|vienna"
    r"|budapest|bucharest|tallinn|toronto|vancouver|montreal|ottawa|sydney"
    r"|melbourne|auckland|tokyo|seoul|beijing|shanghai|bangalore|bengaluru"
    r"|hyderabad|mumbai|delhi|chennai|pune|tel\s+aviv|s[aã]o\s+paulo"
    r"|mexico\s+city|bogot[aá]|buenos\s+aires|santiago|nairobi|lagos|cairo)\b",
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

# Word-bounded state-name matcher; longest-first so "west virginia" beats "virginia".
_STATE_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted(_STATE_NAMES.values(), key=len, reverse=True)) + r")\b"
)


def is_local_or_remote(loc: str, prefs: dict | None = None) -> bool:
    """True if `loc` is in the configured home area or acceptable remote.

    `prefs` defaults to the profile's preferences; tests pass their own dict."""
    if not loc:
        return False

    p            = prefs if prefs is not None else preferences()
    # Hyphens read as spaces for term matching: boards write "New-York" and
    # "CAN-Remote". State-code regexes keep the raw string (they handle "-").
    loc_lower    = loc.lower().replace("-", " ")
    home_terms   = [t.lower() for t in p["home_terms"]]
    home_states  = {s.upper() for s in p["home_states"]}
    home_names   = {_STATE_NAMES[s] for s in home_states if s in _STATE_NAMES}

    # Step 1: home tokens always win, even in multi-location strings
    if any(t in loc_lower for t in home_terms):
        return True

    # Step 2: an explicit home-state signal anywhere also wins. Bare codes are
    # matched uppercase ("Port Washington, NY" — the lowercased "washington"
    # must NOT read as Washington state); full names word-bounded.
    if any(re.search(rf"\b{code}\b", loc) for code in home_states):
        return True
    if any(re.search(rf"\b{name}\b", loc_lower) for name in home_names):
        return True

    # Step 3: US-prefixed state codes ("US, CA; US, NY") — scan ALL of them,
    # block only when none is a home state.
    codes = {m.group(1).upper() for m in _STATE_CODE_RE.finditer(loc)}
    if codes:
        if codes & home_states:
            return True
        return False

    # Step 4: block listings that name only non-home states (home names already
    # returned True above, so any name found here is foreign to the user)
    if _STATE_NAME_RE.search(loc_lower):
        return False

    # Step 5: remote, within the configured scope
    if p["allow_remote"] and any(t in loc_lower for t in REMOTE_TERMS):
        scope = p["remote_scope"]
        if scope == "anywhere":
            return True
        if scope == "us":
            # US-anchored remote passes; so does a bare "Remote" with no foreign
            # geography signal — most US companies don't anchor their US-only
            # remote listings.
            return bool(_US_ANCHOR_RE.search(loc_lower)) or not _FOREIGN_RE.search(loc_lower)
        return False  # scope == "none"

    return False
