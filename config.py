"""
Central config + user profile loader.

Everything user-specific lives in resume/profile.yaml (the résumé, identity, and
preferences). This module reads it once and exposes small typed accessors with
sane defaults, so no other module hardcodes a name, location, or tuning constant.

Copy resume/profile.example.yaml to resume/profile.yaml and fill it in.
"""
from __future__ import annotations

import functools
from pathlib import Path

import yaml

ROOT         = Path(__file__).parent
PROFILE_PATH = ROOT / "resume" / "profile.yaml"


def mtime_cached(path: Path):
    """Cache a zero-arg loader and recompute only when `path`'s mtime changes.

    The MCP server is a long-running process. Plain @lru_cache pinned the first
    read of profile.yaml/targets.yaml for the life of the process, so edits never
    took effect until a restart. This reloads on change, costs one stat() per call,
    and exposes .cache_clear() for tests."""
    def deco(fn):
        state: dict = {"mtime": None, "val": None}

        @functools.wraps(fn)
        def wrapper():
            try:
                m = path.stat().st_mtime
            except OSError:
                m = None
            if m != state["mtime"]:
                state["val"] = fn()
                state["mtime"] = m
            return state["val"]

        wrapper.cache_clear = lambda: state.update(mtime=None, val=None)  # type: ignore[attr-defined]
        return wrapper

    return deco

# Defaults applied when a key is absent, so a minimal profile still works.
_DEFAULT_PREFS = {
    "home_terms":   ["new york", "nyc", "new york city",
                     "manhattan", "brooklyn", "queens", "bronx"],
    "home_states":  ["NY"],
    "allow_remote": True,
    "remote_scope": "us",            # "us" | "anywhere" | "none"
    "enable_jobspy": False,          # Indeed/Google scrape — off by default (noisy, heavy deps)
    "enable_adzuna": False,          # Adzuna aggregator (free API key, broad market coverage)
    "enable_remotive": False,        # Remotive remote-jobs board (free, no key)
    "brief_delivery": "auto",        # auto | telegram | email | both | none
    "publish": False,                # push a dashboard snapshot to Turso (web /admin)
}

_DEFAULT_WEIGHTS = {
    "ai_ml":             3.0,
    "model_providers":   2.5,
    "protocols_tooling": 2.5,
    "leadership":        2.0,
    "architecture":      1.8,
    "backend":           1.5,
    "cloud_devops":      1.2,
    "frontend":          0.8,
}


@mtime_cached(PROFILE_PATH)
def profile() -> dict:
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"{PROFILE_PATH} not found. Copy resume/profile.example.yaml to "
            f"resume/profile.yaml and fill in your details."
        )
    return yaml.safe_load(PROFILE_PATH.read_text()) or {}


# The accessors below derive from profile() and are cheap to rebuild, so they're
# left uncached. profile() reloads on file change; these see it immediately.
def preferences() -> dict:
    return {**_DEFAULT_PREFS, **(profile().get("preferences") or {})}


def category_weights() -> dict:
    user = (profile().get("scoring") or {}).get("category_weights") or {}
    return {**_DEFAULT_WEIGHTS, **user}


def company_aliases() -> dict:
    """Lower-cased {spelling: canonical} merges for sub-brands and aggregators."""
    return {k.strip().lower(): v for k, v in (profile().get("company_aliases") or {}).items()}


def prep_guides() -> dict:
    """Optional {company: guide_text} interview notes."""
    return profile().get("prep") or {}


def contact() -> dict:
    return profile().get("contact") or {}


def secret(name: str) -> str:
    """Read a credential by name: environment first, then briefing.conf, then
    telegram.conf (legacy). The single key=value reader for everything outside
    profile.yaml — API keys (Adzuna, Turso) and brief delivery (Telegram, SMTP)."""
    import os

    val = os.environ.get(name, "").strip()
    if val:
        return val
    for fname in ("briefing.conf", "telegram.conf"):
        conf = ROOT / fname
        if not conf.exists():
            continue
        for line in conf.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip()
    return ""
