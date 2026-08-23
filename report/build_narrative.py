"""
Phase 5b — the narrative
========================

The content index (§15) is the skeleton: 75 rows saying which GRI question is
answered by which STARS field. This turns it into something a person reads.

THE ONE RULE, AND HOW IT IS ENFORCED
    CLAUDE.md §3: the LLM never touches a number it could alter. Here that is
    three separate mechanisms, not one promise:

      1. Numbers are never shown to the model. A numeric fact reaches it only
         as `{{ op6_annual_scope_1_ghg_emissions }}`. It cannot copy a figure
         it was never given.
      2. Jinja2 renders with StrictUndefined, so a token the model INVENTED
         raises instead of quietly rendering as an empty string. A hallucinated
         placeholder is a crash, not a blank space in the report.
      3. After rendering, audit_digits() scans the finished prose. Every
         number-like string must trace to a substituted value, to the source
         material supplied for that section, or to a GRI reference. Anything
         else fails the build.

    Mechanism 3 is the one that matters, because it does not trust the model,
    the prompt, or mechanisms 1 and 2.

WHAT THE MODEL IS ACTUALLY FOR
    Not the figures — the sentences. It decides order, emphasis and register,
    and it summarises the universities' own narrative answers (PA-3 governance
    prose, PA-11 health provision, PA-2 commitments) into readable paragraphs.
    That material is prose in the source and prose in the output; nothing about
    it is hallucinable-by-omission the way a figure is.

NUMBERS VS PROSE — WHERE THE LINE IS DRAWN
    value_type number/year  -> a TOKEN. The model never sees the value.
    everything else         -> source material. Booleans ("Yes"), short text
                               and the long narratives are shown to the model,
                               which may paraphrase them. §3 protects numbers;
                               paraphrasing "Yes" into "the institution does
                               operate such a committee" is the model doing its
                               job. Any DIGIT the model lifts out of that
                               material is still caught by the audit.

RUN
    python -m report.build_narrative                 all three, auto backend
    python -m report.build_narrative cork            one institution
    python -m report.build_narrative --backend stub  force offline
    python -m report.build_narrative --section governance
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

import pandas as pd
from jinja2 import Environment, StrictUndefined, TemplateError, meta

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from report.llm import QuotaExhausted, WriterError, get_writer            # noqa: E402
from scrapers.institutions import PROJECT_ROOT, resolve   # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "rag"))
try:
    from retrieve import LaneMisuse, retrieve             # noqa: E402
except Exception:                                         # pragma: no cover
    retrieve = None                                       # index not built yet
    LaneMisuse = RuntimeError

GRI_JSON = PROJECT_ROOT / "standards" / "gri_disclosures.json"
MAPPING = PROJECT_ROOT / "mapping" / "stars_gri_mapping.csv"
MASTER = PROJECT_ROOT / "Combined_universities_data" / "esg_master_dataset.csv"
OUT_DIR = PROJECT_ROOT / "report" / "output"
CACHE_DIR = PROJECT_ROOT / "report" / "cache_narrative"

TOKENISED_TYPES = {"number", "year"}
USABLE = {"equivalent", "component", "intensity", "partial"}

# Long source passages are trimmed before they go in the prompt. The model needs
# enough to paraphrase, not the whole 4,000-character answer.
CONTEXT_CHARS = 700

# How many retrieved passages each section gets, and how tight the match must be.
STYLE_K = 3          # lane A — general ESG explainers. HOW to write.
EVIDENCE_K = 4       # institution lane — this university's own evidence PDFs.
RETRIEVAL_MIN_SCORE = 0.35
EVIDENCE_CHARS = 600


# --------------------------------------------------------------------------
# The report outline. Hand-written, and deliberately so: the order of a GRI
# report is a reporting convention, not something to ask a model to invent.
# --------------------------------------------------------------------------
SECTIONS = [
    {
        "key": "organisation",
        "title": "The organisation and its reporting",
        "disclosures": ["2-1", "2-2", "2-3", "2-4", "2-5", "2-6"],
        "brief": "Introduce the institution and the basis of this report: what "
                 "it is, which entities are covered, what period the figures "
                 "describe and whether anything was externally assured.",
    },
    {
        "key": "workforce",
        "title": "Activities and workers",
        "disclosures": ["2-7", "2-8"],
        "brief": "Describe the size and composition of the workforce, and be "
                 "explicit about what the source data cannot tell us.",
    },
    {
        "key": "governance",
        "title": "Governance",
        "disclosures": ["2-9", "2-10", "2-11", "2-12", "2-13", "2-14", "2-15",
                        "2-16", "2-17", "2-18", "2-19", "2-20", "2-21"],
        "brief": "Describe who governs the institution, who is represented on "
                 "its highest decision-making body, and how responsibility for "
                 "sustainability is delegated. Where GRI asks how that body "
                 "behaves rather than who sits on it, say plainly that the "
                 "source does not answer.",
    },
    {
        "key": "strategy",
        "title": "Strategy, policies and practices",
        "disclosures": ["2-22", "2-23", "2-24", "2-25", "2-26", "2-27", "2-28"],
        "brief": "Describe the institution's sustainability vision, the "
                 "commitments it has made publicly, and the mechanisms through "
                 "which people can raise concerns.",
    },
    {
        "key": "stakeholders",
        "title": "Stakeholder engagement",
        "disclosures": ["2-29", "2-30"],
        "brief": "Describe how students, staff and the local community are "
                 "consulted, and through which standing bodies.",
    },
    {
        "key": "environment",
        "title": "Environmental performance",
        "disclosures": ["301-1", "301-2", "301-3", "302-1", "302-2", "302-3",
                        "302-4", "302-5", "303-1", "303-2", "303-3", "303-4",
                        "303-5", "305-1", "305-2", "305-3", "305-4", "305-5",
                        "305-6", "305-7", "306-1", "306-2", "306-3", "306-4",
                        "306-5", "308-1", "308-2"],
        "brief": "Report energy, water, emissions and waste performance. This "
                 "is the most quantitative section: lead with the figures.",
    },
    {
        "key": "social",
        "title": "Social and economic performance",
        "disclosures": ["202-1", "202-2", "204-1", "401-1", "401-2", "401-3",
                        "403-1", "403-2", "403-3", "403-4", "403-5", "403-6",
                        "403-7", "403-8", "403-9", "403-10", "405-1", "405-2"],
        "brief": "Report pay, employment conditions, occupational health and "
                 "safety, and workforce diversity.",
    },
]


def slug(credit: str, field: str) -> str:
    """A Jinja-safe token name that a reader can still recognise.

    The credit prefix is load-bearing: 'Full-time equivalent of employees'
    appears under PRE-3, OP-3, OP-5, OP-6 and OP-12, and without the prefix
    those five collapse into one token.
    """
    base = re.sub(r"[^a-z0-9]+", "_", f"{credit} {field}".lower()).strip("_")
    return base[:60].rstrip("_")


def gather(institution, section, gri, mapping, master) -> dict:
    """Everything this section can say, split into figures, prose and gaps."""
    inst = master[master.institution == institution.name]
    titles = {n: t for s in gri["standards"].values()
              for n, t in s["disclosures"].items()}

    figures, context, gaps, caveats, unavailable = {}, [], [], [], []

    for number in section["disclosures"]:
        rows = mapping[(mapping.gri_disclosure.astype(str).str.strip() == number)
                       & (mapping.review_status == "confirmed")]
        if rows.empty:
            continue

        gap_rows = rows[rows.relationship == "gap_gri_side"]
        if len(gap_rows):
            gaps.append({"disclosure": number,
                         "title": titles.get(number, ""),
                         "reason": redact_figures(str(gap_rows.iloc[0].rationale))})
            continue

        for r in rows[rows.relationship.isin(USABLE)].itertuples(index=False):
            credit, field = str(r.stars_credit).strip(), str(r.stars_field).strip()
            match = inst[(inst.credit_code == credit) & (inst.field == field)]
            if match.empty or pd.isna(match.iloc[0].value) or \
                    not str(match.iloc[0].value).strip():
                unavailable.append(f"GRI {number} ({credit} / {field})")
                continue

            v = match.iloc[0]
            value, units = str(v.value).strip(), (
                str(v.units).strip() if pd.notna(v.units) else "")

            if pd.notna(r.caveat) and str(r.caveat).strip():
                # "GRI 2-13:", never a bare "2-13:". Since 2026-08-23 an
                # unprefixed disclosure number is audited as data, so a bare
                # label here would put "2-13" in the prompt, invite the model to
                # echo it, and then fail the build for a reference we supplied.
                caveats.append(
                    f"GRI {number}: {redact_figures(str(r.caveat).strip())}")

            if str(v.value_type) in TOKENISED_TYPES:
                figures[slug(credit, field)] = {
                    "value": value, "units": units, "label": field,
                    "disclosure": number, "credit": credit,
                    "gri_title": titles.get(number, ""),
                }
            else:
                text = value if len(value) <= CONTEXT_CHARS else \
                    value[:CONTEXT_CHARS] + " […]"
                context.append({"disclosure": number, "credit": credit,
                                "label": field, "text": text,
                                "gri_title": titles.get(number, "")})

    support = retrieve_support(institution, section)

    return {"figures": figures, "context": context, "gaps": gaps,
            "caveats": sorted(set(caveats)),
            "unavailable": sorted(set(unavailable)),
            "style": support["style"], "evidence": support["evidence"]}


def retrieve_support(institution, section) -> dict:
    """Two kinds of retrieved help, with very different jobs.

    STYLE (lane A) — general ESG explainers, no facts about our universities.
    This is what the knowledge corpus was built for: the register and vocabulary
    of ESG reporting. peer_report chunks are excluded by retrieve()'s default,
    which is the guard that keeps Toronto's carbon figure out of Berkeley's
    report (§13).

    EVIDENCE (institution lane) — this university's own uploaded PDFs: climate
    plans, policies, pay-gap reports. Material that exists nowhere else in the
    pipeline; esg_master_dataset.csv holds the STARS answers, not the documents
    those answers cite. `institution=` is mandatory and enforced by LaneMisuse.

    ⚠️ BOTH ARE FIGURE-REDACTED before they reach the prompt.
        Retrieved passages are the one input here that is NOT verified
        field-by-field against the dataset. A document may be from a different
        year or a different reporting boundary than the STARS submission, so a
        figure lifted out of one would be traceable to a real PDF and still
        wrong for the sentence it lands in. Redacting keeps the roles clean:
        retrieval supplies language and argument, the mapped dataset supplies
        every number. The §3 guarantee is unchanged — every digit in the
        finished report still traces to esg_master_dataset.csv.
    """
    if retrieve is None:
        return {"style": [], "evidence": []}

    query = f"{section['title']}. {section['brief']}"
    style, evidence = [], []

    try:
        for hit in retrieve(query, k=STYLE_K, lane="knowledge",
                            drop_quantities=True,
                            min_score=RETRIEVAL_MIN_SCORE):
            style.append({"source": hit.source, "cite": hit.cite(),
                          "text": redact_figures(hit.text[:CONTEXT_CHARS])})
    except Exception as exc:                             # pragma: no cover
        print(f"       [warn] style retrieval unavailable: {exc}")

    try:
        for hit in retrieve(query, k=EVIDENCE_K, lane="institution",
                            institution=institution.name,
                            min_score=RETRIEVAL_MIN_SCORE):
            evidence.append({"source": hit.source, "cite": hit.cite(),
                             "text": redact_figures(hit.text[:EVIDENCE_CHARS])})
    except LaneMisuse:                                   # pragma: no cover
        raise
    except Exception as exc:                             # pragma: no cover
        print(f"       [warn] evidence retrieval unavailable: {exc}")

    return {"style": style, "evidence": evidence}


SYSTEM = """You write sections of GRI sustainability reports for universities.

