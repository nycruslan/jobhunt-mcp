#!/usr/bin/env python3.11
"""
JobHunt MCP Server
Exposes job search automation as Claude tools via the Model Context Protocol.

Policy: READ-ONLY from all external job platforms. Never POSTs to any job board.
All application submission is human-in-the-loop.

Tools:
  jobhunt_status     — pipeline overview + counts
  jobhunt_stats      — application funnel + response-rate analytics
  jobhunt_pull_feed  — refresh openings from target ATS boards (read-only)
  jobhunt_today      — today's new matches scored against your resume
  jobhunt_referrals  — LinkedIn contacts at a specific company
  jobhunt_draft      — tailored resume + cover letter for a role
  jobhunt_applied    — mark a role as applied, snapshot what was sent
  jobhunt_active_applications — list jobs in applied/screen/onsite
  jobhunt_set_status — advance a job's status (screen/onsite/offer/rejected/...)
  jobhunt_followup   — draft a polite nudge for a stale application
  jobhunt_prep       — interview themes for a company
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

MCP_DIR = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[RotatingFileHandler(MCP_DIR / "server.log", maxBytes=1_000_000, backupCount=2)],
)
log = logging.getLogger("jobhunt_mcp")

sys.path.insert(0, str(MCP_DIR))

import yaml
from mcp.server.fastmcp import FastMCP

import config
import tracker
import score as scorer
import feeds
import publish
from referrals.match import find_contacts, total_connections
from resume.tailor import tailor as tailor_resume
from cover.draft import draft as draft_cover, save_cover

mcp = FastMCP("JobHunt")
tracker.init_db()

# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_targets() -> dict:
    return yaml.safe_load((MCP_DIR / "targets.yaml").read_text())


def _all_companies() -> list[dict]:
    targets = _load_targets()
    companies = []
    for tier in targets.values():
        companies.extend(tier.get("companies", []))
    return companies


def _fmt_job(job: dict, show_jd: bool = False) -> str:
    comp, is_actual = scorer.display_comp(job)
    if comp:
        tc = f"${comp}" if is_actual else f"~${comp} (est)"
    else:
        tc = "n/a"
    contacts = find_contacts(job["company"])
    contact_str = f"  👥 {len(contacts)} contact(s)" if contacts else "  👤 no contacts"
    loc = job.get("location") or ("Remote" if job.get("remote") else "NYC")

    lines = [
        f"**{job['company']} — {job['title']}**",
        f"  Score: {job['score']}%  |  TC: {tc}  |  {loc}",
        f"  ID: {job['id']}",
        f"  URL: {job.get('url', 'n/a')}",
        contact_str,
    ]
    if show_jd and job.get("jd_text"):
        lines.append(f"\n  JD (excerpt):\n  {job['jd_text'][:600]}...")
    return "\n".join(lines)


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def jobhunt_status() -> str:
    """
    Show your full job search pipeline: counts by status, top matches, and
    pending follow-ups. Use this to get an at-a-glance view of where you stand.
    """
    counts = tracker.pipeline_counts()
    followups = tracker.get_followups(days=5)
    total = sum(counts.values())
    conn_count = total_connections()

    lines = ["📊 **JobHunt Pipeline**\n"]
    lines.append(f"LinkedIn connections loaded: {conn_count}")
    lines.append("")

    status_order = ["new", "reviewed", "drafted", "applied", "screen", "onsite", "offer", "rejected"]
    emojis = {"new":"🆕","reviewed":"👀","drafted":"✏️","applied":"📨",
               "screen":"📞","onsite":"🏢","offer":"🎉","rejected":"❌"}
    for s in status_order:
        n = counts.get(s, 0)
        if n:
            lines.append(f"  {emojis.get(s, '•')} {s.title():<12} {n}")

    lines.append(f"\n  Total tracked: {total}")

    if followups:
        lines.append(f"\n⏳ **Follow-ups due ({len(followups)}):**")
        now_utc = datetime.now(timezone.utc)
        for j in followups:
            try:
                days_ago = (now_utc - datetime.fromisoformat(j["applied_at"])).days
            except (ValueError, TypeError):
                days_ago = 0
            lines.append(f"  • {j['company']} — {j['title']} (applied {days_ago}d ago)")
            lines.append(f"    → call jobhunt_followup(job_id='{j['id']}')")

    lines.append(
        "\n💡 Commands:\n"
        "  jobhunt_pull_feed()      — refresh openings\n"
        "  jobhunt_today()          — review today's matches\n"
        "  jobhunt_draft(job_id)    — tailor resume + cover letter\n"
        "  jobhunt_applied(job_id)  — mark as applied"
    )
    return "\n".join(lines)


@mcp.tool()
def jobhunt_stats() -> str:
    """
    Application conversion analytics: how your pipeline is actually performing.
    Shows the funnel, your response rate, and where you've applied recently.
    Complements jobhunt_status (which is the at-a-glance pipeline view).
    """
    s = tracker.funnel_stats()
    counts = s["counts"]

    lines = ["📈 **Application Funnel**\n"]
    if not s["applied_total"]:
        lines.append("No applications logged yet. Mark roles with jobhunt_applied(job_id) to start tracking conversion.")
        return "\n".join(lines)

    lines.append(f"  Applied:    {s['applied_total']}")
    lines.append(f"  Responses:  {s['responded']}  ({s['response_rate']}% response rate)")
    stage_bits = [f"{counts[k]} {k}" for k in ("screen", "onsite", "offer", "rejected") if counts.get(k)]
    if stage_bits:
        lines.append("  Breakdown:  " + " · ".join(stage_bits))
    if s["offers"]:
        lines.append(f"\n🎉 {s['offers']} offer(s)!")

    by_co = tracker.applied_count_by_company(days=90)
    if by_co:
        lines.append("\n**Applied by company (last 90d):**")
        for co, n in sorted(by_co.items(), key=lambda x: -x[1]):
            lines.append(f"  • {co}: {n}")

    return "\n".join(lines)


@mcp.tool()
def jobhunt_pull_feed(company: str = "", min_score: int = 45) -> str:
    """
    Fetch fresh job openings from all target ATS boards + JobSpy (Indeed/Google Jobs).
    Read-only requests only — never posts or applies to anything.

    When company is empty, also runs the JobSpy supplemental feed which catches
    FAANG and other companies without clean public APIs (Meta, Apple, Microsoft, etc.).

    Args:
        company:   Optional company name to refresh just one company (skips JobSpy).
        min_score: Reporting threshold only (0-100). Everything fetched is stored;
                   this is what counts as a "match worth your time" in the summary.
    """
    companies = _all_companies()
    if company:
        companies = [c for c in companies if c["name"].lower() == company.lower()]
        if not companies:
            return f"❌ Company '{company}' not found in targets.yaml."

    prefs = config.preferences()
    full = not company  # aggregators are market-wide; only run them on a full pull
    new_count, errors, skipped = feeds.pull(
        companies,
        score_fn=scorer.score_job,
        upsert_fn=tracker.upsert_job,
        include_jobspy=full and prefs["enable_jobspy"],
        include_adzuna=full and prefs["enable_adzuna"],
        include_remotive=full and prefs["enable_remotive"],
    )

    lines = [f"✅ Feed refresh complete — **{new_count} new job(s)** added (everything stored, refreshed existing)."]

    if skipped:
        lines.append("\n⚠️ Manual ATS (check career sites directly):")
        for name, detail in skipped:
            lines.append(f"  • {name} ({detail})")

    if errors:
        lines.append("\n❌ Errors:")
        for name, detail in errors:
            lines.append(f"  • {name}: {detail}")

    lines.append(f"\nRun jobhunt_today(min_score={min_score}) to review new matches.")
    publish.publish_safe()
    return "\n".join(lines)


@mcp.tool()
def jobhunt_today(min_score: int = 60) -> str:
    """
    Show today's new job matches scored against your resume.
    Presents each role with score, TC estimate, and referral contacts.

    Scoring (2026): strong matches at top-paying targets land 75-95; solid roles
    60-75; off-list firms cap around 73. Default min_score=60 shows the matches
    worth your time. Use jobhunt_search() to browse all stored roles.

    Args:
        min_score: Minimum score to show (default 60).
    """
    jobs = tracker.get_today_new(min_score=min_score)

    if not jobs:
        _, total_stored = tracker.search_jobs(min_score=min_score, status="new")
        if total_stored:
            return (
                f"No new jobs fetched today, but **{total_stored} unreviewed job(s)** are "
                f"already in the tracker (score ≥ {min_score}%).\n\n"
                f"Browse them with:\n"
                f"  jobhunt_search()                    — top matches\n"
                f"  jobhunt_search(company='stripe')    — filter by company\n"
                f"  jobhunt_search(query='agent')       — filter by keyword\n"
                f"  jobhunt_search(min_score=40)        — broader view"
            )
        return (
            "No matches today. Run jobhunt_pull_feed() to fetch fresh openings.\n"
            "Tip: Run it once now to populate the tracker."
        )

    lines = [f"🔍 **{len(jobs)} new match(es) today** (score ≥ {min_score}%):\n"]
    for i, job in enumerate(jobs, 1):
        lines.append(f"{'─'*50}")
        lines.append(f"{i}. {_fmt_job(job)}")
        lines.append("")

    lines.append(
        "💡 Next steps:\n"
        "  jobhunt_referrals(company='...')    — see your contacts there\n"
        "  jobhunt_draft(job_id='...')         — generate tailored resume + cover letter"
    )
    return "\n".join(lines)


@mcp.tool()
def jobhunt_search(
    query: str = "",
    company: str = "",
    min_score: int = 55,
    status: str = "new",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """
    Browse ALL jobs in the tracker — not just today's new arrivals.
    Sorted by match score descending. Supports keyword search, company filter,
    status filter, and pagination across every stored role.

    Scoring (2026): top-paying target matches land 75-95, off-list firms cap ~73.
    The sweet spot is min_score=60 for strong matches, 45 for a broader view.

    Args:
        query:      Keyword to match against title or JD text (e.g. 'agent', 'platform', 'staff').
        company:    Filter to a single company (e.g. 'anthropic', 'stripe', 'openai').
        min_score:  Minimum match score 0–100 (default 55).
        status:     Pipeline status to show (default 'new'; e.g. 'applied', 'drafted', 'rejected').
        page:       Page number for pagination (default 1, 20 results per page).
        page_size:  Results per page, max 25 (default 20).
    """
    page_size = min(max(page_size, 1), 25)
    offset = (page - 1) * page_size

    jobs, total = tracker.search_jobs(
        query=query,
        company=company,
        min_score=min_score,
        status=status,
        limit=page_size,
        offset=offset,
    )

    if not jobs:
        hints = []
        if min_score > 60:
            hints.append(f"jobhunt_search(min_score=60)")
        if company:
            hints.append(f"jobhunt_search()  — remove company filter")
        if query:
            hints.append(f"jobhunt_search()  — remove keyword filter")
        hint_str = "\n  ".join(hints) if hints else "jobhunt_pull_feed()  — refresh the feed"
        return f"No jobs found (score ≥ {min_score}%). Try:\n  {hint_str}"

    total_pages = max(1, (total + page_size - 1) // page_size)
    filter_desc = ""
    if company:
        filter_desc += f" · company={company}"
    if query:
        filter_desc += f" · keyword='{query}'"

    lines = [
        f"🔍 **{total} job(s) found{filter_desc}** — page {page}/{total_pages} (score ≥ {min_score}%)\n"
    ]
    for i, job in enumerate(jobs, offset + 1):
        lines.append("─" * 50)
        lines.append(f"{i}. {_fmt_job(job)}")
        lines.append("")

    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(f"jobhunt_search(page={page - 1})  ← prev")
        if page < total_pages:
            nav.append(f"jobhunt_search(page={page + 1})  → next")
        lines.append("📄 " + "   |   ".join(nav))
        lines.append("")

    lines.append(
        "💡 Actions:\n"
        "  jobhunt_draft(job_id='...')           — tailored resume + cover letter\n"
        "  jobhunt_referrals(company='...')      — LinkedIn contacts\n"
        "  jobhunt_dismiss(job_id='...')         — hide forever\n"
        "  jobhunt_search(query='agent')         — filter by keyword\n"
        "  jobhunt_search(company='stripe')      — filter by company"
    )
    return "\n".join(lines)


@mcp.tool()
def jobhunt_referrals(company: str) -> str:
    """
    Find your LinkedIn connections who work at the given company.
    Uses your official LinkedIn data export — no scraping.

    Args:
        company: Company name (e.g. 'Anthropic', 'Stripe', 'Two Sigma').
    """
    contacts = find_contacts(company)

    if not contacts:
        return (
            f"No LinkedIn connections found at {company}.\n\n"
            f"Cold application strategy:\n"
            f"1. Search LinkedIn for '{company}' + 'Software Engineer' to find 2nd-degree connections\n"
            f"2. Ask a mutual contact for an intro\n"
            f"3. Email the recruiter directly (find on LinkedIn or company site)"
        )

    lines = [f"👥 **{len(contacts)} connection(s) at {company}:**\n"]
    for c in contacts:
        lines.append(f"• **{c['name']}** — {c['position']}")
        if c.get("profile_url"):
            lines.append(f"  {c['profile_url']}")
        lines.append("")

    prof        = config.profile()
    target_role = (prof.get("target_roles") or ["Senior Software Engineer"])[0]
    cur_company = (prof.get("experience") or [{}])[0].get("company", "")
    bg          = f" given my background at {cur_company}" if cur_company else ""

    lines.append(
        "📝 **Suggested referral DM** (send from YOUR LinkedIn manually):\n\n"
        f"Hi [Name], hope you're doing well! I've been following {company}'s work closely "
        f"and I'm exploring a move. Saw there's a {target_role} opening that looks like a "
        f"great fit{bg}. Would you be open to a quick referral, or just share any context "
        f"on the team? No pressure either way, appreciate you!"
    )
    return "\n".join(lines)


@mcp.tool()
def jobhunt_draft(job_id: str) -> str:
    """
    Generate a tailored resume and cover letter for a specific job.
    Saves output to ~/.jobhunt_mcp/output/ and marks the job as 'drafted'.

    Args:
        job_id: Job ID from jobhunt_today() or jobhunt_status().
    """
    job = tracker.get_job(job_id)
    if not job:
        return f"❌ Job ID '{job_id}' not found. Run jobhunt_today() to see current jobs."

    company = job["company"]
    title   = job["title"]
    jd_text = job.get("jd_text", "")

    # Tailored resume
    resume_result = tailor_resume(job_id, company, title, jd_text)

    # Cover letter
    cover_result = draft_cover(job_id, company, title, jd_text)

    # Referral contacts
    contacts = find_contacts(company)

    # Update tracker
    tracker.update_status(
        job_id, "drafted",
        resume_path=resume_result["output_path"],
        cover_path=cover_result["output_path"],
    )

    comp, is_actual = scorer.display_comp(job)
    if comp:
        tc = f"${comp} (from posting)" if is_actual else f"~${comp} (company band)"
    else:
        tc = "n/a"
    keywords = scorer.extract_keywords(jd_text)

    md_path  = Path(resume_result["output_path"])
    pdf_path = md_path.with_suffix(".pdf")
    has_pdf  = pdf_path.exists()

    lines = [
        f"✅ **Draft ready — {company}: {title}**\n",
        f"Score: {job['score']}%  |  TC range: {tc}",
        f"Top JD keywords: {', '.join(keywords[:10])}",
        "",
    ]

    if has_pdf:
        lines += [
            f"📄 Resume PDF (upload this):",
            f"   {pdf_path}",
        ]
    else:
        lines += [
            f"📄 Resume Markdown:",
            f"   {md_path}",
        ]

    lines += [
        f"📝 Cover letter (paste into application):",
        f"   {cover_result['output_path']}",
    ]

    if not resume_result["via_api"]:
        lines += [
            "",
            "⚠️  ANTHROPIC_API_KEY not set — resume uses your full master bullets.",
            "   To enable AI tailoring: add to ~/.zshrc:",
            "   export ANTHROPIC_API_KEY='sk-ant-...'",
            "   Then: source ~/.zshrc",
            "",
            "   Or ask me to tailor it now: just say 'tailor my resume for this role'.",
        ]

    if contacts:
        lines += ["", f"👥 {len(contacts)} referral contact(s) at {company} — run jobhunt_referrals(company='{company}') for details"]

    lines += [
        "",
        f"🔗 **Apply URL:** {job.get('url', 'company career site')}",
        "",
        "═══════════════════════════════════════════════════════════════",
        "📋 JOB DESCRIPTION (use this to write a tailored cover letter)",
        "═══════════════════════════════════════════════════════════════",
        jd_text[:4000] if jd_text else "(no JD text stored — fetch from URL above)",
        "═══════════════════════════════════════════════════════════════",
        "",
        "**Next steps:**",
        f"1. {'Open the PDF above and upload it' if has_pdf else 'Open the Markdown above'}",
        f"2. Write a tailored cover letter using the JD above, then call jobhunt_save_cover(job_id='{job_id}', cover_text=...) to save it",
        f"3. Apply at: {job.get('url', 'company career site')}",
        f"4. After applying, run: jobhunt_applied(job_id='{job_id}')",
    ]

    return "\n".join(lines)


@mcp.tool()
def jobhunt_save_cover(job_id: str, cover_text: str) -> str:
    """
    Save a cover letter for a specific job (overwrites any existing draft).
    Use this after writing a tailored cover letter inline in the chat.

    Args:
        job_id:     Job ID from jobhunt_today() or jobhunt_status().
        cover_text: The full cover letter text (1 paragraph, no greeting/signoff).
    """
    job = tracker.get_job(job_id)
    if not job:
        return f"❌ Job ID '{job_id}' not found."

    path = save_cover(job_id, job["company"], cover_text)
    tracker.update_status(job_id, "drafted", cover_path=str(path))
    return f"✅ Cover letter saved → {path}"


@mcp.tool()
def jobhunt_applied(job_id: str, notes: str = "") -> str:
    """
    Mark a job as applied. Records the application date and snapshots the state.

    Args:
        job_id: Job ID from jobhunt_today() or jobhunt_status().
        notes:  Optional notes (e.g. referral name, portal used).
    """
    job = tracker.get_job(job_id)
    if not job:
        return f"❌ Job ID '{job_id}' not found."

    if job["status"] == "applied":
        return f"ℹ️  Already marked applied on {job['applied_at']}."

    tracker.update_status(job_id, "applied", notes=notes)
    job = tracker.get_job(job_id)
    publish.publish_safe()

    return (
        f"📨 **Applied — {job['company']}: {job['title']}**\n"
        f"   Applied at: {job['applied_at']}\n"
        f"   Resume: {job.get('resume_path', 'n/a')}\n"
        f"   Cover: {job.get('cover_path', 'n/a')}\n"
        f"   Notes: {notes or '—'}\n\n"
        f"I'll flag this for a follow-up nudge in 5 days if no response.\n"
        f"Run jobhunt_status() to see your full pipeline."
    )


@mcp.tool()
def jobhunt_active_applications() -> str:
    """
    List every job in an active application stage (applied, screen, onsite).
    Use this to know what to check for updates, e.g. before scanning email for
    recruiter replies (see the /jobhunt-sync command).
    """
    rows = tracker.active_applications()
    if not rows:
        return "No active applications. Mark roles with jobhunt_applied(job_id) first."

    lines = [f"📨 **{len(rows)} active application(s):**\n"]
    for j in rows:
        applied = (j.get("applied_at") or "")[:10]
        lines.append(f"• {j['company']} — {j['title']}")
        lines.append(f"  id: {j['id']}  |  status: {j['status']}  |  applied: {applied or 'n/a'}")
    return "\n".join(lines)


@mcp.tool()
def jobhunt_set_status(job_id: str, status: str, notes: str = "") -> str:
    """
    Advance a job's pipeline status: reviewed, drafted, applied, screen, onsite,
    offer, rejected, withdrawn. Use this when an application moves (e.g. a recruiter
    email turns it into a 'screen', or a rejection comes in). For a first-time apply,
    prefer jobhunt_applied (it also snapshots resume/cover and sets the apply date).

    Args:
        job_id: Job ID.
        status: New pipeline status.
        notes:  Optional context (e.g. 'screen invite, email 2026-06-07'). Appended
                to any existing notes, never overwritten.
    """
    job = tracker.get_job(job_id)
    if not job:
        return f"❌ Job ID '{job_id}' not found."

    status = status.strip().lower()
    if status not in tracker.VALID_STATUSES:
        return f"❌ Invalid status '{status}'. Choose from: {', '.join(sorted(tracker.VALID_STATUSES))}."

    prev = job["status"]
    kwargs = {}
    if notes:
        kwargs["notes"] = f"{job['notes']} | {notes}" if job.get("notes") else notes
    tracker.update_status(job_id, status, **kwargs)
    publish.publish_safe()

    msg = f"✅ {job['company']} — {job['title']}: {prev} → {status}"
    return f"{msg}  ({notes})" if notes else msg


@mcp.tool()
def jobhunt_dismiss(job_id: str) -> str:
    """
    Dismiss a job — hide it from briefings forever. Use when you've decided
    a role isn't a fit and don't want to keep seeing it.

    Args:
        job_id: Job ID from the morning briefing.
    """
    job = tracker.get_job(job_id)
    if not job:
        return f"❌ Job ID '{job_id}' not found."
    if tracker.dismiss_job(job_id):
        return f"🚫 Dismissed: {job['company']} — {job['title']}. Won't show in future briefings."
    return f"❌ Could not dismiss '{job_id}'."


@mcp.tool()
def jobhunt_snooze_company(company: str, days: int = 30) -> str:
    """
    Mute all new roles from a company for N days. Useful when a company keeps
    posting roles that aren't relevant (e.g. Stripe Support).

    Args:
        company: Company name (case-insensitive).
        days:    Number of days to mute. Defaults to 30.
    """
    until_iso = tracker.snooze_company(company, days)
    return (
        f"😴 Snoozed *{company}* for {days} days (until {until_iso[:10]}). "
        f"Run jobhunt_unsnooze_company('{company}') to undo."
    )


@mcp.tool()
def jobhunt_unsnooze_company(company: str) -> str:
    """Lift a company snooze early."""
    if tracker.unsnooze_company(company):
        return f"✅ Unsnoozed *{company}*. New roles will appear in the next briefing."
    return f"ℹ️  *{company}* was not snoozed."


@mcp.tool()
def jobhunt_followup(job_id: str) -> str:
    """
    Draft a polite, brief follow-up message for a stale application.

    Args:
        job_id: Job ID from jobhunt_status() follow-ups list.
    """
    job = tracker.get_job(job_id)
    if not job:
        return f"❌ Job ID '{job_id}' not found."

    days_since = 0
    if job.get("applied_at"):
        try:
            delta = datetime.now(timezone.utc) - datetime.fromisoformat(job["applied_at"])
            days_since = delta.days
        except ValueError:
            pass

    company = job["company"]
    title   = job["title"]

    c        = config.contact()
    sig_bits = [b for b in (c.get("email"), c.get("phone")) if b]
    signature = c.get("name", "")
    if sig_bits:
        signature += "\n" + " | ".join(sig_bits)

    followup = (
        f"Hi [Recruiter name],\n\n"
        f"I wanted to briefly follow up on my application for the {title} role at {company} "
        f"submitted {days_since} days ago. I remain very interested and would love to learn "
        f"about next steps when you have a moment. Happy to provide any additional context.\n\n"
        f"Thanks,\n{signature}"
    )

    return (
        f"📧 **Follow-up draft — {company}: {title}**\n"
        f"Applied: {days_since} days ago\n\n"
        f"---\n{followup}\n---\n\n"
        f"Send this to the recruiter via email or LinkedIn. "
        f"Find their contact at: {job.get('url', company + ' careers page')}"
    )


@mcp.tool()
def jobhunt_prep(company: str) -> str:
    """
    Interview preparation context for a target company: culture, known interview style,
    what to research, and suggested questions to ask.

    Args:
        company: Company name (e.g. 'Anthropic', 'Two Sigma').
    """
    guide = config.prep_guides().get(company)
    if guide:
        return guide

    # No static guide — ground prep in a real stored posting for this company so
    # Claude can expand it against the actual JD (status="" searches all statuses).
    jobs, _ = tracker.search_jobs(company=company, min_score=0, status="", limit=1)
    if jobs and jobs[0].get("jd_text"):
        job = jobs[0]
        keywords = scorer.extract_keywords(job["jd_text"])[:12]
        return (
            f"**{company} — interview prep**\n\n"
            f"Grounded in a stored posting: *{job['title']}*.\n"
            f"Likely focus areas (pulled from the JD): {', '.join(keywords) or 'general SWE'}\n\n"
            f"Draft prep from the JD below: the core systems the role owns, how the "
            f"candidate's background maps to them, 4-5 talking points, and 3 sharp "
            f"questions to ask the interviewer.\n\n"
            f"JD excerpt:\n{job['jd_text'][:1500]}"
        )

    # Generic guide for companies with no stored posting either
    return (
        f"**{company} Interview Prep**\n\n"
        f"No specific guide yet. General senior SWE prep:\n"
        f"• Coding: LC Medium/Hard — arrays, trees, graphs, DP\n"
        f"• Systems design: distributed systems, caching, message queues, DB tradeoffs\n"
        f"• Behavioral: STAR format — leadership, conflict resolution, architecture decisions\n"
        f"• {company}-specific: Read their engineering blog, recent tech talks, open source repos\n"
        f"• Questions to ask: Team structure, AI strategy, biggest technical challenges\n\n"
        f"Resources: Glassdoor interview reviews for '{company}', Blind, levels.fyi"
    )


# ── Prompts ──────────────────────────────────────────────────────────────────────
# Prompts surface as slash commands across MCP clients, including Claude Desktop
# (where the Claude Code `~/.claude/commands` files are not read). They return a
# short instruction; the tools above do the real work.

@mcp.prompt()
def today() -> str:
    """Pull fresh jobs and show today's top matches."""
    return (
        "Call jobhunt_pull_feed, then jobhunt_today. Show matches sorted by score "
        "descending with TC range and apply URL, and flag roles that have LinkedIn "
        "referral contacts."
    )


