"""
Honest quality check on the knowledge index.

A high similarity score only says "this is the closest chunk in the corpus" --
it says nothing about whether the corpus HAS a good answer. This script asks
questions Phase 5 will realistically ask and prints the top hit for each, so
the corpus's real ceiling is visible rather than assumed.

Some questions below are expected to fail. That is the point: knowing which
questions this corpus cannot answer tells Phase 5 when to rely on the GRI
standards in standards/ instead.

RUN
    python eval_retrieval.py        (from rag/)
"""

from retrieve import backend_name, retrieve

QUESTIONS = [
    # (question, what a good answer would look like)
    ("What is double materiality?",
     "the CSRD idea: impact on the world AND financial impact"),
    ("What is the difference between GRI and SASB?",
     "GRI = broad stakeholder impact, SASB = financially material by industry"),
    ("How should an organization describe its emissions reporting?",
     "framing/tone for an emissions narrative"),
    ("What is a materiality assessment and why does it matter?",
     "process for choosing what to report"),
    ("What does STARS measure and how is it scored?",
     "AASHE STARS credits, ratings, points"),
    ("What is a living wage and how is pay equity reported?",
     "likely ABSENT — corpus has no pay-equity depth"),
    ("What are the exact disclosure requirements of GRI 305-1?",
     "likely ABSENT — corpus has explainers, not the standard text"),
]


def main():
    print(f"backend: {backend_name()}\n")
    weak = []

    for question, expectation in QUESTIONS:
        hits = retrieve(question, k=3)
        print("=" * 78)
        print(f"Q: {question}")
        print(f"   (looking for: {expectation})")
        if not hits:
            print("   NO HITS")
            weak.append(question)
            continue
        for h in hits:
            text = " ".join(h.text.split())
            print(f"   [{h.score:.3f}] {h.source} ({h.source_type})")
            print(f"           {text[:150]}...")
        if hits[0].score < 0.45:
            weak.append(question)

    print("\n" + "=" * 78)
    print(f"Questions with a weak best-match (<0.45): {len(weak)} of {len(QUESTIONS)}")
    for q in weak:
        print(f"  - {q}")
    print("\nA weak score here is information, not a bug: it marks a topic the")
    print("knowledge corpus cannot ground, so Phase 5 must not ask it to.")


if __name__ == "__main__":
    main()
