"""Structural tests for the Airflow DAG.

Skipped unless Airflow is installed; CI runs them in a dedicated job against the
pinned Airflow version, so a DAG that fails to import never reaches a scheduler.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("airflow")

from airflow.dag_processing.dagbag import DagBag  # noqa: E402

DAGS = Path(__file__).resolve().parents[1] / "airflow" / "dags"


@pytest.fixture(scope="module")
def dag():
    bag = DagBag(dag_folder=str(DAGS))
    assert bag.import_errors == {}
    return bag.dags["vehicle_market_daily"]


def test_task_graph(dag):
    upstream = {task.task_id: task.upstream_task_ids for task in dag.tasks}
    assert upstream == {
        "extract_sandoris": set(),
        "extract_apziura": set(),
        "check_source_freshness": {"extract_sandoris", "extract_apziura"},
        "dbt_build": {"check_source_freshness"},
        "export_marts": {"dbt_build"},
    }


def test_schedule_runs_once_a_day_in_vilnius_time(dag):
    assert dag.schedule == "0 6 * * *"
    assert str(dag.timezone) == "Europe/Vilnius"
    assert dag.catchup is False
    assert dag.max_active_runs == 1


def test_every_task_retries_and_has_a_timeout(dag):
    for task in dag.tasks:
        assert task.retries >= 2, task.task_id
        assert task.execution_timeout is not None, task.task_id


def test_commands_call_the_pipeline_cli(dag):
    commands = {task.task_id: task.bash_command for task in dag.tasks}
    assert "extract --dataset sandoris" in commands["extract_sandoris"]
    assert "extract --dataset apziura" in commands["extract_apziura"]
    assert "source freshness" in commands["check_source_freshness"]
    assert " build " in commands["dbt_build"]
    assert commands["export_marts"].endswith(" export")
