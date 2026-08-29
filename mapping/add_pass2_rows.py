"""
Second mapping pass — the prose disclosures the first pass never looked at.
==========================================================================

The first pass went looking for tonnes and megawatt-hours. It found them, and
GRI 302/303/305/306 came out well covered. But 46 of 67 disclosures ended up
"Not assessed" in the content index, including 21 of GRI 2's mandatory General
Disclosures — questions about governance, policy commitments and stakeholder
engagement, which STARS answers in prose rather than numbers. Lane C exists
precisely because the S and G pillars are prose; the mapping had not used it.

`mapping/find_candidates.py` surfaced the candidates by embedding each
disclosure's verbatim requirement text against every populated STARS field.
Every row below was then read against the requirement text and the real values
before being written — the similarity score chose what to *look at*, never what
to accept. Several high-scoring candidates were rejected on reading and are
recorded here as gap rows with the reason.

This script is idempotent: it skips any (credit, field, disclosure) triple that
is already in the table, so re-running it cannot duplicate rows.

RUN
    python -m mapping.add_pass2_rows            show what would change
    python -m mapping.add_pass2_rows --write    apply it
"""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from scrapers.institutions import PROJECT_ROOT  # noqa: E402

MAPPING = PROJECT_ROOT / "mapping" / "stars_gri_mapping.csv"
REVIEWED = "2026-08-20"


def row(credit, field, std, disc, rel, conf, rationale, caveat="", note=""):
    return {
        "stars_credit": credit, "stars_field": field,
        "gri_standard": std, "gri_disclosure": disc,
        "relationship": rel, "confidence": conf,
        "review_status": "confirmed",
        "rationale": rationale, "caveat": caveat,
        "claude_verdict": "agree", "claude_note": note,
        "reviewed_by": "claude", "reviewed_date": REVIEWED,
    }


def gap(std, disc, rationale, caveat=""):
    """GRI asks something STARS does not collect. A finding, not a blank."""
    return {
        "stars_credit": "", "stars_field": "",
        "gri_standard": std, "gri_disclosure": disc,
        "relationship": "gap_gri_side", "confidence": "high",
        "review_status": "confirmed",
        "rationale": rationale, "caveat": caveat,
        "claude_verdict": "agree", "claude_note": "",
        "reviewed_by": "claude", "reviewed_date": REVIEWED,
    }


