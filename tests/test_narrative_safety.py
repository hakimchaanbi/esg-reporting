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
import re
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

    print("\n3a. Every mapped figure reaches the model — no token collisions\n")

    # ⚠️ The guarantee is that a PRINTED figure is real. It was never that every
    # REAL figure was offered, and that gap opened a hole: slug() truncates
    # token names to 60 characters, STARS discriminates many fields in their
    # suffix, and `figures[slug(...)] = ...` was a silent dict overwrite.
    #
    # "Scope 2 … electricity (market-based)" and "(location-based)" collapsed to
    # one name, so TU Dublin's market-based 4,992 tCO2e — its own declared
    # method — never reached the model. The model then wrote that the total was
    # "left unstated" while the content index printed 4,992 in the same
    # document. Nothing caught it: every digit still traced to the dataset.
    from report.build_narrative import slug, unique_tokens   # noqa: E402

    market = "Scope 2 GHG emissions from off-site sources of electricity (market-based)"
    location = "Scope 2 GHG emissions from off-site sources of electricity (location-based)"
    check("the raw slug for these two DOES still collide (the bug is real)",
          slug("OP-6", market) == slug("OP-6", location),
          f"both -> {slug('OP-6', market)}")

    tokens = unique_tokens({("OP-6", market), ("OP-6", location)})
    check("unique_tokens separates them",
          tokens[("OP-6", market)] != tokens[("OP-6", location)],
          f"{tokens[('OP-6', market)]} vs {tokens[('OP-6', location)]}")
    check("and the naming is deterministic, not order-dependent",
          unique_tokens({("OP-6", location), ("OP-6", market)}) == tokens)

    # The property, across everything actually built: one token per field, and
    # every mapped-and-populated numeric field present.
    collisions, offered = [], 0
    for inst in resolve([]):
        for section in SECTIONS:
            figures = gather(inst, section, gri, mapping, master)["figures"]
            labels = [f["label"] for f in figures.values()]
            offered += len(figures)
            if len(set(labels)) != len(labels):
                dupes = [x for x in labels if labels.count(x) > 1]
                collisions.append(f"{inst.key}/{section['key']}: {dupes[:2]}")
    check(f"{offered} figures across 24 sections, none sharing a token",
          not collisions, "; ".join(collisions[:3]))

    tud = next(i for i in resolve([]) if i.key == "tudublin")
    env = next(s for s in SECTIONS if s["key"] == "environment")
    env_figs = gather(tud, env, gri, mapping, master)["figures"]
    by_label = {f["label"]: f["value"] for f in env_figs.values()}
    check("TU Dublin's market-based scope 2 is offered, not overwritten",
          by_label.get(market) == "4,992",
          f"got {by_label.get(market)!r} — dataset says '4,992'")

    print("\n3b. Caveats do not smuggle another university's figures in\n")

    # ⚠️ This block deliberately does NOT use numbers_in().
    #
    # It used to. numbers_in() and redact_figures() share GRI_REF, so the test
    # was asking the redactor to mark its own homework: anything GRI_REF wrongly
    # exempted, redact_figures kept AND numbers_in ignored, and the test
    # reported zero survivors. It could not fail. That is how "40-50" survived
    # in caveat text undetected for as long as it did.
    #
    # Instead: find EVERY digit run with a scanner that knows nothing about GRI,
    # then clear survivors against the disclosure list read straight from
    # gri_disclosures.json. If GRI_REF is wrong, this list is still right.
    from report.build_narrative import redact_figures            # noqa: E402

    naive_digits = re.compile(r"\d[\d,.]*")
    vocabulary = {n for s in gri["standards"].values() for n in s["disclosures"]}
    vocabulary |= {s.split()[-1] for s in gri["standards"]}

    def unexplained(text: str) -> list[str]:
        """Digit runs not accounted for by a real GRI reference in the text.

        ⚠️ The PREFIX IS REQUIRED here too. An earlier version cleared any digit
        sitting near a vocabulary entry, so `2-30 per cent` cleared itself —
        `2-30` is a real disclosure number. Independence from GRI_REF was not
        enough; the scanner has to be independent of the assumption GRI_REF got
        wrong, which was that a disclosure-shaped string is self-identifying.
        """
        out = []
        for m in naive_digits.finditer(text):
            # Strip trailing punctuation BEFORE testing, not after. `\d[\d,.]*`
            # swallows the comma in "Scope 1, Scope 2", so the exemption check
            # became \bScope\s+1,\b — which cannot match, and the scanner
            # reported a legitimate Scope reference as an unexplained figure.
            digit = m.group().rstrip(".,")
            if not digit:
                continue
            window = text[max(0, m.start() - 14):m.end() + 6]
            if any(re.search(r"(?i)\b(?:GRI|Disclosure)\s+%s\b" % re.escape(ref),
                             window) for ref in vocabulary):
                continue                       # part of e.g. "GRI 305-1"
            if re.search(r"(?i)\bScope\s+%s\b" % re.escape(digit), window):
                continue
            out.append(digit)
        return out

    sample = ("GRI 302-1-b is broader here: this STARS field also includes "
              "renewable electricity (Berkeley 18,173 MWh), it reads "
              "0.21 MWh for TU Dublin, and coverage ran 40-50 per cent.")
    redacted = redact_figures(sample)
    check("figures are stripped from caveat text, including ranges",
          unexplained(redacted) == [], f"survived: {unexplained(redacted)}")
    check("the GRI reference survives redaction",
          "302-1" in redacted, redacted[:90])

    all_caveats = [c for s in SECTIONS
                   for c in gather(cork, s, gri, mapping, master)["caveats"]]
    surviving = sorted({n for c in all_caveats for n in unexplained(c)})
    check(f"no figure survives in any of {len(all_caveats)} live caveats",
          not surviving, f"survived: {surviving[:5]}")

    print("\n3e. PROPERTY — an UNPREFIXED number is data, whatever it "
          "looks like\n")

    # ⚠️ This check used to assert exactly "40-50" and "61-70" — the two strings
    # from the bug report. Testing the instance instead of the property is why
    # the second hole survived the first fix: the prefix stayed optional for
    # disclosure numbers, the vocabulary contains 2-1 … 2-30, and `2-3 percent`
    # sailed through while `40-50` was caught.
    #
    # So sweep the WHOLE vocabulary. For every disclosure GRI defines, the bare
    # form must be audited as data and the prefixed form must not. That is the
    # actual rule, and it cannot be satisfied by special-casing a bug report.
    every = sorted({n for s in gri["standards"].values() for n in s["disclosures"]})

    leaked_bare, lost_prefixed = [], []
    for number in every:
        if not audit_digits(f"It fell by {number} per cent.", [], [])["invented"]:
            leaked_bare.append(number)
        if audit_digits(f"See Disclosure {number} for detail.", [], [])["invented"]:
            lost_prefixed.append(number)

    check(f"all {len(every)} disclosure numbers are audited when UNPREFIXED",
          not leaked_bare, f"still invisible: {leaked_bare[:8]}")
    check(f"all {len(every)} are exempt when written 'Disclosure N' / 'GRI N'",
          not lost_prefixed, f"wrongly flagged: {lost_prefixed[:8]}")

    # The originally reported shapes, kept so the specific regression is named.
    for rogue, want in [("cut emissions by 40-50 metric tons", {"40", "50"}),
                        ("fell 2-3 percent last year", {"2", "3"}),
                        ("diverted 2-30 per cent more waste", {"2", "30"}),
                        ("a cost of 306-5 million euro", {"306", "5"})]:
        got = set(audit_digits(rogue, [], [])["invented"])
        check(f"{rogue[:38]!r} -> audited", want <= got, f"caught: {sorted(got)}")

    real_refs = ("Disclosure 305-1 under GRI 305 covers Scope 1 emissions, "
                 "GRI 2-9 governance, and GRI 403-10 work-related ill health.")
    check("prefixed references are still exempt",
          not audit_digits(real_refs, [], [])["invented"],
          f"wrongly flagged: {audit_digits(real_refs, [], [])['invented']}")

    print("\n3c. Retrieved passages carry no figures into the prompt\n")

    # Lane A style extracts and the institution's own evidence PDFs are the one
    # input not verified field-by-field against the dataset. A document can be
    # from a different year or boundary than the STARS submission, so a figure
    # lifted from one would trace to a real PDF and still be wrong for the
    # sentence. Both are redacted; this proves it on live retrieval output.
    # Uses unexplained(), NOT numbers_in(). numbers_in shares GRI_REF with
    # redact_figures, so checking redaction with it asks the redactor to mark
    # its own homework — the exact mistake 3b was rewritten to avoid, which was
    # then reintroduced twelve lines below it.
    checked, dirty = 0, []
    for s in SECTIONS:
        f = gather(cork, s, gri, mapping, master)
        for passage in f["style"] + f["evidence"]:
            checked += 1
            found = unexplained(passage["text"])
            if found:
                dirty.append(f"{passage['source'][:30]}: {found[:3]}")
    check(f"no figure survives in any of {checked} retrieved passages",
          not dirty, "; ".join(dirty[:3]))
    check("retrieval is actually returning passages (not vacuous)",
          checked > 20, f"{checked} passages across {len(SECTIONS)} sections")

    print("\n3d. Evidence is scoped to the institution being written about\n")

    others = [i for i in ("berkeley", "tudublin")]
    foreign = []
    for s in SECTIONS:
        for passage in gather(cork, s, gri, mapping, master)["evidence"]:
            if not passage["cite"].startswith(cork.name):
                foreign.append(passage["cite"][:60])
    check("every evidence passage in Cork's prompt is Cork's own",
          not foreign, f"foreign: {foreign[:3]}")

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
