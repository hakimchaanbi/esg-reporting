# ESG Report Automation (ESPRIT Project #45)

Automated ESG reporting system for universities: scrape public sustainability
data → structure it → map it onto international reporting frameworks →
generate a report with an LLM → feed a BI dashboard.

Built as a 4th-year engineering project at ESPRIT School of Engineering
(Tunisia), supervised by Hiba Maalaoui.

## Pipeline

| # | Phase | Status |
|---|-------|--------|
| 1 | **Knowledge** — scrape ESG reference sites → RAG corpus | done |
| 2 | **Extraction** — scrape AASHE STARS reports (scores + detail) | done |
| 3 | **Structure** — combine into one schema, tag E/S/G pillars | done |
| 4 | **Map** — STARS credits → GRI / TCFD / ESRS disclosures | next |
| 5 | **Generate** — LLM writes prose, code injects numbers | pending |
| 6 | **Output** — ESG report + BI dashboard | pending |

Target frameworks: GRI, ISSB, CSRD/ESRS, TCFD, SASB.

Data sources: STARS 3.0 reports for UC Berkeley, University College Cork, and
Technological University Dublin. See `CLAUDE.md` for the full reasoning
behind institution selection, methodology caveats, and the non-hallucinable
number-injection design.

## Setup

```bash
uv sync
export AASHE_SESSIONID="<sessionid cookie value from browser devtools>"  # required for deep scrapers only
```

## Repo layout

- `scrape_*.py` — Branch B scrapers (STARS scorecards + credit detail) and
  Branch A scraper (knowledge corpus)
- `combine_universities.py` — Phase 3 dataset merge
- `Berkley/`, `Cork/`, `Dublin/` — per-institution scraped output
- `knowledge_sources/` — RAG corpus text
- `Combined_universities_data/` — merged Phase 3 dataset
