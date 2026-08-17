"""
The three institutions, in one place.
=====================================

Every per-university difference in the whole scraping layer lives here. Before
this, six near-identical scraper files each carried their own copy of the slug,
the report date and four output paths — the Berkeley and Cork deep scrapers
differed by about 37 lines out of 300, and all 37 were configuration.

That meant a parser bug had to be fixed three times. It was, in fact, fixed
zero times for two years, because nobody noticed the same bug existed in
triplicate (see CLAUDE.md §6.5).

Paths are resolved against the project root, so scripts work from any working
directory instead of only from inside the institution folder.

NOTE the folder for Berkeley is spelled "Berkley" on disk. Preserved as-is —
renaming it would break the existing caches for no benefit.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_URL = "https://reports.aashe.org"

# STARS category codes → human-readable names. Shared by every scraper.
CATEGORY_NAMES = {
    "PRE": "Report Preface",
    "AC": "Academics",
    "EN": "Engagement",
    "OP": "Operations",                  # Environmental pillar
    "PA": "Planning & Administration",   # Social + Governance pillars
    "IL": "Innovation & Leadership",
}
CATEGORY_CODES = tuple(CATEGORY_NAMES)

# One browser User-Agent for all requests; the default python-requests one gets
# rejected by some servers.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# AASHE is a guest server, not ours. CLAUDE.md §6.7.
PAUSE_SECONDS = 1.5


# E/S/G pillar grouping (CLAUDE.md §8). A reasoned curation decision, NOT an
# official STARS designation — STARS ships no E/S/G labels.
#
# This lived in two files (the credit parser and the score combiner) with a
# comment in each warning that they must be kept in sync. They are now one
# function, so they cannot drift.
PILLARS = {"OP": "Environmental", "AC": "Context", "EN": "Context",
           "IL": "Bonus", "PRE": "Preface"}
GOVERNANCE_PA_MAX = 5      # PA-1..PA-5 governance, PA-6..PA-13 social


def pillar_for(credit_code: str) -> str:
    """'OP-6' -> 'Environmental'. PA splits by credit number."""
    category = str(credit_code).split("-")[0]
    if category != "PA":
        return PILLARS.get(category, "Unknown")
    import re
    m = re.match(r"PA-(\d+)", str(credit_code))
    return "Governance" if m and int(m.group(1)) <= GOVERNANCE_PA_MAX else "Social"


@dataclass(frozen=True)
class Institution:
    key: str            # short name used on the command line
    name: str           # display name — appears in every output CSV
    slug: str           # the AASHE URL segment
    report_date: str    # the report version, also a URL segment
    folder: str         # where this institution's files live
    prefix: str         # filename prefix, e.g. "berkeley_stars.csv"
    cache_dirname: str  # credit-page cache directory name

    # ---- URLs -------------------------------------------------------
    @property
    def report_url(self) -> str:
        return f"{BASE_URL}/institutions/{self.slug}/report/{self.report_date}/"

    @property
    def report_tag(self) -> str:
        """The URL fragment that identifies a link as belonging to this report."""
        return f"/report/{self.report_date}/"

    # ---- paths ------------------------------------------------------
    @property
    def dir(self) -> pathlib.Path:
        return PROJECT_ROOT / self.folder

    @property
    def scorecard_cache(self) -> pathlib.Path:
        return self.dir / f"{self.prefix}_scorecard.html"

    @property
    def credit_cache_dir(self) -> pathlib.Path:
        return self.dir / self.cache_dirname

    @property
    def stars_csv(self) -> pathlib.Path:
        """One row per credit: the scorecard scores."""
        return self.dir / f"{self.prefix}_stars.csv"

    @property
    def fields_csv(self) -> pathlib.Path:
        """One row per field: the credit-detail measurements."""
        return self.dir / f"{self.prefix}_fields.csv"

    @property
    def credits_txt(self) -> pathlib.Path:
        """Human-readable dump of the credit pages."""
        return self.dir / f"{self.prefix}_credits.txt"


INSTITUTIONS: dict[str, Institution] = {
    "berkeley": Institution(
        key="berkeley",
        name="University of California, Berkeley",
        slug="university-of-california-berkeley-ca",
        report_date="2025-02-19",
        folder="Berkley",
        prefix="berkeley",
        cache_dirname="cache_credits",
    ),
    "cork": Institution(
        key="cork",
        name="University College Cork",
        slug="university-college-cork-national-university-of-ireland-cork-co-corcaigh",
        report_date="2026-03-05",
        folder="Cork",
        prefix="cork",
        cache_dirname="cache_credits_cork",
    ),
    "tudublin": Institution(
        key="tudublin",
        name="Technological University Dublin",
        slug="technological-university-dublin-dublin",
        report_date="2024-12-02",
        folder="Dublin",
        prefix="tudublin",
        cache_dirname="cache_credits_tudublin",
    ),
}


def resolve(keys: list[str] | None) -> list[Institution]:
    """Turn CLI names into Institution objects; no names means all of them."""
    if not keys:
        return list(INSTITUTIONS.values())
    chosen = []
    for k in keys:
        if k not in INSTITUTIONS:
            raise SystemExit(
                f"unknown institution {k!r}. "
                f"choose from: {', '.join(INSTITUTIONS)}")
        chosen.append(INSTITUTIONS[k])
    return chosen
