# Teiko Assessment

**Author:** Zhongyi (James) Guo
**Date:** 07/30/2026

## Quick start

```bash
make setup      # install dependencies
make pipeline   # build the database and generate every output
make dashboard  # serve the dashboard (Codespaces should automatically direct you to port 8501)
```

## Conclusions

- **The database splits one wide CSV into three tables** — `subjects`, `samples`,
  and `cell_counts` — so each fact is stored once, beside the thing it describes.
  Cell counts are kept long (one row per sample and cell population) rather than
  five columns, which is what makes every analysis below a `GROUP BY` and lets a
  new cell population arrive without a schema change. Details in
  [Database Schema](#database-schema).

- **No cell population differed significantly** between responders and
  non-responders at an FDR-adjusted p-value of 0.05. We chose the **Mann-Whitney U
  test** because it compares ranks and so does not assume the data are normally
  distributed.

  | Cell population | Median diff (pp) | p | p adjusted | Rank-biserial | Significant |
  |---|---|---|---|---|---|
  | `cd4_t_cell` | +0.387 | 0.0124 | 0.0621 | 0.113 | No |
  | `nk_cell` | −0.220 | 0.1270 | 0.3170 | −0.069 | No |
  | `b_cell` | −0.173 | 0.3460 | 0.4320 | −0.043 | No |
  | `monocyte` | −0.482 | 0.2640 | 0.4320 | −0.050 | No |
  | `cd8_t_cell` | −0.113 | 0.6220 | 0.6220 | −0.022 | No |


- **Baseline subset:** 656 melanoma PBMC samples at day 0 from miraclib-treated
  patients.

  | Category | Value | Unit | Count |
  |---|---|---|---|
  | Project | `prj1` | samples | 384 |
  | Project | `prj3` | samples | 272 |
  | Response | Non-responder | subjects | 325 |
  | Response | Responder | subjects | 331 |
  | Sex | Females | subjects | 312 |
  | Sex | Males | subjects | 344 |
  
  384 samples were from project `prj1` and 272 samples were from project `prj3` (totaling 656 samples).
  325 subjects were non-responders and 331 were responders.
  312 subjects were females and 344 subjects were males.

- **Mean B cell count**, melanoma males who responded, at day 0, across all sample
  and treatment types: **10206.15** over 485 samples.

  | Condition | Sex | Response | Day | Sample type | Treatment | n | Cell population | Mean count |
  |---|---|---|---|---|---|---|---|---|
  | melanoma | Males | Responder | 0 | all | all | 485 | `b_cell` | 10206.15 |

## Database Schema

```
subjects                 samples                        cell_counts
subject_id  PK   <---+   sample_id   PK  <-----------+  sample_id   FK
project              +-- subject_id  FK               |  population
condition                sample_type                  +- count
age, sex                 time_from_treatment_start        PK (sample_id, population)
treatment, response
```

- **Three tables, not one wide CSV.** Patient facts, sample facts, and
  measurements each sit with the thing they describe; a two-join query recovers
  the original row.
- **Subject attributes stored once.** They repeat on every sample in the CSV.
  Lifting them out makes a correction one `UPDATE` and prevents a subject from
  being both a responder and not.
- **Counts long, not wide.** One row per (sample, cell population), so analysis by
  cell population is a `GROUP BY`, a sixth cell population is an `INSERT` rather
  than an `ALTER TABLE`, and relative frequency is one window function.
- **`response` is nullable.** Healthy/untreated subjects get `NULL`, not `""`, so
  `WHERE response IN ('yes','no')` excludes them without a special case.

### Scaling to hundreds of projects

Row count isn't the binding constraint — 100 projects at this size is ~5M rows,
which SQLite handles. **Write concurrency breaks first**, since SQLite serializes
writers; the schema ports to Postgres unchanged. Beyond that:

- A **`projects` table**, once a project has its own attributes (site, assay
  panel, dates) and `prj1` vs `PRJ1` becomes a real risk.
- **Lookup tables** for `condition` / `treatment` / `sample_type` / `population`,
  so a typo fails at write time instead of silently dropping rows from filtered
  queries.
- **Composite indexes** on `subjects(condition, treatment)` and
  `samples(sample_type, time_from_treatment_start)` — the filters every analysis
  actually uses.
- **Precompute relative frequency** (materialized view, or `total_count` on
  `samples`) rather than recomputing the window function per query; mirror to
  DuckDB/Parquet for heavy analytics, which the long format already suits.
- **Provenance columns** (`batch`, `loaded_at`, `source_file`) — cheap now,
  painful to backfill when a batch needs retracting.

## Code structure

| Script | Role |
|---|---|
| `load_data.py` | CSV → SQLite. Owns the schema and all parsing. |
| `data_overview.py` | Relative frequency per (sample, cell population). |
| `statistical_analysis.py` | Responders vs non-responders, with a boxplot. |
| `data_subset_analysis.py` | Baseline subset and its breakdowns. |
| `dashboard.py` | Streamlit UI over the same database and statistics. |

- **One stage per file, communicating through the database.** No pipeline stage
  imports another, so any stage reruns alone and changing an analysis can't affect
  the load. Only the dashboard imports, reusing the statistics rather than
  duplicating them.
- **SQL filters, pandas computes.** Each script opens with a named query constant
  defining its cohort in one visible block, rather than a chain of DataFrame masks.
- **Silent on success.** Output during `make pipeline` means something went wrong.
  A missing database exits naming the fix, not a traceback.
- **The subject is the unit of analysis.** Each patient has three PBMC samples, so
  samples aren't independent observations; treating them as such would inflate the
  effective sample size threefold. Each subject is collapsed to one mean before
  testing, giving n = 656 rather than 1,968.


## Dashboard

```bash
make dashboard   # opens http://localhost:8501
```

If the browser doesn't open, use the printed URL — in Codespaces, the forwarded
port 8501. `make dashboard PORT=8600` if the port is taken.

Sidebar filters set the cohort; three tabs show its composition, the responder
comparison, and the baseline subset. Statistics are imported from
`statistical_analysis.py`, so the dashboard and the CSVs cannot disagree.
