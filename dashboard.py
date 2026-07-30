"""dashboard.py

Author: Zhongyi (James) Guo
Date: 07/30/2026

Interactive view of the cell-count database: pick a cohort in the sidebar, see
its composition, the responder comparison, and the baseline breakdowns.

The statistics come from statistical_analysis.py rather than being reimplemented
here, so the dashboard and the pipeline CSVs can never disagree.

Usage
-----
    make dashboard
    streamlit run dashboard.py
"""

import os
import sqlite3

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from statistical_analysis import POPULATIONS, boxplot_figure, compare, significance_table

DB_PATH = os.environ.get("CELL_COUNT_DB", "cell_count.db")
BASELINE_DAY = 0

# Everything the dashboard needs, in one pass: per-sample relative frequency
# alongside the subject and sample metadata the filters act on.
DASHBOARD_QUERY = """
SELECT
    u.subject_id,
    u.project,
    u.condition,
    u.age,
    u.sex,
    u.treatment,
    u.response,
    s.sample_id,
    s.sample_type,
    s.time_from_treatment_start AS day,
    c.population,
    c.count AS cell_count,
    100.0 * c.count / SUM(c.count) OVER (PARTITION BY c.sample_id) AS percentage
FROM cell_counts c
JOIN samples  s USING (sample_id)
JOIN subjects u USING (subject_id)
"""


@st.cache_data(show_spinner="Loading database…")
def load_data(db_path):
    """Read the whole joined table once and cache it.

    It is ~52k rows, small enough to hold in memory, so every filter change is a
    pandas mask rather than another round trip to SQLite.
    """
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql(DASHBOARD_QUERY, conn)
    finally:
        conn.close()
    df["group"] = df["response"].map({"yes": "Responder", "no": "Non-responder"})
    # Relabel for display only; the database keeps the M/F codes. Rewriting the
    # column rather than adding a second one means the filter, the breakdown and
    # the sample table all read the same way without special-casing each.
    df["sex"] = df["sex"].map({"M": "Male", "F": "Female"}).fillna(df["sex"])
    return df


def multiselect_all(label, options, default=None):
    """A multiselect that treats an empty selection as 'no filter'."""
    chosen = st.sidebar.multiselect(label, options, default=default)
    return chosen or options


def subject_means(df):
    """One value per subject and population.

    A subject contributes several samples, which are not independent, so the
    subject is the unit of analysis for the comparison below.
    """
    return (df.groupby(["subject_id", "response", "group", "population"], as_index=False)
              ["percentage"].mean())


def testable(df):
    """True when both groups have enough subjects for a per-population test."""
    per_group = df.groupby(["population", "response"])["subject_id"].nunique().unstack(fill_value=0)
    return (set(per_group.columns) >= {"yes", "no"}) and bool((per_group >= 2).all().all())


def counts_by(df, column, unit):
    """Count samples or subjects per value of `column`, as a sorted table."""
    series = (df.groupby(column)["sample_id"].nunique() if unit == "samples"
              else df.groupby(column)["subject_id"].nunique())
    return series.rename(unit).sort_index().to_frame()


st.set_page_config(page_title="Cell Count Analysis", page_icon="🧬", layout="wide")
st.title("Cell Count Analysis")

if not os.path.exists(DB_PATH):
    st.error(f"Database not found: `{DB_PATH}`. Run `make pipeline` first.")
    st.stop()

data = load_data(DB_PATH)

# ---------------------------------------------------------------- sidebar ----
st.sidebar.header("Cohort")
st.sidebar.caption("Defaults reproduce the cohort in the pipeline outputs.")

conditions = multiselect_all("Condition", sorted(data["condition"].dropna().unique()), ["melanoma"])
treatments = multiselect_all("Treatment", sorted(data["treatment"].dropna().unique()), ["miraclib"])
sample_types = multiselect_all("Sample type", sorted(data["sample_type"].dropna().unique()), ["PBMC"])
sexes = multiselect_all("Sex", sorted(data["sex"].dropna().unique()))
days = multiselect_all("Day from treatment start", sorted(data["day"].dropna().unique()))

