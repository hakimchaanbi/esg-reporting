"""
Turn the downloaded STARS evidence documents into plain text
============================================================

Reads documents/cache/ (populated by fetch_documents.py) and writes one .txt
per document into documents/text/, plus an extraction report appended to the
manifest.

Separate from the download for the usual reason: this can be re-run and
rewritten as often as needed without fetching anything again.

HOW EACH FORMAT IS READ
    .pdf            pdftotext -layout (poppler). Already on the system and
                    already used for the GRI standards.
    .xlsx .xlsm     openpyxl in read-only mode. Cell values joined per row —
                    these are inventories (course lists, diversity worksheets),
                    so the rows ARE the content.
    .docx           stdlib only: a .docx is a zip holding word/document.xml.
                    Five files did not justify another dependency.
    images          skipped. Reading them would need OCR, which is a different
                    project and a different accuracy conversation.

THE THING TO WATCH FOR — SCANNED PDFS
    A PDF can be a picture of a page with no text layer at all. pdftotext
    returns almost nothing and exits successfully, so the failure is silent.
    Anything under MIN_CHARS is reported as `no_text_layer` rather than counted
    as a success, because a 40-page policy that yields 12 characters has not
    been read.

RUN
    python -m scrapers.extract_documents
    python -m scrapers.extract_documents --force    re-extract everything
"""

from __future__ import annotations

import argparse
import re
import subprocess
import zipfile
from xml.etree import ElementTree

import pandas as pd

from .institutions import PROJECT_ROOT

DOC_DIR = PROJECT_ROOT / "documents"
CACHE_DIR = DOC_DIR / "cache"
TEXT_DIR = DOC_DIR / "text"
MANIFEST = DOC_DIR / "manifest.csv"

# Below this, a document has not really been read. Chosen so a one-page memo
# still passes but a scanned report yielding page numbers alone does not.
MIN_CHARS = 200

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def from_pdf(path) -> tuple[str, str]:
    try:
        out = subprocess.run(["pdftotext", "-layout", "-q", str(path), "-"],
                             capture_output=True, timeout=180)
    except FileNotFoundError:
        return "", "pdftotext not installed (apt install poppler-utils)"
    except subprocess.TimeoutExpired:
        return "", "pdftotext timed out"
    return clean(out.stdout.decode("utf-8", errors="replace")), ""


def from_spreadsheet(path) -> tuple[str, str]:
    try:
        import openpyxl
    except ImportError:
        return "", "openpyxl not installed"
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:                                   # noqa: BLE001
        return "", f"openpyxl: {type(exc).__name__}"

    parts = []
    try:
        for sheet in wb.worksheets:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row
                         if c is not None and str(c).strip()]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                parts.append(f"### sheet: {sheet.title}\n" + "\n".join(rows))
    except Exception as exc:                                   # noqa: BLE001
        return clean("\n\n".join(parts)), f"partial: {type(exc).__name__}"
    finally:
        wb.close()

    return clean("\n\n".join(parts)), ""


def from_docx(path) -> tuple[str, str]:
    """A .docx is a zip; the prose lives in <w:t> elements of document.xml."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        return "", f"docx: {type(exc).__name__}"

    root = ElementTree.fromstring(xml)
    lines, current = [], []
    for node in root.iter():
        if node.tag == f"{WORD_NS}t" and node.text:
            current.append(node.text)
        elif node.tag == f"{WORD_NS}p":
            if current:
                lines.append("".join(current))
                current = []
    if current:
        lines.append("".join(current))
    return clean("\n".join(lines)), ""


EXTRACTORS = {
    ".pdf": from_pdf,
    ".xlsx": from_spreadsheet,
    ".xlsm": from_spreadsheet,
    ".xls": from_spreadsheet,
    ".docx": from_docx,
}
SKIP_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".gif", ".webp"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="re-extract even where a .txt already exists")
    args = ap.parse_args()

    if not MANIFEST.exists():
        raise SystemExit(f"[stop] {MANIFEST} not found — run "
                         f"python -m scrapers.fetch_documents first")

    manifest = pd.read_csv(MANIFEST)
    have = manifest[manifest.local_file.notna()
                    & (manifest.local_file.astype(str).str.strip() != "")]
    print(f"[plan] {len(have)} documents on disk")

    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    counts = {"ok": 0, "no_text_layer": 0, "skipped_image": 0,
              "unsupported": 0, "error": 0}
    scans = []

    for i, r in enumerate(have.itertuples(index=False), 1):
        src = CACHE_DIR / str(r.local_file)
        if not src.exists():
            results[r.url] = ("error", 0, "file missing from cache")
            counts["error"] += 1
            continue

        ext = ("." + str(r.original_name).lower().rsplit(".", 1)[-1]
               if "." in str(r.original_name) else src.suffix.lower())

        if ext in SKIP_EXT:
            results[r.url] = ("skipped_image", 0, "image — would need OCR")
            counts["skipped_image"] += 1
            continue

        extractor = EXTRACTORS.get(ext)
        if extractor is None:
            results[r.url] = ("unsupported", 0, f"no extractor for {ext}")
            counts["unsupported"] += 1
            continue

        out_path = TEXT_DIR / (src.stem + ".txt")
        if out_path.exists() and not args.force:
            text = out_path.read_text(encoding="utf-8", errors="replace")
            note = ""
        else:
            text, note = extractor(src)
            if text:
                out_path.write_text(text, encoding="utf-8")

        if note and not text:
            status = "error"
        elif len(text) < MIN_CHARS:
            status = "no_text_layer"
            scans.append((r.original_name, len(text), r.institution))
        else:
            status = "ok"

        counts[status] += 1
        results[r.url] = (status, len(text), note)

        if i % 20 == 0 or i == len(have):
            print(f"  [{i:>3}/{len(have)}] {counts['ok']} ok, "
                  f"{counts['no_text_layer']} no text layer")

    manifest["extract_status"] = manifest.url.map(
        lambda u: results.get(u, ("not_downloaded", 0, ""))[0])
    manifest["text_chars"] = manifest.url.map(
        lambda u: results.get(u, ("", 0, ""))[1])
    manifest.to_csv(MANIFEST, index=False)

    total = sum(v for k, v in
                ((u, results[u][1]) for u in results) if True)
    print(f"\n[done] " + "  ".join(f"{k}={v}" for k, v in counts.items()
                                   if v))
    print(f"       {total:,} characters of text -> {TEXT_DIR}")

    if scans:
        print(f"\n[note] {len(scans)} document(s) yielded almost no text — "
              f"these are scans, not text PDFs. OCR would be needed:")
        for name, n, inst in scans[:10]:
            print(f"   {n:>5} chars  {str(inst)[:22]:24} {str(name)[:44]}")

    ok = manifest[manifest.extract_status == "ok"]
    if len(ok):
        print("\n--- extracted text per institution ---")
        for inst, g in ok.groupby("institution"):
            print(f"  {str(inst)[:34]:36} {len(g):3} docs  "
                  f"{g.text_chars.sum():>10,} chars")


if __name__ == "__main__":
    main()
