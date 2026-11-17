# Design notes

How the pipeline is built, why, what can go wrong and what would have to
change at a larger scale. Figures are from a full run on a laptop
(8 cores, 8 GB RAM) in November 2026.

## Goals and non-goals

**Goals**

* Load two public datasets completely and keep them current without manual work.
* Never publish a wrong number silently: every assumption is a test.
* Re-runnable at any time with the same result (idempotent at every step).
* Cheap to run: a laptop, a free GitHub runner, or a small VM.

**Non-goals**

* Real-time data. The sources change at most daily; a daily batch is enough.
* A general-purpose warehouse. The marts answer specific questions.
* Linking transactions to vehicles. The publisher pseudonymises identifiers
  separately per dataset, so the join is impossible by design.

## Size of the problem

| | Transactions (Regitra) | Inspections (TRANSEKSTA) |
|---|---|---|
| Rows | 9.4 million | 15.8 million (14.3 million after de-duplication) |
| Raw Parquet | 423 MB, 67 partitions | 610 MB, 143 partitions |
| Largest partition | 187k rows, 8.8 MB | 314k rows, 11.3 MB |
| History | May 2021 onwards, mutable | 2015 onwards, append-only, frozen since May 2025 |
| Refresh | roughly weekly | not refreshed since May 2025 |

First load: about 30 minutes (network bound). Daily run: under a minute of
extraction and three to four minutes of `dbt build` (176 nodes). Warehouse file:
5 GB.

## Layers

```
API  ->  raw (Parquet, VARCHAR)  ->  staging  ->  intermediate  ->  marts  ->  export (Parquet)  ->  dashboard
```

| Layer | Holds | Rule |
|---|---|---|
| raw | exactly what the API returned, one file per month | never edited, only replaced whole |
| staging | one clean row per business entity | type, rename, de-duplicate; no business logic |
| intermediate | business flags and English categories | joins to reference seeds |
| marts | facts, a dimension and aggregates | what people query |
| export | the 15 aggregate marts as Parquet | the only thing the dashboard reads |

## Decisions and trade-offs

### DuckDB instead of PostgreSQL or a cloud warehouse

25 million rows is small data. DuckDB builds every model in two minutes on one
machine, needs no server and lets anyone who clones the repo run the whole
pipeline. The cost is that it is single-node and single-writer: two processes
cannot write to the warehouse at the same time, which is why Airflow runs at
most one DAG run at a time. The SQL is standard enough to move to BigQuery or
Snowflake with dbt adapter changes (see *Scaling*).

### Monthly partitions, cut on a column that cannot move

A transaction document can be edited after it was first published. If the raw
layer were partitioned by transaction date, an edit to a 2022 document would
change a 2022 file, and every daily run would have to re-download all history to
notice. Partitioning by *modification* month means a closed month never changes:
the daily run re-pulls only the two newest partitions plus anything missing.
Inspections are append-only, so they are partitioned by inspection month.

Monthly is a balance between request count and file size: the largest month is
11 MB of Parquet. At 10x volume weekly partitions would keep files and
downloads small (see *Scaling*).

### Validate, then publish atomically

A partition is built in a local temp directory and only published when its row
count is at least the API's own `count()` for the same window. Publishing is a
rename on local disk or a single PUT on S3, so a reader sees the old complete
file or the new complete file, never a partial one. If one partition fails, the
others are still recorded in the manifest and the run fails at the end, so a
retry only redoes the failed month.

### Raw stays untyped

Every raw column is `VARCHAR`. If the publisher sends `"n/a"` in a numeric
column, the load still succeeds and a dbt test reports it, instead of the
extract crashing at 3 a.m. with nothing loaded.

### Incremental on arrival time, not on the source timestamp

`fct_vehicle_transactions` is incremental. The obvious watermark,
`max(modified_at)`, is wrong: a backfill or a gap repair loads records whose
`modified_at` is older than the watermark, and they would be skipped forever.
The reconciliation test (fact rows must equal staging rows) caught exactly this
in the first version. The watermark is now `extracted_at`, the time a row
arrived. Merging is `delete+insert` on the document id, so a re-pulled partition
updates rows in place instead of duplicating them.

The inspection models are rebuilt in full on each run. The source is frozen, a
full rebuild takes under a minute, and a full rebuild has no watermark to get
wrong. If the source starts updating again, `fct_inspections` would become
incremental the same way.

### De-duplicate on content, not on the record id

The inspection publisher re-released a third of 2018 and 2024 under new record
ids. Identical rows are collapsed by hashing every published attribute. The key
deliberately includes every column: a narrower key (vehicle, week, station)
merged rows that differed in validity period, which a test exposed. The price of
the wide key is that two genuinely separate visits identical in every attribute
in the same week count once; in the years without the publication fault that is
fewer than 1 row in 2,000.

