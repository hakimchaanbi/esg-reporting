"""
Knowledge-source scraper v2 — ESG reference corpus
==================================================

Collects clean article text from ESG reference sites so the LLM can learn what
ESG is, what the frameworks are, and what a report reads like.

This is Phase 1 (extraction) for the KNOWLEDGE branch — counterpart to the STARS
scrapers, which handle the DATA branch. Output is clean prose, not scores.
Chunking/embedding happens later in the RAG phase, deliberately kept separate so
you can read and verify what was captured.

WHAT'S NEW IN v2
    * Corrected source list — dead/blocked/marketing URLs replaced.
    * Added STARS + GRI + CSRD + SASB sources (the frameworks this project
      actually reads from and writes to — the biggest gap in v1).
    * FRESH_RUN clears old .txt files so stale results can't pile up and get
      embedded twice under two different names.
    * Encoding fix — stops the mojibake ("617,090â") seen in v1.
    * Boilerplate scrub — removes leaked template code ({{...}}).
    * Quality gate — every file is scored and flagged: language, ESG density,
      sales-page patterns, consent walls, template junk. Flags land in the
      summary so problems are visible without reading 20 files by hand.

SETUP
    pip install requests trafilatura
    # optional, only for JavaScript-heavy pages:
    pip install playwright && playwright install chromium

RUN
    python scrape_knowledge_v2.py

OUTPUT
    knowledge_sources/*.txt          one clean text file per source
    knowledge_sources/_summary.csv   words, method, quality flags, status
"""

import csv
import re
import time
import pathlib
import requests
import trafilatura

# ----------------------------------------------------------------------
# SOURCES
#   Grouped by role in the knowledge base. Edit freely — the scraper does
#   not care how many there are.
# ----------------------------------------------------------------------
SOURCES = [
    # ---------- what ESG is ----------
    ("cambridge-esg",          "https://dictionary.cambridge.org/dictionary/english/esg"),
    ("ibm-esg",                "https://www.ibm.com/think/topics/environmental-social-and-governance"),
    ("cfi-esg",                "https://corporatefinanceinstitute.com/resources/esg/esg-environmental-social-governance/"),
    ("robeco-esg-definition",  "https://www.robeco.com/en-us/glossary/sustainable-investing/esg-definition"),
    ("robeco-sustainability",  "https://www.robeco.com/en-us/glossary/sustainable-investing/definitions-of-sustainability"),

    # ---------- history & reporting practice ----------
    ("ibm-esg-history",        "https://www.ibm.com/think/topics/environmental-social-and-governance-history"),
    ("ibm-esg-reporting",      "https://www.ibm.com/think/topics/esg-reporting"),

    # ---------- the frameworks this project must output to ----------
    ("ibm-esg-frameworks",     "https://www.ibm.com/think/topics/esg-frameworks"),
    ("gri-standards",          "https://www.globalreporting.org/standards/"),
    ("ibm-gri",                "https://www.ibm.com/think/topics/global-reporting-initiative"),
    ("ibm-csrd",               "https://www.ibm.com/think/topics/csrd"),
    ("ibm-sasb",               "https://www.ibm.com/think/topics/sasb"),

    # ---------- STARS: the framework our DATA comes from ----------
    ("stars-about",            "https://stars.aashe.org/about-stars/"),
    ("stars-terminology",      "https://stars.aashe.org/participate/basic-terminology/"),
    ("stars-technical-manual", "https://stars.aashe.org/resources-support/technical-manual/"),

    # ---------- how ESG gets rated ----------
    ("msci-esg-ratings",       "https://www.msci.com/data-and-analytics/sustainability-solutions/esg-ratings"),
    # NOTE: Greenscope is a French consultancy comparing rating agencies —
    # good content, but it is NOT S&P. Labelled accurately on purpose.
    ("greenscope-agencies",    "https://www.greenscope.io/esg/agence-notation-esg"),

    # ---------- open ESG data ----------
    ("worldbank-framework",    "https://www.worldbank.org/en/news/feature/2022/12/12/world-bank-relaunches-sovereign-esg-data-portal"),

    # ---------- university examples ----------
    ("toronto-annual-report",  "https://sustainability.utoronto.ca/resources/annual-reports/2024-2025-annual-report/"),
    ("manchester-sustain",     "https://www.manchester.ac.uk/about/social-responsibility/environmental-sustainability/our-sustainability-commitments/sustainability-strategy/"),

    # ---------- REMOVED in v2, and why ----------
    # spglobal-esg-scores / spglobal-csa : returned 0 words — spglobal.com blocks
    #     plain requests. Retry with Playwright if you want S&P's own wording.
    # worldbank-data360   : pure JavaScript app, returns 0 words without a browser.
    # worldbank-about     : served the same JS portal shell as the homepage —
    #     blog posts and a random country snapshot, not the framework.
]

