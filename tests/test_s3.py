"""The raw layer on object storage, against a local S3 emulator (moto).

Covers the whole remote path: the extractor publishes partitions and the
manifest to a bucket, and dbt (target ``s3``) builds the warehouse by reading
them straight from the bucket. No AWS account or network access is needed.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import duckdb
import httpx
import pytest
import respx

from lt_vehicle_market.config import SANDORIS, Settings
from lt_vehicle_market.extract import run_extract
from lt_vehicle_market.storage import RawStore

moto_server = pytest.importorskip("moto.server")
boto3 = pytest.importorskip("boto3")

ROOT = Path(__file__).resolve().parents[1]
BUCKET = "lvm-test-lake"
HEADER = ",".join(SANDORIS.columns)
ROW = (
    "{id},doc{id},act{id},Pirkimo-pardavimo sutartis,2026-10-03T00:00:00,"
    "LIETUVA,4500.0,Euras,Bankiniu pavedimu,2026-10-04T09:15:00"
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def s3_endpoint() -> Iterator[str]:
    port = free_port()
    server = moto_server.ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    endpoint = f"http://127.0.0.1:{port}"
    previous = {k: os.environ.get(k) for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")}
    os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing")
    boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1").create_bucket(Bucket=BUCKET)
    try:
        yield endpoint
    finally:
        server.stop()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_store_round_trip_on_object_storage(s3_endpoint: str, tmp_path: Path):
    store = RawStore(f"s3://{BUCKET}/roundtrip", endpoint_url=s3_endpoint)
    assert store.is_remote

    dest = store.partition_uri(SANDORIS, date(2026, 10, 1))
    assert not store.exists(dest)
    with store.staging_dir(dest) as tmp:
        assert not str(tmp).startswith(f"{BUCKET}")  # staging is always local
        (tmp / "f.parquet").write_bytes(b"PAR1-test")
        store.publish(tmp / "f.parquet", dest)

    assert store.exists(dest)
    assert store.size(dest) == len(b"PAR1-test")
    assert store.read_json(store.manifest_uri(SANDORIS)) == {}
    store.write_json(store.manifest_uri(SANDORIS), {"2026-10": {"rows": 3}})
    assert store.read_json(store.manifest_uri(SANDORIS)) == {"2026-10": {"rows": 3}}


@respx.mock  # only httpx is intercepted; s3fs talks to the emulator through aiohttp
def test_extract_to_bucket_then_dbt_builds_from_bucket(
    s3_endpoint: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # 1. extract into the bucket (the open data API is mocked)
    served = iter(range(1_000))  # every row gets its own id, across partitions

    def api(request: httpx.Request) -> httpx.Response:
        if "count()" in request.url.query.decode():
            return httpx.Response(200, json={"_data": [{"count()": 3}]})
        rows = "\n".join(ROW.format(id=next(served)) for _ in range(3))
        return httpx.Response(200, text=f"{HEADER}\n{rows}\n")

    respx.route(host="api.test").mock(side_effect=api)
    raw_uri = f"s3://{BUCKET}/lake"
    settings = Settings(
        api_base="https://api.test", data_dir=tmp_path, raw_uri=raw_uri, s3_endpoint_url=s3_endpoint
    )
    results = run_extract(SANDORIS, settings=settings, today=date(2021, 6, 15))
    assert [r.month for r in results] == ["2021-05", "2021-06"]

    store = RawStore(raw_uri, endpoint_url=s3_endpoint)
    assert store.exists(store.partition_uri(SANDORIS, date(2021, 6, 1)))
    manifest = store.read_json(store.manifest_uri(SANDORIS))
    assert sorted(manifest) == ["2021-05", "2021-06"]
    assert not (tmp_path / "raw").exists()  # nothing landed on local disk

    # 2. dbt reads the raw layer straight from the bucket
    env = os.environ | {
        "LVM_DATA_DIR": str(tmp_path),
        "LVM_RAW_URI": raw_uri,
        "LVM_S3_ENDPOINT_URL": s3_endpoint,
        "AWS_DEFAULT_REGION": "us-east-1",
        "DBT_TARGET": "s3",
    }
    dbt = Path(sys.executable).parent / "dbt"
    result = subprocess.run(
        [
            str(dbt), "run",
            "--project-dir", str(ROOT / "dbt"),
            "--profiles-dir", str(ROOT / "dbt"),
            "--target-path", str(tmp_path / "target"),
            "--log-path", str(tmp_path / "logs"),
            "--select", "stg_regitra__transactions",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout[-3000:]

    with duckdb.connect(str(tmp_path / "warehouse.duckdb"), read_only=True) as con:
        loaded = con.execute("select count(*) from staging.stg_regitra__transactions").fetchone()
    assert loaded == (sum(r.rows for r in results),)
    assert json.dumps(manifest)  # manifest is plain JSON