@mcp.prompt()
def search(query: str = "", company: str = "") -> str:
    """Browse all stored jobs, optionally by keyword and/or company."""
    return (
        f"Call jobhunt_search(query='{query}', company='{company}', min_score=60). "
        "Show score, TC, location, and apply URL per role, plus the pagination hint."
    )


@mcp.prompt()
def draft(job_id: str) -> str:
    """Tailored resume PDF + cover letter for a job id."""
    return (
        f"Call jobhunt_draft(job_id='{job_id}'). Read the returned JD, write a "
        "1-paragraph cover letter using the candidate's background from profile.yaml, "
        f"then save it with jobhunt_save_cover(job_id='{job_id}', cover_text=...). Show "
        "the PDF path, the cover letter in a copy-friendly block, and the apply URL.\n\n"
        "Cover voice: open specific to the company, end with a clear ask. No em dashes, "
        "no rule-of-three triplets, vary sentence length, plain verbs, no buzzwords."
    )


@mcp.prompt()
def cover(job_id: str) -> str:
    """Just the cover letter for a job id."""
    return (
        f"Fetch the JD via jobhunt_draft(job_id='{job_id}'), write a 1-paragraph cover "
        "letter from profile.yaml plus the JD, and save it with jobhunt_save_cover. Same "
        "human voice as the draft prompt. Show it in a copy-friendly block."
    )


