# Job Search Monitor

Scrapes [FINN.no](https://www.finn.no) and [arbeidsplassen.nav.no](https://arbeidsplassen.nav.no)
daily for full-time job postings matching a defined profile (AI / Cloud / DevOps / Platform /
Cybersecurity Engineer), filters to English-friendly roles, and publishes a deadline-sorted report
as a static page via GitHub Pages.

## How it works

- `job_monitor.py` searches both sites for each keyword in `KEYWORDS`, keeps only postings whose
  title matches a core set of relevant terms (filters out hardware/mechanical/sales roles that
  only matched on body text), fetches each candidate's deadline and employment type, and checks
  NAV postings for an English working-language requirement (FINN is filtered at search time via
  `working_language=2`). Employment type is shown as-is (Full-time / Part-time / Temporary), except
  a title containing "intern"/"summer student"/"trainee" is labelled Internship, and "graduate" is
  labelled Graduate Program, regardless of the site's own employment-type field. Nothing is
  excluded by employment type — internships and graduate programs are kept, not just full-time.
- Results are merged into `data/postings.json`, which persists across runs: already-seen postings
  are kept and updated (not duplicated), expired ones (deadline passed more than 3 days ago) are
  dropped — a brief grace period, since "Applied" status lives only in the browser (see below) and
  this script has no way to know not to drop something you've marked as applied. Kept short on
  purpose so the list stays mostly current rather than accumulating closed postings.
- `docs/index.html` is regenerated from that data on every run — one list sorted by deadline
  ascending, colour-coded by urgency (red: ≤3 days, amber: ≤7 days, grey: rolling/no deadline).
  Each row shows its Type (Full-time/Internship/Graduate Program/etc.) as plain text, so browser
  Ctrl+F reliably finds it. A dropdown lets you mark a posting "Applied" — it turns the row green
  with a checkmark and persists via the browser's localStorage (per-device, not synced).
- `.github/workflows/daily-job-search.yml` runs this once a day (07:00 UTC) and commits the
  updated `data/` and `docs/` back to the repo. GitHub Pages serves `docs/` automatically.

## Running locally

```bash
pip install -r requirements.txt
python job_monitor.py
```

Open `docs/index.html` in a browser, or serve it (`python -m http.server` from `docs/`) to view it
the way GitHub Pages would.

## Adjusting the search

Edit `KEYWORDS` and `POSITIVE_TITLE_TERMS` in `job_monitor.py` to change what counts as relevant.

