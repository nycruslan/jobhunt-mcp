Scan email for updates on active applications and advance the pipeline. $ARGUMENTS

Close the loop: the tracker only knows what it's told. This checks your inbox for
recruiter replies and proposes status changes, which YOU confirm before anything
is written.

**Guardrails (do not break these):**
- Gmail access is READ-ONLY. Only search and read threads. Never send, archive, label, or delete anything.
- NEVER change a job's status without explicit user confirmation in this conversation.
- Be conservative. If a match is ambiguous, leave the job alone and flag it for manual review.

**Preconditions:**
- Needs a connected Gmail MCP (the claude.ai Gmail connector exposes thread search + read, e.g. `search_threads` and `get_thread`). If no Gmail tool is available, tell the user to add the Gmail connector in Claude, then stop.

**Steps:**

1. Call `jobhunt_active_applications` to get every job in applied / screen / onsite, with its id, company, title, current status, and applied date.

2. For each distinct company, search Gmail (read-only) for recent, relevant threads. Use a tight window (default last 45 days; if the user passed a number of days in $ARGUMENTS, use that). Good queries combine the company name with role/recruiting language and the applied date as a floor. Skip obvious marketing/newsletter mail.

3. Read the matching threads and classify the LATEST state of each application:
   - interview / phone screen / scheduling → **screen**
   - onsite / final round / panel → **onsite**
   - offer → **offer**
   - rejection / "moving forward with other candidates" / "not proceeding" → **rejected**
   - assessment/OA, or just an acknowledgment with no movement → no change
   Map each thread to the right job by matching the role title. If a company has several active roles and it's unclear which one, ask the user instead of guessing.

4. Present a single review table before writing anything:
   `Company — Title | current → proposed | evidence (subject · date)`
   Group by proposed change. List stale ones too: active >5 days with no reply, so the user can follow up.

5. Ask the user to confirm: apply all, pick specific ones, or skip. Wait for their answer.

6. For each confirmed change, call `jobhunt_set_status(job_id, status, notes="from email: <subject> (<date>)")`. Use the real subject and date so the note is auditable.

7. Summarize what changed. For stale no-reply applications, offer `/jobhunt-prep` (if a screen is coming) or remind them `jobhunt_followup(job_id)` drafts a nudge.
