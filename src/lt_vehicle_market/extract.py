"""Extract datasets from the Lithuanian open data API into partitioned Parquet.

Design
------
* The extractor is generic: a :class:`DatasetSpec` names the dataset, its
  columns and the date column the monthly partitions are cut on.
* For a mutable dataset the partition column is the modification timestamp, so
  a closed month never changes and only the newest partitions are re-pulled.
* Every run is idempotent: a partition is built in a local temp directory,
  validated against the API's own ``count()`` and only then atomically
  published to the raw store (a local folder or an S3-compatible bucket).
* A record modified again later also shows up in a newer partition. The raw
  layer keeps both versions (append-only history); deduplication to the latest
  version happens in the dbt staging model.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import ParamSpec, TypeVar
from urllib.parse import quote

import duckdb
import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from lt_vehicle_market.config import DatasetSpec, Settings
from lt_vehicle_market.storage import RawStore

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


class RowCountMismatch(RuntimeError):
    """Downloaded fewer rows than the API reported for the same window."""


class ExtractError(RuntimeError):
    """At least one partition of a run could not be loaded."""


class SchemaMismatch(RuntimeError):
    """The CSV header is not the column list that was requested."""


@dataclass(frozen=True)
class PartitionResult:
    dataset: str
    month: str
    rows: int
    api_count: int
    bytes: int
    extracted_at: str


# --------------------------------------------------------------------------- #
# Partition windows
# --------------------------------------------------------------------------- #
def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def month_range(start: date, end: date) -> list[date]:
    """All month starts from ``start`` to ``end`` inclusive."""
    months, cur = [], month_start(start)
    while cur <= month_start(end):
        months.append(cur)
        cur = next_month(cur)
    return months


def window_filter(spec: DatasetSpec, month: date) -> str:
    """Query filter selecting the records that belong to ``month``.

    The first partition is open-ended on the left so nothing older is lost.
    """
    upper = f'{spec.partition_field}<"{next_month(month).isoformat()}"'
    if month <= spec.first_partition:
        return upper
    return f'{spec.partition_field}>="{month.isoformat()}"&{upper}'


# --------------------------------------------------------------------------- #
# API access
# --------------------------------------------------------------------------- #
def _url(settings: Settings, spec: DatasetSpec, query: str) -> str:
    return f"{settings.dataset_url(spec)}?{quote(query, safe='()&=,_')}"


def _is_retryable(exc: BaseException) -> bool:
    """Network failures, throttling and server errors; never a 4xx client error."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def _retrying(fn: Callable[P, R]) -> Callable[P, R]:
    wrapped: Callable[P, R] = retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )(fn)
    return wrapped


@_retrying
def fetch_count(client: httpx.Client, settings: Settings, spec: DatasetSpec, month: date) -> int:
    resp = client.get(_url(settings, spec, f"{window_filter(spec, month)}&count()"))
    resp.raise_for_status()
    return int(resp.json()["_data"][0]["count()"])


@_retrying
def download_csv(
    client: httpx.Client, settings: Settings, spec: DatasetSpec, month: date, dest: Path
) -> int:
    """Stream one partition as CSV to ``dest``. Returns bytes written."""
    select = f"select({','.join(spec.columns)})"
    url = _url(settings, spec, f"{window_filter(spec, month)}&{select}&format(csv)")
    written = 0
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                fh.write(chunk)
                written += len(chunk)
    return written


