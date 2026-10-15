"""
Job search monitor: scrapes FINN.no and arbeidsplassen.nav.no for postings
matching Nafiul's profile, filters to relevant/English-friendly/full-time
roles, merges with previously-seen postings (data/postings.json), drops
expired ones, and renders docs/index.html for GitHub Pages.

Run daily via .github/workflows/daily-job-search.yml.
"""
import re
import time
import json
import datetime as dt
from pathlib import Path
from dataclasses import dataclass, field, asdict

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

KEYWORDS = [
    "AI Engineer",
    "Cloud Engineer",
    "DevOps Engineer",
    "Platform Engineer",
    "Cybersecurity Engineer",
    "Kubernetes",
    "Terraform",
]

POSITIVE_TITLE_TERMS = [
    "ai", "ml", "machine learning", "data engineer", "data scientist",
    "cloud", "devops", "dev ops", "platform", "kubernetes", "terraform",
    "docker", "azure", "aws", "cyber", "security", "site reliability",
    "sre", "infrastructure",
]

NORWEGIAN_MONTHS = {
    "januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
}

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "postings.json"
HTML_FILE = ROOT / "docs" / "index.html"


@dataclass
class Posting:
    source: str
    title: str
    company: str
    location: str
    url: str
    deadline: "dt.date | None" = None
    full_time: bool = True
    english_ok: bool = True
    matched_keywords: set = field(default_factory=set)
    first_seen: "dt.date | None" = None


def title_is_relevant(title: str) -> bool:
    t = title.lower()
    return any(term in t for term in POSITIVE_TITLE_TERMS)


def parse_nav_deadline(text: str, today: dt.date) -> "dt.date | None":
    low = text.lower()
    if re.search(r"senest\s+i\s+dag", low):
        return today
    if re.search(r"senest\s+i\s+morgen", low):
        return today + dt.timedelta(days=1)
    m = re.search(r"senest\s+(?:\w+\s+)?(\d{1,2})\.\s+(\w+)", text, re.IGNORECASE)
    if not m:
        return None
    day = int(m.group(1))
    month = NORWEGIAN_MONTHS.get(m.group(2).lower())
    if not month:
        return None
    year = today.year
    try:
        d = dt.date(year, month, day)
    except ValueError:
        return None
    if d < today - dt.timedelta(days=30):
        d = dt.date(year + 1, month, day)
    return d


def search_finn(keyword: str) -> list[Posting]:
    url = "https://www.finn.no/job/fulltime/search.html"
    params = {"q": keyword, "working_language": 2}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    results, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/job/ad/" not in href:
            continue
        job_url = href if href.startswith("http") else f"https://www.finn.no{href}"
        if job_url in seen:
            continue
        seen.add(job_url)
        title = a.get_text(strip=True)
        if not title_is_relevant(title):
            continue
        node = a
        for _ in range(4):
            node = node.parent
            if node is None:
                break
        card_text = node.get_text(" | ", strip=True) if node is not None else ""
        parts = card_text.split(" | ")
        company = parts[1] if len(parts) > 1 else ""
        location = parts[2] if len(parts) > 2 else ""
        results.append(Posting(source="FINN", title=title, company=company,
                                location=location, url=job_url))
    return results


def enrich_finn(posting: Posting) -> None:
    try:
        r = requests.get(posting.url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException:
        return
    soup = BeautifulSoup(r.text, "html.parser")
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string)
        except (TypeError, ValueError):
            continue
        payload = data.get("script:ld+json", data)
        if payload.get("@type") != "JobPosting":
            continue
        vt = payload.get("validThrough")
        if vt:
            try:
                posting.deadline = dt.date.fromisoformat(vt[:10])
            except ValueError:
                pass
        emp = payload.get("employmentType") or []
        if isinstance(emp, str):
            emp = [emp]
        posting.full_time = any("FULL" in e.upper() for e in emp) if emp else True
        org = payload.get("hiringOrganization") or {}
        if org.get("name"):
            posting.company = org["name"]
        loc = payload.get("jobLocation", {}).get("address", {})
        if loc.get("addressLocality"):
            posting.location = loc["addressLocality"]
        return


def search_nav(keyword: str, today: dt.date) -> list[Posting]:
    url = "https://arbeidsplassen.nav.no/stillinger"
    params = {"q": keyword}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    results, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/stilling/" not in href:
            continue
        job_url = href if href.startswith("http") else f"https://arbeidsplassen.nav.no{href}"
        if job_url in seen:
            continue
        seen.add(job_url)

        article = a.find_parent("article")
        label = (article.get("aria-label") if article else "") or ""
        parts = [p.strip() for p in label.split(",") if p.strip()]
        if len(parts) >= 3:
            title, company, location = ", ".join(parts[:-2]), parts[-2], parts[-1]
        elif len(parts) == 2:
            title, location, company = parts[0], parts[1], ""
        elif len(parts) == 1:
            title, company, location = parts[0], "", ""
        else:
            title, company, location = a.get_text(strip=True), "", ""

        if not title_is_relevant(title):
            continue

        card_text = article.get_text(" | ", strip=True) if article else ""
        deadline = parse_nav_deadline(card_text, today)
        results.append(Posting(source="NAV", title=title, company=company,
                                location=location, url=job_url, deadline=deadline))
    return results


