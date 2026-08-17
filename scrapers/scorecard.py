"""
STARS scorecard scraper — all institutions
==========================================

Replaces scrape_berkeley.py / scrape_cork.py / scrape_tudublin.py, which were
byte-identical apart from four configuration constants (now in
institutions.py).

WHAT IT DOES
    1. Fetches the scorecard page — every credit is listed on this one page,
       so one request per university, not fifty.
    2. Parses each credit row: code, name, category, status, score, max.
    3. Writes one tidy CSV per institution, one row per credit.

The HTML is cached to disk, so after the first run the parser works offline.
That is what makes it safe to iterate on parsing without re-hitting AASHE.

RUN
    python -m scrapers.scorecard              all three
    python -m scrapers.scorecard berkeley     just one
"""

from __future__ import annotations

import argparse
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .institutions import (CATEGORY_NAMES, HEADERS, PAUSE_SECONDS, Institution,
                           resolve)


def fetch_html(url: str, cache) -> str:
    """Return page HTML, downloading only if not already cached."""
    if cache.exists():
        print(f"[fetch] cached: {cache.name}")
        return cache.read_text(encoding="utf-8")

    print(f"[fetch] downloading: {url}")
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    # requests guesses latin-1 for unlabelled pages and mangles UTF-8
    # (CLAUDE.md §6.3).
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    time.sleep(PAUSE_SECONDS)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(response.text, encoding="utf-8")
    print(f"[fetch] cached: {cache.name} ({len(response.text):,} bytes)")
    return response.text


def parse_score(cell_text: str):
    """'10.79 / 16.00' -> (10.79, 16.00). No score -> (None, None)."""
    match = re.search(r"([\d.]+)\s*/\s*([\d.]+)", cell_text)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None, None


def category_from_url(href: str):
    """'.../report/2025-02-19/OP/energy-climate/OP-6/' -> ('OP', 'OP-6')."""
    parts = [p for p in href.split("/") if p]
    credit_code = parts[-1]
    category_code = parts[-3] if len(parts) >= 3 else ""
    return category_code, credit_code


def parse_scorecard(html: str, institution: Institution) -> pd.DataFrame:
    """Walk the scorecard tables and build one row per credit."""
    soup = BeautifulSoup(html, "lxml")
    rows = []

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            link = tr.find("a", href=True)
            if not link:
                continue                       # header / spacer row

            href = link["href"]
            if "/report/" not in href:
                continue                       # not a credit link

            category_code, credit_code = category_from_url(href)
            if category_code not in CATEGORY_NAMES:
                continue

            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            status = cells[1] if len(cells) > 1 else ""
            score, maximum = parse_score(cells[-1] if cells else "")

            rows.append({
                "institution": institution.name,
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


def scrape_one(institution: Institution) -> pd.DataFrame:
    html = fetch_html(institution.report_url, institution.scorecard_cache)
    df = parse_scorecard(html, institution)

    if df.empty:
        print(f"[warn] {institution.key}: no credits parsed — layout may have "
              f"changed.")
        return df

    df.to_csv(institution.stars_csv, index=False)
    scored = df.dropna(subset=["score"])
    na = (df["status"] == "Not Applicable").sum()
    print(f"[save] {institution.key}: {len(df)} credits "
          f"({len(scored)} scored, {na} not applicable) -> "
          f"{institution.stars_csv.name}")
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("institutions", nargs="*",
                    help="berkeley / cork / tudublin (default: all)")
    args = ap.parse_args()

    for institution in resolve(args.institutions):
        scrape_one(institution)


if __name__ == "__main__":
    main()