# --------------------------------------------------------------------------
# GRI 2 — General Disclosures. The whole standard was unmapped.
# --------------------------------------------------------------------------
GRI2 = [
    row("PRE-3", "Institutional control", "GRI 2", "2-1", "component", "medium",
        "GRI 2-1-b requires the nature of ownership and legal form. STARS "
        "'Institutional control' reports whether the institution is public or "
        "private, which is that answer for the higher-education sector.",
        "GRI 2-1 also requires the legal name, the location of headquarters and "
        "the countries of operation. STARS carries none of these as fields — "
        "they are report metadata, not credit data."),

    row("PRE-3", "Narrative outlining the institutional boundary used to complete this report",
        "GRI 2", "2-2", "component", "high",
        "GRI 2-2-a requires the entities included in the sustainability "
        "reporting. This STARS field is a written statement of exactly that: "
        "which campuses, sites and controlled entities the submission covers.",
        "GRI 2-2-b/c additionally ask whether the reporting entities differ "
        "from those in the financial statements and how minority interests are "
        "consolidated. STARS asks neither."),

    row("PRE-3", "Which of the following features are included within the institutional boundary?",
        "GRI 2", "2-6", "partial", "medium",
        "GRI 2-6-b asks the organization to describe its activities. STARS "
        "lists the campus features inside the boundary (agricultural school, "
        "medical centre, farm, hospital…), which is a partial description of "
        "what the institution actually operates.",
        "GRI 2-6 asks for the sectors the organization is active in, its value "
        "chain, its products and services and the markets served. A list of "
        "campus features covers only the activities, and only those with a "
        "physical footprint."),

    gap("GRI 2", "2-4",
        "GRI 2-4 requires restatements of information from earlier periods and "
        "the reason for them. STARS submissions are independent snapshots; the "
        "report carries no restatement field and no link to the previous "
        "submission's figures.",
        "STARS v2.2 and earlier scored Operations credits against the "
        "institution's own baseline and v3.0 scores against a peer group, so "
        "cross-version figures are not comparable in the first place — see "
        "CLAUDE.md 6.4."),

    row("PRE-4", "Were any independent audits or external assurance processes used in the preparation of this report?",
        "GRI 2", "2-5", "component", "high",
        "GRI 2-5-b turns on whether the sustainability reporting has been "
        "externally assured. This STARS field is that yes/no, asked of the "
        "same body of reported information.",
        "GRI 2-5 additionally requires the assurance standard used, the level "
        "of assurance obtained, the limitations of the process and the "
        "relationship with the assurance provider. STARS captures none of "
        "these; the free-text field is optional and unstructured."),

    row("PRE-4", "Narrative outlining the independent audits or external assurance processes used in the preparation of this report",
        "GRI 2", "2-5", "component", "medium",
        "Where assurance was used, this field describes what was assured and "
        "by whom — GRI 2-5-b-ii and 2-5-b-iii in free text.",
        "Only populated where the institution answered yes to the assurance "
        "question, so it is absent for most submissions."),

    row("OP-6", "Performance year for scope 1 and 2 GHG emissions",
        "GRI 2", "2-3", "partial", "low",
        "GRI 2-3-a requires the reporting period covered by the reported "
        "information. STARS states a performance year per credit; this is the "
        "one governing the flagship emissions figures.",
        "STARS has no single reporting period, and the per-credit years diverge "
        "inside one submission: Cork's credits run from 2023 (construction "
        "waste) to 2025 (living wage, investment), Berkeley's from 2023 to "
        "2024. Only TU Dublin is uniform, at 2023. Any single period stated for "
        "a GRI report built on this data would be wrong for some of its "
        "figures. GRI 2-3 also requires the reporting frequency, the "
        "publication date and a contact point; STARS collects none of these."),

    row("PRE-4", "List of personnel who led the reporting process",
        "GRI 2", "2-3", "partial", "low",
        "GRI 2-3-d requires a contact point for questions about the report. "
        "STARS names the people who led the reporting process, who are the "
        "nearest thing the submission designates.",
        "Named preparers are not a designated contact point: STARS records "
        "names and roles without contact details, and does not say who should "
        "receive enquiries."),

    row("PRE-3", "Full-time equivalent of employees", "GRI 2", "2-7",
        "partial", "medium",
        "GRI 2-7 asks for the total number of employees. STARS reports a "
        "full-time-equivalent employee count, which is the same population "
        "measured a different way.",
        "FTE is not a headcount: two half-time staff count as one. GRI 2-7 "
        "further requires the breakdown by employment contract (permanent / "
        "temporary), by employment type (full- / part-time), by gender and by "
        "region. STARS collects a single undifferentiated figure."),

    gap("GRI 2", "2-8",
        "GRI 2-8 requires the number of workers who are not employees but whose "
        "work is controlled by the organization, and their contractual "
        "relationship. STARS counts employees and students only. PA-13 counts "
        "'significant contractors' (45 at TU Dublin, 240 at Berkeley) but that "
        "is a count of contracting firms, not of the people working under them."),

    # 2-9: PA-3 is the strongest unmapped find in the whole dataset.
    row("PA-3", "Are one or more academic staff representatives included as members of the institution’s highest decision-making body?",
        "GRI 2", "2-9", "component", "high",
        "GRI 2-9-c-v requires the composition of the highest governance body to "
        "state the representation of stakeholders. STARS asks this of the same "
        "body — 'the institution's highest decision-making body' — for academic "
        "staff, and all three institutions answer it.",
        "GRI 2-9 also requires the number of executive and non-executive "
        "members, their independence, tenure, other significant positions held, "
        "and composition by gender and under-represented social group. STARS "
        "records only whether each constituency is represented."),

    row("PA-3", "Are one or more staff members representing non-managerial workers included as members of the institution’s highest decision-making body?",
        "GRI 2", "2-9", "component", "high",
        "GRI 2-9-c-v, for non-managerial workers on the highest governance "
        "body. This is the constituency GRI most often finds unrepresented, and "
        "STARS asks about it directly.",
        "See the caveat on the academic-staff row: representation is recorded, "
        "composition is not."),

    row("PA-3", "Are one or more student representatives included as members of the institution’s highest decision-making body?",
        "GRI 2", "2-9", "component", "high",
        "GRI 2-9-c-v, for students. Students have no corporate analogue, but "
        "they are unambiguously a stakeholder group represented on the "
        "governance body, which is what the disclosure asks for.",
        "See the caveat on the academic-staff row."),

    row("PA-3", "Narrative and/or website URL outlining academic staff representation on the institution’s highest decision-making body",
        "GRI 2", "2-9", "component", "medium",
        "The narrative names the highest decision-making body and describes how "
        "it is composed — GRI 2-9-a (governance structure) in prose rather than "
        "as a structured field.",
        "Free text of variable depth; it is not a substitute for the numeric "
        "composition GRI 2-9-c requires."),

    gap("GRI 2", "2-10",
        "GRI 2-10 requires the criteria and processes for nominating and "
        "selecting members of the highest governance body. STARS PA-3 records "
        "whether constituencies are represented and whether they hold voting "
        "rights, but nothing about how any member is nominated, selected or "
        "removed."),

    gap("GRI 2", "2-11",
        "GRI 2-11 asks whether the chair of the highest governance body is also "
        "a senior executive, and how conflicts are managed if so. STARS records "
        "no information about the chair."),

    gap("GRI 2", "2-12",
        "GRI 2-12 requires the role of the highest governance body in "
        "overseeing due diligence, engaging stakeholders in it and reviewing "
        "its effectiveness. STARS PA-1 covers management-level sustainability "
        "coordination (mapped to 2-13) and PA-3 covers who sits on the "
        "governing body, but neither describes what that body does about "
        "impacts."),

    row("PA-1", "Does the institution have one or more sustainability officers?",
        "GRI 2", "2-13", "component", "high",
        "GRI 2-13-a asks whether the organization has appointed senior "
        "executives with responsibility for the management of impacts. A "
        "sustainability officer is that appointment.",
        "GRI 2-13-b also requires whether and how often those executives report "
        "to the highest governance body. STARS does not ask."),

    row("PA-1", "Is at least one of the institution’s sustainability committees, officers, or offices charged with coordinating various campus constituencies in the advancement of sustainability across the entire institution?",
        "GRI 2", "2-13", "component", "high",
        "GRI 2-13-a asks how responsibility for managing impacts is delegated "
        "across the organization. This field asks whether the delegation is "
        "institution-wide rather than confined to one unit, which is the "
        "substance of the requirement.",
        "See the caveat on the sustainability-officer row."),

    row("PA-1", "Narrative and/or website URL providing an overview of the institution’s sustainability officers",
        "GRI 2", "2-13", "component", "medium",
        "Describes who holds delegated responsibility and for what — GRI 2-13-a "
        "in prose. All three institutions populate it; TU Dublin additionally "
        "supplies the full job descriptions.",
        "Free text; the reporting line to the highest governance body is not "
        "consistently stated."),

    row("PRE-1", "Executive cover letter", "GRI 2", "2-14", "partial", "low",
        "GRI 2-14 asks whether the highest governance body reviews and approves "
        "the reported information. STARS requires a signed executive cover "
        "letter with every submission, which evidences senior-executive "
        "endorsement of the report.",
        "Endorsement by a senior executive is not review and approval by the "
        "highest governance body, and STARS records neither who approved the "
        "content nor whether material topics were reviewed. The field value is "
        "an attachment filename, so the letter's text is not in the dataset."),

    gap("GRI 2", "2-15",
        "GRI 2-15 requires the processes for preventing and mitigating "
        "conflicts of interest on the highest governance body, and whether "
        "cross-board membership, shareholding and related-party transactions "
        "are disclosed. STARS collects none of this."),

    gap("GRI 2", "2-16",
        "GRI 2-16 requires the total number and nature of critical concerns "
        "communicated to the highest governance body. STARS has no incident or "
        "escalation reporting of any kind."),

    gap("GRI 2", "2-17",
        "GRI 2-17 requires the measures taken to advance the collective "
        "knowledge of the highest governance body on sustainable development. "
        "STARS EN-3 covers sustainability training for staff and AC-5 covers "
        "sustainability literacy among students; neither is aimed at the "
        "governing body."),

    gap("GRI 2", "2-18",
        "GRI 2-18 requires the processes for evaluating the performance of the "
        "highest governance body, whether the evaluations are independent, and "
        "the actions taken in response. STARS does not ask."),

    gap("GRI 2", "2-19",
        "GRI 2-19 requires the remuneration policies for the highest governance "
        "body and senior executives — fixed and variable pay, sign-on bonuses, "
        "termination payments, clawbacks and retirement benefits. STARS PA-13 "
        "measures living-wage coverage across all employees, which is a "
        "different population and a different question."),

    gap("GRI 2", "2-20",
        "GRI 2-20 requires the process for determining remuneration, including "
        "whether an independent remuneration committee is involved and how "
        "stakeholder views on remuneration are taken into account. STARS does "
        "not ask."),

    row("PA-2", "Narrative detailing the institution’s guiding vision or goals for sustainability and the plan(s) in which they are published",
        "GRI 2", "2-22", "partial", "medium",
        "GRI 2-22 requires a statement on the relevance of sustainable "
        "development to the organization and its strategy. This field is the "
        "institution's published sustainability vision and the plans carrying "
        "it, which is that content.",
        "GRI 2-22 requires the statement to come from the highest governance "
        "body or the most senior executive. STARS records the institution's "
        "published vision without attributing it to a named signatory, so the "
        "authorship the disclosure turns on is absent."),

    row("PA-2", "Has the institution made a public commitment to sustainability, as evidenced by an external commitment or a published plan?",
        "GRI 2", "2-23", "component", "high",
        "GRI 2-23-a asks whether the organization has policy commitments for "
        "responsible business conduct. This field is that yes/no, evidenced by "
        "an external commitment or a published plan.",
        "GRI 2-23 specifically requires commitments to respect human rights, to "
        "the UN Guiding Principles and to due diligence. A sustainability "
        "commitment is broader and does not imply any of these."),

    row("PA-2", "Narrative and/or website URL outlining the institution’s external sustainability commitments that include a reporting requirement",
        "GRI 2", "2-23", "component", "high",
        "GRI 2-23-b-ii asks which authoritative intergovernmental instruments "
        "the commitments reference. This field lists the external commitments "
        "the institution has signed that carry a reporting obligation, which is "
        "where those instruments appear.",
        "STARS asks only for commitments carrying a reporting requirement, so "
        "commitments without one are out of scope of the field."),

    row("OP-9", "Does the institution have a published code of conduct to guide suppliers on the institution’s social and environmental expectations for them?",
        "GRI 2", "2-24", "component", "high",
        "GRI 2-24-a-iii asks how the organization implements its policy "
        "commitments through its business relationships. A published supplier "
        "code of conduct is the standard instrument for exactly that.",
        "GRI 2-24 also requires how responsibility is allocated internally and "
        "how the commitments are embedded in strategies and procedures."),

    row("EN-3", "Does the institution make available sustainability-focused training opportunities to non-academic staff on at least an annual basis?",
        "GRI 2", "2-24", "component", "medium",
        "GRI 2-24-b asks how the organization provides training on implementing "
        "its policy commitments. Annual sustainability training for staff is "
        "that training.",
        "STARS asks about non-academic staff only, and about sustainability "
        "training generally rather than training on the specific commitments."),

    row("PA-1", "Narrative outlining the activities and substantive accomplishments of the institution-wide coordinating body or officer during the previous three years",
        "GRI 2", "2-24", "partial", "medium",
        "GRI 2-24-a asks how the organization embeds its commitments across "
        "activities and business relationships. This narrative reports what the "
        "coordinating body actually did over three years, which is evidence of "
        "embedding rather than a description of the mechanism.",
        "It describes outcomes, not the allocation of responsibility, the "
        "integration into procedures, or the handling of commitments through "
        "business relationships that GRI 2-24-a enumerates."),

    row("PA-12", "Does the institution publish information on grievance resolution in a format that is accessible to all employees?",
        "GRI 2", "2-25", "partial", "medium",
        "GRI 2-25-c asks about the grievance mechanisms through which "
        "stakeholders can raise concerns and seek remedy. STARS records whether "
        "grievance-resolution information is published accessibly to employees.",
        "STARS records only that the information is published — not how the "
        "mechanism operates, who may use it, or its effectiveness — and covers "
        "employees only, where GRI 2-25 covers all affected stakeholders."),

    row("PA-12", "Does the institution publish information on whistleblower protections in a format that is accessible to all employees?",
        "GRI 2", "2-26", "component", "high",
        "GRI 2-26 names whistleblowing mechanisms as a central example of the "
        "mechanisms for raising concerns about business conduct. STARS asks "
        "whether whistleblower protections are published accessibly.",
        "STARS records publication, not a description of how the mechanism "
        "operates, and covers employees only. GRI 2-26 extends to all "
        "individuals, including those in business relationships."),

    row("PA-12", "Narrative and/or website URL providing an overview of the institution’s published measures to protect employee rights",
        "GRI 2", "2-26", "component", "medium",
        "GRI 2-26-a asks the organization to describe the mechanisms for "
        "seeking advice and raising concerns. This narrative describes the "
        "published measures, which is that description for the employee "
        "population.",
        "Employees only; see the caveat on the whistleblower row."),

    gap("GRI 2", "2-27",
        "GRI 2-27 requires the number of significant instances of "
        "non-compliance with laws and regulations, fines incurred and their "
        "monetary value. STARS collects no compliance or enforcement data. The "
        "only nearby field is OP-6's three-year question about the extent of "
        "the institution's emissions-reduction activity, which is unrelated."),

    row("PA-2", "Narrative and/or website URL outlining the institution’s external sustainability commitments that include a reporting requirement",
        "GRI 2", "2-28", "partial", "low",
        "GRI 2-28 requires the industry associations and national or "
        "international advocacy organizations in which the organization "
        "participates significantly. The external-commitments narrative names "
        "the charters, networks and frameworks the institution has signed, "
        "which overlaps that list.",
        "Signing a charter is not membership of an association, and STARS "
        "restricts the field to commitments carrying a reporting requirement. "
        "The institution's association memberships are not collected as such."),

    row("PA-3", "Description of other mechanisms used to consult students on institutional decisions, plans, or policies",
        "GRI 2", "2-29", "component", "high",
        "GRI 2-29-a requires the approach to engaging stakeholders, including "
        "the purpose of the engagement. This field describes the consultation "
        "mechanisms for students — the institution's largest stakeholder group.",
        "GRI 2-29 also asks how stakeholders are identified and how the "
        "organization ensures the engagement is meaningful. STARS asks about "
        "four fixed constituencies and does not cover suppliers, customers or "
        "vulnerable groups."),

    row("PA-3", "Description of other mechanisms used to consult academic staff on institutional decisions, plans, or policies",
        "GRI 2", "2-29", "component", "high",
        "GRI 2-29-a, for academic staff.",
        "See the caveat on the student-consultation row."),

    row("PA-3", "Narrative and/or website URL outlining the ad hoc mechanisms used during the previous three years to consult local community members on institutional decisions, plans, or policies",
        "GRI 2", "2-29", "component", "high",
        "GRI 2-29-a, for the local community — the one stakeholder category "
        "here that is external to the institution.",
        "See the caveat on the student-consultation row."),

    row("PA-3", "Does the institution have one or more ongoing bodies through which local community-based organizations not affiliated with the institution can democratically participate in its governance?",
        "GRI 2", "2-29", "component", "medium",
        "GRI 2-29-a distinguishes ongoing engagement from one-off consultation. "
        "This field records whether unaffiliated community organizations have a "
        "standing route into governance, which is the stronger form.",
        "See the caveat on the student-consultation row."),

    gap("GRI 2", "2-30",
        "GRI 2-30 requires the percentage of total employees covered by "
        "collective bargaining agreements. STARS has no such percentage. PA-12 "
        "records whether freedom-of-association information is published, and "
        "PA-13 records the percentage of significant *contractors* paying a "
        "collectively determined or living wage — a different population and a "
        "measure of wage level rather than of bargaining coverage."),
]