OUT_DIR = pathlib.Path("knowledge_sources")
FRESH_RUN = True          # clear old .txt files first so stale results can't linger
MIN_CHARS = 500           # below this, assume the simple fetch failed → try Playwright
PAUSE_SECONDS = 1.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# ---- quality-gate vocabularies ----
ESG_TERMS = [
    "esg", "environmental", "social", "governance", "sustainab", "emission",
    "carbon", "disclosure", "framework", "reporting", "materiality", "gri",
    "tcfd", "csrd", "esrs", "sasb", "stars", "credit", "indicator",
]
SALES_TERMS = [
    "enroll", "certificate", "instructor", "testimonial", "premium template",
    "upgrading to a paid", "start free", "book a demo", "request a quote",
    "sign up today", "our clients", "pricing",
]
CONSENT_MARKERS = [
    "accept the disclaimer", "clauses de non-responsabilité", "cookie consent",
    "no authorization", "aucune autorisation", "please enable javascript",
    "access denied", "are you a robot",
]
FRENCH_MARKERS = [" les ", " des ", " une ", " est ", " qui ", " pour ", " dans "]


# ----------------------------------------------------------------------
# cleanup helpers
# ----------------------------------------------------------------------
def scrub(text: str) -> str:
    """Remove leaked template code and tidy whitespace."""
    if not text:
        return ""
    # mustache/handlebars templates that leak from some CMS pages
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    # collapse runs of blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # drop lines that are now empty or whitespace-only
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    return "\n".join(lines).strip()


def quality_flags(text: str) -> list:
    """Return a list of short warnings about this text. Empty list = clean."""
    flags = []
    low = text.lower()
    words = max(len(text.split()), 1)

    if any(m in low for m in CONSENT_MARKERS):
        flags.append("CONSENT-WALL")
    if sum(low.count(m) for m in FRENCH_MARKERS) > 25:
        flags.append("FRENCH")
    esg_per_1k = sum(low.count(t) for t in ESG_TERMS) / words * 1000
    if esg_per_1k < 25:
        flags.append(f"LOW-ESG({esg_per_1k:.0f}/1k)")
    if sum(low.count(t) for t in SALES_TERMS) >= 5:
        flags.append("SALES-PAGE")
    if "{{" in text:
        flags.append("TEMPLATE-JUNK")
    if words < 200:
        flags.append("THIN")
    return flags


# ----------------------------------------------------------------------
# fetching — tier 1 (simple) then tier 2 (rendered), only if needed
# ----------------------------------------------------------------------
def fetch_simple(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        # FIX for v1 mojibake: let requests sniff the real encoding instead of
        # falling back to latin-1, which turned UTF-8 symbols into "â".
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
    except Exception as e:
        print(f"      simple fetch error: {e}")
        return ""
    return trafilatura.extract(
        resp.text, include_comments=False, include_tables=True, favor_precision=True
    ) or ""


def fetch_rendered(url: str) -> str:
    """Headless-browser fallback. Degrades gracefully if Playwright is absent."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("      Playwright not installed — skipping render fallback.")
        return ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(url, wait_until="networkidle", timeout=45000)
            html = page.content()
            browser.close()
        return trafilatura.extract(
            html, include_comments=False, include_tables=True, favor_precision=True
        ) or ""
    except Exception as e:
        print(f"      render error: {e}")
        return ""


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def main():
    OUT_DIR.mkdir(exist_ok=True)

    if FRESH_RUN:
        removed = 0
        for old in list(OUT_DIR.glob("*.txt")) + list(OUT_DIR.glob("_summary.csv")):
            old.unlink()
            removed += 1
        if removed:
            print(f"[clean] removed {removed} file(s) from a previous run\n")

    filled = [(n, u) for n, u in SOURCES if u.strip()]
    missing = [n for n, u in SOURCES if not u.strip()]
    if missing:
        print(f"[note] no URL yet for: {', '.join(missing)}")
    if not filled:
        print("[stop] No URLs filled in.")
        return

    summary = []
    for name, url in filled:
        print(f"[get] {name}\n      {url}")

        method = "simple"
        text = scrub(fetch_simple(url))
        time.sleep(PAUSE_SECONDS)

        if len(text) < MIN_CHARS:
            print(f"      only {len(text)} chars — trying rendered fallback…")
            rendered = scrub(fetch_rendered(url))
            if len(rendered) > len(text):
                text, method = rendered, "playwright"

        words = len(text.split())
        flags = quality_flags(text) if text else ["EMPTY"]
        status = "ok" if (len(text) >= MIN_CHARS and not
                          {"CONSENT-WALL", "EMPTY"} & set(flags)) else "CHECK"

        if text:
            (OUT_DIR / f"{name}.txt").write_text(
                f"SOURCE: {name}\nURL: {url}\nWORDS: {words}\n"
                f"{'=' * 60}\n\n{text}\n",
                encoding="utf-8",
            )
            note = f"  [{' '.join(flags)}]" if flags else ""
            print(f"      {status}  ({words} words, {method}){note}\n")
        else:
            print("      FAILED — nothing extracted\n")

        summary.append({
            "source": name, "url": url, "method": method,
            "words": words, "status": status, "flags": " ".join(flags),
        })

    with (OUT_DIR / "_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source", "url", "method", "words", "status", "flags"])
        w.writeheader()
        w.writerows(summary)

    # ---- final report ----
    ok = [s for s in summary if s["status"] == "ok"]
    total = sum(s["words"] for s in ok)
    print("=" * 60)
    print(f"[done] {len(ok)}/{len(summary)} sources captured cleanly — {total:,} words")
    print(f"       files in {OUT_DIR}/   summary in {OUT_DIR}/_summary.csv")
    flagged = [s for s in summary if s["flags"]]
    if flagged:
        print("\n[review] flagged sources:")
        for s in flagged:
            print(f"    {s['source']:<24} {s['flags']}")


if __name__ == "__main__":
    main()
