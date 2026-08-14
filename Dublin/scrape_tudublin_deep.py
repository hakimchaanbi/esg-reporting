"""
STARS deep scraper v2 — Technological University Dublin (authenticated)
=====================================

FIXES THE LOGIN-WALL PROBLEM
    STARS credit-detail pages require a (free) AASHE login. The v1 scraper
    didn't detect this, so it wrote 118 sections that all said "Please log in
    with your AASHE Account" instead of real data.

    v2 does two things differently:
      1. Sends your logged-in session cookie with every request.
      2. Detects the login wall and STOPS immediately with a clear message,
         instead of silently saving useless pages.

────────────────────────────────────────────────────────────────────────
SETUP — one time, takes 2 minutes
────────────────────────────────────────────────────────────────────────
 1. Create a free AASHE account:  https://reports.aashe.org/accounts/signup/
    (Free to anyone — you do NOT need to be an AASHE member.)

 2. Log in in your normal browser, then open any credit page, e.g.
    https://reports.aashe.org/institutions/technological-university-dublin-dublin/report/2024-12-02/OP/energy-climate/OP-6/
    Confirm you can see the questions and answers. If you still can't,
    a free account isn't enough — stop here and see NOTE at the bottom.

 3. Copy your session cookie:
      Chrome/Edge : F12 → Application → Storage → Cookies → reports.aashe.org
      Firefox     : F12 → Storage → Cookies → reports.aashe.org
    Find the row named  sessionid  and copy its Value.

 4. Give it to the script WITHOUT putting it in the file:

      Linux/macOS :  export AASHE_SESSIONID="paste_value_here"
      Windows PS  :  $env:AASHE_SESSIONID="paste_value_here"

    (Using an environment variable keeps the secret out of your code and
     out of git. Never paste it directly into this file.)

 5. IMPORTANT — delete the poisoned cache from the failed v1 run:
      rm -rf cache_credits          (Windows:  rmdir /s cache_credits)
    Otherwise the script will happily re-read the saved login pages.

 6. Run:
      python scrape_tudublin_deep_v2.py

────────────────────────────────────────────────────────────────────────
OUTPUT
    tudublin_credits.txt   readable, one section per credit
    tudublin_qa.csv        SUPERSEDED — the extract_qa() below only reads HTML
                           <table> elements, but STARS keeps its real content
                           outside tables, so this file is 3 distinct questions
                           repeated 118 times and zero real figures. Use
                           parse_credits_v3.py (repo root) instead: same cached
                           HTML, 1,029 real fields. The downloading half of
                           this script is still correct.
    cache_credits/         cached HTML (only saved when NOT a login wall)
"""

import os
import re
import sys
import time
import pathlib
import requests
import pandas as pd
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
BASE = "https://reports.aashe.org"
SCORECARD_CACHE = pathlib.Path("tudublin_scorecard.html")
CREDIT_CACHE_DIR = pathlib.Path("cache_credits_tudublin")
OUT_TXT = pathlib.Path("tudublin_credits.txt")
OUT_CSV = pathlib.Path("tudublin_qa.csv")
REPORT_TAG = "/report/2024-12-02/"

PAUSE_SECONDS = 1.5           # be polite — you're a guest on their server
CATEGORY_CODES = ("AC", "EN", "OP", "PA", "IL", "PRE")

# Read the session cookie from the environment (never hard-code it).
SESSION_ID = os.environ.get("AASHE_SESSIONID", "").strip()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Signatures of the "you must log in" page, taken from the real failed run.
LOGIN_MARKERS = [
    "log in with your aashe account",
    "aashe accounts are free",
    "please log in",
]


def is_login_wall(html: str) -> bool:
    low = html.lower()
    return any(m in low for m in LOGIN_MARKERS)


# ----------------------------------------------------------------------
# session
# ----------------------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    if SESSION_ID:
        s.cookies.set("sessionid", SESSION_ID, domain="reports.aashe.org")
    return s


# ----------------------------------------------------------------------
# STEP 1 — credit URLs from the (public) scorecard
# ----------------------------------------------------------------------
def collect_credit_urls(scorecard_html: str):
    soup = BeautifulSoup(scorecard_html, "lxml")
    urls, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if REPORT_TAG not in href:
            continue
        parts = [p for p in href.split("/") if p]
        code, category = parts[-1], (parts[-3] if len(parts) >= 3 else "")
        if category in CATEGORY_CODES and code not in seen:
            seen.add(code)
            urls.append((code, category,
                         href if href.startswith("http") else BASE + href))
    return urls


# ----------------------------------------------------------------------
# STEP 2 — fetch a credit page (cached, login-aware)
# ----------------------------------------------------------------------
def fetch_credit(session, code: str, url: str):
    """Return (html, from_cache). Never caches a login-wall page."""
    CREDIT_CACHE_DIR.mkdir(exist_ok=True)
    cache = CREDIT_CACHE_DIR / f"{code}.html"

    if cache.exists():
        html = cache.read_text(encoding="utf-8")
        if is_login_wall(html):
            cache.unlink()          # poisoned by the old run — drop and refetch
        else:
            return html, True

    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding
    html = resp.text
    time.sleep(PAUSE_SECONDS)

    if not is_login_wall(html):
        cache.write_text(html, encoding="utf-8")
    return html, False


