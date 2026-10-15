# Job Search Monitor

Scrapes [FINN.no](https://www.finn.no) and [arbeidsplassen.nav.no](https://arbeidsplassen.nav.no)
daily for full-time job postings matching a defined profile (AI / Cloud / DevOps / Platform /
Cybersecurity Engineer), filters to English-friendly roles, and publishes a deadline-sorted report
as a static page via GitHub Pages.

## How it works

- `job_monitor.py` searches both sites for each keyword in `KEYWORDS`, keeps only postings whose
  title matches a core set of relevant terms (filters out hardware/mechanical/sales roles that
  only matched on body text), fetches each candidate's deadline, and checks NAV postings for an
  English working-language requirement (FINN is filtered at search time via `working_language=2`).
- Results are merged into `data/postings.json`, which persists across runs: already-seen postings
  are kept and updated (not duplicated), expired ones (deadline passed) are dropped.
- `docs/index.html` is regenerated from that data on every run — sorted by deadline ascending,
  colour-coded by urgency (red: ≤3 days, amber: ≤7 days, grey: rolling/no deadline).
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

