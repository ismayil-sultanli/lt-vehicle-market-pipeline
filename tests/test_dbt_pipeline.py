"""End-to-end test: fixture CSVs -> raw Parquet -> dbt build -> exported marts.

Uses small samples of the two real datasets, so it runs offline in seconds and
exercises every model, seed, contract, unit test and data test exactly as
production does.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from lt_vehicle_market.config import SANDORIS, DatasetSpec, Settings
from lt_vehicle_market.export import EXPORTED_MARTS, run_export
from lt_vehicle_market.extract import csv_to_parquet
from lt_vehicle_market.sample import run_sample
from lt_vehicle_market.storage import RawStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SANDORIS_CSV = FIXTURES / "sandoris_sample.csv"
APZIURA_CSV = FIXTURES / "apziura_sample.csv"

# The fixture has a few hundred cars, far below the production reporting threshold.
DBT_VARS = "{min_vehicles_per_model: 2}"


def land(spec: DatasetSpec, csv_path: Path, data_dir: Path, month: str) -> None:
    year, mon = month.split("-")
    store = RawStore(Settings(data_dir=data_dir, raw_uri="").raw_root)
    dest = store.partition_uri(spec, date(int(year), int(mon), 1))
    with store.staging_dir(dest) as tmp:
        csv_to_parquet(csv_path, tmp / "part.parquet", datetime.now(UTC), spec.columns)
        store.publish(tmp / "part.parquet", dest)


def dbt_build(tmp_path: Path) -> bool:
    # A subprocess, like in production: dbt must not hold the DuckDB file open
    # while the test (or the export step) reads it.
    dbt = Path(sys.executable).parent / "dbt"
    result = subprocess.run(
        [
            str(dbt), "build",
            "--project-dir", str(ROOT / "dbt"),
            "--profiles-dir", str(ROOT / "dbt"),
            "--target-path", str(tmp_path / "target"),
            "--log-path", str(tmp_path / "logs"),
            "--vars", DBT_VARS,
        ],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    if result.returncode != 0:
        print(result.stdout[-4000:])
    return result.returncode == 0


def scalar(data_dir: Path, sql: str):
    with duckdb.connect(str(data_dir / "warehouse.duckdb"), read_only=True) as con:
        return con.execute(sql).fetchone()[0]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LVM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LVM_RAW_URI", raising=False)
    run_sample(FIXTURES, Settings(data_dir=tmp_path, raw_uri=""))
    return tmp_path


def test_full_build_passes_every_test_and_exports_all_marts(data_dir: Path, tmp_path: Path):
    assert dbt_build(tmp_path)

    transactions = read_rows(SANDORIS_CSV)
    assert scalar(data_dir, "select count(*) from marts.fct_vehicle_transactions") == len(
        transactions
    )
    assert scalar(data_dir, "select count(*) from marts.agg_market_monthly") > 0

    exported = run_export(Settings())
    assert {p.stem for p in exported} == set(EXPORTED_MARTS)
    for path in exported:
        rows = duckdb.execute(f"select count(*) from read_parquet('{path}')").fetchone()[0]
        assert rows > 0, f"{path.name} is empty"


def test_republished_inspections_are_counted_once(data_dir: Path, tmp_path: Path):
    assert dbt_build(tmp_path)

    inspections = read_rows(APZIURA_CSV)
    content = [
        tuple(v for k, v in row.items() if k not in ("_id", "vda_id")) for row in inspections
    ]
    assert len(set(content)) < len(content), "the fixture must contain re-published rows"

    assert scalar(data_dir, "select count(*) from marts.fct_inspections") == len(set(content))
    assert scalar(data_dir, "select duplicate_rows_removed from marts.agg_fleet_status") == (
        len(content) - len(set(content))
    )
    assert scalar(data_dir, "select count(*) from marts.dim_vehicles") == len(
        {row["tp_id"] for row in inspections}
    )


def test_incremental_run_applies_late_modification_once(data_dir: Path, tmp_path: Path):
    assert dbt_build(tmp_path)
    before = scalar(data_dir, "select count(*) from marts.fct_vehicle_transactions")

    # The source edits one document later: it re-appears in a newer partition
    # with a new amount and modification timestamp.
    rows = read_rows(SANDORIS_CSV)
    edited = next(row for row in rows if row["valiuta"] == "Euras")
    edited |= {"suma": "12345.0", "iraso_mod_data": "2026-11-20T10:00:00"}
    update_csv = tmp_path / "update.csv"
    with update_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SANDORIS.columns))
        writer.writeheader()
        writer.writerow(edited)
    land(SANDORIS, update_csv, data_dir, "2026-11")

    assert dbt_build(tmp_path)  # incremental run

    after = scalar(data_dir, "select count(*) from marts.fct_vehicle_transactions")
    amount = scalar(
        data_dir,
        "select declared_amount from marts.fct_vehicle_transactions "
        f"where transaction_id = '{edited['_id']}'",
    )
    assert after == before  # updated in place, not duplicated
    assert float(amount) == 12345.0