# --------------------------------------------------------------------------
# Topic standards the first pass left partly or wholly unmapped.
# --------------------------------------------------------------------------
TOPICS = [
    # --- GRI 204 -----------------------------------------------------------
    gap("GRI 204", "204-1",
        "GRI 204-1 requires the percentage of the procurement budget spent with "
        "suppliers local to significant locations of operation. STARS OP-9 "
        "measures spend with 'social impact suppliers' — social enterprises and "
        "community-benefit businesses — where the qualifying criterion is "
        "social purpose, not locality. The two cannot be substituted: a social "
        "enterprise may be national and a local supplier need not be one."),

    # --- GRI 301: no product, no subject ------------------------------------
    gap("GRI 301", "301-1",
        "GRI 301-1 requires the weight or volume of materials used to produce "
        "and package the organization's primary products. A university produces "
        "no physical product, so the disclosure has no subject. STARS OP-11 "
        "Materials Management covers hazardous waste, surplus and reuse "
        "programmes, which belong to GRI 306, not GRI 301.",
        "This is a sector-fit finding of the same kind as AC-1 and EN-1 on the "
        "STARS side: the framework and the institution type do not line up."),

    gap("GRI 301", "301-2",
        "GRI 301-2 requires the percentage of recycled input materials used to "
        "manufacture the organization's products. No products, no input "
        "materials — see 301-1."),

    gap("GRI 301", "301-3",
        "GRI 301-3 requires the percentage of sold products and their packaging "
        "reclaimed at end of life. No products — see 301-1."),

    # --- GRI 302: two genuine components the numeric pass missed ------------
    row("OP-5", "Total heating and cooling from off-site sources",
        "GRI 302", "302-1", "component", "high",
        "GRI 302-1-c requires purchased electricity, heating, cooling and steam "
        "consumed. The first pass mapped electricity and stationary fuel but "
        "not this field, which is the purchased heating and cooling term.",
        "GRI 302-1 requires joules; STARS reports MMBtu or MWh, so the value "
        "must be converted before it is cited as a GRI figure."),

    row("OP-5", "On-site renewable electricity exported",
        "GRI 302", "302-1", "component", "medium",
        "GRI 302-1-d requires electricity, heating, cooling and steam sold. "
        "Exported on-site renewable electricity is that term.",
        "Zero for all three institutions in the current reporting year, so the "
        "mapping is correct but currently carries no signal."),

    gap("GRI 302", "302-2",
        "GRI 302-2 requires energy consumed outside the organization — the "
        "upstream and downstream energy of the value chain. STARS OP-5 measures "
        "energy consumed inside the institutional boundary only; purchased "
        "heating and cooling, which might look like an outside term, is "
        "classified by GRI under 302-1-c."),

    gap("GRI 302", "302-4",
        "GRI 302-4 requires the amount of energy reduction achieved, in joules, "
        "against a stated base year and methodology. OP-6 carries a percentage "
        "reduction for GHG emissions but OP-5 has no equivalent field for "
        "energy: the credit reports the performance year only, with no baseline "
        "and no reduction figure."),

    gap("GRI 302", "302-5",
        "GRI 302-5 requires reductions in the energy requirements of sold "
        "products and services. A university sells no such products — see "
        "301-1."),

    # --- GRI 303 ------------------------------------------------------------
    row("OP-3", "Level of physical water quantity risk for the institution’s main campus",
        "GRI 303", "303-1", "partial", "medium",
        "GRI 303-1 requires a description of how the organization interacts "
        "with water and of the water-related impacts it faces, and directs "
        "reporters to identify areas with water stress. STARS grades the "
        "physical water-quantity risk of the main campus on a fixed scale, "
        "which is that identification in categorical form.",
        "A risk grade is not the description GRI 303-1 asks for: it says "
        "nothing about how water is withdrawn, consumed or discharged, how the "
        "impacts were identified, or how the institution works with "
        "stakeholders on shared water resources. It also covers the main campus "
        "only, where a multi-campus institution has several."),

    row("OP-3", "Does the institution harvest rainwater on-site for storage and use?",
        "GRI 303", "303-1", "component", "medium",
        "GRI 303-1-a asks how and from where water is withdrawn. On-site "
        "rainwater harvesting is a withdrawal source distinct from the "
        "municipal supply, and STARS records it separately.",
        "Only one of the three institutions quantifies the volume harvested; "
        "the other two answer the yes/no only."),

    gap("GRI 303", "303-2",
        "GRI 303-2 requires the minimum standards set for the quality of "
        "effluent discharge and how they were determined. STARS OP-3 measures "
        "water withdrawal and on-site recovery, and OP-2's water-performance "
        "standards concern building efficiency, not effluent quality. No "
        "discharge-quality data exists."),

    # --- GRI 306 ------------------------------------------------------------
    gap("GRI 306", "306-1",
        "GRI 306-1 requires a description of the inputs, activities and outputs "
        "that lead to waste-related impacts, and whether those impacts arise in "
        "the organization's own activities or up- or downstream. STARS OP-12 "
        "reports tonnages and diversion rates but no process description, and "
        "OP-11 describes programmes rather than the material flows that cause "
        "the waste."),

    row("OP-11", "Does the institution have a surplus program through which institution-owned items that are no longer needed are stored for eventual sale, donation, or reuse?",
        "GRI 306", "306-2", "component", "high",
        "GRI 306-2-a requires the actions taken to prevent waste generation, "
        "explicitly including circularity measures. A surplus programme that "
        "routes redundant assets to sale, donation or reuse is a circularity "
        "measure in the sense the disclosure uses."),

    row("OP-11", "Does the institution have or participate in a reuse program through which employees and/or students can donate personal items for redistribution?",
        "GRI 306", "306-2", "component", "high",
        "GRI 306-2-a, for personal items. Redistribution prevents the waste "
        "from being generated rather than diverting it after the fact."),

    row("OP-11", "Has the institution eliminated the on-site use of at least one form of single-use disposable plastic?",
        "GRI 306", "306-2", "component", "high",
        "GRI 306-2-a, as a prevention measure at source — the clearest "
        "waste-prevention action STARS records."),

    row("OP-11", "Does the institution have a hazardous waste management program or protocol that includes measures to minimize or reduce the use of hazardous materials?",
        "GRI 306", "306-2", "component", "high",
        "GRI 306-2-a covers managing significant impacts from waste generated. "
        "Hazardous waste is the highest-impact stream a research university "
        "produces, and STARS asks whether a minimisation protocol exists.",
        "GRI 306-3 additionally requires hazardous waste to be quantified "
        "separately from non-hazardous. STARS quantifies only non-hazardous and "
        "construction-and-demolition waste, so the tonnage is unavailable."),

    row("OP-11", "Narrative and/or website URL providing an overview of the institution’s composting program",
        "GRI 306", "306-2", "component", "medium",
        "GRI 306-2-a, describing a recovery route operated for organic waste."),

    row("OP-12", "Does the institution have sufficient data on construction and demolition waste to pursue this indicator?",
        "GRI 306", "306-2", "component", "medium",
        "GRI 306-2-c requires the processes used to collect and monitor "
        "waste-related data. This field is STARS' own statement of whether the "
        "institution's waste data collection is adequate for the stream.",
        "It states data sufficiency as a yes/no rather than describing the "
        "collection process, and covers construction and demolition waste only."),

    # --- GRI 308 ------------------------------------------------------------
    row("OP-9", "Does the institution’s supplier code of conduct include one or more expectations in regard to environmental impact that exceed or are additional to regulatory compliance?",
        "GRI 308", "308-1", "partial", "medium",
        "GRI 308-1 measures whether new suppliers are screened using "
        "environmental criteria. STARS records whether the supplier code of "
        "conduct sets environmental expectations beyond legal compliance, which "
        "is the criterion such screening would apply.",
        "GRI 308-1 requires a percentage of new suppliers actually screened. "
        "STARS reports the existence of the criteria, not their application to "
        "any supplier, so no percentage can be derived."),

    row("OP-9", "Percentage of bid solicitations that identify supplier sustainability considerations",
        "GRI 308", "308-1", "partial", "medium",
        "This is the closest STARS comes to a screening rate: the share of bid "
        "solicitations that put supplier sustainability into the appraisal.",
        "The denominator is bid solicitations, not new suppliers, and one "
        "solicitation may attract many suppliers or none. 'Sustainability "
        "considerations' is also broader than the environmental criteria GRI "
        "308-1 specifies. The figure is 0 percent at TU Dublin, so a low value "
        "here should not be read as a screening failure without checking the "
        "product-specification field alongside it."),

    gap("GRI 308", "308-2",
        "GRI 308-2 requires the number of suppliers assessed for environmental "
        "impacts, how many were found to have actual or potential negative "
        "impacts, how many agreed improvements and how many relationships were "
        "terminated. STARS collects no supplier-level assessment outcomes at "
        "all."),

    # --- GRI 401 ------------------------------------------------------------
    row("PA-12", "Percentage of employees eligible for paid all-gender family/medical leave",
        "GRI 401", "401-2", "partial", "medium",
        "GRI 401-2 requires the benefits provided to full-time employees, "
        "naming parental leave among them. STARS reports the share of employees "
        "eligible for paid family and medical leave.",
        "GRI 401-2 turns on the contrast between full-time employees and "
        "temporary or part-time employees, and asks for the benefits by "
        "significant location of operation. STARS gives a single institution-"
        "wide eligibility rate with no employment-type split, so the comparison "
        "the disclosure exists to make cannot be drawn."),

    row("PA-12", "Number of weeks of paid maternity leave", "GRI 401", "401-3",
        "partial", "medium",
        "GRI 401-3 is the parental-leave disclosure. STARS reports the duration "
        "of paid maternity leave, which is the entitlement's substance.",
        "GRI 401-3 requires headcounts by gender: employees entitled to "
        "parental leave, those who took it, those who returned, those still "
        "employed twelve months later, and the resulting return-to-work and "
        "retention rates. STARS reports none of these — it reports the policy, "
        "not its uptake. 'Maternity' is also narrower than GRI's 'parental'."),

    row("PA-12", "Narrative and/or website URL providing an overview of the maternity leave options available to employees",
        "GRI 401", "401-3", "partial", "medium",
        "Describes the parental-leave entitlement and its conditions in prose.",
        "Descriptive only; supplies none of the headcounts or rates GRI 401-3 "
        "requires."),

    # --- GRI 403: PA-11 turns out to answer far more than the first pass saw -
    row("PA-11", "Narrative and/or website URL providing an overview of the institution’s workplace health and safety committees",
        "GRI 403", "403-1", "partial", "low",
        "GRI 403-1-a requires a statement of whether an occupational health and "
        "safety management system has been implemented. STARS asks about "
        "committees rather than the system, but the narratives supplied in "
        "practice describe the institution's safety management system.",
        "STARS never asks the 403-1 question, so an answer only appears where "
        "the institution volunteered it. Nothing records whether the system "
        "exists because of a legal requirement, which standard it follows, or "
        "which workers, activities and workplaces it covers — that is 403-1-b, "
        "and it is absent."),

    gap("GRI 403", "403-2",
        "GRI 403-2 requires the processes for hazard identification, risk "
        "assessment and incident investigation, and how workers can remove "
        "themselves from dangerous situations. STARS PA-11 records the "
        "existence of committees and of health services, but no hazard or "
        "incident process."),

    row("PA-11", "Does the institution make physical health services available to employees?",
        "GRI 403", "403-3", "partial", "low",
        "GRI 403-3 requires a description of the occupational health services' "
        "functions. STARS records whether physical health services are "
        "available to employees, and the narratives sometimes mention "
        "occupational health assessments within them.",
        "General employee health services are not occupational health services: "
        "GRI 403-3 is about the function that identifies and eliminates "
        "workplace hazards, and about how worker health data is kept "
        "confidential. STARS asks about neither."),

    row("PA-11", "Does the institution have an institution-wide health and safety committee or network of committees that brings together workers and management in the development and review of workplace health and safety policies and procedures?",
        "GRI 403", "403-4", "component", "high",
        "GRI 403-4-b concerns formal joint management-worker health and safety "
        "committees. STARS asks whether exactly such a committee exists, in "
        "almost the same words, and all three institutions answer it.",
        "GRI 403-4-b further requires the committee's responsibilities, meeting "
        "frequency, decision-making authority, and whether any workers are "
        "unrepresented. STARS records existence only."),

    row("PA-11", "Narrative and/or website URL providing an overview of the institution’s workplace health and safety committees",
        "GRI 403", "403-4", "component", "high",
        "The narrative describes how the committee is constituted and what it "
        "does — the detail GRI 403-4-b asks for, in free text.",
        "Depth varies by institution; meeting frequency and decision-making "
        "authority are not consistently stated."),

    gap("GRI 403", "403-5",
        "GRI 403-5 requires a description of occupational health and safety "
        "training provided to workers. STARS EN-3 covers sustainability-focused "
        "staff training and PA-11 covers health services, but no credit asks "
        "about health and safety training."),

    row("PA-11", "Does the institution make physical health services available to employees?",
        "GRI 403", "403-6", "component", "high",
        "GRI 403-6-a asks how the organization facilitates workers' access to "
        "non-occupational medical and healthcare services. This is that "
        "access, asked of employees.",
        "GRI 403-6-a also requires the scope of access provided; STARS records "
        "availability as a yes/no, with the scope left to the narrative."),

    row("PA-11", "Does the institution make behavioral health services available to employees?",
        "GRI 403", "403-6", "component", "high",
        "GRI 403-6-a, for mental and behavioural health — the non-occupational "
        "service GRI most often finds unreported."),

    row("PA-11", "Does the institution make free or reduced cost fitness activities available to employees?",
        "GRI 403", "403-6", "component", "high",
        "GRI 403-6-b requires the voluntary health promotion services offered "
        "to workers to address major non-work-related health risks. Subsidised "
        "fitness provision is a textbook example."),

    row("PA-11", "Does the institution prohibit smoking and tobacco use across the entire campus?",
        "GRI 403", "403-6", "component", "high",
        "GRI 403-6-b requires the specific non-work-related health risks "
        "addressed. Tobacco is the canonical one, and STARS records the "
        "institution-wide prohibition.",
        "A prohibition is a control rather than a voluntary promotion service; "
        "STARS also records the weaker variants (indoor-only, restricted "
        "outdoor smoking) in separate fields."),

    row("PA-11", "Does the institution make contemplative and/or spiritual activities available to employees?",
        "GRI 403", "403-6", "component", "medium",
        "GRI 403-6-b, as a voluntary health-promotion offering addressing "
        "stress and mental wellbeing."),

    gap("GRI 403", "403-7",
        "GRI 403-7 requires the approach to preventing occupational health and "
        "safety impacts directly linked to the organization through its "
        "business relationships. STARS PA-11 covers the institution's own "
        "workforce and students; OP-9's supplier code of conduct touches worker "
        "treatment but records no health-and-safety expectation or its "
        "enforcement."),

    gap("GRI 403", "403-8",
        "GRI 403-8 requires the number and percentage of workers covered by an "
        "occupational health and safety management system, split by whether the "
        "system is internally audited or externally certified. STARS records "
        "whether a safety committee exists but counts no covered workers, so no "
        "percentage can be produced. This sits alongside 403-9 and 403-10: "
        "PA-11 is named 'Health, Safety and Wellbeing' and contains no numeric "
        "health or safety data at all."),
]

