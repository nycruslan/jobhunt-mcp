"""
Compensation extraction — turn a job's real pay into a compact band string.

Three entry points, one shared formatter, so every feed normalizes to the same
shape (e.g. "207-301K", "150-200K", "60-85/hr"). The leading "$" is intentionally
*not* included — callers render it ("💰 $...", "TC: $...") and the company-band
fallback in score.py uses the same no-dollar convention.

  parse_comp(text)                  — scrape a salary range out of JD prose.
                                      Covers the pay-transparency ranges that
                                      NYC/CA/WA/CO law forces into the posting.
  comp_from_cents(min, max, cur)    — Greenhouse pay_input_ranges (cents).
  comp_from_amounts(min, max, ivl)  — JobSpy structured salary columns (dollars).

All three return "" when there's nothing trustworthy to report.
"""
from __future__ import annotations

import re

# Plausibility gates so we never report equity grants, signing bonuses, or
# random "$500 referral" noise as base comp.
_ANNUAL_MIN = 30_000
_ANNUAL_MAX = 3_000_000
_HOURLY_MIN = 15
_HOURLY_MAX = 2_000

# A single dollar amount: "$207,000", "$207000", "$207K", "$1.2M", "207k".
# Kept as one alternation so both the range and single-amount patterns share it.
_AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?\s?[kKmM]?|\d{4,7})"

# Tight range: two amounts joined directly by a dash / "to". The first must carry
# a "$"; the second may drop it ("$207,000 - 301,000").
_RANGE_TIGHT = re.compile(
    r"\$\s?" + _AMOUNT + r"\s?(?:-|–|—|to)\s?\$?\s?" + _AMOUNT,
    re.IGNORECASE,
)
# Wide range: two $-amounts with a dash-like separator buried in filler. Greenhouse
# wraps its pay range in markup ("$405,000 <span>…divider…—…</span> $485,000"), and
# legacy rows still carry the stripped "mdash;" remnant. Only DASH cues are allowed
# in the gap (never "to") so "salary $X ... up to $Y bonus" can't get stitched.
_RANGE_WIDE = re.compile(
    r"\$\s?" + _AMOUNT + r"[^$\n]{0,40}?(?:-|–|—|mdash|ndash)[^$\n]{0,40}?\$\s?" + _AMOUNT,
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(r"\$\s?" + _AMOUNT, re.IGNORECASE)

# JobSpy (Indeed/Google) stores descriptions as escaped markdown, so a real
# posting reads "$207000 \- $301000". Drop the backslash before punctuation
# before any matching, or the range separator is never seen.
_UNESCAPE_RE = re.compile(r"\\([-+–—.,$/])")

# A lone dollar figure is only trusted as comp when a salary cue sits nearby —
# otherwise "$1,200,000 in equity" or "$5M raised" would masquerade as base pay.
_SALARY_CUE = re.compile(
    r"salary|base pay|base compensation|annual(?:ly)?|/\s?year|per year|\bOTE\b|pay range|compensation range",
    re.IGNORECASE,
)
_CUE_WINDOW = 60


def _to_dollars(tok: str) -> float | None:
    """'207,000' -> 207000, '207k' -> 207000, '1.2m' -> 1200000. None if unparseable."""
    if not tok:
        return None
    t = tok.strip().lower().replace(",", "").replace(" ", "")
    mult = 1.0
    if t.endswith("k"):
        mult, t = 1_000.0, t[:-1]
    elif t.endswith("m"):
        mult, t = 1_000_000.0, t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return None


def _k(n: float) -> str:
    """Dollars -> rounded thousands token: 207000 -> '207', 207500 -> '208'."""
    return str(round(n / 1000))


def _format(lo: float, hi: float, hourly: bool) -> str:
    """Build the band string. Assumes lo <= hi and values already validated."""
    if hourly:
        a = f"{lo:g}"
        b = f"{hi:g}"
        return f"{a}/hr" if a == b else f"{a}-{b}/hr"
    a, b = _k(lo), _k(hi)
    return f"{a}K" if a == b else f"{a}-{b}K"


def _band(lo: float | None, hi: float | None, *, hourly_hint: bool = False) -> str:
    """Validate a (lo, hi) pair and format it, or return '' if implausible."""
    vals = [v for v in (lo, hi) if v is not None]
    if not vals:
        return ""
    lo = min(vals)
    hi = max(vals)

    # Hourly if explicitly hinted or both endpoints are too small to be annual.
    hourly = hourly_hint or hi < 1_000
    if hourly:
        if _HOURLY_MIN <= lo <= hi <= _HOURLY_MAX:
            return _format(lo, hi, hourly=True)
        return ""
    if _ANNUAL_MIN <= lo <= hi <= _ANNUAL_MAX:
        return _format(lo, hi, hourly=False)
    return ""


def comp_from_cents(min_cents, max_cents, currency: str = "USD") -> str:
    """Greenhouse pay_input_ranges: amounts arrive in cents. Non-USD is skipped."""
    if currency and currency.upper() not in ("USD", ""):
        return ""
    lo = (min_cents or 0) / 100 or None
    hi = (max_cents or 0) / 100 or None
    return _band(lo, hi)


def comp_from_amounts(min_amount, max_amount, interval: str = "") -> str:
    """JobSpy salary columns: amounts are dollars (yearly) or dollars/hour."""
    try:
        lo = float(min_amount) if min_amount not in (None, "") else None
        hi = float(max_amount) if max_amount not in (None, "") else None
    except (TypeError, ValueError):
        return ""
    hourly = (interval or "").strip().lower() in ("hourly", "hour")
    return _band(lo, hi, hourly_hint=hourly)


def parse_comp(text: str) -> str:
    """Pull the first trustworthy salary band out of free-text JD prose."""
    if not text:
        return ""

    text = _UNESCAPE_RE.sub(r"\1", text)
    hourly_doc = bool(re.search(r"\bper hour\b|/\s?hr\b|hourly", text, re.IGNORECASE))

    for pattern in (_RANGE_TIGHT, _RANGE_WIDE):
        for m in pattern.finditer(text):
            band = _band(_to_dollars(m.group(1)), _to_dollars(m.group(2)),
                         hourly_hint=hourly_doc)
            if band:
                return band

    # No range matched — accept a lone amount only if it's clearly an annual
    # salary (K/M suffix or a large bare number) AND a salary cue sits nearby,
    # so equity grants and signing bonuses don't get mistaken for base pay.
    for m in _SINGLE_RE.finditer(text):
        tok = m.group(1)
        val = _to_dollars(tok)
        if val is None:
            continue
        has_suffix = tok.strip().lower().endswith(("k", "m"))
        if not has_suffix and val < 50_000:
            continue
        window = text[max(0, m.start() - _CUE_WINDOW): m.end() + _CUE_WINDOW]
        if not _SALARY_CUE.search(window):
            continue
        band = _band(val, val)
        if band:
            return band

    return ""
