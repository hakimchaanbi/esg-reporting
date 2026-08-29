# ESG Report Automation (ESPRIT Project #45)

An automated ESG reporting system for universities: scrape public
sustainability data → structure it → map it onto the GRI Standards → generate a
report with an LLM → feed a BI dashboard.

Built as a 4th-year engineering project at ESPRIT School of Engineering
(Tunisia), supervised by Hiba Maalaoui.

**`CLAUDE.md` is the real documentation.** It carries the design decisions, the
methodology caveats, the gotchas and the open problems. This file is the map.

## Pipeline

| # | Phase | Status |
|---|-------|--------|
| 1 | **Knowledge** — scrape ESG reference sites → retrieval corpus | done |
| 2 | **Extraction** — scrape AASHE STARS reports (scores + credit detail) | done |
| 3 | **Structure** — combine into one schema, tag E/S/G pillars | done |
| 4 | **Map** — STARS fields → GRI disclosures | done |
| 5 | **Generate** — LLM writes prose, code injects the numbers | done |
| 6 | **Output** — GRI content index · narrative · BI dashboard | done |

### Scope: GRI only

The supervisor settled this on 2026-08-14. **ISSB, CSRD/ESRS, TCFD and SASB are
out of scope.** The mapping is one hand-built, cited STARS→GRI table rather than
five shallow ones; the report notes that the approach extends to the others.

## The design decision everything rests on

**The LLM never writes a number.** It produces prose containing placeholders —
`{{ op_6_annual_scope_1_ghg_emissions }}` — and code substitutes the real value
from the dataset. The model is never shown a figure, so it cannot copy one
wrongly, and a scan of the finished prose fails the build if any digit cannot be
traced back to the data.

The mapping table is likewise built by hand against GRI's own published
requirement text, never generated. A fabricated mapping in an ESG tool is an
integrity failure, not a bug.

Limits of that claim are stated honestly in `CLAUDE.md` §17 — read them before
repeating the phrase "non-hallucinable by construction" anywhere it matters.

## Data

STARS 3.0 reports for **UC Berkeley**, **University College Cork** and
**Technological University Dublin** — 3,197 extracted field/value pairs across
118 credit pages each.

STARS data is © AASHE, publicly accessible and usable in research **with
attribution**. It is not openly licensed. Cite as:
*[Institution] STARS Report. AASHE. [Date published]. Retrieved from [URL].*

`CLAUDE.md` §4 explains why these three institutions and not others — including
why none of the ten European universities originally suggested could be used.

## Setup

```bash
uv sync
```

Two secrets, both environment variables, never committed:

```bash
export AASHE_SESSIONID="<sessionid cookie from browser devtools>"  # credit-detail scraping only
echo 'GEMINI_API_KEY=<key from https://aistudio.google.com/apikey>' >> .env   # report generation only
```

Everything except scraping and generation runs offline with no credentials.

## Running it

```bash
# Phase 2-3 — extract and combine  (scraping needs AASHE_SESSIONID)
python -m scrapers.scorecard
python -m scrapers.credit_pages          # download only
python -m scrapers.parse_credit_pages    # parse only, offline
python -m pipeline.combine_scores
python -m pipeline.build_master          # -> esg_master_dataset.csv

# Phase 4 — the mapping
python mapping/validate_mapping.py           # integrity gate
python mapping/validate_mapping.py --review  # GRI text beside real values

# Phase 5-6 — the report
python -m report.build_content_index     # the GRI index (no LLM)
python -m report.build_narrative         # the prose (needs GEMINI_API_KEY)
python -m report.build_narrative --backend stub   # offline, no key

# Phase 6b-c — dashboard and finished report (no key, no network)
python -m report.build_bi_table          # three tidy CSVs
streamlit run report/dashboard.py
python -m report.build_full_report       # narrative + index -> md, html, pdf

# Tests
python tests/test_parse_credits.py
python tests/test_gri_requirements.py
python tests/test_content_index.py
python tests/test_narrative_safety.py
python tests/test_bi_table.py
python mapping/test_validator_catches_fabrication.py
python rag/test_retrieval_safety.py
```

⚠️ Gemini's free tier allows very few requests per day and the limit is **per
model**. Set `GEMINI_MODEL` to switch. See `CLAUDE.md` §17.