# --------------------------------------------------------------------------
# Third pass, 2026-08-22 — GRI 405-1-b, found by the external review.
#
# 405-1 has two halves and the first pass only tried the first one:
#
#   405-1-a  percentage of individuals within the GOVERNANCE BODIES, by gender,
#            age group, and other diversity indicators
#   405-1-b  percentage of EMPLOYEES PER EMPLOYEE CATEGORY, same three splits
#
# Two rows existed, both pointing at executive staff, and both caveated as
# "executive staff is not GRI's governance bodies". True — but that is an
# objection to 405-1-a, and nobody checked 405-1-b, where "executive staff" is
# a perfectly ordinary employee category. Meanwhile academic and non-academic
# staff, which are also employee categories, sat unmapped with populated values
# for all three universities.
#
# One caveat gave the wrong reason outright: "GRI counts employees by category
# whereas STARS also reports students, who are outside GRI's scope." That is
# true of the STUDENT rows, which are correctly left unmapped, and says nothing
# about the staff rows it was attached to.
#
# 405-1-a remains genuinely unanswered: PA-3 records WHICH constituencies sit on
# the highest decision-making body, never what percentage of it they are. That
# belongs in the caveats, not in a gap row — a disclosure with usable rows
# cannot also carry one.
# --------------------------------------------------------------------------