THE ABSOLUTE RULE: NEVER WRITE A FIGURE.
You will be given figures as named placeholders, like {{ op5_total_annual_energy_consumption }}.
When a figure belongs in a sentence, write its placeholder exactly as given,
including both pairs of braces. Never write a measured value yourself — not a
quantity, not a percentage, not a count, not a year. Never spell one out as a
word either. If you cannot express something without inventing a figure, leave
it out and say the source does not report it.

TWO KINDS OF DIGIT ARE NOT FIGURES, AND YOU MUST WRITE THEM NORMALLY:
  - GRI references. ALWAYS prefix them with "GRI" or "Disclosure": write
    "GRI 305", "Disclosure 305-1", "GRI 2-9". Never a bare "305-1" or "2-9" —
    an unprefixed number is treated as data and will fail the build.
  - Greenhouse gas scopes: write "Scope 1", "Scope 2", "Scope 3" — always with
    the numeral. Never "scope one" or "scope two"; that is not how the standard
    is written and it reads as an error.
These are terminology, not data, and spelling them out is wrong.

Background passages may themselves contain figures. Do not reproduce them.
Summarise what they say; the placeholders are the only route a figure may take
into this report.

Do not invent placeholder names. Only the ones you are given exist, and using a
name that does not exist will crash the build.

