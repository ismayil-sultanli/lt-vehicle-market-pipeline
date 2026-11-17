from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from lt_vehicle_market.config import APZIURA, SANDORIS, Settings
from lt_vehicle_market.sample import land_csv, run_sample
from lt_vehicle_market.storage import RawStore

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def rows_in(path: Path) -> int:
    return duckdb.execute(f"select count(*) from read_csv('{path}', header = true)").fetchone()[0]


def test_samples_are_split_into_the_extractors_monthly_partitions(tmp_path: Path):
    store = RawStore(tmp_path)
    written = land_csv(SANDORIS, FIXTURES / "sandoris_sample.csv", store)

    assert sum(written.values()) == rows_in(FIXTURES / "sandoris_sample.csv")
    folders = sorted(p.name for p in (tmp_path / "sandoris").iterdir())
    assert folders == [f"mod_month={month}" for month in sorted(written)]
    # every row sits in the partition of its own modification month
    misplaced = duckdb.execute(
        f"select count(*) from read_parquet('{tmp_path}/sandoris/*/*.parquet', "
        "hive_partitioning = true) where substr(iraso_mod_data, 1, 7) <> mod_month"
    ).fetchone()[0]
    assert misplaced == 0
    # no scratch files left behind next to the partitions
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sandoris"]


def test_run_sample_lands_both_datasets(tmp_path: Path):
    landed = run_sample(FIXTURES, Settings(data_dir=tmp_path, raw_uri=""))

    assert set(landed) == {SANDORIS.name, APZIURA.name}
    assert sum(landed[APZIURA.name].values()) == rows_in(FIXTURES / "apziura_sample.csv")
    assert all(name.startswith("inspection_month=") for name in
               (p.name for p in (tmp_path / "raw" / "apziura").iterdir()))  # fmt: skip


def test_missing_sample_files_fail_with_a_clear_message(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="sandoris_sample.csv"):
        run_sample(tmp_path / "empty", Settings(data_dir=tmp_path, raw_uri=""))
