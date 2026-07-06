Automated morning sync: advance the pipeline from email, then stage materials. $ARGUMENTS

Read-only on email. You confirm anything high-stakes. Designed to run unattended
on a schedule (see "Scheduling" below), but works on demand too.

**1. Gather what's in flight**
- Call `jobhunt_active_applications` to list applied/screen/onsite roles.
- Call `jobhunt_status` to see what's `drafted` but not yet marked applied.

**2. Scan Gmail (READ-ONLY)**
Search the connected Gmail for messages within the window ($ARGUMENTS days, default 3)
about those companies. Look for two things:
- **Application receipts** — "thank you for applying", "we received your application". These confirm a role you drafted is actually submitted.
- **Recruiter replies** — a rejection, an interview/screen request, an onsite invite, or an offer.

Classify each message into one signal: `application_received`, `rejected`,
`interview`, `onsite`, or `offer`. Skip anything ambiguous or unrelated.
Before classifying, check the sender: the domain must plausibly belong to the
company or its ATS (greenhouse.io, lever.co, ashbyhq.com, myworkday.com, and
the like, with the company named in the message). Skip anything from an
unrelated or suspicious domain, whatever it claims.

**3. Record each update safely**
For every classified message call:
`jobhunt_record_update(company="...", signal="...", evidence="<subject or short quote>")`

The tool decides what is safe: `interview` applies automatically, and
`application_received` does too when the role was already drafted or applied.
`rejected`, `onsite`, and `offer` come back asking you to confirm (a rejection is
terminal, so it always gets a human look). It never guesses when several
applications match the same company, and never moves a stage backwards. Do not
call `jobhunt_set_status` directly here — let the tool hold the policy.

**4. Pre-stage materials for new top matches (optional, default 3)**
For up to 3 of today's highest-scoring `new` matches that aren't drafted yet:
- Call `jobhunt_draft(job_id=...)`, read the JD, write the 1-paragraph cover letter
  in the candidate's voice (follow CLAUDE.md), and save it with `jobhunt_save_cover`.
- This marks them `drafted` with a resume PDF and cover ready, so applying later is review-and-submit.
Skip this step if you only want the email sync.

**5. Report**
Summarize in three short groups:
- ✅ Auto-applied (what moved, e.g. "Stripe drafted→applied").
- 🔔 Needs confirmation (rejected/onsite/offer, or multiple-match ambiguity) with the exact tool call to run.
- 📄 Pre-drafted (company, role, PDF path) if step 4 ran.

Never change a status without either the tool's auto-apply or your explicit confirmation.
Never send any outbound email or message.

**Scheduling**
Run this unattended with the `/schedule` skill (a cloud cron agent), e.g. daily at 8am
on weekdays. It needs the connected Gmail and the jobhunt MCP server. The deterministic
policy lives in `auto.py` and is covered by tests, so the scheduled run stays predictable.
