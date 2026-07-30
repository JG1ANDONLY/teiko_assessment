"""load_data.py

Author: Zhongyi (James) Guo
Date: 07/28/2026

Initialize a SQLite database with a normalized schema and load all rows from
cell-count.csv.

Schema (3NF):

    subjects        one row per subject (patient)
      subject_id    TEXT  PK
      project       TEXT
      condition     TEXT
      age           INTEGER
      sex           TEXT
      treatment     TEXT
      response      TEXT

    samples         one row per biological sample (a subject may have many)
      sample_id                   TEXT  PK
      subject_id                  TEXT  FK -> subjects.subject_id
      sample_type                 TEXT  (PBMC / WB)
      time_from_treatment_start   INTEGER

    cell_counts     long format: one row per (sample, cell population)
      sample_id     TEXT  FK -> samples.sample_id
      population     TEXT  (b_cell, cd8_t_cell, cd4_t_cell, nk_cell, monocyte)
      count         INTEGER
      PK (sample_id, population)

Why this design
---------------
* The one wide CSV is split into three tables so each column sits with the thing it
  describes: patient information stays in `subjects`, sample information stays in `samples`,
  measurements stay in `cell_counts`. The original row is recoverable with a join.
* Subject attributes repeat on every one of a subject's samples, so lifting them into
  `subjects` avoids that repetition and the update anomalies it invites.
* Long-format counts make per-population analysis a simple GROUP BY, and new
  populations need no schema migration.

Usage
-----
    python load_data.py                 # writes ./cell_count.db from ./cell-count.csv
"""

import argparse
import csv
import os
import sqlite3

# Columns in cell-count.csv that are cell-population counts (long-format pivot).
CELL_POPULATIONS = ["b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte"]

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS subjects (
    subject_id  TEXT PRIMARY KEY,
    project     TEXT NOT NULL,
    condition   TEXT,
    age         INTEGER,
    sex         TEXT,
    treatment   TEXT,
    response    TEXT
);

CREATE TABLE IF NOT EXISTS samples (
    sample_id                  TEXT PRIMARY KEY,
    subject_id                 TEXT NOT NULL REFERENCES subjects(subject_id),
    sample_type                TEXT,
    time_from_treatment_start  INTEGER
);

CREATE TABLE IF NOT EXISTS cell_counts (
    sample_id   TEXT NOT NULL REFERENCES samples(sample_id),
    population  TEXT NOT NULL,
    count       INTEGER NOT NULL,
    PRIMARY KEY (sample_id, population)
);

CREATE INDEX IF NOT EXISTS idx_samples_subject   ON samples(subject_id);
CREATE INDEX IF NOT EXISTS idx_cellcounts_pop     ON cell_counts(population);
"""


def _int_or_none(value):
    """Parse an int, returning None for blank/missing values."""
    value = (value or "").strip()
    return int(value) if value != "" else None


def _text_or_none(value):
    """Return stripped text, or None if blank (e.g. response for healthy subjects)."""
    value = (value or "").strip()
    return value if value != "" else None


def init_db(conn):
    """Create the schema. Drops existing tables first for a clean, idempotent load."""
    conn.executescript(
        "DROP TABLE IF EXISTS cell_counts;"
        "DROP TABLE IF EXISTS samples;"
        "DROP TABLE IF EXISTS subjects;"
    )
    conn.executescript(SCHEMA)


def load_csv(conn, csv_path):
    """Load all rows from csv_path into the database."""
    subjects = {}          # subject_id -> row tuple (deduplicated)
    samples = []           # list of sample row tuples
    cell_counts = []       # list of (sample_id, population, count) tuples

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Subject-level attributes repeat across a subject's samples, so we
            # record each subject only once (first occurrence wins).
            subject_id = row["subject"]
            if subject_id not in subjects:
                subjects[subject_id] = (
                    subject_id,
                    row["project"],
                    _text_or_none(row["condition"]),
                    _int_or_none(row["age"]),
                    _text_or_none(row["sex"]),
                    _text_or_none(row["treatment"]),
                    _text_or_none(row["response"]),  # NULL for healthy/untreated
                )

            # Every CSV row is a distinct sample.
            sample_id = row["sample"]
            samples.append(
                (
                    sample_id,
                    subject_id,
                    _text_or_none(row["sample_type"]),
                    _int_or_none(row["time_from_treatment_start"]),
                )
            )

            # Pivot the five wide count columns into one long row per population.
            for population in CELL_POPULATIONS:
                cell_counts.append((sample_id, population, _int_or_none(row[population])))

    # Bulk insert each table in one call. Parent tables (subjects, samples) go
    # before children so foreign-key references always resolve.
    conn.executemany(
        "INSERT INTO subjects VALUES (?, ?, ?, ?, ?, ?, ?)", subjects.values()
    )
    conn.executemany("INSERT INTO samples VALUES (?, ?, ?, ?)", samples)
    conn.executemany("INSERT INTO cell_counts VALUES (?, ?, ?)", cell_counts)
    conn.commit()

    return len(subjects), len(samples), len(cell_counts)


def main():
    parser = argparse.ArgumentParser(description="Load cell-count.csv into SQLite.")
    parser.add_argument("--csv", default="cell-count.csv", help="Path to cell-count.csv")
    parser.add_argument("--db", default="cell_count.db", help="Path to output SQLite database")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        raise SystemExit(f"CSV not found: {args.csv}")

    conn = sqlite3.connect(args.db)
    try:
        init_db(conn)
        n_subjects, n_samples, n_counts = load_csv(conn, args.csv)
    finally:
        conn.close()

    print(f"Loaded into {args.db}:")
    print(f"  subjects:    {n_subjects}")
    print(f"  samples:     {n_samples}")
    print(f"  cell_counts: {n_counts}")


if __name__ == "__main__":
    main()
