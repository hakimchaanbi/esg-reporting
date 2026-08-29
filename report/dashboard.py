"""
Phase 6b — the BI dashboard
===========================

RUN
    streamlit run report/dashboard.py

Reads only the three tidy tables from build_bi_table.py. It computes nothing of
its own beyond selection and layout, so anything on screen can be traced to a
CSV row and from there to esg_master_dataset.csv. No LLM, no live scraping.

WHAT THIS DASHBOARD REFUSES TO DO, AND WHY
    It will not chart absolute totals across institutions. Berkeley withdraws
    2,092,006 cubic metres of water a year; Cork withdraws 54,153. Berkeley is
    roughly ten times the size. A bar chart of raw totals reads "Berkeley is
    worst at everything", which is false, and it is the first thing anyone will
    challenge.

    Cross-institution comparison is therefore restricted to the eight INTENSITY
    metrics — per person and per unit of floor area — which all three report.
    Absolute figures are still available, but only one institution at a time.

    That restriction is not cosmetic. It also surfaces the most interesting
    thing in the data: the two denominators disagree. Berkeley has the highest
    water and emissions per person and the LOWEST energy per square metre. Which
    university "performs best" depends on whether you divide by people or by
    floor area, and a dashboard that hides that is lying by omission.

THE FOURTH TAB IS THE POINT
    Scores and metrics are what STARS already publishes. The contribution here
    is the GRI view: how much of an international disclosure standard a
    university can actually answer, and what it structurally cannot. That is the
    research finding, so it gets a tab of its own rather than a footnote.
"""

from __future__ import annotations

import pathlib
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scrapers.institutions import PROJECT_ROOT  # noqa: E402

OUT_DIR = PROJECT_ROOT / "report" / "output"
MAPPING = PROJECT_ROOT / "mapping" / "stars_gri_mapping.csv"

# One colour per institution, held constant across every chart so the eye can
# track a university between tabs.
COLOURS = {
    "University of California, Berkeley": "#1f4e79",
    "University College Cork": "#c0504d",
    "Technological University Dublin": "#4f6228",
}
STATUS_COLOURS = {
    "Reported": "#4f6228",
    "Partially reported": "#d99694",
    "Not reported": "#a6a6a6",
    "Not assessed": "#000000",
}


@st.cache_data
def load():
    missing = [n for n in ("bi_scores", "bi_metrics", "bi_coverage")
               if not (OUT_DIR / f"{n}.csv").exists()]
    if missing:
        st.error(f"Missing {missing}. Run: python -m report.build_bi_table")
        st.stop()
    return (pd.read_csv(OUT_DIR / "bi_scores.csv"),
            pd.read_csv(OUT_DIR / "bi_metrics.csv"),
            pd.read_csv(OUT_DIR / "bi_coverage.csv"),
            pd.read_csv(MAPPING))


st.set_page_config(page_title="University ESG — STARS to GRI",
                   layout="wide", page_icon="🌱")
scores, metrics, coverage, mapping = load()

st.title("University ESG reporting — AASHE STARS mapped to GRI")
st.caption(
    "Source: STARS 3.0 reports for UC Berkeley, University College Cork and "
    "Technological University Dublin, used with attribution to AASHE. "
    "Every figure traces to `esg_master_dataset.csv`; nothing here is generated."
)

tab_overview, tab_compare, tab_gri, tab_gaps = st.tabs(
    ["Overview", "Comparison", "GRI coverage", "The gaps"])


