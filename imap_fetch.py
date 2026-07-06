#!/usr/bin/env python3.11
"""
Read-only Gmail fetch over IMAP for the JobHunt autosync.

The claude.ai Gmail connector isn't available in a headless run (no interactive
claude.ai session on the VPS), so the autosync reads Gmail here instead and hands
the messages to the agent as text. Read-only: it logs in, lists, logs out, never
modifies anything. Stdlib only.

Credentials live in imap.conf next to this file (chmod 600, see imap.conf.example):
    GMAIL_ADDRESS=you@gmail.com
    GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx   # a Google App Password, not your login

Usage: imap_fetch.py [days]   (default 3)

Exits non-zero with a one-line stderr message on connection/auth failure so the
calling script can detect it. One bad message never aborts the whole fetch.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import re
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from pathlib import Path

CONF = Path(__file__).resolve().parent / "imap.conf"
MAX_MESSAGES = 60
SNIPPET = 280


def _conf() -> dict:
    d: dict = {}
    for line in CONF.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            d[k.strip()] = v.strip()
    return d


def _decode(payload: bytes, charset: str | None) -> str:
    """Decode bytes with a declared charset, guarding against bogus codec NAMES
    (errors='ignore' does not catch LookupError). latin-1 never fails."""
    for cs in (charset, "utf-8"):
        if not cs:
            continue
        try:
            return payload.decode(cs, "ignore")
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("latin-1", "ignore")


def _dec(s: str) -> str:
    if not s:
        return ""
    out = ""
    for txt, enc in decode_header(s):
        out += _decode(txt, enc) if isinstance(txt, bytes) else txt
    return re.sub(r"\s+", " ", out).strip()


def _strip_html(text: str) -> str:
    """Crude but sufficient tag strip for a snippet: drop style/script, then tags."""
    import html as _html

    text = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return _html.unescape(text)


def _snippet(msg) -> str:
    """First SNIPPET chars of the body. Prefers text/plain; most ATS mail is
    HTML-only, so fall back to text/html with tags stripped."""
    try:
        parts = msg.walk() if msg.is_multipart() else [msg]
        plain, htm = "", ""
        for part in parts:
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = _decode(payload, part.get_content_charset())
            if ctype == "text/plain" and not plain:
                plain = text
            elif ctype == "text/html" and not htm:
                htm = text
        body = plain or (_strip_html(htm) if htm else "")
        return re.sub(r"\s+", " ", body).strip()[:SNIPPET]
    except Exception:
        pass
    return ""


def _from_domain(from_header: str) -> str:
    """Bare sender domain, so the classifying agent can check sender-vs-company."""
    addr = email.utils.parseaddr(from_header)[1]
    return addr.rpartition("@")[2].lower() if "@" in addr else ""


def main() -> int:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    if not CONF.exists():
        print(f"ERROR: {CONF} not found (see imap.conf.example)", file=sys.stderr)
        return 2
    c = _conf()
    addr, pw = c.get("GMAIL_ADDRESS"), c.get("GMAIL_APP_PASSWORD")
    if not addr or not pw:
        print("ERROR: GMAIL_ADDRESS / GMAIL_APP_PASSWORD missing in imap.conf", file=sys.stderr)
        return 2
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com")
        M.login(addr, pw)
    except Exception as e:
        print(f"ERROR: IMAP connect/login failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    try:
        M.select("INBOX", readonly=True)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = M.search(None, f"(SINCE {since})")
        ids = data[0].split() if data and data[0] else []
        recent = list(reversed(ids))[:MAX_MESSAGES]
        print(f"# {len(recent)} inbox messages in the last {days} days (newest first):")
        for i in recent:
            try:
                typ, md = M.fetch(i, "(RFC822)")
                if typ != "OK" or not md or not md[0]:
                    continue
                msg = email.message_from_bytes(md[0][1])
                raw_from = msg.get("From", "") or ""
                print("---")
                print(f"FROM: {_dec(raw_from)}")
                print(f"SENDER_DOMAIN: {_from_domain(raw_from)}")
                print(f"DATE: {(msg.get('Date', '') or '')[:31]}")
                print(f"SUBJ: {_dec(msg.get('Subject', ''))}")
                print(f"BODY: {_snippet(msg)}")
            except Exception as e:
                print(f"WARN: skipped message {i!r}: {type(e).__name__}", file=sys.stderr)
                continue
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
