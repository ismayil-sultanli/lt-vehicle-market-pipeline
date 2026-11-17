"""Daily ELT for Lithuanian vehicle transactions and technical inspections.

    extract_sandoris ─┐
                      ├─> source freshness -> dbt build -> export marts
    extract_apziura  ─┘

The pipeline code lives in its own virtualenv (LVM_BIN) so Airflow's and dbt's
dependency trees never have to agree; Airflow only orchestrates shell commands.
Every task is idempotent, so retries and manual re-runs are always safe.
"""

from __future__ import annotations

import os
import shlex
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PROJECT_DIR = Path(os.getenv("LVM_PROJECT_DIR", Path(__file__).resolve().parents[2]))
BIN = os.getenv("LVM_BIN", str(PROJECT_DIR / ".venv" / "bin"))
LVM = shlex.quote(f"{BIN}/lvm")
DBT = shlex.quote(f"{BIN}/dbt") + " {cmd} --project-dir dbt --profiles-dir dbt"

default_args = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(hours=1),
}

with DAG(
    dag_id="vehicle_market_daily",
    description="Open data API -> Parquet -> DuckDB/dbt -> dashboard marts",
    schedule="0 6 * * *",  # 06:00 Vilnius time: the start_date carries the timezone
    start_date=pendulum.datetime(2026, 11, 1, tz="Europe/Vilnius"),
    catchup=False,  # the extract is state-based (missing + recent partitions), not date-based
    max_active_runs=1,
    default_args=default_args,
    tags=["elt", "open-data", "dbt"],
    doc_md=__doc__,
) as dag:
    common = {"cwd": str(PROJECT_DIR), "append_env": True}

    # One extract task per source dataset: they are independent, so they run in
    # parallel and a failure in one is retried without re-pulling the other.
    extracts = [
        BashOperator(
            task_id=f"extract_{dataset}",
            bash_command=f"{LVM} extract --dataset {dataset} --refresh-months 2",
            doc_md=f"Backfill missing `{dataset}` partitions and re-pull the two newest ones.",
            **common,
        )
        for dataset in ("sandoris", "apziura")
    ]

    freshness = BashOperator(
        task_id="check_source_freshness",
        bash_command=DBT.format(cmd="source freshness"),
        doc_md="Fail early if the publisher stopped updating the dataset.",
        **common,
    )

    build = BashOperator(
        task_id="dbt_build",
        bash_command=DBT.format(cmd="build"),
        doc_md="Seeds, models and data tests in dependency order.",
        **common,
    )

    export = BashOperator(
        task_id="export_marts",
        bash_command=f"{LVM} export",
        doc_md="Publish aggregate marts as Parquet for the dashboard.",
        **common,
    )

    extracts >> freshness >> build >> export