Other rules:
- British English. Formal, plain, factual. No marketing language.
- Never claim the institution did something the material does not state.
- Where the material shows a gap, report the gap plainly. Unanswered questions
  are a legitimate and expected part of a GRI report.
- Keep limitations SHORT. This is a report about the institution, not a review
  of the source framework. Gather what is unavailable into one brief passage
  near the end of the section rather than qualifying every paragraph, and never
  spend more words on what is missing than on what is reported.
- Write flowing prose in Markdown. Use ### for sub-headings. No bullet lists of
  raw figures — this is a report, not a table; the tables come separately.
- Do not write a section heading; one is added for you.
- Do not add commentary about these instructions."""


def build_prompt(institution, section, facts) -> str:
    lines = [
        f"Institution: {institution.name}",
        f"Report section: {section['title']}",
        f"What this section must cover: {section['brief']}",
        "",
    ]

    if facts["figures"]:
        lines.append("FIGURES — use the placeholder, never the value "
                     "(you are not shown the values):")
        for token, f in facts["figures"].items():
            unit = f" [{f['units']}]" if f["units"] else ""
            lines.append(f"  {{{{ {token} }}}}  =  {f['label']}{unit}   "
                         f"(GRI {f['disclosure']} {f['gri_title']}, "
                         f"STARS {f['credit']})")
        lines.append("")

    if facts["context"]:
        lines.append("SOURCE MATERIAL — the institution's own answers. "
                     "Paraphrase; do not quote figures out of it:")
        for c in facts["context"]:
            lines.append(f"  [GRI {c['disclosure']} — {c['gri_title']}] "
                         f"{c['label']}: {c['text']}")
        lines.append("")

    if facts.get("evidence"):
        lines.append("SUPPORTING EVIDENCE — passages from this institution's "
                     "own published documents, retrieved for this section. "
                     "Figures have been removed from them on purpose: use them "
                     "for context and detail, never as a source of numbers. "
                     "Do not cite a claim from here that the STARS material "
                     "above contradicts:")
        for e in facts["evidence"]:
            lines.append(f"  [{e['source']}] {e['text']}")
        lines.append("")

    if facts.get("style"):
        lines.append("HOUSE STYLE — extracts from professional ESG reporting "
                     "guidance, included to show the expected register and "
                     "vocabulary. These are about OTHER organisations and "
                     "reporting in general. Take the WRITING STYLE from them "
                     "and nothing else: no facts, no claims, no figures:")
        for s in facts["style"]:
            lines.append(f"  [{s['source']}] {s['text']}")
        lines.append("")

    if facts["caveats"]:
        lines.append("CAVEATS — each of these must be stated in the prose, "
                     "not hidden. They are the honest limits of the data:")
        for c in facts["caveats"]:
            lines.append(f"  - {c}")
        lines.append("")

    if facts["gaps"]:
        lines.append("NOT REPORTED — GRI asks these and the source cannot "
                     "answer. Say so, briefly and without apology:")
        for g in facts["gaps"]:
            lines.append(f"  - GRI {g['disclosure']} {g['title']}: {g['reason']}")
        lines.append("")

    if facts["unavailable"]:
        lines.append("MAPPED BUT LEFT BLANK by this institution — do not "
                     "present these as reported:")
        for u in facts["unavailable"][:12]:
            lines.append(f"  - {u}")
        lines.append("")

    lines.append("Write the section now.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The audit. This is the part that does not trust anything above it.
# --------------------------------------------------------------------------
NUMBERISH = re.compile(r"\d[\d,.]*")


def _gri_reference_pattern() -> re.Pattern:
    """Digits that are GRI vocabulary rather than data, and must not be audited.

    ⚠️ THIS WAS THE WORST BUG IN THE PROJECT. The pattern used to be:

        r"\\b(?:GRI\\s+)?\\d{1,3}-\\d{1,2}\\b|\\bGRI\\s+\\d{1,3}\\b|\\bScope\\s+[123]\\b"

    The `(?:GRI\\s+)?` is optional, so the first alternative matched ANY short
    number-hyphen-number: `40-50`, `61-70`, `999-99`, `123-45`. `numbers_in()`
    deletes every match before scanning, so a fabricated figure written as a
    range was invisible — four of them rendered into a report section with the
    audit reporting `invented: []`. It made "non-hallucinable by construction"
    false, and it is reachable in ordinary use because STARS answers are full of
    ranges ("50 to 100") that a model will naturally rewrite as "50-100".

    The fix is to stop pattern-matching the SHAPE of a reference and enumerate
    the actual vocabulary: the 75 disclosure numbers and 12 standard numbers
    from gri_disclosures.json. `40-50` is not a disclosure, so it is data, so it
    gets audited. Anything GRI later adds arrives by regenerating that file
    rather than by loosening a regex.

    Failure direction matters: if the vocabulary cannot be read, this returns a
    pattern that exempts almost nothing. Real GRI references then get flagged as
    unaccounted-for, which is noisy and safe. The old failure was silent and
    unsafe.
    """
    numbers, standards = set(), set()
    try:
        gri = json.loads(GRI_JSON.read_text(encoding="utf-8"))
        for standard, body in gri["standards"].items():
            standards.add(standard.split()[-1])        # "GRI 305" -> "305"
            numbers.update(body["disclosures"])        # "305-1", "403-10", ...
    except Exception as exc:                            # pragma: no cover
        print(f"[warn] could not read the GRI vocabulary ({exc}); every "
              f"disclosure reference will be audited as if it were data.")

    # ⚠️ SECOND FIX, 2026-08-23. The first one enumerated the vocabulary but
    # left the GRI/Disclosure prefix OPTIONAL for disclosure numbers, and the
    # vocabulary contains 2-1 … 2-30. So `2-3 percent`, `2-30 per cent`,
    # `2-9 years` and `306-5 million` were all still deleted before the audit
    # looked — four fabricated figures went into a finished report while the
    # build printed "Every digit in every section traced to the dataset".
    #
    # The galling part is that the comment right here already contained the
    # correct reasoning — "a bare 305 is a plausible measurement, so the prefix
    # is REQUIRED" — and did not apply it to disclosures, where `2-3` is a far
    # more plausible measurement than `305` ever was.
    #
    # THE PREFIX IS NOW MANDATORY EVERYWHERE. A bare `305-1` in the prose is
    # audited as data and will fail the build. That is the safe direction: the
    # cost is a false positive on an unprefixed reference, which is loud, and
    # the system prompt tells the model to always write "GRI 305-1" or
    # "Disclosure 305-1" — which is what it does unprompted anyway.
    prefix = r"(?:GRI|Disclosure)\s+"
    parts = []
    if numbers:
        # Longest first so 403-10 is consumed before 403-1 can match its prefix.
        alt = "|".join(re.escape(n)
                       for n in sorted(numbers, key=len, reverse=True))
        parts.append(rf"\b{prefix}(?:{alt})\b")
    if standards:
        alt = "|".join(re.escape(s)
                       for s in sorted(standards, key=len, reverse=True))
        parts.append(rf"\b{prefix}(?:{alt})\b")
    parts.append(r"\bScope\s+[123]\b")
    return re.compile("|".join(parts), re.IGNORECASE)


GRI_REF = _gri_reference_pattern()
SPELLED = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
    r"billion)\b", re.IGNORECASE)


def redact_figures(text: str) -> str:
    """Blank out figures in editorial text before it reaches the prompt.

    Caveats and gap rationales are MY prose about all three universities, and
    several of them quote real values to make their point — "0.21 MWh for TU
    Dublin, 0 for Cork and Berkeley", "Berkeley 18,173 MWh", "45 at TU Dublin,
    240 at Berkeley". Passed through verbatim, Cork's prompt would contain
    Berkeley's figures, which is precisely the cross-institution contamination
    §13 guards against in the RAG layer — arriving through a door nobody had
    thought to lock.

    The caveat's argument survives redaction; only the illustrative numbers go.
    GRI references and Scope 1/2/3 are preserved, since a caveat that cannot
    name the disclosure it qualifies is useless.
    """
    out, last = [], 0
    for m in GRI_REF.finditer(text):
        out.append(NUMBERISH.sub("[figure]", text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(NUMBERISH.sub("[figure]", text[last:]))
    return "".join(out)


def numbers_in(text: str) -> list[str]:
    """Number-like strings, ignoring GRI references and Scope 1/2/3.

    Trailing punctuation is stripped: a figure at the end of a sentence matches
    as '2024', not '2024.', otherwise every sentence-final number looks
    unaccounted for.
    """
    found = NUMBERISH.findall(GRI_REF.sub(" ", text))
    return [n.rstrip(".,") for n in found if n.rstrip(".,")]


def audit_digits(rendered: str, substituted: list[str], context: list[str]):
    """Where did every digit in the finished prose come from?

    Three tiers, deliberately:
      ok       — the digit came from a value code substituted in.
      review   — it appears verbatim in the source material for this section,
                 so it traces to the dataset, but the model chose to retype it
                 and could in principle have attached it to the wrong claim.
      INVENTED — it appears nowhere. Hard failure.
    """
    from_tokens, from_context = set(), set()
    for v in substituted:
        from_tokens.update(numbers_in(v))
    for c in context:
        from_context.update(numbers_in(c))

    ok, review, invented = [], [], []
    for n in numbers_in(rendered):
        if n in from_tokens:
            ok.append(n)
        elif n in from_context:
            review.append(n)
        else:
            invented.append(n)

    spelled = sorted(set(m.lower() for m in SPELLED.findall(rendered)))
    return {"ok": ok, "review": sorted(set(review)),
            "invented": sorted(set(invented)), "spelled": spelled}


def render(prose: str, figures: dict) -> tuple[str, list[str]]:
    """Substitute the figures. StrictUndefined turns an invented token into a
    crash rather than a silent hole in a sentence."""
    values = {t: (f"{f['value']} {f['units']}".strip() if f["units"]
                  else f["value"])
              for t, f in figures.items()}
    env = Environment(undefined=StrictUndefined, autoescape=False)
    try:
        template_ast = env.parse(prose)
        out = env.from_string(prose).render(**values)
    except TemplateError as exc:
        raise WriterError(
            f"The model used a placeholder that does not exist: {exc}. "
            "This is caught rather than rendered blank, on purpose.") from exc

    # Ask Jinja which variables the template actually references. Matching the
    # literal string "{{ token }}" instead looks simpler and is wrong: any line
    # wrap inside the braces silently misses it, and every figure in that
    # sentence then reads as unaccounted-for in the audit.
    referenced = meta.find_undeclared_variables(template_ast)
    used = [values[t] for t in referenced if t in values]
    return out, used


def cache_path(writer, institution, section, prompt) -> pathlib.Path:
    """Where one generated section lives between runs.

    Keyed on the model, the system rule and the prompt, so changing any of them
    regenerates. Note what is NOT in the key: the figure VALUES. They never
    reach the prompt (that is the whole design), so a corrected number in
    esg_master_dataset.csv flows into the report on the next run without
    spending an API call — substitution happens fresh every time against live
    data, and only the sentences are cached.
    """
    digest = hashlib.sha256(
        f"{getattr(writer, 'model', writer.name)}\0{SYSTEM}\0{prompt}"
        .encode("utf-8")).hexdigest()[:8]
    return CACHE_DIR / f"{institution.key}__{section['key']}__{digest}.md"


def write_section(writer, institution, section, facts, use_cache=True) -> dict:
    prompt = build_prompt(institution, section, facts)
    tokens = list(facts["figures"])

    # The free tier allows very few calls a day, so never pay twice for the
    # same section. A run that dies halfway resumes instead of restarting.
    path = cache_path(writer, institution, section, prompt)
    cached = use_cache and path.exists()
    if cached:
        prose = path.read_text(encoding="utf-8")
    else:
        prose = writer.write(SYSTEM, prompt, tokens)
        if use_cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(prose, encoding="utf-8")

    rendered, used = render(prose, facts["figures"])
    context_texts = [c["text"] for c in facts["context"]]
    audit = audit_digits(rendered, used, context_texts)
    return {"prose": rendered, "audit": audit, "tokens_offered": len(tokens),
            "tokens_used": len(used), "cached": cached}


def main():
    # A full run is ~21 paced API calls and takes minutes. Without this, stdout
    # is block-buffered whenever output is piped or redirected and the progress
    # lines all appear at the end — which looks exactly like a hang.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:                               # pragma: no cover
        pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("institutions", nargs="*")
    ap.add_argument("--backend", choices=["gemini", "stub", "rogue"])
    ap.add_argument("--section", help="build only this section key")
    ap.add_argument("--no-cache", action="store_true",
                    help="regenerate every section, ignoring cached prose")
    args = ap.parse_args()

    for path in (GRI_JSON, MAPPING, MASTER):
        if not path.exists():
            sys.exit(f"[stop] missing {path}")

    gri = json.loads(GRI_JSON.read_text(encoding="utf-8"))
    mapping = pd.read_csv(MAPPING)
    master = pd.read_csv(MASTER)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        writer = get_writer(args.backend)
    except WriterError as exc:
        sys.exit(f"[stop] {exc}")

    sections = [s for s in SECTIONS
                if not args.section or s["key"] == args.section]
    if not sections:
        sys.exit(f"[stop] no section named {args.section!r}. "
                 f"Choose from {[s['key'] for s in SECTIONS]}")

    audit_rows, failed, out_of_quota = [], False, False

    for institution in resolve(args.institutions):
        if out_of_quota:
            break
        print(f"\n[{institution.key}] {institution.name}")
        parts = [f"# Sustainability report — {institution.name}", "",
                 "Prepared **with reference to** the GRI Standards. Source "
                 f"data: [{institution.name} STARS Report]"
                 f"({institution.report_url}), AASHE. STARS data is used with "
                 "attribution to AASHE.", ""]
        incomplete = []

        for section in sections:
            facts = gather(institution, section, gri, mapping, master)
            try:
                result = write_section(writer, institution, section, facts,
                                       use_cache=not args.no_cache)
            except QuotaExhausted as exc:
                print(f"  [quota] {exc}")
                incomplete.append(section["title"])
                out_of_quota = failed = True
                break
            except WriterError as exc:
                print(f"  [FAIL] {section['title']}: {exc}")
                incomplete.append(section["title"])
                failed = True
                continue

            a = result["audit"]
            status = "FAIL" if a["invented"] else ("hit " if result["cached"]
                                                   else "ok  ")
            if a["invented"]:
                failed = True
                incomplete.append(section["title"])
            print(f"  [{status:4}] {section['title']:38} "
                  f"{result['tokens_used']}/{result['tokens_offered']} figures"
                  + (f"  INVENTED: {a['invented'][:6]}" if a["invented"] else "")
                  + (f"  review: {a['review'][:4]}" if a["review"] else "")
                  + (f"  spelled: {a['spelled'][:4]}" if a["spelled"] else ""))

            audit_rows.append({
                "institution": institution.name, "section": section["key"],
                "backend": writer.name,
                "figures_offered": result["tokens_offered"],
                "figures_used": result["tokens_used"],
                "digits_from_figures": len(a["ok"]),
                "digits_needing_review": "; ".join(a["review"]),
                "digits_invented": "; ".join(a["invented"]),
                "spelled_numbers": "; ".join(a["spelled"]),
            })
            parts += [f"## {section['title']}", "", result["prose"], ""]

        # --section is for iterating on one section's prompt without spending
        # seven API calls. It must NEVER touch the real report: `parts` holds
        # only the section that was built, so writing it over a complete file
        # would silently destroy the other six. It goes to its own preview file
        # instead, and the full report is only ever written by a full run —
        # which is cheap anyway, because the other sections come from cache.
        if args.section:
            preview = OUT_DIR / f"{institution.key}_{args.section}_preview.md"
            if incomplete:
                print(f"  [skip] {args.section} incomplete, nothing written")
            else:
                preview.write_text("\n".join(parts), encoding="utf-8")
                print(f"  -> {preview.relative_to(PROJECT_ROOT)}  "
                      f"(preview only — the full report is untouched)")
            continue

        # Never leave a file that looks like a report but is not one. The first
        # real run wrote a 323-byte tudublin report containing a title and zero
        # sections, because every section had failed on quota — the build said
        # STOP and wrote the file anyway. Anyone opening the directory later,
        # including a reviewer, would have found three plausible-looking
        # reports of which one was empty.
        out = OUT_DIR / f"{institution.key}_gri_report.md"
        if incomplete:
            print(f"  [skip] not written — {len(incomplete)} section(s) "
                  f"incomplete: {', '.join(incomplete[:3])}")
            if out.exists():
                stale = out.with_suffix(".md.incomplete")
                out.rename(stale)
                print(f"         moved the previous file to "
                      f"{stale.name} so it cannot be mistaken for finished")
        else:
            out.write_text("\n".join(parts), encoding="utf-8")
            print(f"  -> {out.relative_to(PROJECT_ROOT)}")

    if audit_rows:
        # The --section guard above protected the report .md and stopped one
        # file short. This CSV is the only record of which digits need human
        # review, and §17 names it as the way to tell stub output from real —
        # and a one-section preview run was overwriting all 21 rows with 1.
        # Same bug, same command, the file next door.
        if args.section:
            audit_path = OUT_DIR / f"narrative_audit_{args.section}_preview.csv"
        else:
            audit_path = OUT_DIR / "narrative_audit.csv"
        pd.DataFrame(audit_rows).to_csv(audit_path, index=False)
        print(f"\n[save] number audit -> {audit_path.relative_to(PROJECT_ROOT)}")

    if failed:
        sys.exit("\n[STOP] a section failed the number audit or the model call. "
                 "Nothing above is safe to hand in until that is clean.")
    print("\nEvery digit in every section traced to the dataset.")


if __name__ == "__main__":
    main()