def enrich_nav_language(posting: Posting) -> None:
    try:
        r = requests.get(posting.url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException:
        return
    soup = BeautifulSoup(r.text, "html.parser")
    dt_tag = soup.find("dt", string=lambda s: s and "Arbeidsspr" in s)
    if dt_tag:
        dd = dt_tag.find_next_sibling("dd")
        if dd:
            posting.english_ok = "engelsk" in dd.get_text(strip=True).lower()


def load_existing() -> dict[str, dict]:
    if not DATA_FILE.exists():
        return {}
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {p["url"]: p for p in data.get("postings", [])}


def posting_to_dict(p: Posting) -> dict:
    d = asdict(p)
    d["deadline"] = p.deadline.isoformat() if p.deadline else None
    d["first_seen"] = p.first_seen.isoformat() if p.first_seen else None
    d["matched_keywords"] = sorted(p.matched_keywords)
    return d


def render_html(postings: list[dict], today: dt.date) -> str:
    # Precompute display fields server-side; the client just partitions by
    # applied/not-applied (read from localStorage) and renders.
    enriched = []
    for p in postings:
        if p["deadline"]:
            dl_date = dt.date.fromisoformat(p["deadline"])
            days_left = (dl_date - today).days
            if days_left < 0:
                urgency, dl_text = "rolling", p["deadline"] + " (closed)"
            elif days_left <= 3:
                urgency, dl_text = "urgent", p["deadline"] + f" ({days_left}d)"
            elif days_left <= 7:
                urgency, dl_text = "soon", p["deadline"] + f" ({days_left}d)"
            else:
                urgency, dl_text = "normal", p["deadline"] + f" ({days_left}d)"
            sort_key = dl_date.toordinal()
        else:
            urgency, dl_text, sort_key = "rolling", "Rolling / unknown", 99999999
        enriched.append({**p, "urgency": urgency, "dl_text": dl_text, "sort_key": sort_key,
                          "matched": ", ".join(p["matched_keywords"])})

    postings_json = json.dumps(enriched, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Job Search Monitor</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0; padding: 16px;
          background: #0d1117; color: #e6edf3; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
  .meta {{ color: #8b949e; font-size: 0.85rem; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #30363d; vertical-align: top; }}
  th {{ position: sticky; top: 0; background: #161b22; font-size: 0.8rem; }}
  tr.urgent td:first-child {{ color: #ff7b72; font-weight: 600; }}
  tr.soon td:first-child {{ color: #e3b341; font-weight: 600; }}
  tr.rolling td:first-child {{ color: #8b949e; }}
  tr.normal td:first-child {{ color: #e6edf3; }}
  tr.is-applied {{ background: rgba(63, 185, 80, 0.12); }}
  tr.is-applied td:first-child {{ color: #3fb950 !important; }}
  .check {{ color: #3fb950; margin-right: 4px; }}
  a {{ color: #58a6ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .kw {{ color: #8b949e; font-size: 0.75rem; }}
  select.applied-toggle {{
    background: #21262d; color: #e6edf3; border: 1px solid #30363d; border-radius: 6px;
    padding: 3px 6px; font-size: 0.8rem;
  }}
  tr.is-applied select.applied-toggle {{ border-color: #3fb950; }}
  @media (max-width: 700px) {{
    table, thead, tbody, th, td, tr {{ display: block; }}
    thead {{ display: none; }}
    tr {{ margin-bottom: 12px; border-bottom: 2px solid #30363d; padding-bottom: 8px; }}
    td {{ border: none; padding: 3px 0; }}
    td:first-child {{ font-weight: 700; }}
  }}
</style>
</head>
<body>
  <h1>Job Search Monitor</h1>
  <p class="meta">Updated {today.isoformat()} &middot; {len(postings)} tracked postings &middot;
     AI / Cloud / DevOps / Platform / Cybersecurity, English-friendly, full-time, Norway</p>

  <table>
    <thead><tr><th>Deadline</th><th>Title</th><th>Company</th><th>Status</th></tr></thead>
    <tbody id="postings-body"></tbody>
  </table>

<script>
const POSTINGS = {postings_json};
const STORAGE_KEY = "jobMonitorApplied";

function loadApplied() {{
  try {{
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}");
  }} catch (e) {{ return {{}}; }}
}}
function saveApplied(state) {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }} catch (e) {{}}
}}

function rowHtml(p, isApplied) {{
  const kwLine = p.matched ? `<div class="kw">${{p.matched}}</div>` : "";
  const check = isApplied ? `<span class="check">&#10003;</span>` : "";
  return `
    <tr class="${{p.urgency}}${{isApplied ? " is-applied" : ""}}" data-url="${{p.url}}">
      <td>${{p.dl_text}}</td>
      <td>${{check}}<a href="${{p.url}}" target="_blank" rel="noopener">${{p.title}}</a>${{kwLine}}</td>
      <td>${{p.company}}<br>${{p.location}}</td>
      <td>
        <select class="applied-toggle" data-url="${{p.url}}">
          <option value="no" ${{isApplied ? "" : "selected"}}>Not applied</option>
          <option value="yes" ${{isApplied ? "selected" : ""}}>Applied</option>
        </select>
      </td>
    </tr>`;
}}

function render() {{
  const applied = loadApplied();
  const sorted = [...POSTINGS].sort((a, b) => a.sort_key - b.sort_key);

  document.getElementById("postings-body").innerHTML =
    sorted.map(p => rowHtml(p, !!applied[p.url])).join("");

  document.querySelectorAll("select.applied-toggle").forEach(sel => {{
    sel.addEventListener("change", () => {{
      const state = loadApplied();
      if (sel.value === "yes") {{ state[sel.dataset.url] = true; }}
      else {{ delete state[sel.dataset.url]; }}
      saveApplied(state);
      render();
    }});
  }});
}}

render();
</script>
</body>
</html>"""


def main():
    today = dt.date.today()
    scraped: dict[str, Posting] = {}

    print(f"=== Searching FINN ({len(KEYWORDS)} keywords) ===")
    for kw in KEYWORDS:
        try:
            found = search_finn(kw)
        except requests.RequestException as e:
            print(f"  FINN search failed for '{kw}': {e}")
            continue
        for p in found:
            if p.url in scraped:
                scraped[p.url].matched_keywords.add(kw)
            else:
                p.matched_keywords.add(kw)
                scraped[p.url] = p
        time.sleep(1)

    print(f"=== Searching NAV ({len(KEYWORDS)} keywords) ===")
    for kw in KEYWORDS:
        try:
            found = search_nav(kw, today)
        except requests.RequestException as e:
            print(f"  NAV search failed for '{kw}': {e}")
            continue
        for p in found:
            if p.url in scraped:
                scraped[p.url].matched_keywords.add(kw)
            else:
                p.matched_keywords.add(kw)
                scraped[p.url] = p
        time.sleep(1)

    print(f"Total unique candidates: {len(scraped)}")
    print("Enriching FINN (deadline + full-time)...")
    for p in scraped.values():
        if p.source == "FINN":
            enrich_finn(p)
            time.sleep(0.5)

    print("Checking NAV language...")
    for p in scraped.values():
        if p.source == "NAV":
            enrich_nav_language(p)
            time.sleep(0.5)

    scraped = {u: p for u, p in scraped.items() if p.full_time and p.english_ok}
    print(f"After full-time + English filter: {len(scraped)}")

    # --- merge with existing persisted state ---
    existing = load_existing()
    merged: dict[str, Posting] = {}

    EXPIRY_GRACE_DAYS = 30  # keep closed postings around a while - you may have
                             # marked one "Applied" in the browser (localStorage),
                             # which this script has no way to see, so don't drop
                             # it the instant its deadline passes.
    for url, old in existing.items():
        old_deadline = dt.date.fromisoformat(old["deadline"]) if old["deadline"] else None
        if old_deadline and old_deadline < today - dt.timedelta(days=EXPIRY_GRACE_DAYS):
            continue  # expired well past the grace window, drop
        merged[url] = Posting(
            source=old["source"], title=old["title"], company=old["company"],
            location=old["location"], url=url, deadline=old_deadline,
            matched_keywords=set(old["matched_keywords"]),
            first_seen=dt.date.fromisoformat(old["first_seen"]) if old["first_seen"] else today,
        )

    new_count = 0
    for url, p in scraped.items():
        if url in merged:
            merged[url].deadline = p.deadline
            merged[url].company = p.company or merged[url].company
            merged[url].location = p.location or merged[url].location
            merged[url].matched_keywords |= p.matched_keywords
        else:
            p.first_seen = today
            merged[url] = p
            new_count += 1

    print(f"New postings today: {new_count}")
    print(f"Total open postings after merge: {len(merged)}")

    final = sorted(merged.values(), key=lambda p: (p.deadline is None, p.deadline or dt.date.max))
    final_dicts = [posting_to_dict(p) for p in final]

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "postings": final_dicts},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    HTML_FILE.parent.mkdir(parents=True, exist_ok=True)
    HTML_FILE.write_text(render_html(final_dicts, today), encoding="utf-8")
    print(f"Wrote {DATA_FILE} and {HTML_FILE}")


if __name__ == "__main__":
    main()
