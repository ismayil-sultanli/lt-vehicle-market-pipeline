from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote

import duckdb
import httpx
import pytest
import respx

from lt_vehicle_market.config import APZIURA, SANDORIS, Settings
from lt_vehicle_market.extract import (
    ExtractError,
    RowCountMismatch,
    SchemaMismatch,
    _is_retryable,
    csv_to_parquet,
    extract_partition,
    month_range,
    next_month,
    plan_partitions,
    run_extract,
    window_filter,
)
from lt_vehicle_market.storage import RawStore

SOURCE_COLUMNS = SANDORIS.columns
HEADER = ",".join(SOURCE_COLUMNS)
ROW = (
    "{id},doc{id},act{id},Pirkimo-pardavimo sutartis,2026-10-03T00:00:00,"
    "LIETUVA,4500.0,Euras,Bankiniu pavedimu,2026-10-04T09:15:00"
)


def part(store: RawStore, month: date, spec=SANDORIS) -> Path:
    """Local path of a partition file."""
    return Path(store.partition_uri(spec, month))


def local_store(settings: Settings) -> RawStore:
    return RawStore(settings.raw_root)


def csv_body(n: int) -> str:
    return "\n".join([HEADER, *(ROW.format(id=i) for i in range(n))]) + "\n"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(api_base="https://api.test", data_dir=tmp_path)


def mock_api(router: respx.MockRouter, count: int, rows: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "count()" in request.url.query.decode():
            return httpx.Response(200, json={"_data": [{"count()": count}]})
        return httpx.Response(200, text=csv_body(rows))

    router.get(url__startswith=f"https://api.test/{SANDORIS.path}").mock(side_effect=handler)


# ----------------------------------------------------------------- windows --
def test_next_month_rolls_over_year():
    assert next_month(date(2025, 12, 1)) == date(2026, 1, 1)


def test_month_range_is_inclusive():
    assert month_range(date(2025, 11, 17), date(2026, 2, 3)) == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]


def test_first_partition_is_open_ended():
    assert window_filter(SANDORIS, date(2021, 5, 1)) == 'iraso_mod_data<"2021-06-01"'


def test_each_dataset_is_windowed_on_its_own_column_and_folder(tmp_path: Path):
    assert window_filter(APZIURA, date(2024, 12, 1)) == (
        'ta_savaites_data>="2024-12-01"&ta_savaites_data<"2025-01-01"'
    )
    store = RawStore(tmp_path)
    inspections = part(store, date(2024, 12, 1), APZIURA)
    assert inspections.parent.name == "inspection_month=2024-12"
    assert inspections.parent.parent == tmp_path / "apziura"
    assert part(store, date(2024, 12, 1)).parent.name == "mod_month=2024-12"


def test_since_before_the_first_partition_is_clamped(tmp_path: Path):
    plan = plan_partitions(
        RawStore(tmp_path), SANDORIS, today=date(2021, 6, 2), since=date(2019, 1, 1)
    )
    assert plan == [date(2021, 5, 1), date(2021, 6, 1)]


def test_regular_partition_is_half_open_interval():
    assert window_filter(SANDORIS, date(2026, 10, 1)) == (
        'iraso_mod_data>="2026-10-01"&iraso_mod_data<"2026-11-01"'
    )


# ---------------------------------------------------------------- planning --
def test_plan_first_run_is_full_backfill(tmp_path: Path):
    plan = plan_partitions(RawStore(tmp_path), SANDORIS, today=date(2021, 8, 15))
    assert plan == [date(2021, m, 1) for m in (5, 6, 7, 8)]


def test_plan_incremental_only_refreshes_recent_and_missing(tmp_path: Path):
    for m in (5, 6, 8, 9):  # July is a gap that must be repaired
        p = part(RawStore(tmp_path), date(2021, m, 1))
        p.parent.mkdir(parents=True)
        p.touch()
    plan = plan_partitions(RawStore(tmp_path), SANDORIS, today=date(2021, 9, 20), refresh_months=2)
    assert plan == [date(2021, 7, 1), date(2021, 8, 1), date(2021, 9, 1)]


def test_plan_full_refresh_ignores_existing(tmp_path: Path):
    p = part(RawStore(tmp_path), date(2021, 5, 1))
    p.parent.mkdir(parents=True)
    p.touch()
    assert (
        len(
            plan_partitions(RawStore(tmp_path), SANDORIS, today=date(2021, 6, 1), full_refresh=True)
        )
        == 2
    )


# ----------------------------------------------------------------- landing --
def test_reordered_or_renamed_columns_are_rejected(tmp_path: Path):
    reordered = [SOURCE_COLUMNS[1], SOURCE_COLUMNS[0], *SOURCE_COLUMNS[2:]]
    bad = tmp_path / "bad.csv"
    bad.write_text(",".join(reordered) + "\n" + ",".join("x" * len(reordered)) + "\n")
    with pytest.raises(SchemaMismatch):
        csv_to_parquet(bad, tmp_path / "out.parquet", datetime(2026, 1, 1), SOURCE_COLUMNS)


