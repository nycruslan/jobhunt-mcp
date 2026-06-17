"""
Resume rendering — builds a clean Markdown + PDF resume from the master profile.

Deterministic and local: the resume is your profile.yaml, laid out and rendered
to a single-page PDF. Role-specific tailoring happens inline in the Claude
conversation (which already has the JD and your full background), not through a
separate API call.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

import config

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "resumes"


def tailor(job_id: str, company: str, title: str = "", jd_text: str = "") -> dict:
    """Render the master resume to Markdown + PDF for this role.

    title/jd_text are accepted for call-site stability; the file name is keyed on
    company + job_id. Returns {"output_path": <markdown path>}.
    """
    master = yaml.safe_load(config.PROFILE_PATH.read_text())
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _save_markdown(master, job_id, company)
    return {"output_path": str(path)}


def _job_header_lines(exp: dict) -> list[str]:
    """Two-column header rows: Company/Location and Title/Date. The tab tells the
    PDF renderer to right-align the second column."""
    dates = f"{_fmt_date(exp['start'])} – {_fmt_date(exp['end'])}"
    return [
        f"**{exp['company']}**\t**{exp['location']}**",
        f"*{exp['title']}*\t*{dates}*",
    ]


def _save_markdown(resume: dict, job_id: str, company: str) -> Path:
    c = resume["contact"]
    contact_parts = [c["location"], c["phone"], c["email"], c["linkedin"]]
    if c.get("portfolio"):
        contact_parts.append(c["portfolio"])

    lines = [f"# {c['name']}", " | ".join(contact_parts), ""]

    if resume.get("summary"):
        lines += ["## Summary", resume["summary"].strip(), ""]

    lines.append("## Experience")
    for exp in resume["experience"]:
        lines += _job_header_lines(exp) + [""]
        for b in exp["bullets"]:
            lines.append(f"- {b}")
        lines.append("")

    lines.append("## Skills")
    for category, skills in resume.get("skills", {}).items():
        lines.append(f"**{_pretty_category(category)}:** {', '.join(skills)}")
    lines.append("")

    lines.append("## Education")
    for edu in resume.get("education", []):
        lines.append(
            f"**{edu['institution']}** — {edu['degree']} "
            f"({_fmt_date(edu['start'])} – {_fmt_date(edu['end'])})"
        )
    lines.append("")

    slug = f"{company.lower().replace(' ', '_')}_{job_id}"
    path = OUTPUT_DIR / f"{slug}.md"
    path.write_text("\n".join(lines))

    # Render a PDF alongside the Markdown. A PDF failure never blocks the draft.
    try:
        from resume.render_pdf import render_pdf
        render_pdf(path, path.with_suffix(".pdf"))
    except Exception as exc:
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