### Late registrations

About 10% of sales reach the registry more than a month after the contract
date. The newest three months are therefore flagged `is_complete_month = false`
and excluded from trends and KPIs. Without this, every month looks like a
collapse in sales when it is first shown.

### Airflow shells out to the pipeline

The DAG runs `lvm` and `dbt` from a separate virtualenv with `BashOperator`.
Airflow and dbt pin conflicting versions of shared libraries; keeping them apart
avoids that, keeps Airflow a pure scheduler, and means every task is a command a
developer can run by hand. The cost is coarser observability than a dbt-native
integration such as Cosmos, which would map each model to a task.

GitHub Actions runs the same steps daily as a hosted fallback, so the data keeps
flowing without a long-running Airflow instance.

### The dashboard reads exported files, not the warehouse

The warehouse is 5 GB and single-writer. The dashboard instead reads 15
aggregate files totalling 120 kB, from a folder, an HTTPS URL or the snapshot
committed to the repository. It can be hosted for free, cannot slow down the
pipeline, and cannot contain business logic, because it never sees a fact row.

## Failure modes

| What goes wrong | What happens |
|---|---|
| API is down or slow | Retried with exponential backoff on 429 and 5xx (5 attempts); 4xx errors fail at once. Airflow retries the task twice more. |
| Download is cut short | Row count below the API count: the partition is rejected and the previous file is kept. |
| Publisher renames or reorders a column | The CSV header is compared with the requested columns before loading; the run fails loudly. |
| Publisher sends a bad value | Lands as text; a dbt test fails or warns, depending on severity. |
| A new category appears (document type, country, make) | Mapped to `Unmapped` or `Other`; coverage tests fail if the unmapped share passes a threshold. |
| Publisher stops updating | `dbt source freshness` warns after 14 days and errors after 45 (transactions). |
| A mart changes shape | Enforced dbt contracts fail the build; the dashboard tests fail in CI. |
| Process killed mid-run | Partitions are atomic; partitions on disk but missing from the manifest are reloaded on the next run. |
| Publisher deletes records | Not detected in closed partitions until a `--full-refresh`. Known gap. |

## Testing strategy

| Level | Tool | Purpose |
|---|---|---|
| Extractor logic | pytest with a mocked API | windows, planning, retries, atomicity, failure isolation |
| Object storage | pytest with an S3 emulator (moto) | extract to a bucket and build dbt from it |
| Business rules | dbt unit tests | fixed inputs, exact expected outputs |
| Data | dbt data tests | keys, relationships, ranges, grain, reconciliation, coverage |
| Interfaces | dbt contracts, export test | column names and types the dashboard depends on |
| End to end | pytest + real-data fixtures | full `dbt build` on samples of both datasets |
| Orchestration | pytest under Airflow 3.4 | the DAG imports and has the intended shape |
| Presentation | Streamlit AppTest | both tabs render; filters do not break the page |

Unit tests use fixed inputs; data tests run against the real data on every
build. The first catches a wrong rule, the second a surprising input.

## Scaling

What breaks first if the data grew 100 times (2.5 billion rows):

1. **The staging de-duplication.** `stg_regitra__transactions` ranks every row
   by document on every run. At 100x it should become incremental, ranking only
   documents that arrived since the last run.
2. **Single-node DuckDB.** The warehouse would no longer fit comfortably on one
   machine. The models would move to BigQuery, Snowflake or MotherDuck; the
   raw layer is already Parquet and already works on S3, so only the dbt adapter
   and a handful of dialect-specific functions change.
3. **Monthly downloads.** A month would be about a gigabyte of CSV in one HTTP
   response. Weekly or daily partitions, or the API's cursor pagination, would
   keep each request small and make retries cheap.
4. **Airflow standalone.** Fine for one DAG; production would use the
   Kubernetes or Celery executor with a PostgreSQL metadata database.

What does not need to change: the layer boundaries, the idempotent publish, the
tests and the export-based serving layer.

## Security and privacy

* Both datasets are pseudonymised by the publisher; no personal data is loaded.
* No credentials in the repository. S3 credentials come from the standard AWS
  environment variables; the dbt profile only references them.
* The dashboard is read-only and reads aggregates only.

## What I would do next

* Convert non-EUR amounts with ECB reference rates instead of excluding them.
* Make `stg_regitra__transactions` incremental (see *Scaling*).
* Detect deleted records with a periodic count comparison per closed partition.
* Volume anomaly tests: alert when a day's row count is far from its usual range.
* Publish the dbt documentation site with lineage to GitHub Pages.
