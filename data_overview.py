"""data_overview.py

Author: Zhongyi (James) Guo
Date: 07/29/2026

Relative frequency of each cell population in each sample.

One row per (sample, population), with columns:
sample, total_count, population, count, percentage.

Usage
-----
    python data_overview.py                    # writes cell_frequencies.csv
"""

import argparse
import os
import sqlite3

import pandas as pd

# Per-sample total via window function, so counts and totals sit on the same row.
FREQUENCY_QUERY = """
SELECT
    sample_id                                                   AS sample,
    SUM(count) OVER (PARTITION BY sample_id)                    AS total_count,
    population,
    count,
    printf('%.2f%%', 100.0 * count / NULLIF(SUM(count) OVER (PARTITION BY sample_id), 0))
                                                                AS percentage
FROM cell_counts
ORDER BY sample_id, population
"""


def cell_frequencies(conn):
    """Return the summary table as a DataFrame."""
    return pd.read_sql(FREQUENCY_QUERY, conn)


def main():
    parser = argparse.ArgumentParser(
        description="Summarize relative frequency of each cell population per sample."
    )
    parser.add_argument("--db", default="cell_count.db",
                        help="Path to the SQLite database")
    parser.add_argument("--out", default="cell_frequencies.csv",
                        help="Path for the output CSV")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f"Database not found: {args.db}\nRun `python load_data.py` first.")

    conn = sqlite3.connect(args.db)
    try:
        df = cell_frequencies(conn)
    finally:
        conn.close()

    df.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
