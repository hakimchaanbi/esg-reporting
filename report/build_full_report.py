"""
Phase 6c — assemble the finished report
=======================================

A GRI report is two things: the narrative and the content index. Until now this
project produced them as two separate files, which meant handing a supervisor
`<key>_gri_report.md` and `<key>_gri_index.md` and explaining how they relate.
This joins them, adds the front matter a report needs, and exports HTML and PDF.

    python -m report.build_full_report
    python -m report.build_full_report cork

⚠️ THIS WRITES A NEW FILE AND NEVER TOUCHES ITS INPUTS.

    <key>_gri_report.md   narrative      — written by build_narrative.py
    <key>_gri_index.md    content index  — written by build_content_index.py
    <key>_gri_full.md     both, assembled — written HERE, and only here
    <key>_gri_full.html/.pdf

    Each file has exactly one writer. Merging in place would look tidier and
    would be a trap: the next `build_narrative` run overwrites
    `<key>_gri_report.md` with narrative-only, and if that were the assembled
    document the content index would vanish silently, with no error and no
    obvious moment of loss.

INCOMPLETE INPUTS ARE REFUSED, NOT PATCHED OVER
    If an institution has no narrative — TU Dublin's is unfinished while the
    daily API quota is spent — nothing is written for it and the reason is
    printed. Same discipline as build_narrative.py: a file that looks like a
    finished report must be one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from scrapers.institutions import PROJECT_ROOT, resolve  # noqa: E402

OUT_DIR = PROJECT_ROOT / "report" / "output"

# Print stylesheet. Deliberately plain: this is a compliance document, and a
# supervisor reading a PDF cares about legibility and page breaks, not styling.
CSS = """
@page { size: A4; margin: 22mm 18mm; @bottom-center {
    content: counter(page) " of " counter(pages); font-size: 9pt; color: #666; } }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 10.5pt;
       line-height: 1.5; color: #1a1a1a; }
h1 { font-size: 20pt; border-bottom: 2px solid #2c4a1e; padding-bottom: 6px;
     color: #2c4a1e; }
h2 { font-size: 14pt; color: #2c4a1e; margin-top: 22px;
     page-break-after: avoid; border-bottom: 1px solid #ccc; padding-bottom: 3px; }
h3 { font-size: 11.5pt; color: #444; margin-top: 16px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 8pt;
        margin: 10px 0; page-break-inside: auto; }
th { background: #2c4a1e; color: #fff; text-align: left; padding: 5px;
     font-weight: normal; }
td { border-bottom: 1px solid #ddd; padding: 4px 5px; vertical-align: top; }
tr { page-break-inside: avoid; }
code { background: #f2f2f2; padding: 1px 3px; font-size: 9pt; }
blockquote { border-left: 3px solid #2c4a1e; margin-left: 0; padding-left: 12px;
             color: #444; font-style: italic; }
.frontmatter { background: #f7f7f4; border: 1px solid #ddd; padding: 12px 16px;
               margin: 16px 0; font-size: 9.5pt; }
"""


def front_matter(institution, narrative_md: str) -> str:
    """The methodology statement. Every claim in it is checkable."""
    today = dt.date.today().isoformat()
    return f"""# Sustainability Report — {institution.name}

Prepared **with reference to** the GRI Standards · compiled {today}

<div class="frontmatter">

**About this report.** It is generated from {institution.name}'s public AASHE
STARS 3.0 submission, mapped onto the GRI Standards. It covers 78 GRI
disclosures across 13 standards. Where a disclosure cannot be answered from
STARS data, the report says so and why, rather than omitting the question.

**How the figures got here — and why they can be trusted.** Every number in
this document was copied by code from the extracted STARS dataset. The language
model that wrote the prose was never shown a figure: it wrote named placeholders
and the values were substituted afterwards, so it could not alter, round or
invent one. After substitution the finished text is scanned, and the build fails
if any number in it cannot be traced back to the source data. The model chose
the sentences; it did not choose the numbers.

**What that guarantee does not cover.** It applies to figures. Qualitative
statements are drawn from the institution's own STARS narrative answers, but no
mechanical check confirms that a sentence describing them is faithful.

**"With reference to", not "in accordance with".** GRI reserves *in accordance*
for reports answering every Universal Disclosure plus all disclosures for each
material topic. This report does not, so it makes the weaker and correct claim.

**Source and attribution.** [{institution.name} STARS Report]({institution.report_url}),
AASHE. STARS data is publicly accessible and used here with attribution to
AASHE; it is not openly licensed.

</div>

---
"""


def assemble(institution) -> str | None:
    narrative_path = OUT_DIR / f"{institution.key}_gri_report.md"
    index_path = OUT_DIR / f"{institution.key}_gri_index.md"

    missing = [p.name for p in (narrative_path, index_path) if not p.exists()]
    if missing:
        print(f"  [skip] {institution.key}: missing {', '.join(missing)}")
        if narrative_path.name in missing:
            print("         the narrative is incomplete — run "
                  "`python -m report.build_narrative`")
        return None

    narrative = narrative_path.read_text(encoding="utf-8")
    index = index_path.read_text(encoding="utf-8")

    # Both source files open with their own H1 and attribution line; the
    # assembled document supplies its own, so drop theirs rather than printing
    # three titles.
    body = "\n".join(narrative.split("\n")[4:]).strip()
    index_body = "\n".join(index.split("\n")[4:]).strip()

    return (front_matter(institution, narrative)
            + "\n" + body
            + "\n\n---\n\n# GRI content index\n\n"
            + index_body
            + "\n\n---\n\n## Verifying this report\n\n"
              "Every figure above is recorded in `report/output/index_provenance.csv`\n"
              "with the exact STARS credit and field it came from, so any number\n"
              "can be traced to a row of the source dataset without trusting the\n"
              "generator. `tests/test_content_index.py` re-derives them\n"
              "independently of the code that produced them.\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("institutions", nargs="*")
    ap.add_argument("--no-pdf", action="store_true",
                    help="skip PDF export (markdown and HTML only)")
    args = ap.parse_args()

    try:
        import markdown
    except ImportError:
        sys.exit("[stop] pip install markdown")

    built = 0
    for institution in resolve(args.institutions):
        doc = assemble(institution)
        if doc is None:
            continue

        md_path = OUT_DIR / f"{institution.key}_gri_full.md"
        md_path.write_text(doc, encoding="utf-8")

        html_body = markdown.markdown(
            doc, extensions=["tables", "md_in_html", "attr_list"])
        html = (f"<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>Sustainability Report — {institution.name}</title>"
                f"<style>{CSS}</style></head><body>{html_body}</body></html>")
        html_path = OUT_DIR / f"{institution.key}_gri_full.html"
        html_path.write_text(html, encoding="utf-8")

        print(f"  [ok] {institution.name}")
        print(f"       -> {md_path.relative_to(PROJECT_ROOT)}")
        print(f"       -> {html_path.relative_to(PROJECT_ROOT)}")

        if not args.no_pdf:
            try:
                from weasyprint import HTML
                pdf_path = OUT_DIR / f"{institution.key}_gri_full.pdf"
                HTML(string=html).write_pdf(pdf_path)
                size = pdf_path.stat().st_size / 1024
                print(f"       -> {pdf_path.relative_to(PROJECT_ROOT)} "
                      f"({size:,.0f} KB)")
            except Exception as exc:                     # noqa: BLE001
                print(f"       [warn] no PDF: {exc}")
                print("              markdown and HTML are still written; "
                      "print the HTML from a browser instead")
        built += 1

    if not built:
        sys.exit("\n[stop] nothing assembled — no institution has both a "
                 "narrative and a content index yet.")
    print(f"\n[done] {built} complete report(s) assembled.")


if __name__ == "__main__":
    main()
