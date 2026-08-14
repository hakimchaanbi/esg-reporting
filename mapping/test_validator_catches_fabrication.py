"""
Negative test: prove validate_mapping.py rejects fabricated references.

The whole integrity claim of Phase 4 is "an invented GRI disclosure or a STARS
field that was never scraped cannot reach the report". That claim is worth
nothing unless it is tested, so this deliberately injects four bad rows and
asserts each one is caught.

RUN
    python test_validator_catches_fabrication.py
"""

import pandas as pd

import validate_mapping as vm

BAD_ROWS = [
    # (description, row dict, substring expected in the error)
    ("invented GRI disclosure number",
     dict(stars_credit="OP-6", stars_field="Annual scope 1 GHG emissions",
          gri_standard="GRI 305", gri_disclosure="305-99",
          relationship="equivalent", confidence="high", review_status="proposed",
          rationale="fabricated", caveat=""),
     "does not exist"),

    ("real disclosure filed under the wrong standard",
     dict(stars_credit="OP-6", stars_field="Annual scope 1 GHG emissions",
          gri_standard="GRI 302", gri_disclosure="305-1",
          relationship="equivalent", confidence="high", review_status="proposed",
          rationale="wrong parent standard", caveat=""),
     "belongs to"),

    ("STARS field that was never scraped",
     dict(stars_credit="OP-6", stars_field="Total lifecycle emissions of campus cats",
          gri_standard="GRI 305", gri_disclosure="305-1",
          relationship="equivalent", confidence="high", review_status="proposed",
          rationale="fabricated field", caveat=""),
     "does not exist under"),

    ("STARS credit that does not exist",
     dict(stars_credit="OP-99", stars_field="",
          gri_standard="GRI 305", gri_disclosure="305-1",
          relationship="equivalent", confidence="high", review_status="proposed",
          rationale="fabricated credit", caveat=""),
     "not in the dataset"),
]


def main():
    mapping, gri, master = vm.load()

    clean_errors, _ = vm.validate(mapping, gri, master)
    print(f"baseline: {len(clean_errors)} errors on the real table "
          f"({'clean' if not clean_errors else 'NOT CLEAN'})")
    if clean_errors:
        print("  the real table must be clean before this test means anything")
        for e in clean_errors:
            print(f"    {e}")
        raise SystemExit(1)

    print()
    failures = 0
    for desc, row, expected in BAD_ROWS:
        poisoned = pd.concat([mapping, pd.DataFrame([row])], ignore_index=True)
        errors, _ = vm.validate(poisoned, gri, master)
        caught = any(expected in e for e in errors)
        print(f"  [{'PASS' if caught else 'FAIL'}] {desc}")
        if caught:
            hit = next(e for e in errors if expected in e)
            print(f"         -> {hit}")
        else:
            failures += 1
            print(f"         -> NOT CAUGHT. Expected an error containing "
                  f"{expected!r}")

    print()
    if failures:
        raise SystemExit(f"{failures} fabrication(s) slipped through — the "
                         f"integrity guarantee is broken.")
    print("All fabrications rejected. A mapping row cannot cite a GRI "
          "disclosure or a STARS field that does not exist.")


if __name__ == "__main__":
    main()