AGE_GAP = ("No STARS credit collects employee age at all, so GRI 405-1's "
           "age-group split (under 30 / 30-50 / over 50) is unanswerable for "
           "every employee category.")
BODY_GAP = ("405-1-a is still not answered: STARS PA-3 records which "
            "constituencies are represented on the highest decision-making "
            "body, never what percentage of that body they make up.")
GENDER_BUCKET = ("STARS reports one combined figure for 'women or other "
                 "marginalized gender identities' rather than a percentage per "
                 "gender, so the split GRI asks for is two buckets, not three.")
INDEX_NOT_PERCENT = ("This is a diversity INDEX (a single 0-1 concentration "
                     "score), not the percentage breakdown GRI 405-1-b asks "
                     "for. It shows how mixed the group is, not what share each "
                     "group holds.")
TUD_UNPARSEABLE = ("DATA QUALITY: TU Dublin's value is the string '0 Revised on "
                   "Nov. 24, 2025' — annotation text concatenated onto the "
                   "figure — so the field is typed `text`, not `number`, and "
                   "will not parse. Cork and Berkeley are clean.")

# GRI 303-3 says "megaliters" three times in its requirement text. STARS reports
# cubic meters — a factor of 1,000. The project already flags the identical
# problem on GRI 302-1 ("STARS reports megawatt-hours - convertible, but state
# the conversion"), so the omission here was inconsistency rather than a
# judgement. No figure is wrong; the disclosure is simply not in GRI's unit.
ML_CONVERSION = ("UNITS: GRI 303-3 requires megaliters and STARS reports cubic "
                 "meters. Divide by 1,000 before citing the figure as a GRI "
                 "303-3 value, and state the conversion — the same treatment "
                 "GRI 302-1 gets for megawatt-hours against joules.")

# GRI 306-3/4/5 all rest on the same limitation — STARS collects non-hazardous
# waste only, and holds no hazardous TONNAGE anywhere (OP-11 has a programme
# boolean and narratives, nothing weighed). But the three disclosures are not
# structured alike, which is why they do not all take the same label:
#
#   306-3-a  Total weight of waste generated.        <- one requirement, ALL waste.
#            There is no non-hazardous sub-requirement, so the STARS figure
#            answers nothing exactly -> `partial`, and it stays that way.
#
#   306-4-c  Total weight of NON-HAZARDOUS waste diverted from disposal,
#            broken down by preparation for reuse / recycling / other recovery.
#            Word for word the STARS field, and STARS supplies all three
#            recovery operations -> a required PART is answered exactly.
#
#   306-5-c  Same shape for waste directed to disposal.
#
# So `equivalent` overclaimed — it means "answers the disclosure as written",
# and neither 306-4 nor 306-5 is answered while the hazardous half is missing.
# `partial` would underclaim, because 306-4-c IS satisfied. `component` is the
# project's own word for "supplies one required part of a multi-part
# disclosure", which is precisely the situation. Chosen by Hakim 2026-08-22
# after the three options were laid out.
HAZARDOUS_GAP = ("NOT THE WHOLE DISCLOSURE: the hazardous half is absent. STARS "
                 "weighs no hazardous waste anywhere — OP-11 records only "
                 "whether a hazardous-waste programme exists and describes it "
                 "in prose. For a research university that is a materially "
                 "significant stream going unreported, and it is a finding "
                 "about STARS rather than about these institutions.")

# The two original 202-1 caveats both asserted "The GRI ratio cannot be derived
# from STARS at all." That is overstated, and the second review was right to
# call it: PA-13's wage floor IS the standard entry-level wage, so the numerator
# is present. What is absent is the local statutory minimum wage — an external
# figure STARS never collects — and the gender split, which is genuinely
# unanswerable. Saying "impossible" when the honest answer is "one external
# constant away, plus an unfixable gender gap" understates the project's own
# data and is the kind of claim an examiner can disprove in one grep.
WAGE_RATIO_TRUTH = (
    "DOES NOT SATISFY GRI 202-1. GRI wants the RATIO of standard entry-level "
    "wage to the local MINIMUM wage, BY GENDER. STARS benchmarks against a "
    "LIVING wage instead and has no gender split. Precisely: the NUMERATOR "
    "exists — PA-13's `Wage floor for regular/permanent employees` is the "
    "entry-level wage — but the local statutory minimum wage is not in STARS at "
    "any credit, and the gender split is not collected anywhere. Report only as "
    "a higher-education sector variant, stating plainly that 202-1 is "
    "unsatisfied. Values are bare numbers with no currency - EUR for the Irish "
    "universities, USD for Berkeley - and are not comparable across them "
    "without saying so.")