@mcp.prompt()
def prep(company: str) -> str:
    """Interview prep for a company."""
    return (
        f"Call jobhunt_prep(company='{company}'). If it returns a JD-grounded scaffold, "
        "expand it into full prep: core systems, how the candidate maps to them, 4-5 "
        "talking points, and 3 sharp questions to ask."
    )


@mcp.prompt()
def referrals(company: str) -> str:
    """LinkedIn contacts at a company."""
    return (
        f"Call jobhunt_referrals(company='{company}'). List each contact with role and "
        "profile link, then show the suggested DM. Remind the user to send it themselves."
    )


@mcp.prompt()
def stats() -> str:
    """Application funnel analytics."""
    return "Call jobhunt_stats and present the funnel, response rate, and applied-by-company."


@mcp.prompt()
def sync(days: str = "") -> str:
    """Scan email for application updates (read-only; you confirm every change)."""
    window = f" within the last {days} days" if days else ""
    return (
        "Run the email sync. Call jobhunt_active_applications, then search the user's "
        f"connected Gmail (READ-ONLY) for recruiter replies on those companies{window}. "
        "Classify each as screen/onsite/offer/rejected or no change, show a review table "
        "with evidence, and only after the user confirms, call jobhunt_set_status for "
        "each approved change. Never change status without explicit confirmation."
    )


@mcp.prompt()
def setup() -> str:
    """Set up JobHunt: build a profile from a resume, pick targets, wire the brief."""
    return (
        "Walk the user through setup conversationally; do not make them hand-edit YAML. "
        "Read resume/profile.example.yaml for the schema, ask for their resume (pasted "
        "text, a PDF path, or a LinkedIn export) and write resume/profile.yaml, set "
        "preferences (location, remote, brief_delivery), help trim targets.yaml, and "
        "optionally configure the Telegram/email brief in briefing.conf. Finish with a "
        "jobhunt_pull_feed + jobhunt_today smoke test."
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("JobHunt MCP server starting…")
    mcp.run()


if __name__ == "__main__":
    main()