# ----------------------------------------------------------------------
# STEP 3 — extract Q&A (unchanged logic, it was never the problem)
# ----------------------------------------------------------------------
def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_qa(html: str):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    title_el = soup.find(["h1", "h2"])
    title = clean(title_el.get_text()) if title_el else clean(
        soup.title.get_text() if soup.title else "")

    qa_pairs, narrative = [], []
    SKIP_LABELS = {"credit", "status", "points", "rating", "score",
                   "complete", "valid through", "liaison", "submitted"}
    SCORE_RE = re.compile(r"^[\d.]+\s*/\s*[\d.]+$")

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) != 2:
                continue
            q, a = clean(cells[0].get_text()), clean(cells[1].get_text())
            if not (q and a) or len(q) <= 3:
                continue
            if q.lower() in SKIP_LABELS or a.lower() in SKIP_LABELS:
                continue
            if SCORE_RE.match(a):
                continue
            qa_pairs.append((q, a))

    for dl in soup.find_all("dl"):
        for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
            q, a = clean(dt.get_text()), clean(dd.get_text())
            if q and a:
                qa_pairs.append((q, a))

    for p in soup.find_all("p"):
        line = clean(p.get_text())
        if len(line) > 40:
            narrative.append(line)

    seen = set()
    qa_pairs = [(q, a) for q, a in qa_pairs if not (q + a in seen or seen.add(q + a))]
    seen = set()
    narrative = [n for n in narrative if not (n in seen or seen.add(n))]
    return title, qa_pairs, narrative


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def main():
    if not SCORECARD_CACHE.exists():
        print("[error] run scrape_tudublin.py first to create the scorecard cache.")
        return

    if not SESSION_ID:
        print("[warn] AASHE_SESSIONID is not set — you will almost certainly hit")
        print("       the login wall. See SETUP at the top of this file.\n")

    session = make_session()
    urls = collect_credit_urls(SCORECARD_CACHE.read_text(encoding="utf-8"))
    print(f"[plan] {len(urls)} credit pages to visit\n")

    # --- preflight: test ONE page before hammering the server 118 times ---
    code, category, url = urls[0]
    html, _ = fetch_credit(session, code, url)
    if is_login_wall(html):
        print("=" * 66)
        print("STOPPED — still hitting the AASHE login wall.")
        print("=" * 66)
        print("Nothing was saved. Check, in order:")
        print("  1. Is AASHE_SESSIONID set in THIS terminal?  (echo $AASHE_SESSIONID)")
        print("  2. Did you copy the value of 'sessionid' (not its name)?")
        print("  3. Is the session still valid? Log in again and recopy.")
        print("  4. Open a credit page in your browser while logged in —")
        print("     if YOU can't see the Q&A there, a free account isn't")
        print("     enough and scraping won't help. Request Data Displays")
        print("     access instead: https://reports.aashe.org/cfm/dd-access/")
        sys.exit(1)
    print("[auth] preflight OK — real content returned. Continuing.\n")

    csv_rows, blocked = [], 0
    with OUT_TXT.open("w", encoding="utf-8") as f:
        for i, (code, category, url) in enumerate(urls, 1):
            html, cached = fetch_credit(session, code, url)

            if is_login_wall(html):
                blocked += 1
                print(f"  [{i:>3}/{len(urls)}] {code:<8} BLOCKED (login wall)")
                continue

            title, qa, narrative = extract_qa(html)
            f.write("=" * 70 + f"\n{code}  [{category}]  {title}\n{url}\n" + "=" * 70 + "\n")
            for q, a in qa:
                f.write(f"\nQ: {q}\nA: {a}\n")
                csv_rows.append({"credit_code": code, "category": category,
                                 "question": q, "answer": a})
            if narrative:
                f.write("\n--- narrative ---\n" + "\n".join(narrative) + "\n")
            f.write("\n\n")

            tag = " (cached)" if cached else ""
            print(f"  [{i:>3}/{len(urls)}] {code:<8} {len(qa)} Q&A, {len(narrative)} para{tag}")

    pd.DataFrame(csv_rows).to_csv(OUT_CSV, index=False)

    print("\n" + "=" * 66)
    print(f"[done] {len(urls) - blocked}/{len(urls)} credits extracted, "
          f"{len(csv_rows)} Q&A rows -> {OUT_CSV}")
    if blocked:
        print(f"[warn] {blocked} credits were blocked by the login wall.")
    if not csv_rows:
        print("[warn] ZERO Q&A extracted — the pages may use a layout this")
        print("       parser doesn't recognise. Send one file from")
        print("       cache_credits/ for inspection.")


if __name__ == "__main__":
    main()