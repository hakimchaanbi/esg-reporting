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
import json
import re
import sys

import pandas as pd
from jinja2 import Environment, StrictUndefined, TemplateError, meta

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from report.llm import WriterError, get_writer            # noqa: E402
from scrapers.institutions import PROJECT_ROOT, resolve   # noqa: E402

GRI_JSON = PROJECT_ROOT / "standards" / "gri_disclosures.json"
MAPPING = PROJECT_ROOT / "mapping" / "stars_gri_mapping.csv"
MASTER = PROJECT_ROOT / "Combined_universities_data" / "esg_master_dataset.csv"
OUT_DIR = PROJECT_ROOT / "report" / "output"

TOKENISED_TYPES = {"number", "year"}
USABLE = {"equivalent", "component", "intensity", "partial"}

# Long source passages are trimmed before they go in the prompt. The model needs
# enough to paraphrase, not the whole 4,000-character answer.
CONTEXT_CHARS = 700


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
                unavailable.append(f"{number} ({credit} / {field})")
                continue

            v = match.iloc[0]
            value, units = str(v.value).strip(), (
                str(v.units).strip() if pd.notna(v.units) else "")

            if pd.notna(r.caveat) and str(r.caveat).strip():
                caveats.append(f"{number}: {redact_figures(str(r.caveat).strip())}")

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

    return {"figures": figures, "context": context, "gaps": gaps,
            "caveats": sorted(set(caveats)), "unavailable": sorted(set(unavailable))}


SYSTEM = """You write sections of GRI sustainability reports for universities.

THE ABSOLUTE RULE: NEVER WRITE A NUMBER.
You will be given figures as named placeholders, like {{ op5_total_annual_energy_consumption }}.
When a figure belongs in a sentence, write its placeholder exactly as given,
including both pairs of braces. Never write a digit yourself — not a value, not
a percentage, not a count, not a year. Never spell a number out as a word
either. If you cannot express something without inventing a number, leave it
out and say the source does not report it.

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
GRI_REF = re.compile(r"\b(?:GRI\s+)?\d{1,3}-\d{1,2}\b|\bGRI\s+\d{1,3}\b"
                     r"|\bScope\s+[123]\b", re.IGNORECASE)
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


def write_section(writer, institution, section, facts) -> dict:
    prompt = build_prompt(institution, section, facts)
    tokens = list(facts["figures"])
    prose = writer.write(SYSTEM, prompt, tokens)
    rendered, used = render(prose, facts["figures"])
    context_texts = [c["text"] for c in facts["context"]]
    audit = audit_digits(rendered, used, context_texts)
    return {"prose": rendered, "audit": audit, "tokens_offered": len(tokens),
            "tokens_used": len(used)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("institutions", nargs="*")
    ap.add_argument("--backend", choices=["gemini", "stub", "rogue"])
    ap.add_argument("--section", help="build only this section key")
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

    audit_rows, failed = [], False

    for institution in resolve(args.institutions):
        print(f"\n[{institution.key}] {institution.name}")
        parts = [f"# Sustainability report — {institution.name}", "",
                 "Prepared **with reference to** the GRI Standards. Source "
                 f"data: [{institution.name} STARS Report]"
                 f"({institution.report_url}), AASHE. STARS data is used with "
                 "attribution to AASHE.", ""]

        for section in sections:
            facts = gather(institution, section, gri, mapping, master)
            try:
                result = write_section(writer, institution, section, facts)
            except WriterError as exc:
                print(f"  [FAIL] {section['title']}: {exc}")
                failed = True
                continue

            a = result["audit"]
            status = "FAIL" if a["invented"] else "ok"
            if a["invented"]:
                failed = True
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

        out = OUT_DIR / f"{institution.key}_gri_report.md"
        out.write_text("\n".join(parts), encoding="utf-8")
        print(f"  -> {out.relative_to(PROJECT_ROOT)}")

    if audit_rows:
        audit_path = OUT_DIR / "narrative_audit.csv"
        pd.DataFrame(audit_rows).to_csv(audit_path, index=False)
        print(f"\n[save] number audit -> {audit_path.relative_to(PROJECT_ROOT)}")

    if failed:
        sys.exit("\n[STOP] a section failed the number audit or the model call. "
                 "Nothing above is safe to hand in until that is clean.")
    print("\nEvery digit in every section traced to the dataset.")


if __name__ == "__main__":
    main()
