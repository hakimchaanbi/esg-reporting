"""
Download the documents linked from STARS answers
================================================

STARS answers do not only contain numbers and prose — they link out to the
evidence: emissions inventories, sustainability strategies, policy PDFs, course
spreadsheets. 140 unique documents across the three universities.

    86  hosted on the universities' own sites — public, no login
    54  uploaded to AASHE (/media/...) — need AASHE_SESSIONID

This DOWNLOADS ONLY. Text extraction is extract_documents.py, for the same
reason download and parse are separate everywhere else in this project: the
extractor can then be rewritten and re-run against the cache without touching
anyone's server again.

WHERE THE URLS COME FROM
    The `links` column of combined_credit_fields.csv, added to the parser for
    this purpose. Before that the hrefs were discarded — 421 links kept only
    their label ("Pre-assessment", a truncated filename) and lost the
    destination entirely.

POLITENESS
    1.5s between requests to the same host, a real User-Agent, and everything
    cached so a re-run downloads nothing. AASHE data is publicly accessible and
    usable in research with attribution (CLAUDE.md §6.7); these documents belong
    to the universities and are treated the same way.

RUN
    python -m scrapers.fetch_documents                 public documents only
    python -m scrapers.fetch_documents --with-aashe    also the 54 uploads
                                                       (needs AASHE_SESSIONID)
    python -m scrapers.fetch_documents --dry-run       list what would be fetched
"""

from __future__ import annotations

import argparse
import hashlib
import os
import time
from collections import defaultdict
from urllib.parse import unquote, urlparse

import pandas as pd
import requests

from .institutions import HEADERS, PROJECT_ROOT

FIELDS_CSV = PROJECT_ROOT / "Combined_universities_data" / "combined_credit_fields.csv"
DOC_DIR = PROJECT_ROOT / "documents"
CACHE_DIR = DOC_DIR / "cache"
MANIFEST = DOC_DIR / "manifest.csv"

DOC_EXT = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".csv",
           ".txt", ".rtf")

PAUSE_PER_HOST = 1.5
TIMEOUT = 60
MAX_BYTES = 80 * 1024 * 1024      # a STARS attachment should never exceed this

# A downloaded login page or 404 page is worse than nothing: it looks like a
# successful fetch and quietly becomes "evidence".
LOGIN_MARKERS = (b"log in with your aashe account", b"aashe accounts are free",
                 b"please log in", b"<title>sign in")


