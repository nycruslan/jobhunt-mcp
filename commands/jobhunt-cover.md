Write a custom cover letter for the job with id: $ARGUMENTS

1. Fetch the JD: call `jobhunt_draft(job_id="$ARGUMENTS")` (idempotent — reuse the existing PDF, just focus on the letter).
2. Using the candidate's background from `resume/profile.yaml` and the JD, write a 1-paragraph cover letter inline.
3. Save it: `jobhunt_save_cover(job_id="$ARGUMENTS", cover_text=...)`.
4. Show the letter in a copy-friendly code block and the apply URL.

Cover voice: open specific to the company, end with a clear ask. Follow the
writing style in CLAUDE.md (no em dashes, no rule-of-three triplets, varied
sentence length, plain verbs, no buzzwords).