# ----------------------------------------------------------------------
with tab_overview:
    st.subheader("STARS performance by pillar")
    st.caption(
        "Scores are credit-level and counted once per credit. The pillar "
        "grouping is a reasoned mapping of STARS categories onto E/S/G — STARS "
        "ships no such labels (CLAUDE.md §8)."
    )

    real = scores[scores.pillar.isin(
        ["Environmental", "Social", "Governance", "Context", "Bonus"])]
    pillar = (real.groupby(["institution", "pillar"], as_index=False)
              .agg(score=("score", "sum"), available=("max", "sum")))

    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.bar(pillar, x="pillar", y="score", color="institution",
                     barmode="group", color_discrete_map=COLOURS,
                     labels={"score": "points earned", "pillar": ""})
        fig.update_layout(legend=dict(orientation="h", y=-0.25), height=420)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        pct = pillar.assign(
            pct=(pillar.score / pillar.available.replace(0, pd.NA) * 100).round(1))
        fig2 = px.bar(pct, x="pct", y="pillar", color="institution",
                      barmode="group", orientation="h",
                      color_discrete_map=COLOURS,
                      labels={"pct": "% of points available", "pillar": ""})
        fig2.update_layout(showlegend=False, height=420)
        st.plotly_chart(fig2, use_container_width=True)

    st.info(
        "**Points earned and share of points available rank differently.** "
        "Bonus credits are capped in reality and Context credits (academics and "
        "engagement) carry far more points than Governance, so a tall bar is not "
        "the same as strong performance.", icon="ℹ️")

    st.subheader("Credit detail")
    inst = st.selectbox("Institution", sorted(scores.institution.unique()),
                        key="ov_inst")
    view = scores[scores.institution == inst][
        ["credit_code", "credit_name", "pillar", "status", "score", "max",
         "pct_of_max"]]
    st.dataframe(view, use_container_width=True, hide_index=True, height=340)


# ----------------------------------------------------------------------
with tab_compare:
    st.subheader("Comparing three universities of very different size")
    st.warning(
        "**Absolute totals are not comparable here and this tab will not chart "
        "them.** Berkeley withdraws 2,092,006 m³ of water a year; Cork "
        "withdraws 54,153. Berkeley is roughly ten times the size, so a chart "
        "of raw totals would say it is worst at everything, which is false. "
        "Only normalised metrics appear below.", icon="⚠️")

    inten = metrics[metrics.is_intensity & metrics.comparable]
    basis = st.radio("Normalise by", ["per person", "per unit of floor area"],
                     horizontal=True)
    chosen = inten[inten.field.str.contains(basis, case=False)]

    for field, group in chosen.groupby("field"):
        units = group.iloc[0].units
        fig = px.bar(group.sort_values("value_numeric"),
                     x="value_numeric", y="institution", orientation="h",
                     color="institution", color_discrete_map=COLOURS,
                     labels={"value_numeric": units or "", "institution": ""})
        fig.update_layout(showlegend=False, height=210,
                          margin=dict(l=0, r=0, t=34, b=0),
                          title=dict(text=field, font=dict(size=14)))
        st.plotly_chart(fig, use_container_width=True)

    st.success(
        "**The denominator changes the answer.** Berkeley has the highest water "
        "use and emissions *per person*, and the LOWEST energy use *per square "
        "metre*. Switch the toggle above and watch the ranking invert. Neither "
        "view is the true one — which is exactly why a single headline number "
        "would be misleading.", icon="🔍")

    with st.expander("Absolute figures — one institution at a time"):
        inst = st.selectbox("Institution", sorted(metrics.institution.unique()),
                            key="cmp_inst")
        one = metrics[(metrics.institution == inst) & ~metrics.is_intensity]
        pillar_pick = st.multiselect(
            "Pillar", sorted(one.pillar.dropna().unique()),
            default=["Environmental"])
        show = one[one.pillar.isin(pillar_pick)] if pillar_pick else one
        st.dataframe(
            show[["credit_code", "indicator", "field", "value_numeric",
                  "units", "gri_disclosure"]].sort_values(
                ["credit_code", "field"]),
            use_container_width=True, hide_index=True, height=420)