**You do not need an API key to reproduce the reports.** `report/cache_narrative/`
is committed, so `build_narrative` reads the generated prose from disk and the
whole pipeline runs offline. A key is only needed to generate *new* prose — after
changing the mapping, or for TU Dublin's two unfinished sections.

## Repo layout

```
scrapers/          STARS scraping. institutions.py holds ALL per-university
                   config; download and parse are separate modules on purpose
pipeline/          combine_scores.py, build_master.py -> esg_master_dataset.csv
standards/         GRI vocabulary + verbatim requirement text (fetch_gri.py)
mapping/           stars_gri_mapping.csv, its validator, and the negative test
rag/               chunking, embeddings, retrieval + its safety tests
report/            build_content_index.py, build_narrative.py, llm.py, output/
tests/             cross-cutting verification
scrape_knowledge.py            Branch A corpus scraper
Berkley/ Cork/ Dublin/         per-institution scraped output and HTML caches
knowledge_sources/             Branch A corpus text
Combined_universities_data/    esg_master_dataset.csv — what everything reads
documents/                     evidence PDFs cited by STARS answers (gitignored)
```

Berkeley's folder is spelled `Berkley` on disk. Left alone deliberately —
renaming breaks the caches for no benefit.

## Status and known problems

Phase 4 and 5 are built and tested; the BI dashboard is not started.

An independent review on 2026-08-22 verified the extraction end to end — all
3,197 pairs re-derived from the cached HTML by a separate extractor with zero
disagreements, and 45 derived figures reproduced exactly for all three
universities — and found several defects in the safety and documentation
layers.

All thirteen are **fixed**, and the failure modes are written up in
`CLAUDE.md` §14 because they are worth remembering:

- a regex hole that let any number written as `40-50` walk past the number audit
- the test that should have caught it, which shared the same flawed pattern
- three further tests that could not fail, now each with a positive control
- `--section` overwriting a whole report with one section
- the `section` column, blank on 2,768 rows and wrong on 63

- GRI 405-1-b, where four populated employee-category fields were unmapped
  because the disclosure's second half had never been checked
- GRI 303-3's megalitre/cubic-metre mismatch, uncaveated while the identical
  302-1 mismatch was flagged
- the waste disclosures, where `306-4`/`306-5` claimed `equivalent` under a
  limitation that had downgraded `306-3` to `partial`

A **second** review on 2026-08-23, told to distrust those fixes because the same
author made them, found that two were incomplete — the number audit still let a
figure written as `2-3` through, and one caveat shipped a statement the same
day's fix had falsified. Both are fixed, along with the biggest structural gap
either review found: **GRI 3: Material Topics was missing from the vocabulary
altogether**, so a report claiming to follow the GRI Standards never listed the
disclosures that decide which standards apply.

That produced the finding most worth carrying into the defence: **AASHE
determined materiality for the higher-education sector; the institutions did not
determine it for themselves.** GRI 3-1 is therefore a gap that no amount of
data extraction can fill — see `CLAUDE.md` §14.20.

Both reviews' strongest positive result stands: an independently written
extractor reproduced all 3,197 field/value pairs from the cached HTML with zero
disagreements, and 45 derived figures — scope totals, intensities, FTE sums,
percentage reductions — reproduced exactly for all three universities.

GRI 305 has since been completed too — the base year, the baseline emissions,
the rationale and the methodology were all present and unmapped, which is what
turns an emissions section from a snapshot into a trend and makes the absolute
reduction derivable.

Still open (`CLAUDE.md` §14 items 18 and 21): four `equivalent` rows that no
longer meet their own definition, and the question of which topic standards to
cover.

The **BI dashboard** is built (`CLAUDE.md` §18). It deliberately refuses to
chart absolute totals across the three universities — Berkeley withdraws
2,092,006 m³ of water a year and Cork 54,153, so a raw-totals chart would say
Berkeley is worst at everything, which is false. Comparison is restricted to the
eight normalised metrics all three report, which surfaces the more interesting
result: **Berkeley has the highest water use per person and the lowest energy
use per square metre**, so the ranking inverts with the denominator.

The finished deliverable is one document per institution — narrative, GRI content
index and a methodology statement — as Markdown, HTML and a 31-page PDF
(`CLAUDE.md` §19). Berkeley's and Cork's are complete.

Outstanding: TU Dublin's narrative is **two sections short**. The daily Gemini
quota ran out mid-run and the build correctly refused to write a partial report;
two calls finish it.
