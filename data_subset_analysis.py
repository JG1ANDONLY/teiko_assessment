"""data_subset_analysis.py

Author: Zhongyi (James) Guo
Date: 07/30/2026

Baseline subset of the melanoma / miraclib / PBMC cohort, with the breakdowns
needed to check how that subset is composed.

Baseline is time_from_treatment_start = 0: the draw taken before miraclib has
had a chance to act, so it describes the patients as they entered treatment.

Outputs
-------
    melanoma_miraclib_pbmc_baseline.csv  one row per baseline sample, with metadata
    baseline_breakdown.csv               counts by project, response and sex
    baseline_b_cell_males.csv            mean b_cell count, male responders at baseline

Usage
-----
    python data_subset_analysis.py
"""

import argparse
import os
import sqlite3

import pandas as pd

BASELINE_DAY = 0

# Melanoma PBMC samples at baseline, from patients treated with miraclib.
BASELINE_QUERY = """
SELECT
    s.sample_id,
    u.subject_id,
    u.project,
    u.condition,
    u.age,
    u.sex,
    u.treatment,
    u.response,
    s.sample_type,
    s.time_from_treatment_start
FROM samples s
JOIN subjects u USING (subject_id)
WHERE u.condition   = 'melanoma'
  AND u.treatment   = 'miraclib'
  AND s.sample_type = 'PBMC'
  AND s.time_from_treatment_start = :day
ORDER BY s.sample_id
"""

# B cell counts for melanoma male responders at baseline. Deliberately no filter
# on sample_type or treatment: this question spans all of them.
B_CELL_QUERY = """
SELECT
    c.count AS cell_count
FROM cell_counts c
JOIN samples  s USING (sample_id)
JOIN subjects u USING (subject_id)
WHERE u.condition = 'melanoma'
  AND u.sex       = 'M'
  AND u.response  = 'yes'
  AND c.population = 'b_cell'
  AND s.time_from_treatment_start = :day
"""


def baseline_samples(conn):
    """Melanoma PBMC samples at baseline from miraclib-treated patients."""
    return pd.read_sql(BASELINE_QUERY, conn, params={"day": BASELINE_DAY})


def breakdown(samples):
    """Compose the baseline subset three ways, as one tidy table.

    Projects are counted in samples, responders and sexes in subjects, matching
    how each question is asked. The two agree here anyway, since a subject
    contributes exactly one baseline PBMC sample, but the `unit` column keeps
    that an explicit claim rather than a coincidence the reader has to infer.
    """
    groupings = [
        ("project", "samples", samples.groupby("project").size()),
        ("response", "subjects", samples.groupby("response")["subject_id"].nunique()),
        ("sex", "subjects", samples.groupby("sex")["subject_id"].nunique()),
    ]
    rows = [
        {"category": category, "value": value, "unit": unit, "count": int(n)}
        for category, unit, counts in groupings
        for value, n in counts.items()
    ]
    return pd.DataFrame(rows)


def b_cell_average(conn):
    """Mean b_cell count for melanoma male responders at baseline."""
    df = pd.read_sql(B_CELL_QUERY, conn, params={"day": BASELINE_DAY})
    return pd.DataFrame([{
        "condition": "melanoma",
        "sex": "M",
        "response": "yes",
        "time_from_treatment_start": BASELINE_DAY,
        "sample_type": "all",
        "treatment": "all",
        "n_samples": len(df),
        "cell_type": "b_cell",
        "mean_count": round(df["cell_count"].mean(), 2),
    }])


def main():
    parser = argparse.ArgumentParser(
        description="Summarize the baseline melanoma / miraclib / PBMC subset."
    )
    parser.add_argument("--db", default="cell_count.db", help="Path to the SQLite database")
    parser.add_argument("--samples", default="melanoma_miraclib_pbmc_baseline.csv",
                        help="Output CSV of baseline samples")
    parser.add_argument("--breakdown", default="baseline_breakdown.csv",
                        help="Output CSV of counts by project, response and sex")
    parser.add_argument("--bcell", default="baseline_b_cell_males.csv",
                        help="Output CSV of the male responder b_cell average")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f"Database not found: {args.db}\nRun `python load_data.py` first.")

    conn = sqlite3.connect(args.db)
    try:
        samples = baseline_samples(conn)
        b_cells = b_cell_average(conn)
    finally:
        conn.close()

    samples.to_csv(args.samples, index=False)
    breakdown(samples).to_csv(args.breakdown, index=False)
    b_cells.to_csv(args.bcell, index=False)


if __name__ == "__main__":
    main()