def test_quoted_commas_and_escaped_quotes_survive_the_round_trip(tmp_path: Path):
    # Real cases: document types containing commas, and a trailer model named 10"
    # which the API writes as "10""" (RFC 4180).
    src = tmp_path / "quoted.csv"
    src.write_text(
        HEADER + "\n" + '1,d1,a1,"Prašymas, patvirtintas URM",2026-10-03T00:00:00,'
        'LIETUVA,10.0,"Nežinomas, nenurodyta",Nenurodyta,2026-10-04T09:15:00\n'
        '2,d2,a2,"10""",2026-10-03T00:00:00,LIETUVA,5.0,Euras,Nenurodyta,2026-10-04T09:15:00\n',
        encoding="utf-8",
    )
    out = tmp_path / "out.parquet"
    assert csv_to_parquet(src, out, datetime(2026, 1, 1), SOURCE_COLUMNS) == 2
    rows = duckdb.execute(
        "select dok_rusis, valiuta "
        f"from read_parquet('{out}', hive_partitioning = false) order by _id"
    ).fetchall()
    assert rows == [
        ("Prašymas, patvirtintas URM", "Nežinomas, nenurodyta"),
        ('10"', "Euras"),
    ]


@pytest.mark.parametrize(
    ("status", "expected"), [(500, True), (503, True), (429, True), (400, False), (404, False)]
)
def test_only_server_side_failures_are_retried(status: int, expected: bool):
    request = httpx.Request("GET", "https://api.test")
    exc = httpx.HTTPStatusError(
        "x", request=request, response=httpx.Response(status, request=request)
    )
    assert _is_retryable(exc) is expected
    assert _is_retryable(httpx.ConnectError("down")) is True


# ----------------------------------------------------------------- extract --
@respx.mock
def test_extract_partition_writes_typed_free_parquet(settings: Settings):
    mock_api(respx.mock, count=3, rows=3)
    with httpx.Client() as client:
        result = extract_partition(
            client, settings, local_store(settings), SANDORIS, date(2026, 10, 1)
        )

    assert (result.month, result.rows, result.api_count) == ("2026-10", 3, 3)
    path = part(local_store(settings), date(2026, 10, 1))
    schema = duckdb.execute(
        f"describe select * from read_parquet('{path}', hive_partitioning = false)"
    ).fetchall()
    assert [col[0] for col in schema] == [*SOURCE_COLUMNS, "_extracted_at"]
    # raw layer stays untyped: casting is dbt's job
    assert {col[1] for col in schema[: len(SOURCE_COLUMNS)]} == {"VARCHAR"}


@respx.mock
def test_truncated_download_is_rejected_and_keeps_previous_file(settings: Settings):
    month = date(2026, 10, 1)
    final = part(local_store(settings), month)
    final.parent.mkdir(parents=True)
    final.write_text("previous good partition")

    mock_api(respx.mock, count=10, rows=4)
    with httpx.Client() as client, pytest.raises(RowCountMismatch):
        extract_partition(client, settings, local_store(settings), SANDORIS, month)

    assert final.read_text() == "previous good partition"
    assert list(final.parent.iterdir()) == [final]  # temp files cleaned up


@respx.mock
def test_run_extract_is_idempotent_and_writes_manifest(settings: Settings):
    mock_api(respx.mock, count=2, rows=2)
    kwargs = dict(spec=SANDORIS, settings=settings, today=date(2021, 6, 10), refresh_months=1)

    first = run_extract(**kwargs)
    second = run_extract(**kwargs)

    assert [r.month for r in first] == ["2021-05", "2021-06"]
    assert [r.month for r in second] == ["2021-06"]  # only the open month again
    total = duckdb.execute(
        f"select count(*) from read_parquet('{settings.raw_root}/sandoris/*/*.parquet')"
    ).fetchone()[0]
    assert total == 4  # re-running did not duplicate rows
    assert Path(local_store(settings).manifest_uri(SANDORIS)).exists()


@respx.mock
def test_one_failed_partition_does_not_hide_the_successful_ones(settings: Settings):
    def handler(request: httpx.Request) -> httpx.Response:
        query = unquote(request.url.query.decode())
        if "count()" in query:
            return httpx.Response(200, json={"_data": [{"count()": 2}]})
        # the 2021-06 window (the one ending at 2021-07-01) is cut short by the server
        return httpx.Response(200, text=csv_body(1 if '<"2021-07-01"' in query else 2))

    respx.mock.get(url__startswith=f"https://api.test/{SANDORIS.path}").mock(side_effect=handler)

    with pytest.raises(ExtractError, match="2021-06"):
        run_extract(SANDORIS, settings=settings, today=date(2021, 7, 10))

    raw_dir = Path(settings.raw_root) / "sandoris"
    landed = sorted(p.parent.name for p in raw_dir.glob("*/data.parquet"))
    assert landed == ["mod_month=2021-05", "mod_month=2021-07"]
    manifest = json.loads((raw_dir / "_manifest.json").read_text())
    assert sorted(manifest) == ["2021-05", "2021-07"]


def test_partition_missing_from_the_manifest_is_reloaded(tmp_path: Path):
    for m in (5, 6, 7, 8):
        p = part(RawStore(tmp_path), date(2021, m, 1))
        p.parent.mkdir(parents=True)
        p.touch()
    plan = plan_partitions(
        RawStore(tmp_path), SANDORIS, today=date(2021, 8, 20), refresh_months=1,
        recorded={"2021-05", "2021-07", "2021-08"},
    )  # fmt: skip
    assert plan == [date(2021, 6, 1), date(2021, 8, 1)]
