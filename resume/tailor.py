"""
Resume tailoring — generates a JD-specific resume using Claude.

If ANTHROPIC_API_KEY is set: calls Claude API directly.
If not set: returns structured data so Claude-in-conversation can tailor.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import yaml

import config

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "resumes"


def load_master() -> dict:
    # Fresh copy each call — tailoring mutates the dict, so never share config's cache.
    return yaml.safe_load(config.PROFILE_PATH.read_text())


def tailor(job_id: str, company: str, title: str, jd_text: str) -> dict:
    """
    Produce a tailored resume for this specific role.

    Returns:
        {
            "tailored_yaml": {...},   # modified master with reordered bullets
            "output_path":  str,      # where the markdown file was saved
            "via_api":      bool,     # True if Claude API was used
        }
    """
    master = load_master()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        tailored = _tailor_via_api(master, company, title, jd_text, api_key)
    else:
        # Return raw data — Claude in conversation will tailor
        tailored = master
        tailored["_tailor_note"] = (
            "ANTHROPIC_API_KEY not set. "
            "Tailor bullets manually or set the key in ~/.zshrc."
        )

    path = _save_markdown(tailored, job_id, company, title)
    return {"tailored_yaml": tailored, "output_path": str(path), "via_api": bool(api_key)}


def _tailor_via_api(master: dict, company: str, title: str, jd_text: str, api_key: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    name = master.get("contact", {}).get("name", "the candidate")
    bullets_text = "\n".join(
        f"- {b}" for exp in master["experience"] for b in exp["bullets"]
    )
    skills_text = ", ".join(master.get("all_skills_flat", []))

    prompt = f"""You are tailoring {name}'s resume for this specific role.

Role: {title} at {company}

Job Description:
{jd_text[:3000]}

Current resume bullets:
{bullets_text}

Current skills: {skills_text}

Instructions:
1. Select and reorder the 5-7 most relevant bullets for this role from the existing ones.
2. Lightly rephrase each selected bullet to echo JD language (max 20% word change — keep it honest).
3. List the top 8 most relevant skills for this role from the skills list.
4. Write a 2-sentence summary tailored to this role.

CRITICAL — make this read like a human wrote it, not AI. 2026 AI detectors flag these patterns:
- NO em dashes (—). Use periods, commas, or rephrase.
- NO rule-of-three triplets ("A, B, and C" patterns). Mix pairs, quads, or single ideas. Max one triplet per bullet, never two.
- NO flagged verbs: Architected, Spearheaded, Leveraged, Engineered, Implemented, Pivotal, Showcasing, Delve. Use plain verbs: built, ran, wrote, shipped, set up, used.
- NO buzzwords: "end-to-end", "robust", "comprehensive", "seamless", "ensuring", "responsible AI practices", "track record".
- VARY sentence length. Some short. Some longer. Not all parallel.
- Asymmetric numbers (about 35%, roughly 55%, around 8 teams) NOT round ones (35%, 60%, 10+).
- Conversational where natural: "Stack:", "Today", "Cut X to Y", contractions OK.

Return ONLY a JSON object with keys: "bullets" (list of strings), "top_skills" (list of strings), "summary" (string).

No explanation, just JSON."""

    msg = client.messages.create(
        model=config.preferences()["tailor_model"],
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    import json
    try:
        tailored_data = json.loads(msg.content[0].text)
        master["_tailored"] = tailored_data
    except json.JSONDecodeError:
        master["_tailor_note"] = "API tailor parse failed — use raw bullets"

    return master


def _save_markdown(resume: dict, job_id: str, company: str, title: str) -> Path:
    c = resume["contact"]
    tailored = resume.get("_tailored", {})

    contact_parts = [c['location'], c['phone'], c['email'], c['linkedin']]
    if c.get('portfolio'):
        contact_parts.append(c['portfolio'])

    lines = [
        f"# {c['name']}",
        " | ".join(contact_parts),
        "",
    ]

    # Summary — prefer Claude-tailored summary; otherwise use profile.yaml summary
    summary_text = tailored.get("summary") or resume.get("summary")
    if summary_text:
        lines += ["## Summary", summary_text.strip(), ""]

    # Experience — two-column layout: Company/Title left, Location/Date right
    # Tab-separated lines tell the renderer to right-align the second column.
    lines.append("## Experience")

    def job_header_lines(exp: dict) -> list[str]:
        dates = f"{_fmt_date(exp['start'])} – {_fmt_date(exp['end'])}"
        return [
            f"**{exp['company']}**\t**{exp['location']}**",
            f"*{exp['title']}*\t*{dates}*",
        ]

    if tailored.get("bullets"):
        exp = resume["experience"][0]
        lines += job_header_lines(exp) + [""]
        for b in tailored["bullets"]:
            lines.append(f"- {b}")
        lines.append("")
        for exp in resume["experience"][1:]:
            lines += job_header_lines(exp) + [""]
            for b in exp["bullets"][:2]:
                lines.append(f"- {b}")
            lines.append("")
    else:
        for exp in resume["experience"]:
            lines += job_header_lines(exp) + [""]
            for b in exp["bullets"]:
                lines.append(f"- {b}")
            lines.append("")

    # Skills
    lines.append("## Skills")
    if tailored.get("top_skills"):
        lines.append(", ".join(tailored["top_skills"]))
    else:
        for category, skills in resume.get("skills", {}).items():
            lines.append(f"**{_pretty_category(category)}:** {', '.join(skills)}")
    lines.append("")

    # Education
    lines.append("## Education")
    for edu in resume.get("education", []):
        lines.append(f"**{edu['institution']}** — {edu['degree']} ({_fmt_date(edu['start'])} – {_fmt_date(edu['end'])})")
    lines.append("")

    if resume.get("_tailor_note"):
        lines += ["---", f"*Note: {resume['_tailor_note']}*"]

    slug = f"{company.lower().replace(' ', '_')}_{job_id}"
    path = OUTPUT_DIR / f"{slug}.md"
    path.write_text("\n".join(lines))

    # Render PDF alongside the Markdown
    try:
        from resume.render_pdf import render_pdf
        render_pdf(path, path.with_suffix(".pdf"))
    except Exception as exc:
        # PDF failure never blocks the draft — Markdown is always the source of truth
        import logging
        logging.getLogger("jobhunt_mcp").warning("PDF render failed: %s", exc)

    return path


_CATEGORY_LABELS = {
    "ai_ml":             "AI / ML",
    "model_providers":   "Model Providers",
    "protocols_tooling": "Protocols & Tooling",
    "architecture":      "Architecture",
    "backend":           "Backend",
    "frontend":          "Frontend",
    "cloud_devops":      "Cloud & DevOps",
    "leadership":        "Leadership",
}


def _pretty_category(key: str) -> str:
    return _CATEGORY_LABELS.get(key, key.replace("_", " ").title())


def _fmt_date(d: str) -> str:
    if d == "present":
        return "Present"
    try:
        return datetime.strptime(d, "%Y-%m").strftime("%b %Y")
    except ValueError:
        return str(d)
