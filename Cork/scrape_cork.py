"""
STARS scraper — University College Cork
=============================================

Scrapes one university's STARS 3.0 scorecard into a clean table.

WHAT IT DOES
    1. Fetches the scorecard page (all credits are listed on this one page).
    2. Parses every credit row: code, name, category, status, score, max.
    3. Saves the result as a tidy CSV — one row per credit.

WHY IT'S SHAPED THIS WAY
    - The scorecard page already contains every credit and its score, so we
      don't need to visit ~50 individual credit pages. One request, done.
    - We cache the downloaded HTML to disk. After the first run the parser
      works offline, so you can re-run and tweak parsing without re-hitting
      the site. Polite to AASHE, and much faster to develop against.

RUN
    pip install requests beautifulsoup4 lxml pandas
    python scrape_cork.py

OUTPUT
    cork_stars.csv
"""

import re
import time
import pathlib
import requests
import pandas as pd
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# CONFIG — everything you'd change to point this at another university
# ----------------------------------------------------------------------
INSTITUTION = "University College Cork"
REPORT_URL = "https://reports.aashe.org/institutions/university-college-cork-national-university-of-ireland-cork-co-corcaigh/report/2026-03-05/"
CACHE_FILE = pathlib.Path("cork_scorecard.html")
OUTPUT_CSV = pathlib.Path("cork_stars.csv")

# A real browser User-Agent. Some servers reject the default python one.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

# STARS category codes → human-readable pillar grouping.
# AC/EN feed context; OP is the Environmental pillar; PA holds Social + Governance.
CATEGORY_NAMES = {
    "PRE": "Report Preface",
    "AC": "Academics",
    "EN": "Engagement",
    "OP": "Operations",           # Environmental pillar
    "PA": "Planning & Administration",  # Social + Governance pillars
    "IL": "Innovation & Leadership",
}


# ----------------------------------------------------------------------
# PASS 1 — FETCH  (with on-disk caching)
# ----------------------------------------------------------------------
def fetch_html(url: str, cache: pathlib.Path) -> str:
    """Return the page HTML, downloading only if we haven't already cached it."""
    if cache.exists():
        print(f"[fetch] using cached copy: {cache}")
        return cache.read_text(encoding="utf-8")

    print(f"[fetch] downloading: {url}")
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()          # stop loudly on 403/404/500
    time.sleep(1)                        # be polite — one page, one second
    cache.write_text(response.text, encoding="utf-8")
    print(f"[fetch] saved cache: {cache}  ({len(response.text):,} bytes)")
    return response.text


# ----------------------------------------------------------------------
# PASS 2 — PARSE
# ----------------------------------------------------------------------
def parse_score(cell_text: str):
    """
    Turn a points cell like '10.79 / 16.00' into (10.79, 16.00).
    Returns (None, None) when the cell has no score (e.g. 'Not Applicable').
    """
    match = re.search(r"([\d.]+)\s*/\s*([\d.]+)", cell_text)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None, None


def category_from_url(href: str):
    """
    Pull the category code and credit code out of a credit URL.
    e.g. '.../report/2026-03-05/OP/energy-climate/OP-6/'  ->  ('OP', 'OP-6')
    """
    parts = [p for p in href.split("/") if p]      # drop empty segments
    # the credit code is the last segment; the category code is 3 before it
    credit_code = parts[-1]
    category_code = parts[-3] if len(parts) >= 3 else ""
    return category_code, credit_code


def parse_scorecard(html: str) -> pd.DataFrame:
    """Walk the scorecard tables and build one row per credit."""
    soup = BeautifulSoup(html, "lxml")
    rows = []

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            link = tr.find("a", href=True)
            if not link:
                continue                          # header / spacer row

            href = link["href"]
            if "/report/" not in href:
                continue                          # not a credit link

            # only rows that look like real credits (have a category code)
            category_code, credit_code = category_from_url(href)
            if category_code not in CATEGORY_NAMES:
                continue

            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            # typical credit row: [credit name, status, "X / Y"]
            status = cells[1] if len(cells) > 1 else ""
            points_text = cells[-1] if cells else ""
            score, maximum = parse_score(points_text)

            rows.append({
                "institution": INSTITUTION,
                "category_code": category_code,
                "category": CATEGORY_NAMES[category_code],
                "credit_code": credit_code,
                "credit_name": link.get_text(strip=True),
                "status": status,
                "score": score,
                "max": maximum,
            })

    df = pd.DataFrame(rows).drop_duplicates(subset=["credit_code"])
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------
# PASS 3 — SAVE  (+ a quick sanity report)
# ----------------------------------------------------------------------
def main():
    html = fetch_html(REPORT_URL, CACHE_FILE)
    df = parse_scorecard(html)

    if df.empty:
        print("[warn] no credits parsed — the page layout may have changed.")
        return

    df.to_csv(OUTPUT_CSV, index=False)
    print(f"[save] wrote {len(df)} credits -> {OUTPUT_CSV}\n")

    # --- sanity report: what did we actually get? ---
    scored = df.dropna(subset=["score"])
    print(f"  credits parsed         : {len(df)}")
    print(f"  with a numeric score   : {len(scored)}")
    print(f"  marked 'Not Applicable': {(df['status'] == 'Not Applicable').sum()}")
    print("\n  credits per category:")
    for cat, n in df["category"].value_counts().items():
        print(f"    {cat:<28} {n}")
    print("\n  first few rows:")
    print(df[["credit_code", "credit_name", "status", "score", "max"]].head(6).to_string(index=False))


if __name__ == "__main__":
    main()