# --------------------------------------------------------------------------- #
# Landing
# --------------------------------------------------------------------------- #
def csv_to_parquet(
    csv_path: Path, parquet_path: Path, extracted_at: datetime, columns: tuple[str, ...]
) -> int:
    """Convert a downloaded CSV into a zstd Parquet file. Returns the row count.

    Everything stays VARCHAR in the raw layer: typing is a transformation and
    belongs to dbt, where a bad value can be tested instead of crashing the load.
    """
    # Columns are read by position, so the header must be exactly what was asked for.
    with csv_path.open(encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh), [])
    if tuple(header) != tuple(columns):
        raise SchemaMismatch(f"expected columns {list(columns)}, got {header}")

    column_types = ", ".join(f"'{c}': 'VARCHAR'" for c in columns)
    con = duckdb.connect()
    try:
        # hive_partitioning is disabled on purpose: the temp file lives inside the
        # partition directory and the partition key must not leak into the file.
        con.execute(
            f"""
            copy (
                select *, timestamp '{extracted_at:%Y-%m-%d %H:%M:%S}' as _extracted_at
                from read_csv(
                    '{csv_path}',
                    header = true,
                    columns = {{{column_types}}},
                    -- RFC 4180 spelled out: with explicit columns DuckDB would
                    -- otherwise guess the dialect and misread values like 10""
                    delim = ',', quote = '"', escape = '"',
                    hive_partitioning = false
                )
            ) to '{parquet_path}' (format parquet, compression zstd)
            """
        )
        row = con.execute(
            f"select count(*) from read_parquet('{parquet_path}', hive_partitioning = false)"
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()


def extract_partition(
    client: httpx.Client, settings: Settings, store: RawStore, spec: DatasetSpec, month: date
) -> PartitionResult:
    """Download, validate and atomically publish one monthly partition."""
    dest = store.partition_uri(spec, month)
    extracted_at = datetime.now(UTC).replace(microsecond=0)

    api_count = fetch_count(client, settings, spec, month)
    with store.staging_dir(dest) as tmp:
        csv_path, tmp_parquet = tmp / "part.csv", tmp / "part.parquet"
        size = download_csv(client, settings, spec, month, csv_path)
        rows = csv_to_parquet(csv_path, tmp_parquet, extracted_at, spec.columns)
        # The open month keeps growing while we download, so more rows than the
        # earlier count is fine; fewer means a truncated response.
        if rows < api_count:
            raise RowCountMismatch(
                f"{spec.name} {month:%Y-%m}: got {rows} rows, API reported {api_count}"
            )
        parquet_bytes = tmp_parquet.stat().st_size
        store.publish(tmp_parquet, dest)

    log.info("%s %s: %s rows (%.1f MB csv)", spec.name, f"{month:%Y-%m}", f"{rows:,}", size / 1e6)
    return PartitionResult(
        dataset=spec.name,
        month=f"{month:%Y-%m}",
        rows=rows,
        api_count=api_count,
        bytes=parquet_bytes,
        extracted_at=extracted_at.isoformat(),
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def plan_partitions(
    store: RawStore,
    spec: DatasetSpec,
    today: date,
    refresh_months: int = 2,
    full_refresh: bool = False,
    since: date | None = None,
    recorded: Collection[str] | None = None,
) -> list[date]:
    """Decide which partitions this run must (re)load.

    * anything missing on disk (first run = full backfill, later = gap repair)
    * anything on disk that the manifest does not vouch for (``recorded`` holds
      the manifest's months), e.g. after a run that was killed mid-way
    * the last ``refresh_months`` months, which may still receive new records
    """
    months = month_range(max(since or spec.first_partition, spec.first_partition), today)
    if full_refresh:
        return months
    volatile = set(months[-refresh_months:]) if refresh_months > 0 else set()

    def needs_load(month: date) -> bool:
        if month in volatile or not store.exists(store.partition_uri(spec, month)):
            return True
        return recorded is not None and f"{month:%Y-%m}" not in recorded

    return [m for m in months if needs_load(m)]


def run_extract(
    spec: DatasetSpec,
    settings: Settings | None = None,
    today: date | None = None,
    refresh_months: int = 2,
    full_refresh: bool = False,
    since: date | None = None,
) -> list[PartitionResult]:
    settings = settings or Settings()
    today = today or datetime.now(UTC).date()
    store = RawStore(settings.raw_root, settings.s3_endpoint_url)

    manifest_uri = store.manifest_uri(spec)
    manifest = store.read_json(manifest_uri)
    todo = plan_partitions(
        store, spec, today, refresh_months, full_refresh, since, recorded=manifest.keys()
    )
    log.info(
        "%s: extracting %d partition(s) into %s/%s", spec.name, len(todo), store.root, spec.name
    )

    results: list[PartitionResult] = []
    failures: list[tuple[date, BaseException]] = []
    with (
        httpx.Client(
            headers={"User-Agent": settings.user_agent},
            timeout=httpx.Timeout(settings.request_timeout_s, connect=30.0),
            follow_redirects=True,
        ) as client,
        ThreadPoolExecutor(max_workers=settings.max_workers) as pool,
    ):
        futures = {
            pool.submit(extract_partition, client, settings, store, spec, m): m for m in todo
        }
        # One failed partition must not hide the ones that succeeded: every
        # success is recorded first, the failure is raised at the end.
        for fut in as_completed(futures):
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001 - re-raised below
                log.error("%s %s failed: %s", spec.name, f"{futures[fut]:%Y-%m}", exc)
                failures.append((futures[fut], exc))
                continue
            results.append(res)
            manifest[res.month] = asdict(res)
            store.write_json(manifest_uri, manifest)

    total = sum(r.rows for r in results)
    log.info("%s: done, %d partition(s), %s rows", spec.name, len(results), f"{total:,}")
    if failures:
        failed = ", ".join(f"{month:%Y-%m}" for month, _ in sorted(failures, key=lambda f: f[0]))
        raise ExtractError(
            f"{spec.name}: {len(failures)} partition(s) failed ({failed})"
        ) from failures[0][1]
    return sorted(results, key=lambda r: r.month)
