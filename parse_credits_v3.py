"""
STARS credit-detail parser v3 — reads the fields the v2 parser could not see
============================================================================

WHAT WAS WRONG WITH v2
    v2 looked for data inside HTML <table> elements. On a STARS credit page the
    only tables are boilerplate: the "Overall Rating / Overall Score / Liaison /
    Submission Date" box, and a Status/Score/Responsible-Party row. Both are
    identical on all 118 pages.

    The real credit content is not in a table at all. Result: berkeley_qa.csv
    and tudublin_qa.csv contained three distinct questions, repeated 118 times,
    and not a single real figure.

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
    This reads the HTML already cached on disk by the deep scrapers. It does not
    contact AASHE, needs no AASHE_SESSIONID, and has no politeness delay — so it
    is safe to run as often as you like.

    Run:  python parse_credits_v3.py
"""

import re
import unicodedata
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
INSTITUTIONS = [
    # display name, cache dir, per-institution output CSV
    ("University of California, Berkeley", "Berkley/cache_credits", "Berkley/berkeley_fields.csv"),
    ("University College Cork", "Cork/cache_credits_cork", "Cork/cork_fields.csv"),
    ("Technological University Dublin", "Dublin/cache_credits_tudublin", "Dublin/tudublin_fields.csv"),
]

COMBINED_OUT = Path("Combined_universities_data/combined_credit_fields.csv")

# STARS renders "no answer given" as a green triple dash.
NOT_REPORTED = {"---", "--", "—"}

# Pillar grouping — kept identical to combine_universities.py (CLAUDE.md §8) so
# the two datasets join cleanly. Changing it here would silently desync them.
PILLARS = {"OP": "Environmental", "AC": "Context", "EN": "Context",
           "IL": "Bonus", "PRE": "Preface"}


def pillar_for(code: str) -> str:
    """PA splits by credit number: PA-1..5 governance, PA-6..13 social."""
    cat = code.split("-")[0]
    if cat != "PA":
        return PILLARS.get(cat, "Unknown")
    m = re.match(r"PA-(\d+)", code)
    return "Governance" if m and int(m.group(1)) <= 5 else "Social"


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
    section = ""
    seen_wells = set()

    # Walk in document order so a section heading applies to the fields that
    # follow it. find_previous() would be wrong: most field-headers carry no
    # <h5>, and the ones that do mark the start of a run.
    for el in soup.find_all(["div", "span"]):
        classes = el.get("class") or []

        if "field-header" in classes:
            h5 = el.find("h5")
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
            "section": section,
            "field": field,
            "value": value,
            "units": units,
            "value_numeric": to_number(value),
            "value_type": classify(field, value, units),
        }


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def sort_key(code: str):
    """PRE-1 … AC-1 … OP-6 … IL-70, numerically not lexically."""
    order = {"PRE": 0, "AC": 1, "EN": 2, "OP": 3, "PA": 4, "IL": 5}
    cat, _, num = code.partition("-")
    return order.get(cat, 9), int(num) if num.isdigit() else 0


def main():
    frames = []

    for institution, cache_dir, out_csv in INSTITUTIONS:
        cache = Path(cache_dir)
        if not cache.is_dir():
            print(f"[skip] {institution}: no cache at {cache_dir}")
            continue

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
        df.insert(0, "institution", institution)
        Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_csv, index=False)
        frames.append(df)

        numeric = int(df["value_numeric"].notna().sum())
        print(f"[ok] {institution}")
        print(f"     {len(pages)} pages -> {len(df)} fields "
              f"({len(pages) - len(empty_pages)} pages with fields)")
        print(f"     {df['field'].nunique()} distinct questions, "
              f"{numeric} numeric values, "
              f"{int((df.value_type == 'not_reported').sum())} not reported")
        print(f"     -> {out_csv}")

        # The v2 failure was invisible because nobody checked this. Now it is
        # checked on every run, and it is loud.
        if df["field"].nunique() < 20:
            print(f"     [WARN] only {df['field'].nunique()} distinct questions — "
                  f"this looks like the v2 boilerplate bug all over again.")

    if not frames:
        print("[error] no caches found — run the deep scrapers first.")
        return

    combined = pd.concat(frames, ignore_index=True)
    COMBINED_OUT.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(COMBINED_OUT, index=False)

    print(f"\n[done] {len(combined)} field rows across {len(frames)} institutions")
    print(f"       -> {COMBINED_OUT}")
    print("\nvalue_type breakdown:")
    for kind, count in combined["value_type"].value_counts().items():
        print(f"  {kind:14} {count:6}")


if __name__ == "__main__":
    main()
