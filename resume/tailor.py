"""
Resume rendering — builds a clean Markdown + PDF resume from the master profile.

Deterministic and local: the resume is your profile.yaml, laid out and rendered
to a single-page PDF. There is no per-role content tailoring here; role-specific
tailoring happens inline in the Claude conversation (which already has the JD
and your full background), not through a separate API call.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import config

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "resumes"


def tailor(job_id: str, company: str, title: str = "", jd_text: str = "") -> dict:
    """Render the master resume to Markdown + PDF for this role.

    Despite the name, this does not tailor content: it renders the master
    profile per job so each application gets its own file for tracking.
    title/jd_text are accepted for call-site stability but unused; the file
    name is keyed on company + job_id. Returns {"output_path": <markdown path>}.
    """
    master = config.profile()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _save_markdown(master, job_id, company)
    return {"output_path": str(path)}


def _txt(value) -> str:
    """Profile value -> markdown-safe string. Tab is the PDF renderer's
    two-column marker, so any tab in profile text would silently split the
    line into columns; collapse tabs to spaces."""
    return str(value).replace("\t", " ")


def _job_header_lines(exp: dict) -> list[str]:
    """Two-column header rows: Company/Location and Title/Date. The tab tells the
    PDF renderer to right-align the second column."""
    dates = f"{_fmt_date(exp['start'])} – {_fmt_date(exp['end'])}"
    return [
        f"**{_txt(exp['company'])}**\t**{_txt(exp['location'])}**",
        f"*{_txt(exp['title'])}*\t*{dates}*",
    ]


def _save_markdown(resume: dict, job_id: str, company: str) -> Path:
    c = resume["contact"]
    contact_parts = [c["location"], c["phone"], c["email"], c["linkedin"]]
    if c.get("portfolio"):
        contact_parts.append(c["portfolio"])

    lines = [f"# {_txt(c['name'])}", _txt(" | ".join(str(p) for p in contact_parts)), ""]

    if resume.get("summary"):
        lines += ["## Summary", _txt(resume["summary"].strip()), ""]

    lines.append("## Experience")
    for exp in resume["experience"]:
        lines += _job_header_lines(exp) + [""]
        for b in exp["bullets"]:
            lines.append(f"- {_txt(b)}")
        lines.append("")

    lines.append("## Skills")
    for category, skills in resume.get("skills", {}).items():
        lines.append(f"**{_pretty_category(category)}:** {_txt(', '.join(skills))}")
    lines.append("")

    lines.append("## Education")
    for edu in resume.get("education", []):
        lines.append(
            f"**{_txt(edu['institution'])}** — {_txt(edu['degree'])} "
            f"({_fmt_date(edu['start'])} – {_fmt_date(edu['end'])})"
        )
    lines.append("")

    slug = f"{config.slugify(company)}_{job_id}"
    path = OUTPUT_DIR / f"{slug}.md"
    path.write_text("\n".join(lines))

    # Render a PDF alongside the Markdown. A PDF failure never blocks the draft,
    # but a stale PDF from an earlier run must not survive a failed re-render
    # (the server treats pdf_path.exists() as success), so remove it first.
    pdf_path = path.with_suffix(".pdf")
    pdf_path.unlink(missing_ok=True)
    try:
        from resume.render_pdf import render_pdf
        render_pdf(path, pdf_path)
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


def _fmt_date(d) -> str:
    """Format a profile date as 'Mon YYYY'. Accepts 'YYYY-MM' strings, the
    literal 'present', and date/datetime objects (unquoted YAML dates parse as
    datetime.date, which strptime would reject with TypeError)."""
    if d == "present":
        return "Present"
    if isinstance(d, (date, datetime)):
        return d.strftime("%b %Y")
    try:
        return datetime.strptime(d, "%Y-%m").strftime("%b %Y")
    except (ValueError, TypeError):
        return _txt(d)
