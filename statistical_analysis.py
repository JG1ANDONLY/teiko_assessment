"""statistical_analysis.py

Author: Zhongyi (James) Guo
Date: 07/29/2026

Compare cell population relative frequencies in responders vs non-responders,
among melanoma patients on miraclib, PBMC samples only.

Outputs
-------
    response_boxplots.png      boxplot per population, responders vs non-responders
    response_significance.csv  test results, one row per population

Usage
-----
    python statistical_analysis.py
"""

import argparse
import os
import sqlite3

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from scipy import stats
from statsmodels.stats.multitest import multipletests

POPULATIONS = ["b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte"]

# Sample-level relative frequencies for the melanoma / miraclib / PBMC cohort.
COHORT_QUERY = """
SELECT
    u.subject_id,
    u.response,
    c.sample_id,
    c.population,
    100.0 * c.count / SUM(c.count) OVER (PARTITION BY c.sample_id) AS percentage
FROM cell_counts c
JOIN samples  s USING (sample_id)
JOIN subjects u USING (subject_id)
WHERE u.condition   = 'melanoma'
  AND u.treatment   = 'miraclib'
  AND s.sample_type = 'PBMC'
  AND u.response IN ('yes', 'no')
"""


def load_cohort(conn):
    """Return the filtered cohort with a readable group label."""
    df = pd.read_sql(COHORT_QUERY, conn)
    df["group"] = df["response"].map({"yes": "Responder", "no": "Non-responder"})
    return df


def compare(df):
    """Mann-Whitney U per population, responders vs non-responders."""
    rows = []
    for pop in POPULATIONS:
        sub = df[df["population"] == pop]
        r = sub.loc[sub["response"] == "yes", "percentage"]
        n = sub.loc[sub["response"] == "no", "percentage"]

        u, p = stats.mannwhitneyu(r, n, alternative="two-sided")
        # Rank-biserial correlation: effect size, -1..1, sign favours responders.
        effect = 2 * u / (len(r) * len(n)) - 1

        rows.append({
            "population": pop,
            "n_responder": len(r),
            "n_non_responder": len(n),
            "median_responder": r.median(),
            "median_non_responder": n.median(),
            "median_diff": r.median() - n.median(),
            "u_statistic": u,
            "p_value": p,
            "rank_biserial": effect,
        })

    out = pd.DataFrame(rows)
    # Five tests, so control the false discovery rate (Benjamini-Hochberg).
    out["p_adjusted"] = multipletests(out["p_value"], method="fdr_bh")[1]
    out["significant"] = out["p_adjusted"] < 0.05
    return out.sort_values("p_adjusted")


# Reporting view of `compare` output: the columns worth reading, in reading order.
REPORT_COLS = ["population", "median_diff", "p_value", "p_adjusted",
               "rank_biserial", "significant"]


def significance_table(results):
    """Rounded, human-readable version of the test results."""
    out = results[REPORT_COLS].copy()
    for col in ["median_diff", "rank_biserial"]:
        out[col] = out[col].round(3)
    # 3 significant digits, still numeric, so tiny p-values do not round to zero.
    for col in ["p_value", "p_adjusted"]:
        out[col] = out[col].map(lambda p: float(f"{p:.3g}"))
    return out


DEFAULT_TITLE = ("Relative cell frequency by miraclib response in PBMC samples "
                 "among melanoma patients")


def boxplot_figure(df, title=DEFAULT_TITLE):
    """Boxplot of relative frequency by population, split by response.

    Returns the figure rather than writing it, so the dashboard can render the
    same chart for an arbitrary cohort that the pipeline writes to PNG.
    """
    sns.set_theme(style="whitegrid")
    fig, ax = plt.subplots(figsize=(11, 6))
    sns.boxplot(data=df, x="population", y="percentage", hue="group",
                order=POPULATIONS, palette=["#4C72B0", "#DD8452"],
                fliersize=2, ax=ax)
    ax.set_xlabel("Cell Type")
    ax.set_ylabel("Relative Frequency (%)")
    ax.set_title(title)
    ax.legend(title="")
    fig.tight_layout()
    return fig


def make_boxplot(df, path):
    """Write the boxplot to path."""
    fig = boxplot_figure(df)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Compare cell population frequencies by miraclib response."
    )
    parser.add_argument("--db", default="cell_count.db", help="Path to the SQLite database")
    parser.add_argument("--plot", default="response_boxplots.png", help="Output boxplot path")
    parser.add_argument("--out", default="response_significance.csv",
                        help="Output significance table CSV")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f"Database not found: {args.db}\nRun `python load_data.py` first.")

    conn = sqlite3.connect(args.db)
    try:
        df = load_cohort(conn)
    finally:
        conn.close()

    make_boxplot(df, args.plot)


    subject_means = (df.groupby(["subject_id", "response", "population"], as_index=False)
                       ["percentage"].mean())
    results = compare(subject_means)

    significance_table(results).to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
