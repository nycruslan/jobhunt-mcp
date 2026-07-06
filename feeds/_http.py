"""
Shared HTTP / HTML helpers for feed modules.

One module-level session per feed file kept the connection pool warm and the
User-Agent identical across modules, but each feed had to re-declare it.
This module centralizes both, plus a tiny dependency-free HTML stripper used
by Greenhouse, Lever, Ashby, and Amazon.
"""
from __future__ import annotations

import html as _html
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "JobHunt/1.0 (personal job search tool)"
DEFAULT_TIMEOUT = 15  # seconds


def build_session(*, content_type_json: bool = False) -> requests.Session:
    """Return a requests.Session pre-configured with our UA + JSON Accept.

    Retries transient failures (429 + 5xx) with exponential backoff so a single
    hiccup doesn't read as a feed outage. Respects Retry-After when a board
    rate-limits us."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    if content_type_json:
        s.headers["Content-Type"] = "application/json"
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG_RE   = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def html_to_text(html: str) -> str:
    """Strip HTML tags, decode entities to real characters, collapse whitespace.

    Decoding (vs the old delete-the-entity approach) keeps real punctuation like
    the em dash in salary ranges. Greenhouse double-encodes ("&amp;mdash;"), so we
    unescape twice; the second pass is a no-op on normal text. Script/style
    bodies are dropped whole — their contents are code, not description."""
    if not html:
        return ""
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(_html.unescape(text))
    return _SPACE_RE.sub(" ", text).strip()
