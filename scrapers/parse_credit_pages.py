"""
STARS credit-detail parser — reads the fields the old parser could not see
==========================================================================

Was parse_credits_v3.py at the project root; moved here so the whole scraping
layer lives in one package and shares institutions.py.

WHAT THE OLD PARSER GOT WRONG
    It looked for data inside HTML <table> elements. On a STARS credit page the
    only tables are boilerplate: the "Overall Rating / Overall Score / Liaison /
    Submission Date" box, and a Status/Score/Responsible-Party row — identical
    on all 118 pages. So berkeley_qa.csv and tudublin_qa.csv held three distinct
    questions repeated 118 times and not a single real figure, while looking
    healthy at 354 rows.

WHERE THE DATA ACTUALLY IS
    A flat run of sibling elements, one per field:

        <div class="field-header"><h5>Scope 1 GHG emissions</h5></div>
        <span class="scorecardFieldTitle">... from stationary combustion:</span>
        <div class="well">134,957 <i>Metric tons of CO2 equivalent</i></div>

    so:  span.scorecardFieldTitle  = the question
         the next div.well         = the answer
         a trailing <i> inside it  = the units
         the last field-header h5  = the section the field sits in

    A section heading applies to every field after it until the next heading.

NO NETWORK ACCESS
    Reads only the HTML already cached by credit_pages.py. No AASHE_SESSIONID,
    no politeness delay — safe to run as often as you like.

RUN
    python -m scrapers.parse_credit_pages              all three
    python -m scrapers.parse_credit_pages berkeley     just one
"""

from __future__ import annotations

import argparse
import re
import unicodedata

import pandas as pd
from bs4 import BeautifulSoup

from .institutions import (BASE_URL, PROJECT_ROOT, Institution, pillar_for,
                           resolve)

COMBINED_OUT = PROJECT_ROOT / "Combined_universities_data" / "combined_credit_fields.csv"

# STARS renders "no answer given" as a green triple dash.
NOT_REPORTED = {"---", "--", "—"}


def clean(text: str) -> str:
    """Collapse whitespace and normalise the unicode STARS emits (nbsp, ’, …)."""
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", text).strip()


# ----------------------------------------------------------------------
# value typing
# ----------------------------------------------------------------------
NUMERIC_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
DATE_RE = re.compile(r"^[A-Z][a-z]{2}\.? \d{1,2}, \d{4}$|^\d{4}-\d{2}-\d{2}$")
YEAR_FIELD_RE = re.compile(r"(?i)\byear\b|\bdate\b")


def classify(field: str, value: str, units: str) -> str:
    """Tag each answer so the BI layer can filter to the numeric subset."""
    if not value:
        return "not_reported"
    if NUMERIC_RE.match(value):
        # "Performance year for water use = 2023" is a number to a regex but not
        # a measurement — averaging it into a metric would be nonsense. Requires
        # all three signals so a genuine count near 2000 is not mislabelled.
        if (YEAR_FIELD_RE.search(field or "")
                and not units
                and re.fullmatch(r"(19|20)\d{2}", value)):
            return "year"
        return "number"
    if value.lower() in {"yes", "no"}:
        return "boolean"
    if value.startswith(("http://", "https://")):
        return "url"
    if DATE_RE.match(value):
        return "date"
    return "text_long" if len(value) > 200 else "text"


def to_number(value: str):
    """'134,957' -> 134957.0 ; anything non-numeric -> None."""
    if not NUMERIC_RE.match(value or ""):
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def read_links(well) -> str:
    """Every href inside an answer, as a space-separated list.

    Without this the destinations are simply lost. 1,249 links live inside
    answer wells; 828 happen to use the URL as their own link text and survive
    into `value`, but 421 keep only a label — "Pre-assessment", a truncated
    filename — and the href goes nowhere. That includes every document
    attachment: 140 unique PDFs, spreadsheets and Word files.

    AASHE paths are relative (/media/secure/...) and are made absolute here so
    the column is usable without knowing where it came from.
    """
    if well is None:
        return ""
    seen, out = set(), []
    for a in well.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        if href.startswith("/"):
            href = BASE_URL + href
        if href not in seen:
            seen.add(href)
            out.append(href)
    return " ".join(out)


def read_well(well) -> tuple[str, str]:
    """Split a .well into (value, units).

    Units live in a trailing <i>, but <i> is also used for emphasis inside
    narrative answers — so only treat it as units when what precedes it is a
    bare number. Otherwise the <i> text stays part of the value.
    """
    if well is None:
        return "", ""

    italics = well.find_all("i")
    if italics:
        candidate = clean(italics[-1].get_text())
        stripped = well.__copy__()
        for tag in stripped.find_all("i"):
            tag.decompose()
        head = clean(stripped.get_text(" "))
        if NUMERIC_RE.match(head):
            return head, candidate

    value = clean(well.get_text(" "))
    return ("", "") if value in NOT_REPORTED else (value, "")


# ----------------------------------------------------------------------
# page parsing
# ----------------------------------------------------------------------
def credit_title(soup) -> str:
    """'University of California, Berkeley OP-6: Greenhouse Gas Emissions'
    -> 'Greenhouse Gas Emissions'."""
    h1 = soup.find("h1")
    if not h1:
        return ""
    text = clean(h1.get_text())
    m = re.search(r"\b[A-Z]{2,4}-\d+:\s*(.+)$", text)
    return m.group(1) if m else text


