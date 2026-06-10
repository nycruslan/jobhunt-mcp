"""
Cover letter drafter — 1 tight paragraph, role-specific, no fluff.

If ANTHROPIC_API_KEY is set: calls Claude API.
If not: returns a template with fill-in-blank markers for Claude-in-conversation.
"""
from __future__ import annotations

import os
from pathlib import Path

import config

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "covers"


def draft(job_id: str, company: str, title: str, jd_text: str) -> dict:
    """
    Generate a cover letter for the role.
    Returns: { "cover_text": str, "output_path": str, "via_api": bool }
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if api_key:
        cover_text = _draft_via_api(company, title, jd_text, api_key)
        via_api = True
    else:
        cover_text = _template(company, title)
        via_api = False

    path = save_cover(job_id, company, cover_text)
    return {"cover_text": cover_text, "output_path": str(path), "via_api": via_api}


def _draft_via_api(company: str, title: str, jd_text: str, api_key: str) -> str:
    import anthropic

    prof       = config.profile()
    name       = prof.get("contact", {}).get("name", "the candidate")
    background = (prof.get("summary") or "").strip()

    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""Write a cover letter opening paragraph for {name} applying for {title} at {company}.

Background: {background}

Job description excerpt:
{jd_text[:2000]}

Rules:
- 1 paragraph, 4-5 sentences max.
- Open with something specific to {company} or the role. NOT "I am excited to apply" or "I am writing to express my interest".
- Reference a specific overlap between his background and the JD.
- Confident, direct tone. Not sycophantic.
- End with a clear ask for a conversation.

CRITICAL — make it read like a human wrote it, not AI. 2026 AI detectors flag these:
- NO em dashes (—), en dashes (–), or double dashes (--). Use periods or commas.
- NO rule-of-three triplets ("A, B, and C"). At most one per paragraph, preferably zero.
- NO flagged verbs: spearheaded, leveraged, architected (use built, ran, shipped, wrote instead).
- NO buzzwords: robust, comprehensive, seamless, end-to-end, ensuring, dynamic, results-driven, passionate.
- Vary sentence length. Mix short and longer sentences.
- Conversational, direct voice. Contractions are fine where they fit.

Return only the paragraph text. No subject line, no greeting, no sign-off."""

    msg = client.messages.create(
        model=config.preferences()["tailor_model"],
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


def _template(company: str, title: str) -> str:
    name = config.contact().get("name", "the candidate")
    return (
        f"[COVER LETTER — {title} at {company}]\n\n"
        f"Tailor this paragraph to reference something specific about {company} and connect "
        f"it to {name}'s background (see resume/profile.yaml). 1 paragraph, 4-5 sentences, "
        f"confident and direct. No em dashes. End with a clear ask for a call.\n\n"
        f"ANTHROPIC_API_KEY not set — draft this in Claude conversation."
    )


def save_cover(job_id: str, company: str, text: str) -> Path:
    """Persist cover letter to disk. Trailing newline always present."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = f"{company.lower().replace(' ', '_')}_{job_id}"
    path = OUTPUT_DIR / f"{slug}.txt"
    path.write_text(text.strip() + "\n")
    return path