def is_document(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(DOC_EXT)


def is_aashe_upload(url: str) -> bool:
    return urlparse(url).netloc.endswith("aashe.org") and "/media/" in url


def target_urls() -> pd.DataFrame:
    """Every document URL, with the credit and field it was cited from."""
    if not FIELDS_CSV.exists():
        raise SystemExit(f"[stop] {FIELDS_CSV} not found — run "
                         f"python -m scrapers.parse_credit_pages")

    df = pd.read_csv(FIELDS_CSV)
    if "links" not in df.columns:
        raise SystemExit("[stop] no `links` column — re-run the parser.")

    rows = []
    for r in df[df.links.notna()].itertuples(index=False):
        for url in str(r.links).split():
            if is_document(url) or is_aashe_upload(url):
                rows.append({"url": url,
                             "institution": r.institution,
                             "credit_code": r.credit_code,
                             "field": r.field,
                             "needs_auth": is_aashe_upload(url)})

    out = pd.DataFrame(rows)
    # One document can be cited from several credits. Keep the first citation
    # for provenance; download once.
    return out.drop_duplicates(subset="url").reset_index(drop=True)


def local_name(url: str) -> str:
    """Stable filename: hash for uniqueness, real extension for readability."""
    digest = hashlib.sha1(url.encode()).hexdigest()[:16]
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext not in DOC_EXT:
        ext = ""
    return f"{digest}{ext}"


def original_name(url: str) -> str:
    return unquote(os.path.basename(urlparse(url).path)) or "(no filename)"


def fetch(session: requests.Session, url: str, dest) -> tuple[str, int, str]:
    """Return (status, bytes, note). Never writes a login page or an error page."""
    if dest.exists() and dest.stat().st_size > 0:
        return "cached", dest.stat().st_size, ""

    try:
        resp = session.get(url, timeout=TIMEOUT, stream=True,
                           allow_redirects=True)
    except requests.RequestException as exc:
        return "error", 0, type(exc).__name__

    if resp.status_code != 200:
        resp.close()
        return "error", 0, f"HTTP {resp.status_code}"

    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
    body = bytearray()
    for chunk in resp.iter_content(1 << 16):
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            resp.close()
            return "error", len(body), "exceeds size limit"
    resp.close()

    if not body:
        return "error", 0, "empty response"

    head = bytes(body[:2000]).lower()
    if any(m in head for m in LOGIN_MARKERS):
        return "blocked", len(body), "login wall"

    # A PDF link that returns HTML is a redirect to an error or consent page.
    if is_document(url) and ctype.startswith("text/html"):
        return "error", len(body), f"got HTML, expected a document"

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(body))
    return "downloaded", len(body), ctype


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with-aashe", action="store_true",
                    help="also fetch the 54 AASHE uploads (needs AASHE_SESSIONID)")
    ap.add_argument("--only-aashe", action="store_true",
                    help="fetch ONLY the AASHE uploads")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N downloads (for a quick trial)")
    args = ap.parse_args()

    targets = target_urls()
    public = targets[~targets.needs_auth]
    gated = targets[targets.needs_auth]

    print(f"[plan] {len(targets)} unique documents cited by STARS answers")
    print(f"       {len(public)} public, {len(gated)} behind the AASHE login")

    if args.only_aashe:
        todo = gated
    elif args.with_aashe:
        todo = targets
    else:
        todo = public

    session_id = os.environ.get("AASHE_SESSIONID", "").strip()
    if len(todo[todo.needs_auth]) and not session_id:
        print("[warn] AASHE_SESSIONID is not set — the gated documents will be "
              "skipped. export it first, or drop --with-aashe.")
        todo = todo[~todo.needs_auth]

    print(f"[plan] fetching {len(todo)}\n")

    if args.dry_run:
        for r in todo.itertuples(index=False):
            tag = "AASHE" if r.needs_auth else "     "
            print(f"  [{tag}] {r.credit_code:7} {original_name(r.url)[:56]}")
        return

    session = requests.Session()
    session.headers.update(HEADERS)
    if session_id:
        session.cookies.set("sessionid", session_id, domain="reports.aashe.org")

    last_hit: dict[str, float] = defaultdict(float)
    records, counts = [], defaultdict(int)

    for i, r in enumerate(todo.itertuples(index=False), 1):
        host = urlparse(r.url).netloc
        wait = PAUSE_PER_HOST - (time.monotonic() - last_hit[host])
        if wait > 0:
            time.sleep(wait)

        dest = CACHE_DIR / local_name(r.url)
        status, size, note = fetch(session, r.url, dest)
        last_hit[host] = time.monotonic()
        counts[status] += 1

        records.append({"url": r.url, "institution": r.institution,
                        "credit_code": r.credit_code, "field": r.field,
                        "original_name": original_name(r.url),
                        "local_file": dest.name if status in ("downloaded", "cached") else "",
                        "bytes": size, "status": status, "note": note})

        mark = {"downloaded": "ok", "cached": "--", "blocked": "AUTH",
                "error": "FAIL"}[status]
        print(f"  [{i:>3}/{len(todo)}] {mark:4} {original_name(r.url)[:52]:54}"
              f" {size / 1000:>7.0f} kB {note}")

        if args.limit and counts["downloaded"] >= args.limit:
            print(f"\n[stop] --limit {args.limit} reached")
            break

    DOC_DIR.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(records)
    if MANIFEST.exists():
        old = pd.read_csv(MANIFEST)
        new = (pd.concat([old, new], ignore_index=True)
                 .drop_duplicates(subset="url", keep="last"))
    new.to_csv(MANIFEST, index=False)

    print(f"\n[done] " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    ok = new[new.status.isin(["downloaded", "cached"])]
    print(f"       {len(ok)} documents on disk, "
          f"{ok.bytes.sum() / 1e6:.1f} MB -> {CACHE_DIR}")
    print(f"       manifest -> {MANIFEST}")

    failed = new[new.status == "error"]
    if len(failed):
        print(f"\n[note] {len(failed)} could not be fetched "
              f"(dead links are normal in a 2024-2026 report set):")
        for r in failed.head(8).itertuples(index=False):
            print(f"   {r.note:22} {r.original_name[:50]}")


if __name__ == "__main__":
    main()
