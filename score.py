"""
Job scoring — JD-relative fit, weighted by skill category, role title, AI signal,
and company compensation/tier.

Replaces the old keyword-density model (which divided matched skills by the FULL
resume skill list, so nothing could score above ~68). The question now is
"how much of what THIS role wants does the candidate have, and is it a top-paying target"
— not "how much of the candidate does this JD happen to mention."

Lexical fit is always-on, local, and free. Returns 0-100. Strong AI-platform
roles at top targets land 75-95.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

import config

_TARGETS = Path(__file__).parent / "targets.yaml"

# Tokens too short / ambiguous to match safely even with word boundaries.
_SKILL_STOPWORDS = {"ai", "ml", "go", "react", "async", "rest", "nlp", "api"}

# Title signals ───────────────────────────────────────────────────────────────
_SENIORITY_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|distinguished|lead|head|vp|vice president|director"
    r"|member of technical staff|\bmts\b)\b",
    re.IGNORECASE,
)
_JUNIOR_RE = re.compile(
    r"\b(intern|internship|co-?op|new ?grad|university|apprentice|graduate program"
    r"|associate|junior|jr\.?|entry[ -]?level|level\s*[i1]\b|\bi\b|\b1\b)\b",
    re.IGNORECASE,
)
# Titles the candidate does not want — disqualify hard.
_OFFROLE_RE = re.compile(
    r"\b(sales|account executive|recruit|talent|people partner|marketing|brand"
    r"|designer|ux research|technical writer|support|customer success|hardware|asic"
    r"|firmware|mechanical|electrical|optical|rf engineer|validation|test technician"
    r"|clinical|nurse|accountant|\btax\b|auditor?|legal counsel|go-to-market|\bgtm\b"
    r"|field engineer|solutions architect|sales engineer|partner manager|operations"
    r"|program manager|product manager|project manager|scrum master|community)\b",
    re.IGNORECASE,
)
# Core role titles the candidate targets.
_GOODROLE_RE = re.compile(
    r"\b(software engineer|swe|backend|back-end|full[ -]?stack|platform engineer"
    r"|infrastructure|distributed systems|machine learning|ml engineer|ai engineer"
    r"|applied (scientist|ai)|research engineer|member of technical staff|mts"
    r"|ai platform|ml platform|systems engineer|engineering manager|tech lead)\b",
    re.IGNORECASE,
)
# Security/cyber that isn't AI-flavored: mild penalty (e.g. Deloitte "Cyber Full-Stack").
_CYBER_RE = re.compile(r"\b(cyber|security|infosec|soc analyst|penetration)\b", re.IGNORECASE)

# Strong AI/domain signal.
_AI_RE = re.compile(
    r"\b(llm|large language model|genai|generative ai|\bagent(ic|s)?\b|rag"
    r"|retrieval[- ]augmented|langchain|langgraph|foundation model|fine[- ]?tun"
    r"|inference|embeddings?|vector (db|database|store)|multi-?agent|mcp"
    r"|model context protocol|prompt|transformer|diffusion|reinforcement learning"
    r"|rlhf|vision model|multimodal)\b",
    re.IGNORECASE,
)


@config.mtime_cached(config.PROFILE_PATH)
def _weighted_skills() -> tuple[tuple[re.Pattern, float], ...]:
    """Compiled (word-boundary pattern, weight) for every categorized resume skill."""
    out: list[tuple[re.Pattern, float]] = []
    weights = config.category_weights()
    skills  = config.profile().get("skills", {})
    for category, items in skills.items():
        w = weights.get(category, 1.0)
        for raw in items:
            term = raw.strip().lower()
            if term in _SKILL_STOPWORDS or len(term) < 3:
                continue
            # Word-boundary match so "rag" never fires on "sto-rag-e".
            pat = re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", re.IGNORECASE)
            out.append((pat, w))
    return tuple(out)


@config.mtime_cached(config.PROFILE_PATH)
def _skills_flat() -> tuple[str, ...]:
    return tuple(s.lower() for s in config.profile().get("all_skills_flat", []))


@config.mtime_cached(_TARGETS)
def _targets() -> dict:
    return yaml.safe_load(_TARGETS.read_text())


@config.mtime_cached(_TARGETS)
def _company_index() -> dict:
    """company_lower -> {tc_max, tc_range}. Built once from targets.yaml."""
    idx: dict[str, dict] = {}
    for tier in _targets().values():
        for co in tier.get("companies", []):
            idx[co["name"].lower()] = {
                "tc_max": _parse_tc_max(co.get("tc_range", "")),
                "tc_range": co.get("tc_range", ""),
            }
    return idx


def _parse_tc_max(tc_range: str) -> int:
    """'450-900K' -> 900, '600-1100K' -> 1100. Returns 0 if unparseable."""
    if not tc_range:
        return 0
    nums = re.findall(r"\d+", tc_range)
    return int(nums[-1]) if nums else 0


# ── Component scores ─────────────────────────────────────────────────────────

def _skill_fit(text: str) -> float:
    """0..38 — weighted JD coverage, saturating. A role hitting ~14 weighted
    points of strong skills approaches full marks."""
    matched_weight = sum(w for pat, w in _weighted_skills() if pat.search(text))
    # Saturate: ~14 weighted points = excellent fit. Tuned against the live corpus.
    return round(38 * min(1.0, matched_weight / 14.0), 1)


def _role_fit(title: str) -> tuple[float, float]:
    """Returns (points 0..18, multiplier). Multiplier punishes off-target titles
    so interns and sales roles can never rank, regardless of keyword soup."""
    pts = 0.0
    mult = 1.0

    is_senior = bool(_SENIORITY_RE.search(title))
    if _GOODROLE_RE.search(title):
        pts += 10
    if is_senior:
        pts += 8

    # Junior penalty only when nothing marks the role as senior. Otherwise
    # "Senior Software Engineer II" (the roman numeral is a level, not a rank)
    # gets crushed to a new-grad score. A real senior signal always wins.
    if _JUNIOR_RE.search(title) and not is_senior:
        mult *= 0.35
    if _OFFROLE_RE.search(title):
        mult *= 0.25
    # Cyber/security with no AI angle: dampen, don't kill.
    if _CYBER_RE.search(title) and not _AI_RE.search(title):
        mult *= 0.6

    return min(pts, 18.0), mult


def _ai_fit(text: str) -> float:
    """0..12 — strength of AI/LLM/agent signal (the candidate's edge)."""
    hits = len(set(m.group(0).lower() for m in _AI_RE.finditer(text)))
    if hits == 0:
        return 0.0
    return round(min(12.0, 5 + hits * 2.0), 1)


def _comp_tc(comp_band: str) -> int:
    """Approx annual TC ceiling in $K from a posting's band: '405-485K' -> 485,
    '60-85/hr' -> ~177. Returns 0 when unparseable."""
    if not comp_band:
        return 0
    nums = re.findall(r"\d+", comp_band)
    if not nums:
        return 0
    hi = int(nums[-1])
    if "/hr" in comp_band.lower():
        hi = round(hi * 2)  # rough hourly → annual $K (~2080 hrs / 1000)
    return hi


def _comp_fit(company: str, comp_band: str = "") -> float:
    """0..32 — the compensation lever. Prefers the posting's real comp so roles at
    companies outside targets.yaml are judged on actual pay, not list membership.
    Falls back to the company band, then a modest baseline."""
    tc = _comp_tc(comp_band)
    if tc <= 0:
        info = _company_index().get((company or "").lower())
        tc = info["tc_max"] if info else 0
    if tc <= 0:
        return 12.0  # unknown comp + off-list company: modest baseline, let role/skill fit decide
    # 1100K -> 32, 300K -> 12. Linear, clamped.
    scaled = (tc - 300) / (1100 - 300) * 20 + 12
    return round(max(8.0, min(32.0, scaled)), 1)


def score_job(title: str, jd_text: str, company: str = "", comp_band: str = "") -> int:
    """0-100 fit score. JD-relative skill fit + role title + AI signal + comp.
    comp_band is the posting's own salary band when known (e.g. '405-485K')."""
    title = title or ""
    combined = f"{title} {jd_text or ''}"

    skill    = _skill_fit(combined)
    ai       = _ai_fit(combined)
    comp_pts = _comp_fit(company, comp_band)
    role_pts, role_mult = _role_fit(title)

    # No JD text (e.g. Workday/NVIDIA): skill_fit is title-only and thin, so lean
    # on role + comp and don't let an empty description sink a known target.
    if not (jd_text or "").strip():
        skill = max(skill, _skill_fit(title))

    raw = (skill + role_pts + ai + comp_pts) * role_mult
    return int(round(min(100.0, max(0.0, raw))))


def extract_keywords(jd_text: str) -> list[str]:
    """Resume skills that appear in the JD (word-boundary), in list order, deduped."""
    if not jd_text:
        return []
    out = []
    for s in _skills_flat():
        if s in _SKILL_STOPWORDS or len(s) < 3:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", jd_text, re.IGNORECASE):
            out.append(s)
    return out


def salary_estimate(company_name: str) -> str:
    """TC range string for a company from targets.yaml."""
    info = _company_index().get((company_name or "").lower())
    return info["tc_range"] if info else ""


def display_comp(job: dict) -> tuple[str, bool]:
    """Comp to show for a job, as (band_without_dollar_sign, is_actual).

    Prefers the posting's own salary (scraped or structured) over the static
    per-company target band, so callers can mark the difference. Returns
    ("", False) when neither source has anything.
    """
    actual = (job.get("comp") or "").strip()
    if actual:
        return actual, True
    return salary_estimate(job.get("company", "")), False
