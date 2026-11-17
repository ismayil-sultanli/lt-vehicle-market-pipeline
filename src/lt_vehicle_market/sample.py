"""Load the bundled sample datasets into the raw layer, without the API.

The samples in ``tests/fixtures`` are small extracts of the real datasets. Landed
with :func:`run_sample`, they let anyone run the whole pipeline (dbt build,
export, dashboard) in under a minute on a fresh clone, and give the dbt unit
tests the upstream tables they need.

Rows are split into the same monthly partitions the extractor would write, so
the raw layer looks exactly like a real one.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from lt_vehicle_market.config import APZIURA, SANDORIS, DatasetSpec, Settings
from lt_vehicle_market.extract import csv_to_parquet
from lt_vehicle_market.storage import RawStore

log = logging.getLogger(__name__)

SAMPLES: dict[str, DatasetSpec] = {
    "sandoris_sample.csv": SANDORIS,
    "apziura_sample.csv": APZIURA,
}


def land_csv(spec: DatasetSpec, csv_path: Path, store: RawStore) -> dict[str, int]:
    """Publish a CSV with the dataset's columns as monthly partitions.

    Returns the number of rows written per partition month.
    """
    extracted_at = datetime.now(UTC).replace(microsecond=0)
    written: dict[str, int] = {}
    # Staged next to (not inside) the dataset folder, so the scratch files can
    # never match the `<dataset>/*/*.parquet` pattern dbt reads.
    with store.staging_dir(store.dataset_uri(spec)) as tmp:
        full = tmp / "all.parquet"
        csv_to_parquet(csv_path, full, extracted_at, spec.columns)
        con = duckdb.connect()
        try:
            months = [
                row[0]
                for row in con.execute(
                    f"select distinct substr({spec.partition_field}, 1, 7) "
                    f"from read_parquet('{full}', hive_partitioning = false) order by 1"
                ).fetchall()
            ]
            for month in months:
                part = tmp / f"{month}.parquet"
                con.execute(
                    f"""
                    copy (
                        select * from read_parquet('{full}', hive_partitioning = false)
                        where substr({spec.partition_field}, 1, 7) = '{month}'
                    ) to '{part}' (format parquet, compression zstd)
                    """
                )
                row = con.execute(f"select count(*) from read_parquet('{part}')").fetchone()
                year, mon = (int(x) for x in month.split("-"))
                store.publish(part, store.partition_uri(spec, date(year, mon, 1)))
                written[month] = int(row[0]) if row else 0
        finally:
            con.close()
    log.info(
        "%s: landed %s sample rows in %d partitions",
        spec.name,
        f"{sum(written.values()):,}",
        len(written),
    )
    return written


def run_sample(source_dir: Path, settings: Settings | None = None) -> dict[str, dict[str, int]]:
    """Land every bundled sample found in ``source_dir``."""
    settings = settings or Settings()
    store = RawStore(settings.raw_root, settings.s3_endpoint_url)
    missing = [name for name in SAMPLES if not (source_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"sample files not found in {source_dir}: {', '.join(missing)}")
    return {spec.name: land_csv(spec, source_dir / name, store) for name, spec in SAMPLES.items()}
