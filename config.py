"""
Central config + user profile loader.

Everything user-specific lives in resume/profile.yaml (the résumé, identity, and
preferences). This module reads it once and exposes small typed accessors with
sane defaults, so no other module hardcodes a name, location, or tuning constant.

Copy resume/profile.example.yaml to resume/profile.yaml and fill it in.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT         = Path(__file__).parent
PROFILE_PATH = ROOT / "resume" / "profile.yaml"

# Defaults applied when a key is absent, so a minimal profile still works.
_DEFAULT_PREFS = {
    "home_terms":   ["new york", "nyc", "new york city",
                     "manhattan", "brooklyn", "queens", "bronx"],
    "home_states":  ["NY"],
    "allow_remote": True,
    "remote_scope": "us",            # "us" | "anywhere" | "none"
    "tailor_model": "claude-haiku-4-5",
    "enable_jobspy": False,          # Indeed/Google scrape — off by default (noisy, heavy deps)
    "brief_delivery": "auto",        # auto | telegram | email | both | none
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


@lru_cache(maxsize=1)
def profile() -> dict:
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"{PROFILE_PATH} not found. Copy resume/profile.example.yaml to "
            f"resume/profile.yaml and fill in your details."
        )
    return yaml.safe_load(PROFILE_PATH.read_text()) or {}


@lru_cache(maxsize=1)
def preferences() -> dict:
    return {**_DEFAULT_PREFS, **(profile().get("preferences") or {})}


@lru_cache(maxsize=1)
def category_weights() -> dict:
    user = (profile().get("scoring") or {}).get("category_weights") or {}
    return {**_DEFAULT_WEIGHTS, **user}


@lru_cache(maxsize=1)
def company_aliases() -> dict:
    """Lower-cased {spelling: canonical} merges for sub-brands and aggregators."""
    return {k.strip().lower(): v for k, v in (profile().get("company_aliases") or {}).items()}


@lru_cache(maxsize=1)
def prep_guides() -> dict:
    """Optional {company: guide_text} interview notes."""
    return profile().get("prep") or {}


def contact() -> dict:
    return profile().get("contact") or {}
