"""Raw-layer storage: a local folder or an S3-compatible bucket behind one interface.

The extractor always builds a partition in a local temp directory and only then
*publishes* it. Publishing is atomic in both back ends: a rename on a local
filesystem, a single PUT on object storage. A reader therefore sees either the
previous complete partition or the new complete one, never a partial file.

Set ``LVM_RAW_URI=s3://bucket/prefix`` to use object storage (AWS S3, Cloudflare
R2, MinIO, ...). Credentials come from the standard AWS environment variables;
``LVM_S3_ENDPOINT_URL`` points at a non-AWS endpoint.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import fsspec

from lt_vehicle_market.config import DatasetSpec


class RawStore:
    def __init__(self, root: str | Path, endpoint_url: str | None = None) -> None:
        self.root = str(root).rstrip("/")
        self.is_remote = "://" in self.root and not self.root.startswith("file://")
        options: dict[str, Any] = {}
        if self.is_remote and endpoint_url:
            options["client_kwargs"] = {"endpoint_url": endpoint_url}
        self.fs: Any
        self.fs, self._base = fsspec.core.url_to_fs(self.root, **options)

    # ------------------------------------------------------------- layout --
    def dataset_uri(self, spec: DatasetSpec) -> str:
        return f"{self._base}/{spec.name}"

    def partition_uri(self, spec: DatasetSpec, month: date) -> str:
        return f"{self.dataset_uri(spec)}/{spec.partition_key}={month:%Y-%m}/data.parquet"

    def manifest_uri(self, spec: DatasetSpec) -> str:
        return f"{self.dataset_uri(spec)}/_manifest.json"

    # ---------------------------------------------------------------- I/O --
    def exists(self, uri: str) -> bool:
        return bool(self.fs.exists(uri))

    def size(self, uri: str) -> int:
        return int(self.fs.size(uri))

    @contextmanager
    def staging_dir(self, dest_uri: str) -> Iterator[Path]:
        """A local scratch directory for building the file that goes to ``dest_uri``.

        For a local store it sits next to the destination, so the final rename
        stays on one filesystem and is atomic.
        """
        if self.is_remote:
            with tempfile.TemporaryDirectory() as tmp:
                yield Path(tmp)
        else:
            parent = Path(dest_uri).parent
            parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=parent) as tmp:
                yield Path(tmp)

    def publish(self, local_file: Path, dest_uri: str) -> None:
        """Atomically make ``local_file`` the content of ``dest_uri``."""
        if self.is_remote:
            self.fs.put_file(str(local_file), dest_uri)
        else:
            Path(dest_uri).parent.mkdir(parents=True, exist_ok=True)
            os.replace(local_file, dest_uri)

    def read_json(self, uri: str) -> dict[str, Any]:
        if not self.exists(uri):
            return {}
        with self.fs.open(uri, "r", encoding="utf-8") as fh:
            data: dict[str, Any] = json.load(fh)
        return data

    def write_json(self, uri: str, data: dict[str, Any]) -> None:
        with self.staging_dir(uri) as tmp:
            local = tmp / "document.json"
            local.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            self.publish(local, uri)