# (stars_credit, stars_field, gri_disclosure) -> the columns to overwrite.
AMENDMENTS = {
    ("PA-13",
     "Percentage of employees that receive remuneration equivalent to at least a living wage",
     "202-1"): {
        "caveat": WAGE_RATIO_TRUTH,
        "claude_verdict": "amend",
        "claude_note":
            "Corrected 2026-08-29. The caveat said the GRI ratio 'cannot be "
            "derived from STARS at all'; the numerator is present and only the "
            "minimum-wage denominator and the gender split are missing.",
        "reviewed_date": "2026-08-29",
    },
    ("PA-13", "Living wage", "202-1"): {
        "caveat": WAGE_RATIO_TRUTH,
        "claude_verdict": "amend",
        "claude_note":
            "Corrected 2026-08-29, same as the coverage-percentage row.",
        "reviewed_date": "2026-08-29",
    },
    # This caveat cross-referenced the two rows below and was not updated when
    # they were downgraded on the same day. It shipped: the sentence "the 306-4
    # and 306-5 rows ARE equivalent" printed verbatim in all three content
    # indexes and went, redacted, into every narrative prompt — the deliverable
    # telling its reader something false about the project's own mapping.
    # Amending a row is not finished until you have grepped for rows that
    # mention it.
    ("OP-12", "Annual non-hazardous waste generated", "306-3"): {
        "caveat":
            "NOT EQUIVALENT - a subset. GRI 306-3-a is TOTAL waste generated "
            "including hazardous, broken down by composition. STARS reports "
            "non-hazardous only and collects no hazardous tonnage at any "
            "credit, so 306-3 cannot be fully satisfied. Do not present "
            "non-hazardous waste as the organisation's total waste. (Contrast "
            "the 306-4 and 306-5 rows, which are `component`: GRI has explicit "
            "non-hazardous lines at 306-4-c and 306-5-c for the STARS figures "
            "to answer, whereas 306-3 has no non-hazardous sub-requirement at "
            "all — which is why this row is weaker than those two, not equal "
            "to them.)",
        "claude_verdict": "amend",
        "claude_note":
            "Corrected 2026-08-23. The sentence still said 306-4 and 306-5 "
            "'ARE equivalent' after commit 5070f0b downgraded both to "
            "`component`. Found by the second external review; it had been "
            "shipping in all three content indexes.",
        "reviewed_date": "2026-08-23",
    },
    ("OP-12", "Total non-hazardous waste diverted from disposal", "306-4"): {
        "relationship": "component",
        "confidence": "high",
        "rationale":
            "GRI 306-4-c is literally 'Total weight of non-hazardous waste "
            "diverted from disposal'. STARS supplies that figure and all three "
            "of the recovery operations GRI names for it, so one required part "
            "of 306-4 is answered exactly.",
        "caveat":
            "Exact scope match on GRI 306-4-c, including its split by recovery "
            "operation (reuse / recycling / other) from the rows below. GRI "
            "306-4-d additionally wants each operation split on-site vs "
            f"off-site, which STARS does not collect. {HAZARDOUS_GAP}",
        "claude_verdict": "amend",
        "claude_note":
            "Downgraded equivalent -> component 2026-08-22. `equivalent` means "
            "'answers the disclosure as written' and 306-4 is not answered "
            "while 306-4-b is empty. `partial` would have been wrong in the "
            "other direction — 306-4-c is satisfied exactly. `component` is the "
            "defined word for a required part. 306-3 stays `partial` because "
            "GRI 306-3 has no non-hazardous sub-requirement to satisfy, which "
            "is what makes the two labels different rather than inconsistent.",
        "reviewed_date": REVIEWED,
    },
    ("OP-12", "Non-hazardous waste disposed of to a landfill or incinerator",
     "306-5"): {
        "relationship": "component",
        "confidence": "medium",
        "rationale":
            "GRI 306-5-c is the total weight of non-hazardous waste directed to "
            "disposal. STARS supplies that total, so one required part of "
            "306-5 is answered.",
        "caveat":
            "WEAKER THAN THE 306-4 EQUIVALENT: GRI 306-5-c also requires the "
            "total split across four disposal operations — incineration with "
            "energy recovery, incineration without, landfilling, other — and "
            "STARS merges landfill and incineration into a single figure. The "
            "waste-to-energy percentage field would separate incineration with "
            "recovery, but only two of the three institutions report it, so "
            f"the split cannot be derived consistently. {HAZARDOUS_GAP}",
        "claude_verdict": "amend",
        "claude_note":
            "Downgraded equivalent -> component 2026-08-22, same reasoning as "
            "306-4. Weaker than that row: 306-4-c's recovery-operation split IS "
            "available from STARS, 306-5-c's disposal-operation split is not.",
        "reviewed_date": REVIEWED,
    },
    ("OP-3", "Total water withdrawal", "303-3"): {
        "caveat":
            "GRI 303-3 requires a breakdown by source AND a separate figure for "
            "areas with water stress. STARS collects neither, so 303-3 cannot "
            f"be fully satisfied from STARS alone. {ML_CONVERSION}",
        "claude_verdict": "amend",
        "claude_note":
            "Unit caveat added 2026-08-22 after an external review noted that "
            "all three 303-3 rows were silent on megaliters vs cubic meters "
            "while the analogous 302-1 mismatch was flagged.",
        "reviewed_date": REVIEWED,
    },
    ("OP-3", "Potable water from off-site sources", "303-3"): {
        "caveat":
            "Maps to the specific GRI 303-3-a-v category 'Third-party water'. "
            "It is the ONLY withdrawal source these universities have — on-site "
            "abstraction is zero for all three — so this equals the total. "
            f"{ML_CONVERSION}",
        "claude_verdict": "amend",
        "claude_note": "Unit caveat added 2026-08-22; see the total-withdrawal row.",
        "reviewed_date": REVIEWED,
    },
    ("OP-3", "Potable water from on-site sources", "303-3"): {
        "caveat":
            "Zero for all three institutions, which is itself the finding: "
            "none of them abstracts its own water. Retained so the GRI 303-3 "
            f"source breakdown is complete rather than silent. {ML_CONVERSION}",
        "claude_verdict": "amend",
        "claude_note":
            "Had no caveat at all before 2026-08-22. Unit conversion added, "
            "plus a note that the zero is meaningful rather than missing.",
        "reviewed_date": REVIEWED,
    },
    ("PA-8",
     "Percentage of executive staff that identify as women or other marginalized gender identities",
     "405-1"): {
        "relationship": "component",
        "confidence": "high",
        "rationale":
            "GRI 405-1-b requires the percentage of employees per employee "
            "category by gender. Executive staff is an employee category and "
            "this is that percentage for it.",
        "caveat": f"{GENDER_BUCKET} {AGE_GAP} {BODY_GAP}",
        "claude_verdict": "amend",
        "claude_note":
            "REFRAMED 2026-08-22. Was `partial` against 405-1-a with the caveat "
            "'executive staff is not GRI governance bodies'. That objection is "
            "sound for 405-1-a and irrelevant to 405-1-b, which is the half "
            "this field actually answers. The old caveat also blamed STARS for "
            "reporting students — true of the student row, which stays "
            "unmapped, and nothing to do with this one.",
        "reviewed_date": REVIEWED,
    },
    ("PA-7", "Ethnic diversity index for executive staff", "405-1"): {
        "relationship": "partial",
        "confidence": "medium",
        "rationale":
            "GRI 405-1-b-iii asks for other indicators of diversity per "
            "employee category. STARS supplies an ethnic diversity index for "
            "executive staff.",
        "caveat": f"{INDEX_NOT_PERCENT} {AGE_GAP} {BODY_GAP} {TUD_UNPARSEABLE}",
        "claude_verdict": "amend",
        "claude_note":
            "REFRAMED 2026-08-22 from 405-1-a to 405-1-b, same reasoning as the "
            "PA-8 executive row. Stays `partial`, but now for the right reason: "
            "an index is not a percentage breakdown.",
        "reviewed_date": REVIEWED,
    },
}

