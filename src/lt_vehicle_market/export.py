"""Publish the aggregate marts as Parquet files: the dashboard's serving layer.

The dashboard never opens the warehouse. It reads these small files, locally or
over HTTPS, so it can be hosted anywhere without shipping 9M+ fact rows.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from lt_vehicle_market.config import Settings

log = logging.getLogger(__name__)

EXPORTED_MARTS: tuple[str, ...] = (
    "agg_market_monthly",
    "agg_payment_methods_monthly",
    "agg_cash_limit_bunching_monthly",
    "agg_import_origins_monthly",
    "agg_transaction_types_monthly",
    "agg_price_bands_yearly",
    "agg_pipeline_status",
    "agg_fleet_fuel_yearly",
    "agg_fleet_makes_yearly",
    "agg_fleet_models",
    "agg_fleet_municipalities",
    "agg_pass_rate_by_age",
    "agg_annual_mileage",
    "agg_odometer_checks_yearly",
    "agg_fleet_status",
)


def run_export(settings: Settings | None = None) -> list[Path]:
    settings = settings or Settings()
    settings.export_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        for mart in EXPORTED_MARTS:
            target = settings.export_dir / f"{mart}.parquet"
            con.execute(
                f"copy (select * from marts.{mart}) to '{target}' "
                "(format parquet, compression zstd)"
            )
            log.info("exported %s (%.0f kB)", target, target.stat().st_size / 1e3)
            written.append(target)
    finally:
        con.close()
    return written
