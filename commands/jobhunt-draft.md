Generate a tailored resume PDF and write a custom cover letter for the job with id: $ARGUMENTS

**Workflow:**

1. Call the `jobhunt_draft` MCP tool with `job_id="$ARGUMENTS"`. It generates the resume PDF at `output/resumes/{slug}.pdf` and returns the full JD text plus the apply URL.
2. Read the JD text. Using the candidate's background from `resume/profile.yaml` (and anything already in this conversation), write a custom 1-paragraph cover letter inline.
3. Call `jobhunt_save_cover(job_id="$ARGUMENTS", cover_text=...)` to save it.
4. Show: the resume PDF path (to upload), the cover letter in a copy-friendly code block, the apply URL, and a reminder to run `/jobhunt-applied` after submitting.

**Cover letter rules:**
- 1 paragraph, 4-5 sentences max.
- Open specific to the company or the role. Never "I am writing to express my interest" or "I am excited to apply".
- Reference a concrete overlap between the candidate's background (from profile.yaml) and what the JD asks for.
- Confident and direct. Not sycophantic.
- End with a clear ask for a conversation.

**Make it read like a human wrote it, not AI:**
- No em dashes, en dashes, or double dashes.
- No rule-of-three triplets ("A, B, and C"). Use pairs, quads, or single ideas.
- No flagged verbs: spearheaded, leveraged, architected, engineered, implemented, showcasing, delve.
- No buzzwords: robust, comprehensive, seamless, end-to-end, ensuring, dynamic, results-driven, passionate, proven track record.
- Vary sentence length. Contractions are fine. Plain verbs: built, ran, shipped, wrote, set up, use.