# ----------------------------------------------------------------------
with tab_gri:
    st.subheader("How much of GRI can a university actually report?")
    st.caption(
        "78 disclosures across 13 GRI standards. Status is derived from the "
        "hand-built STARS→GRI mapping and whether the institution populated the "
        "mapped fields — not from anything a model decided."
    )

    order = ["Reported", "Partially reported", "Not reported", "Not assessed"]
    summary = (coverage.groupby(["institution", "status"], as_index=False)
               .gri_disclosure.count()
               .rename(columns={"gri_disclosure": "disclosures"}))
    summary["status"] = pd.Categorical(summary.status, order, ordered=True)

    fig = px.bar(summary.sort_values("status"), x="institution",
                 y="disclosures", color="status", barmode="stack",
                 color_discrete_map=STATUS_COLOURS, labels={"institution": ""})
    fig.update_layout(height=380, legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True)

    cols = st.columns(3)
    for col, inst in zip(cols, sorted(coverage.institution.unique())):
        got = coverage[(coverage.institution == inst)
                       & (coverage.status == "Reported")]
        col.metric(inst.split(",")[0], f"{len(got)} of 78",
                   help="GRI disclosures fully reportable from STARS data")

    st.subheader("By standard")
    by_std = (coverage.groupby(["gri_standard", "status"], as_index=False)
              .gri_disclosure.count()
              .rename(columns={"gri_disclosure": "n"}))
    by_std["status"] = pd.Categorical(by_std.status, order, ordered=True)
    fig2 = px.bar(by_std.sort_values("status"), x="n", y="gri_standard",
                  color="status", orientation="h", barmode="stack",
                  color_discrete_map=STATUS_COLOURS,
                  labels={"n": "disclosures (all three institutions)",
                          "gri_standard": ""})
    fig2.update_layout(height=460, legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig2, use_container_width=True)

    with st.expander("Every disclosure, per institution"):
        inst = st.selectbox("Institution", sorted(coverage.institution.unique()),
                            key="gri_inst")
        st.dataframe(
            coverage[coverage.institution == inst][
                ["gri_standard", "gri_disclosure", "gri_title", "status",
                 "values_available"]],
            use_container_width=True, hide_index=True, height=420)


# ----------------------------------------------------------------------
with tab_gaps:
    st.subheader("What the frameworks cannot say to each other")
    st.caption(
        "This is the research finding, not a shortfall. Both directions are "
        "recorded deliberately."
    )

    gri_gaps = mapping[(mapping.relationship == "gap_gri_side")
                       & (mapping.review_status == "confirmed")]
    stars_gaps = mapping[mapping.relationship == "gap_stars_side"]

    c1, c2 = st.columns(2)
    c1.metric("GRI asks, STARS cannot answer", len(gri_gaps))
    c2.metric("STARS collects, GRI has no slot", len(stars_gaps))

    st.markdown("#### GRI asks and STARS cannot answer")
    st.dataframe(
        gri_gaps[["gri_standard", "gri_disclosure", "rationale"]]
        .sort_values("gri_disclosure"),
        use_container_width=True, hide_index=True, height=300)

    st.markdown("#### STARS collects and GRI has no vocabulary for it")
    st.dataframe(
        stars_gaps[["stars_credit", "rationale"]],
        use_container_width=True, hide_index=True)

    st.info(
        "**Teaching and research have no corporate analogue.** GRI was written "
        "for companies, which do not run degree programmes or publish research, "
        "so a university's largest activities fall outside it entirely. The "
        "reverse also holds: GRI 301 Materials concerns inputs to manufactured "
        "products, and a university manufactures none.", icon="🎓")

    st.markdown("#### Disclosures reported only partially, and why")
    partial = mapping[(mapping.relationship == "partial")
                      & (mapping.review_status == "confirmed")
                      & mapping.caveat.notna()]
    st.dataframe(
        partial[["gri_disclosure", "stars_credit", "stars_field", "caveat"]]
        .sort_values("gri_disclosure"),
        use_container_width=True, hide_index=True, height=300)
