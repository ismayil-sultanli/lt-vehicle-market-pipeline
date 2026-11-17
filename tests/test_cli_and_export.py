from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest
import yaml

from lt_vehicle_market import cli
from lt_vehicle_market.config import APZIURA, DATASETS, SANDORIS, Settings
from lt_vehicle_market.export import EXPORTED_MARTS, run_export

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------- CLI --
def test_extract_defaults_to_every_dataset(monkeypatch: pytest.MonkeyPatch):
    calls = []
    monkeypatch.setattr(cli, "run_extract", lambda spec, **kw: calls.append((spec.name, kw)))

    assert cli.main(["extract"]) == 0

    assert [name for name, _ in calls] == list(DATASETS)
    assert calls[0][1] == {"refresh_months": 2, "full_refresh": False, "since": None}


def test_extract_passes_options_through(monkeypatch: pytest.MonkeyPatch):
    calls = []
    monkeypatch.setattr(cli, "run_extract", lambda spec, **kw: calls.append((spec, kw)))

    cli.main(
        ["-v", "extract", "--dataset", "apziura", "--since", "2024-03", "--refresh-months", "1",
         "--full-refresh"]
    )  # fmt: skip

    assert calls == [
        (APZIURA, {"refresh_months": 1, "full_refresh": True, "since": date(2024, 3, 1)})
    ]


@pytest.mark.parametrize(
    "argv", [["extract", "--since", "March"], ["extract", "--dataset", "x"], []]
)
def test_bad_arguments_exit_with_usage_error(argv: list[str]):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


def test_sample_command_lands_the_bundled_samples(monkeypatch: pytest.MonkeyPatch):
    calls = []
    monkeypatch.setattr(cli, "run_sample", lambda source: calls.append(source))
    assert cli.main(["sample"]) == 0
    assert cli.main(["sample", "--from", "elsewhere"]) == 0
    assert calls == [Path("tests/fixtures"), Path("elsewhere")]


def test_export_command_runs_the_export(monkeypatch: pytest.MonkeyPatch):
    called = []
    monkeypatch.setattr(cli, "run_export", lambda: called.append(True))
    assert cli.main(["export"]) == 0
    assert called == [True]


# ------------------------------------------------------------------ config --
def test_dataset_catalogue_is_consistent():
    assert set(DATASETS) == {"sandoris", "apziura"}
    for spec in DATASETS.values():
        assert spec.partition_field in spec.columns
        assert spec.columns[0] == "_id"
        assert len(set(spec.columns)) == len(spec.columns)
        assert spec.first_partition.day == 1
    assert SANDORIS.partition_key != APZIURA.partition_key


def test_settings_paths_follow_the_data_dir(tmp_path: Path):
    settings = Settings(api_base="https://api.test/", data_dir=tmp_path, raw_uri="")
    assert settings.dataset_url(SANDORIS) == f"https://api.test/{SANDORIS.path}"
    assert settings.raw_root == str(tmp_path / "raw")
    assert settings.warehouse_path.parent == settings.export_dir.parent == tmp_path


def test_raw_uri_overrides_the_local_default(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, raw_uri="s3://lake/raw")
    assert settings.raw_root == "s3://lake/raw"


# ------------------------------------------------------------------ export --
def test_export_writes_one_parquet_file_per_mart(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    with duckdb.connect(str(settings.warehouse_path)) as con:
        con.execute("create schema marts")
        for mart in EXPORTED_MARTS:
            con.execute(f"create table marts.{mart} as select 1 as n, 'x' as label")

    written = run_export(settings)

    assert [p.name for p in written] == [f"{m}.parquet" for m in EXPORTED_MARTS]
    rows = duckdb.execute(f"select n, label from read_parquet('{written[0]}')").fetchall()
    assert rows == [(1, "x")]


def test_exported_marts_match_the_dashboard_exposure():
    """The dbt exposure documents exactly what the dashboard is served."""
    exposures = yaml.safe_load((ROOT / "dbt" / "models" / "exposures.yml").read_text())
    depends_on = exposures["exposures"][0]["depends_on"]
    declared = {ref.removeprefix("ref('").removesuffix("')") for ref in depends_on}
    assert declared == set(EXPORTED_MARTS)