EMPLOYEE_CATEGORIES = [
    row("PA-8",
        "Percentage of regular/permanent academic staff that identify as women or other marginalized gender identities",
        "GRI 405", "405-1", "component", "high",
        "GRI 405-1-b requires the percentage of employees per employee "
        "category by gender. Academic staff is the largest employee category "
        "at a university, and all three institutions populate this.",
        f"{GENDER_BUCKET} {AGE_GAP} {BODY_GAP}",
        "Found by the external review of 2026-08-22. Populated 3/3 and "
        "unmapped: the first pass looked only at executive staff."),

    row("PA-8",
        "Percentage of regular/permanent non-academic staff that identify as women or other marginalized gender identities",
        "GRI 405", "405-1", "component", "high",
        "GRI 405-1-b, for the professional-services employee category. "
        "Reporting it beside academic staff is what makes the disclosure "
        "meaningful — the two categories differ by roughly fifteen points at "
        "every institution.",
        f"{GENDER_BUCKET} {AGE_GAP} {BODY_GAP}",
        "Populated 3/3, unmapped before 2026-08-22."),

    row("PA-7", "Ethnic diversity index for academic staff",
        "GRI 405", "405-1", "partial", "medium",
        "GRI 405-1-b-iii, other indicators of diversity for the academic "
        "employee category.",
        f"{INDEX_NOT_PERCENT} {AGE_GAP} {BODY_GAP} {TUD_UNPARSEABLE}",
        "Cork 0.44, Berkeley 0.50; TU Dublin unparseable."),

    row("PA-7", "Ethnic diversity index for non-academic staff",
        "GRI 405", "405-1", "partial", "medium",
        "GRI 405-1-b-iii, for the professional-services employee category.",
        f"{INDEX_NOT_PERCENT} {AGE_GAP} {BODY_GAP} {TUD_UNPARSEABLE}",
        "Cork 0.34, Berkeley 0.69; TU Dublin unparseable."),
]

# Deliberately NOT mapped: `Ethnic diversity index for students` and
# `Percentage of students that identify as women…`. Students are not employees
# and not a governance body, so they fall outside 405-1 entirely. This is the
# objection the old executive-staff caveat was reaching for and misapplied.

# --------------------------------------------------------------------------
# Fourth pass, 2026-08-29 — GRI 3: Material Topics, found by the second review.
#
# GRI 3 is UNIVERSAL: every GRI report answers 3-1/3-2/3-3 whatever its topics,
# because they are the disclosures that decide which topic standards apply. It
# was absent from the vocabulary entirely, so a content index headed "with
# reference to the GRI Standards" never listed the questions that govern its own
# scope. §16's lesson one level up — that pass fixed the disclosures missing
# from the chosen standards and never asked whether the set of standards was
# complete.
#
# THE FINDING THIS PRODUCES IS THE POINT, and it is a good one for the report:
# **AASHE determined materiality for the higher-education sector; the
# institutions did not determine it for themselves.** A STARS submission answers
# a fixed credit set decided by the framework. GRI assumes the organisation
# identifies its own impacts, prioritises them, and says who informed that
# process. Neither the process (3-1) nor a declared list (3-2) exists in STARS,
# and no amount of data extraction will produce them — this is a structural
# difference between a scoring scheme and a disclosure standard, the same family
# of finding as GRI having no vocabulary for courses taught.
# --------------------------------------------------------------------------

NO_TOPIC_LIST = ("Asked per material topic, and no material-topics list exists "
                 "(see GRI 3-2) — so these are institution-wide answers to a "
                 "question GRI asks topic by topic.")

MATERIAL_TOPICS = [
    gap("GRI 3", "3-1",
        "GRI 3-1 requires the organisation to describe the process by which it "
        "determined its material topics: how it identified actual and potential "
        "impacts on the economy, environment and people, how it prioritised "
        "them, and which stakeholders and experts informed that. STARS contains "
        "no materiality assessment of any kind.",
        "This is a structural difference, not missing data. AASHE determined "
        "materiality for the whole higher-education sector when it designed the "
        "STARS credit set; the institution answers that fixed set rather than "
        "identifying its own impacts. PA-2 records a climate-vulnerability "
        "assessment and PA-3 records stakeholder consultation, but neither is a "
        "materiality process and neither should be presented as one."),

    row("PA-2", "Has the institution adopted one or more measurable sustainability objectives that address campus operations?",
        "GRI 3", "3-2", "partial", "low",
        "GRI 3-2 requires a list of material topics. STARS has no such list, "
        "but the five areas in which an institution declares measurable "
        "sustainability objectives are the closest thing to a declared topic "
        "set that it publishes.",
        "NOT A MATERIALITY DETERMINATION. These five areas are fixed by STARS "
        "and identical for every institution, so they say where an institution "
        "has set objectives, not which impacts it judged significant and why. "
        "GRI 3-2-b also requires changes against the previous reporting period, "
        "which a single STARS submission cannot show. Presenting these as "
        "material topics would overstate what the institution actually did.",
        "The five objective areas are the nearest declared topic set in STARS."),

    row("PA-2", "Has the institution adopted one or more measurable sustainability objectives that address teaching, learning, and/or research?",
        "GRI 3", "3-2", "partial", "low",
        "GRI 3-2, for the teaching and research area — the one with no "
        "corporate analogue, and the reason a university's topic list cannot "
        "look like a company's.",
        "See the campus-operations row: fixed areas, not a materiality "
        "determination.",
        "Pairs with the AC-1 / AC-6 / EN-1 gap_stars_side rows: STARS collects "
        "teaching and research, GRI has no topic standard for either."),

    row("PA-2", "Has the institution adopted one or more measurable sustainability objectives that address racial equity and/or social justice?",
        "GRI 3", "3-2", "partial", "low",
        "GRI 3-2, for the racial-equity and social-justice area.",
        "See the campus-operations row: fixed areas, not a materiality "
        "determination."),

    row("PA-2", "Narrative listing the institution’s measurable sustainability objectives that address campus operations",
        "GRI 3", "3-3", "partial", "medium",
        "GRI 3-3-e-ii requires the goals, targets and indicators used to "
        "evaluate progress on a material topic. This narrative is exactly "
        "that, for the operations area.",
        f"{NO_TOPIC_LIST} GRI 3-3 also requires the impacts themselves "
        "(3-3-a), whether the organisation is involved through its own "
        "activities or its business relationships (3-3-b), and lessons learned "
        "(3-3-e-iv). STARS collects none of those."),

    row("PA-1", "Narrative outlining the activities and substantive accomplishments of the institution-wide coordinating body or officer during the previous three years",
        "GRI 3", "3-3", "partial", "medium",
        "GRI 3-3-d requires the actions taken to manage a topic and its "
        "impacts. This narrative reports what the coordinating body actually "
        "did over three years, which is that content.",
        f"{NO_TOPIC_LIST} It reports outcomes rather than distinguishing "
        "actions that prevent potential harm from actions that remediate "
        "actual harm, which is the split GRI 3-3-d asks for."),

    row("PA-2", "Has the institution made a public commitment to sustainability, as evidenced by an external commitment or a published plan?",
        "GRI 3", "3-3", "partial", "medium",
        "GRI 3-3-c requires the policies or commitments regarding the material "
        "topic. A public sustainability commitment evidenced by a published "
        "plan is that, at the institutional level.",
        NO_TOPIC_LIST),
]

# --------------------------------------------------------------------------
# Fifth pass, 2026-08-29 — the GRI 305 sub-requirements, found by the second
# review. Exactly the failure the FIRST review predicted would recur: 405-1's
# second half had gone unexamined, and it said a full read of the remaining rows
# would turn up more of the same. It did, in the most important disclosure in
# the report.
#
# GRI 305-1 asks for seven things. The first pass mapped 305-1-a (the gross
# figure) and its components, and never looked at d through g — the base year,
# the emissions in it, the rationale, the methodology. All four are in OP-6,
# populated for all three institutions, and were sitting unmapped. The 305-5 row
# even said in its own note that the baseline figure "is in the dataset", so
# whoever wrote it saw the field and mapped neither.
#
# A base year is not decoration. Without it an emissions section is a snapshot;
# with it the reader can see direction of travel, and 305-5-a's absolute
# reduction becomes derivable.
# --------------------------------------------------------------------------

COMBINED_SCOPES = ("STARS reports ONE baseline covering scope 1 and scope 2 "
                   "together. GRI states the base year separately for 305-1 and "
                   "305-2, so this figure serves both jointly and neither "
                   "alone — it cannot be split.")