cohort = data[
    data["condition"].isin(conditions)
    & data["treatment"].isin(treatments)
    & data["sample_type"].isin(sample_types)
    & data["sex"].isin(sexes)
    & data["day"].isin(days)
]

if cohort.empty:
    st.warning("No samples match these filters.")
    st.stop()

# ------------------------------------------------------------------ header ----
left, mid, right, far = st.columns(4)
left.metric("Subjects", f"{cohort['subject_id'].nunique():,}")
mid.metric("Samples", f"{cohort['sample_id'].nunique():,}")
right.metric("Projects", cohort["project"].nunique())
far.metric("Responders", f"{cohort.loc[cohort['response'] == 'yes', 'subject_id'].nunique():,}")

overview, comparison, baseline = st.tabs(["Overview", "Responder comparison", "Baseline subset"])

# ---------------------------------------------------------------- overview ----
with overview:
    st.subheader("Cohort composition")
    by_project, by_response, by_sex = st.columns(3)
    with by_project:
        st.caption("Samples per project")
        st.dataframe(counts_by(cohort, "project", "samples"), use_container_width=True)
    with by_response:
        st.caption("Subjects per response")
        st.dataframe(counts_by(cohort, "response", "subjects"), use_container_width=True)
    with by_sex:
        st.caption("Subjects per sex")
        st.dataframe(counts_by(cohort, "sex", "subjects"), use_container_width=True)

    st.subheader("Relative frequency per population")
    st.caption("Median and quartiles across samples in the selected cohort.")
    summary = (cohort.groupby("population")["percentage"]
                     .describe()[["count", "mean", "50%", "std", "min", "max"]]
                     .rename(columns={"50%": "median"})
                     .round(2)
                     .reindex(POPULATIONS))
    st.dataframe(summary, use_container_width=True)

# -------------------------------------------------------------- comparison ----
with comparison:
    responder_cohort = cohort[cohort["response"].isin(["yes", "no"])]

    if responder_cohort.empty:
        st.info("No subjects with a recorded response in this cohort. "
                "Healthy and untreated subjects have no response.")
    else:
        means = subject_means(responder_cohort)
        st.caption(
            f"One mean per subject (n = {means['subject_id'].nunique():,}), since a "
            "subject's samples are repeated measures rather than independent observations."
        )

        fig = boxplot_figure(means, title="Relative cell frequency by response")
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)

        if testable(means):
            results = compare(means)
            table = significance_table(results)
            st.subheader("Mann-Whitney U, Benjamini-Hochberg adjusted")
            st.dataframe(table, use_container_width=True, hide_index=True)

            hits = results.loc[results["significant"], "population"].tolist()
            if hits:
                st.success(f"Significant at FDR 5%: {', '.join(hits)}")
            else:
                st.info("No population differs significantly at FDR 5%.")
        else:
            st.warning("Too few subjects in one group to test this cohort.")

# ---------------------------------------------------------------- baseline ----
with baseline:
    st.caption(f"Day {BASELINE_DAY} samples within the selected cohort, before treatment acts.")
    at_baseline = cohort[cohort["day"] == BASELINE_DAY]

    if at_baseline.empty:
        st.info(f"No day {BASELINE_DAY} samples in this cohort. Add day 0 to the sidebar filter.")
    else:
        a, b, c = st.columns(3)
        a.metric("Baseline samples", f"{at_baseline['sample_id'].nunique():,}")
        b.metric("Subjects", f"{at_baseline['subject_id'].nunique():,}")
        c.metric("Projects", at_baseline["project"].nunique())

        st.subheader("Mean cell count per population")
        st.caption("Absolute counts, not relative frequency.")
        means_by_pop = (at_baseline.pivot_table(index="population", columns="group",
                                                values="cell_count", aggfunc="mean")
                                   .round(2).reindex(POPULATIONS))
        st.dataframe(means_by_pop, use_container_width=True)

        st.subheader("Samples")
        st.dataframe(
            at_baseline[["sample_id", "subject_id", "project", "sex", "response",
                         "sample_type", "population", "cell_count"]],
            use_container_width=True, hide_index=True, height=300,
        )
