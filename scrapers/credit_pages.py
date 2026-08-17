"""
STARS credit-page downloader — all institutions
===============================================

Replaces the three *_deep.py scrapers. It does ONE job: get the credit-detail
pages onto disk. Parsing lives in parse_credit_pages.py.

That split is deliberate and it is why the §6.5 bug was cheap to fix: parsing
could be rewritten and re-run twenty times against the cache with no auth, no
network and no waiting. The old files mixed the two, so every parser experiment
would have meant 118 more requests to someone else's server.

The old extract_qa() is NOT carried over. It only searched <table> elements,
which on a STARS credit page contain nothing but the header box, so it produced
354 rows of pure boilerplate per institution (CLAUDE.md §6.5). Its outputs
(*_qa.csv) have been deleted; *_credits.txt files remain on disk pending a check
that nothing unique is left in them.

────────────────────────────────────────────────────────────────────────
AUTH — credit detail pages require a (free) AASHE login
────────────────────────────────────────────────────────────────────────
 1. Free account: https://reports.aashe.org/accounts/signup/
 2. Log in, open any credit page, confirm you can see the Q&A.
 3. Copy the `sessionid` cookie value (F12 → Application/Storage → Cookies).
 4. Pass it by ENVIRONMENT VARIABLE — never hard-code it, never commit it:

        export AASHE_SESSIONID="paste_value_here"       # bash
        $env:AASHE_SESSIONID="paste_value_here"         # PowerShell

A preflight tests one page and aborts with instructions if blocked, rather than
wasting 118 requests discovering the same thing 118 times.

RUN
    python -m scrapers.credit_pages              all three
    python -m scrapers.credit_pages cork         just one
    python -m scrapers.credit_pages --recheck    re-test cached pages for
                                                 login-wall poisoning
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import requests
from bs4 import BeautifulSoup

from .institutions import (BASE_URL, CATEGORY_CODES, HEADERS, PAUSE_SECONDS,
                           Institution, resolve)

# Signatures of the "you must log in" page, taken from a real blocked run.
LOGIN_MARKERS = (
    "log in with your aashe account",
    "aashe accounts are free",
    "please log in",
)


def is_login_wall(html: str) -> bool:
    low = html.lower()
    return any(m in low for m in LOGIN_MARKERS)


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    session_id = os.environ.get("AASHE_SESSIONID", "").strip()
    if session_id:
        session.cookies.set("sessionid", session_id, domain="reports.aashe.org")
    return session


def collect_credit_urls(scorecard_html: str, institution: Institution):
    """Every credit URL linked from the (public) scorecard page."""
    soup = BeautifulSoup(scorecard_html, "lxml")
    urls, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if institution.report_tag not in href:
            continue
        parts = [p for p in href.split("/") if p]
        code = parts[-1]
        category = parts[-3] if len(parts) >= 3 else ""
        if category in CATEGORY_CODES and code not in seen:
            seen.add(code)
            urls.append((code, href if href.startswith("http")
                         else BASE_URL + href))
    return urls


def fetch_credit(session, institution: Institution, code: str, url: str):
    """Return (html, from_cache). A login-wall page is never cached."""
    institution.credit_cache_dir.mkdir(parents=True, exist_ok=True)
    cache = institution.credit_cache_dir / f"{code}.html"

    if cache.exists():
        html = cache.read_text(encoding="utf-8", errors="replace")
        if is_login_wall(html):
            cache.unlink()            # poisoned by an earlier blocked run
        else:
            return html, True

    response = session.get(url, timeout=30)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    html = response.text
    time.sleep(PAUSE_SECONDS)

    if not is_login_wall(html):
        cache.write_text(html, encoding="utf-8")
    return html, False


def blocked_message():
    print("=" * 66)
    print("STOPPED — hitting the AASHE login wall.")
    print("=" * 66)
    print("Nothing was saved. Check, in order:")
    print("  1. Is AASHE_SESSIONID set in THIS shell?  echo $AASHE_SESSIONID")
    print("  2. Did you copy the sessionid VALUE (not its name)?")
    print("  3. Sessions expire — log in again and recopy.")
    print("  4. Open a credit page in your browser while logged in. If YOU")
    print("     cannot see the Q&A there, a free account is not enough:")
    print("     request Data Displays access at")
    print("     https://reports.aashe.org/cfm/dd-access/")


def download_one(institution: Institution, recheck: bool = False) -> int:
    if not institution.scorecard_cache.exists():
        print(f"[skip] {institution.key}: no scorecard cache — "
              f"run `python -m scrapers.scorecard {institution.key}` first.")
        return 0

    session = make_session()
    urls = collect_credit_urls(
        institution.scorecard_cache.read_text(encoding="utf-8"), institution)
    print(f"\n[plan] {institution.key}: {len(urls)} credit pages")

    if not os.environ.get("AASHE_SESSIONID", "").strip():
        cached = len(list(institution.credit_cache_dir.glob("*.html"))) \
            if institution.credit_cache_dir.exists() else 0
        if cached < len(urls):
            print("[warn] AASHE_SESSIONID not set — uncached pages will be "
                  "blocked. See the header of this file.")

    # Preflight one page before hammering the server 118 times.
    code, url = urls[0]
    html, _ = fetch_credit(session, institution, code, url)
    if is_login_wall(html):
        blocked_message()
        sys.exit(1)

    downloaded = blocked = 0
    for i, (code, url) in enumerate(urls, 1):
        html, from_cache = fetch_credit(session, institution, code, url)
        if is_login_wall(html):
            blocked += 1
            print(f"  [{i:>3}/{len(urls)}] {code:<8} BLOCKED")
            continue
        if not from_cache:
            downloaded += 1
        if recheck or not from_cache:
            tag = "cached" if from_cache else "downloaded"
            print(f"  [{i:>3}/{len(urls)}] {code:<8} {tag}")

    have = len(list(institution.credit_cache_dir.glob("*.html")))
    print(f"[done] {institution.key}: {have}/{len(urls)} pages on disk "
          f"({downloaded} new this run)")
    if blocked:
        print(f"[warn] {institution.key}: {blocked} pages blocked by login wall.")
    return have


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("institutions", nargs="*",
                    help="berkeley / cork / tudublin (default: all)")
    ap.add_argument("--recheck", action="store_true",
                    help="report on cached pages too, not just new downloads")
    args = ap.parse_args()

    for institution in resolve(args.institutions):
        download_one(institution, recheck=args.recheck)


if __name__ == "__main__":
    main()