GHG_305 = []
for _disc, _label in (("305-1", "Direct (Scope 1)"),
                      ("305-2", "Energy indirect (Scope 2)")):
    GHG_305 += [
        row("OP-6", "Baseline year for scope 1 and 2 GHG emissions",
            "GRI 305", _disc, "component", "high",
            f"GRI {_disc}-d requires the base year for the calculation. STARS "
            f"states it directly. ({_label} emissions.)",
            COMBINED_SCOPES,
            "Populated 3/3 — TU Dublin 2018, Cork 2017, Berkeley 2019 — and "
            "unmapped until 2026-08-29."),

        row("OP-6", "Baseline scope 1 and 2 GHG emissions",
            "GRI 305", _disc, "partial", "high",
            f"GRI {_disc}-d-ii requires the emissions in the base year. This is "
            f"that figure.",
            f"{COMBINED_SCOPES} So it answers 305-1-d-ii and 305-2-d-ii only as "
            "a combined total, which is weaker than either disclosure asks for "
            "on its own."),

        row("OP-6", "Narrative outlining when and why the GHG emissions baseline was adopted",
            "GRI 305", _disc, "component", "high",
            f"GRI {_disc}-d-i requires the rationale for choosing the base "
            "year, and -d-iii the context for any change that triggered a "
            "recalculation. This narrative is written to answer exactly that.",
            COMBINED_SCOPES),

        row("OP-6", "Description of the methodology or calculator used to conduct the scope 1 and 2 GHG emissions inventory",
            "GRI 305", _disc, "component", "high",
            f"GRI {_disc}-g requires the standards, methodologies, assumptions "
            "and calculation tools used. All three institutions name theirs — "
            "the GHG Protocol Corporate Standard, or a named contractor.",
            f"{COMBINED_SCOPES} GRI additionally requires the source of the "
            f"emission factors and GWP rates ({_disc}-e) and the consolidation "
            f"approach ({_disc}-f); STARS collects neither."),
    ]

GHG_305 += [
    row("OP-6", "Baseline scope 1 and 2 GHG emissions",
        "GRI 305", "305-5", "component", "high",
        "GRI 305-5-a requires the absolute reduction in metric tons of CO2 "
        "equivalent. STARS gives only a percentage — but with the baseline "
        "figure and the current total both in the dataset, THE ABSOLUTE "
        "REDUCTION IS DERIVABLE: baseline minus annual scope 1 and 2. That is a "
        "code-side subtraction of two verified values, not an LLM estimate.",
        "Derive it; do not present the baseline itself as a reduction. The "
        "subtraction is only valid because both figures cover the same combined "
        "scope 1 + 2 boundary."),

    row("OP-6", "Baseline year for scope 1 and 2 GHG emissions",
        "GRI 305", "305-5", "component", "high",
        "GRI 305-5-c requires the base year or baseline against which the "
        "reduction is measured.",
        COMBINED_SCOPES),

    row("OP-6", "Narrative outlining when and why the GHG emissions baseline was adopted",
        "GRI 305", "305-5", "component", "medium",
        "GRI 305-5-c also requires the rationale for choosing that baseline.",
        "GRI 305-5-b (gases included) and 305-5-d (which scopes the reductions "
        "occurred in) remain unanswered — STARS reports the reduction against "
        "the combined scope 1 + 2 total without attributing it to either."),

    # --- 302-1-a: "including fuel types used" ------------------------------
    row("OP-5", "Natural gas", "GRI 302", "302-1", "component", "high",
        "GRI 302-1-a requires non-renewable fuel consumption 'including fuel "
        "types used'. `Total stationary fuel consumption` is already mapped as "
        "the total; this is the type breakdown GRI asks for alongside it, and "
        "it is the dominant fuel at all three institutions.",
        "GRI 302-1 expects joules; STARS reports MWh — convertible, but state "
        "the conversion."),

    row("OP-5", "Heating oil", "GRI 302", "302-1", "component", "high",
        "GRI 302-1-a, fuel type breakdown.",
        "Zero at Cork; a small residual at TU Dublin and Berkeley. Units are "
        "MWh, not joules."),

    row("OP-5", "Coal/coke", "GRI 302", "302-1", "component", "medium",
        "GRI 302-1-a, fuel type breakdown. Zero for all three, which is the "
        "finding: none of these universities still burns coal.",
        "A reported zero, not missing data. Units are MWh, not joules."),

    row("OP-5", "Propane/LPG", "GRI 302", "302-1", "component", "medium",
        "GRI 302-1-a, fuel type breakdown. Zero for all three.",
        "A reported zero, not missing data. STARS also carries an `Other "
        "stationary fuels` catch-all, also zero everywhere, which is what makes "
        "this list of fuel types complete rather than merely partial. Units are "
        "MWh, not joules."),

    # --- 202-1: the numerator exists after all ------------------------------
    row("PA-13", "Wage floor for regular/permanent employees",
        "GRI 202", "202-1", "partial", "medium",
        "GRI 202-1-a is a RATIO: standard entry-level wage divided by the local "
        "minimum wage. The wage floor for regular/permanent employees IS the "
        "standard entry-level wage — the numerator of that ratio.",
        "The DENOMINATOR is what is missing, not the numerator. STARS "
        "benchmarks against a LIVING wage, not the local statutory MINIMUM "
        "wage, and carries no minimum-wage figure at all. Supplying one would "
        "mean introducing an external constant, which is outside this "
        "project's verified-data pipeline. GRI also requires the ratio BY "
        "GENDER, which STARS does not collect at any credit — that half is "
        "unanswerable, not merely unsupplied. STARS additionally reports "
        "separate floors for short-term/casual academic and non-academic "
        "staff. Values are bare numbers: EUR for the Irish universities, USD "
        "for Berkeley, and not comparable without saying so.",
        "Found by the second external review, which correctly noted the old "
        "rationale overstated the gap."),
]

NEW_ROWS = (GRI2 + TOPICS + EMPLOYEE_CATEGORIES + MATERIAL_TOPICS + GHG_305)


def main():
    write = "--write" in sys.argv
    mapping = pd.read_csv(MAPPING)

    existing = {
        (str(r.stars_credit).strip(), str(r.stars_field).strip(),
         str(r.gri_disclosure).strip())
        for r in mapping.itertuples(index=False)
    }

    # Amendments come first: an existing row whose JUDGEMENT was wrong, as
    # opposed to a row that was missing. Rewriting in place rather than adding a
    # second row for the same (credit, field, disclosure) keeps the content
    # index from reporting one field twice.
    amended, already = 0, 0
    for (credit, field, disclosure), columns in AMENDMENTS.items():
        hit = ((mapping.stars_credit.astype(str).str.strip() == credit)
               & (mapping.stars_field.astype(str).str.strip() == field)
               & (mapping.gri_disclosure.astype(str).str.strip() == disclosure))
        if not hit.any():
            print(f"   [warn] amendment target not found: {credit} / "
                  f"{field[:40]} -> {disclosure}")
            continue
        idx = mapping.index[hit][0]
        if all(str(mapping.loc[idx, k]) == str(v) for k, v in columns.items()):
            already += 1
            continue
        for k, v in columns.items():
            mapping.loc[idx, k] = v
        amended += 1
    if amended or already:
        print(f"{len(AMENDMENTS)} amendment(s): {amended} applied, "
              f"{already} already current")

    fresh, skipped = [], 0
    for r in NEW_ROWS:
        key = (r["stars_credit"].strip() or "nan",
               r["stars_field"].strip() or "nan",
               r["gri_disclosure"].strip())
        if key in existing or (r["stars_credit"], r["stars_field"],
                               r["gri_disclosure"]) in existing:
            skipped += 1
            continue
        fresh.append(r)
        existing.add(key)

    by_rel = pd.Series([r["relationship"] for r in fresh]).value_counts()
    print(f"{len(NEW_ROWS)} candidate rows, {skipped} already present, "
          f"{len(fresh)} new")
    for rel, n in by_rel.items():
        print(f"   {rel:16} {n}")

    covered = sorted({r["gri_disclosure"] for r in fresh},
                     key=lambda n: (int(n.split('-')[0]), int(n.split('-')[1])))
    print(f"\n   disclosures newly addressed: {len(covered)}")
    print("   " + " ".join(covered))

    if not write:
        print("\n(dry run — pass --write to apply)")
        return

    out = pd.concat([mapping, pd.DataFrame(fresh)], ignore_index=True)
    out.to_csv(MAPPING, index=False)
    print(f"\n[save] {len(mapping)} -> {len(out)} rows in "
          f"{MAPPING.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
