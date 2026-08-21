"""
Prove the LLM cannot put a number into the report.

CLAUDE.md §3 is the project's one non-negotiable design claim, and until now it
was only a prompt instruction — which is to say, a request. This tests the
mechanisms that make it a guarantee, including by deliberately breaking them.

Five claims, each tested:
  1. A model that writes a bare figure is CAUGHT. (The one that matters. Uses
     the rogue backend, which breaks the rule on purpose.)
  2. A model that invents a placeholder name CRASHES rather than rendering an
     empty string into a sentence.
  3. Numeric values are never in the prompt at all, so there is nothing for the
     model to copy even if it tried.
  4. GRI references (305-1, "GRI 302", "Scope 1") are not mistaken for data —
     otherwise the audit cries wolf on every correct report.
  5. A normal offline run is clean, so the audit is not simply failing always.

RUN
    python tests/test_narrative_safety.py
"""

import json
import pathlib
import sys

import pandas as pd

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from report.build_narrative import (                       # noqa: E402
    SECTIONS, audit_digits, build_prompt, gather, numbers_in, render,
    write_section)
from report.llm import RogueWriter, StubWriter, WriterError  # noqa: E402
from scrapers.institutions import resolve                  # noqa: E402

failures = []


def check(name: str, passed: bool, detail: str = ""):
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")
    if not passed:
        failures.append(name)


def main():
    gri = json.loads((PROJECT_ROOT / "standards" / "gri_disclosures.json")
                     .read_text(encoding="utf-8"))
    mapping = pd.read_csv(PROJECT_ROOT / "mapping" / "stars_gri_mapping.csv")
    master = pd.read_csv(PROJECT_ROOT / "Combined_universities_data"
                         / "esg_master_dataset.csv")

    cork = resolve(["cork"])[0]
    environment = next(s for s in SECTIONS if s["key"] == "environment")
    facts = gather(cork, environment, gri, mapping, master)

    print(f"\nUsing {cork.name} / {environment['title']}: "
          f"{len(facts['figures'])} figures, {len(facts['context'])} passages\n")

    print("1. A model that writes its own figure is caught\n")

    result = write_section(RogueWriter(), cork, environment, facts)
    invented = result["audit"]["invented"]
    check("rogue backend's fabricated numbers are flagged",
          set(invented) >= {"42,000", "17"},
          f"flagged: {invented}")

    print("\n2. An invented placeholder crashes instead of rendering blank\n")

    try:
        render("Emissions totalled {{ total_emissions_of_campus_cats }}.",
               facts["figures"])
        caught = False
    except WriterError as exc:
        caught = "does not exist" in str(exc)
    check("unknown placeholder raises WriterError", caught,
          "StrictUndefined, not the default silent empty string")

    print("\n3. The model is never shown a numeric value\n")

    prompt = build_prompt(cork, environment, facts)

    # Substring matching, which is the strict form: if "22,549" occurs anywhere
    # in the prompt the model could copy it. Single-character values are
    # excluded because a bare "0" collides with the digits inside token names
    # (op_5_, op_12_), GRI references and "CO2" — a collision that tells the
    # model nothing, since it cannot tie a stray "0" to a named quantity.
    leaked = sorted(f"{f['label']} = {f['value']}"
                    for f in facts["figures"].values()
                    if len(f["value"]) > 1 and f["value"] in prompt)
    check(f"none of the {len(facts['figures'])} figure values appear in the prompt",
          not leaked, f"leaked: {leaked[:3]}")

    # The values must still be reachable for substitution — a prompt with no
    # figures would pass the check above trivially.
    check("figures were actually gathered (the check above is not vacuous)",
          len(facts["figures"]) > 10,
          f"{len(facts['figures'])} numeric figures for this section")

    # The honest half. Source passages ARE the institution's own prose and do
    # carry figures; that is documented, not accidental. What must hold is that
    # a digit copied out of them is classified 'review' and never 'ok', so it
    # shows up in narrative_audit.csv for a person to glance at.
    #
    # The environment section happens to have no digits in its passages, so
    # probing it would pass vacuously. Find a section that actually does.
    probe, context_texts = None, []
    for s in SECTIONS:
        texts = [c["text"] for c in gather(cork, s, gri, mapping, master)["context"]]
        found = sorted({n for t in texts for n in numbers_in(t)})
        if found:
            probe, context_texts = found[0], texts
            break
    if probe:
        audit = audit_digits(f"The institution reported {probe} last year.",
                             [], context_texts)
        check("a digit copied from source material is flagged for review, "
              "not silently accepted",
              probe in audit["review"] and not audit["invented"],
              f"probe {probe!r} -> review={audit['review'][:3]} "
              f"invented={audit['invented'][:3]}")
    else:
        check("some section's passages carry figures to test against", False,
              "no digits in any context — probe would be vacuous")

    print("\n3b. Caveats do not smuggle another university's figures in\n")

    # Several caveats quote real values to make their point. Unredacted, Cork's
    # prompt would carry Berkeley's numbers.
    from report.build_narrative import redact_figures            # noqa: E402
    sample = ("GRI 302-1-b is broader here: this STARS field also includes "
              "renewable electricity (Berkeley 18,173 MWh), and it reads "
              "0.21 MWh for TU Dublin.")
    redacted = redact_figures(sample)
    check("figures are stripped from caveat text",
          numbers_in(redacted) == [], f"survived: {numbers_in(redacted)}")
    check("the GRI reference survives redaction",
          "302-1" in redacted, redacted[:80])

    all_caveats = [c for s in SECTIONS
                   for c in gather(cork, s, gri, mapping, master)["caveats"]]
    surviving = sorted({n for c in all_caveats for n in numbers_in(c)})
    check(f"no figure survives in any of {len(all_caveats)} live caveats",
          not surviving, f"survived: {surviving[:5]}")

    print("\n4. GRI references are not mistaken for data\n")

    refs = ("Disclosure 305-1 under GRI 305 covers Scope 1 emissions, "
            "and GRI 302 covers energy.")
    check("305-1, 'GRI 305', 'Scope 1' are not read as figures",
          numbers_in(refs) == [], f"found: {numbers_in(refs)}")

    check("a real figure beside a GRI reference is still seen",
          numbers_in("Under GRI 305-1 it reported 6,215.78 tonnes.")
          == ["6,215.78"],
          f"found: {numbers_in('Under GRI 305-1 it reported 6,215.78 tonnes.')}")

    print("\n5. Sentence-final figures are matched without their full stop\n")

    audit = audit_digits("The total was 6,215.78.", ["6,215.78"], [])
    check("'6,215.78.' matches the substituted '6,215.78'",
          not audit["invented"], f"invented: {audit['invented']}")

    print("\n6. A normal offline run is clean\n")

    stub_failures = []
    for section in SECTIONS:
        f = gather(cork, section, gri, mapping, master)
        r = write_section(StubWriter(), cork, section, f)
        if r["audit"]["invented"]:
            stub_failures.append(f"{section['key']}: {r['audit']['invented']}")
    check("every section passes with the stub backend",
          not stub_failures, "; ".join(stub_failures[:3]))

    print()
    if failures:
        sys.exit(f"{len(failures)} check(s) FAILED: {failures}")
    print("Number safety holds: a fabricated figure is caught, an invented "
          "placeholder crashes,\nand the model never sees a value in the first "
          "place.")


if __name__ == "__main__":
    main()
