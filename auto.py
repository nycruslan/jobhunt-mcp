"""
Pipeline automation policy — the deterministic rules behind the scheduled email
sync (the /jobhunt-autosync command).

Kept pure and free of I/O so it is fully testable. A Claude agent reads Gmail
(read-only) and classifies each message into a `signal`; this module decides what
that means for the tracker: which status it maps to, whether it is safe to apply
automatically or should be surfaced for confirmation, whether it would move the
pipeline forward, and which stored job a company name refers to.
"""
from __future__ import annotations

import re

# A classified email `signal` -> the pipeline status it implies.
SIGNAL_STATUS = {
    "application_received": "applied",
    "rejected":             "rejected",
    "interview":            "screen",
    "onsite":               "onsite",
    "offer":                "offer",
}

# Low-stakes, common transitions apply automatically. High-stakes or irreversible
# ones are surfaced for the human to confirm instead: an onsite to schedule, an
# offer to weigh, and a rejection — terminal, and a spoofed or misread email must
# not be able to close a live application unattended.
AUTO_APPLY_SIGNALS = {"application_received", "interview"}

# A signal may only auto-apply from these current statuses. application_received
# is trustworthy on a role you actually drafted/applied to; landing on an
# untouched 'new'/'reviewed' row means the receipt is probably for a different
# req at the same company, so that case is surfaced for confirmation instead.
_AUTO_APPLY_FROM = {
    "application_received": ("drafted", "applied"),
}

# Which existing rows a signal can attach to. A confirmation lands on a role you
# drafted/saw but had not marked applied; recruiter replies land on active apps.
_CANDIDATE_STATUSES = {
    "application_received": ("new", "reviewed", "drafted", "applied"),
}
_DEFAULT_CANDIDATES = ("applied", "screen", "onsite")

# Forward-progress ordering so a stray or misread email can never regress a stage.
_ORDER = ["new", "reviewed", "drafted", "applied", "screen", "onsite", "offer"]
_TERMINAL = {"rejected", "withdrawn"}

# Structure/legal/too-generic tokens that must not drive a company match on their own.
_GENERIC = {
    "inc", "llc", "ltd", "corp", "co", "the", "and", "group", "holdings",
    "labs", "ai", "io", "technologies", "technology", "systems", "solutions",
    "global", "ventures", "partners", "capital", "software", "data", "services",
    "tech", "studio", "studios", "company", "careers",
}


def signal_status(signal: str) -> str | None:
    """Target pipeline status for a signal, or None if the signal is unknown."""
    return SIGNAL_STATUS.get(signal)


def should_auto_apply(signal: str, current_status: str = "") -> bool:
    """Whether a signal is safe to apply without human confirmation, given the
    matched job's current status. Unknown/unlisted signals never auto-apply."""
    if signal not in AUTO_APPLY_SIGNALS:
        return False
    allowed_from = _AUTO_APPLY_FROM.get(signal)
    return allowed_from is None or current_status in allowed_from


def candidate_statuses(signal: str) -> tuple[str, ...]:
    """Which stored statuses a signal is allowed to attach to."""
    return _CANDIDATE_STATUSES.get(signal, _DEFAULT_CANDIDATES)


def is_forward(current: str, target: str) -> bool:
    """True if moving current -> target is forward progress (or a terminal close).
    Blocks regressions like onsite -> screen from a stale email."""
    if target == current:
        return False
    if target in _TERMINAL:
        return current not in _TERMINAL
    if current in _TERMINAL:
        return False
    try:
        return _ORDER.index(target) > _ORDER.index(current)
    except ValueError:
        return True  # unknown current status: don't block


def _tokens(name: str) -> set[str]:
    raw = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    toks = {t for t in raw.split() if len(t) > 2 and t not in _GENERIC}
    if toks:
        return toks
    # Nothing survived the length filter ('HP', 'EA', 'X'): fall back to the
    # short tokens themselves so tiny company names can still match.
    return {t for t in raw.split() if t not in _GENERIC}


def match_jobs(company: str, jobs: list[dict]) -> list[dict]:
    """Jobs whose company matches `company`, by order-free token containment.

    'Stripe' matches 'Stripe Payments'; 'Scale AI' matches 'Scale AI'. Generic
    tokens are dropped so the legal suffix never drives a match. Returns every
    match; the caller decides what to do when there is more than one (it will not
    auto-apply to a guess)."""
    want = _tokens(company)
    if not want:
        return []
    out = []
    for j in jobs:
        have = _tokens(j.get("company", ""))
        if have and (want <= have or have <= want):
            out.append(j)
    return out
