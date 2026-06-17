"""
Cover letter persistence.

The letter itself is written inline in the Claude conversation, which has the JD
and the candidate's full background. This module only saves it to disk.
"""
from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "covers"


def save_cover(job_id: str, company: str, text: str) -> Path:
    """Persist a cover letter to disk. Trailing newline always present."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = f"{company.lower().replace(' ', '_')}_{job_id}"
    path = OUTPUT_DIR / f"{slug}.txt"
    path.write_text(text.strip() + "\n")
    return path
