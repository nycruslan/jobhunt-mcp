<!-- Shared classification/policy prompt for the unattended JobHunt autosync.
     Both autosync.sh (Gmail connector) and autosync.vps.sh (IMAP text) cat this
     file after a short source-specific preamble. Edit it once, here. -->
Work only through the allowed tools.

1. Call jobhunt_active_applications and jobhunt_status to see in-flight and drafted roles.
2. Match the emails to those companies. Before recording anything, verify the sender
   domain plausibly matches the company: the company's own domain, or a known ATS
   sending on its behalf (greenhouse.io, lever.co, ashbyhq.com, myworkday.com, and
   the like) with the company named in the message. If the sender domain doesn't
   plausibly fit the company, skip the message.
3. Classify each relevant message as ONE signal: application_received, rejected,
   interview, onsite, or offer. Skip anything ambiguous or unrelated.
4. For each, call jobhunt_record_update(company, signal, evidence="<subject or short quote>").
   Use no other write tool; the tool decides auto-apply vs confirm. Rejections are
   surfaced for confirmation, never auto-applied. If several applications match the
   same company, never guess which one — report it as needing confirmation instead.
5. Print a short summary: what was auto-applied and what needs confirmation.
Never send any email or message. Read-only on email.