def parse_page(html: str, code: str):
    """Yield one dict per field on a single credit page."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()

    name = credit_title(soup)
    indicator = section = ""
    seen_wells = set()

    # Walk in document order so a heading applies to the fields that follow it.
    # find_previous() would be wrong: most field-headers carry no heading at all
    # (2,647 of 3,197 are bare guidance wrappers), and the ones that do mark the
    # start of a run.
    #
    # STARS uses TWO heading levels and this parser used to read only the inner
    # one:
    #
    #   <div class="field-header"><h4>6.1 GHG emissions inventory and disclosure</h4>
    #                             <h5>Scope 1 and 2 GHG emissions inventory</h5></div>
    #   ...
    #   <div class="field-header"><h4>6.2 GHG emissions per square meter</h4></div>
    #
    # h4 is the numbered INDICATOR, h5 an optional sub-section inside it. Reading
    # only h5 discarded every h4 (499 of them) AND, worse, let the last h5 leak
    # past the h4 that ended it — `Gross floor area of building space` came out
    # labelled "Scope 3 GHG emissions", which is 6.2 data wearing 6.1's heading.
    # A new h4 therefore RESETS the sub-section: entering indicator 6.2 means we
    # are no longer inside "Scope 3 GHG emissions" and do not yet know what we
    # are inside.
    for el in soup.find_all(["div", "span"]):
        classes = el.get("class") or []

        if "field-header" in classes:
            h4 = el.find("h4")
            h5 = el.find("h5")
            if h4:
                indicator = clean(h4.get_text())
                section = ""
            if h5:
                section = clean(h5.get_text())
            continue

        if "scorecardFieldTitle" not in classes:
            continue

        field = clean(el.get_text()).rstrip(":")
        well = el.find_next("div", class_="well")

        # Titles and wells alternate 1:1; if a well were ever claimed twice it
        # would mean a field is silently borrowing its neighbour's answer.
        if well is not None:
            if id(well) in seen_wells:
                well = None
            else:
                seen_wells.add(id(well))

        value, units = read_well(well)
        yield {
            "credit_code": code,
            "category": code.split("-")[0],
            "pillar": pillar_for(code),
            "credit_name": name,
            "indicator": indicator,
            "section": section,
            "field": field,
            "value": value,
            "units": units,
            "value_numeric": to_number(value),
            "value_type": classify(field, value, units),
            "links": read_links(well),
        }


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def sort_key(code: str):
    """PRE-1 … AC-1 … OP-6 … IL-70, numerically not lexically."""
    order = {"PRE": 0, "AC": 1, "EN": 2, "OP": 3, "PA": 4, "IL": 5}
    cat, _, num = code.partition("-")
    return order.get(cat, 9), int(num) if num.isdigit() else 0


def parse_one(institution: Institution) -> pd.DataFrame:
    cache = institution.credit_cache_dir
    if not cache.is_dir():
        print(f"[skip] {institution.name}: no cache at {cache}")
        return pd.DataFrame()

    pages = sorted(cache.glob("*.html"), key=lambda p: sort_key(p.stem))
    rows, empty_pages = [], []

    for page in pages:
        html = page.read_text(encoding="utf-8", errors="replace")
        page_rows = list(parse_page(html, page.stem))
        if page_rows:
            rows.extend(page_rows)
        else:
            empty_pages.append(page.stem)

    df = pd.DataFrame(rows)
    df.insert(0, "institution", institution.name)
    institution.fields_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(institution.fields_csv, index=False)

    numeric = int(df["value_numeric"].notna().sum())
    print(f"[ok] {institution.name}")
    print(f"     {len(pages)} pages -> {len(df)} fields "
          f"({len(pages) - len(empty_pages)} pages with fields)")
    print(f"     {df['field'].nunique()} distinct questions, "
          f"{numeric} numeric values, "
          f"{int((df.value_type == 'not_reported').sum())} not reported")
    print(f"     -> {institution.fields_csv}")

    # The old failure was invisible because nobody checked this. Now it is
    # checked on every run, and it is loud.
    if df["field"].nunique() < 20:
        print(f"     [WARN] only {df['field'].nunique()} distinct questions — "
              f"this looks like the boilerplate bug all over again.")

    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("institutions", nargs="*",
                    help="berkeley / cork / tudublin (default: all)")
    args = ap.parse_args()

    chosen = resolve(args.institutions)
    frames = [df for df in (parse_one(i) for i in chosen) if not df.empty]

    if not frames:
        print("[error] no caches found — run scrapers.credit_pages first.")
        return

    # Only rewrite the combined file when every institution was parsed,
    # otherwise a single-institution run would silently truncate it.
    if len(chosen) == len(frames) == 3:
        combined = pd.concat(frames, ignore_index=True)
        COMBINED_OUT.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(COMBINED_OUT, index=False)
        print(f"\n[done] {len(combined)} field rows across {len(frames)} "
              f"institutions\n       -> {COMBINED_OUT}")
        print("\nvalue_type breakdown:")
        for kind, count in combined["value_type"].value_counts().items():
            print(f"  {kind:14} {count:6}")
    else:
        print(f"\n[note] parsed {len(frames)} institution(s); "
              f"{COMBINED_OUT.name} left untouched (needs all three).")


if __name__ == "__main__":
    main()
