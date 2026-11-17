"""Runtime configuration and the catalogue of source datasets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class DatasetSpec:
    """Everything the generic extractor needs to know about one API dataset.

    ``columns`` is requested explicitly, which makes the extract a schema
    contract: an upstream rename fails loudly instead of producing NULLs.
    ``partition_field`` is the date/timestamp column the monthly windows are cut
    on. For a mutable dataset it must be the modification timestamp, so that a
    closed month can never change; for an append-only one the event date works.
    """

    name: str
    path: str
    columns: tuple[str, ...]
    partition_field: str
    partition_key: str
    first_partition: date
    description: str = ""


#: Vehicle ownership-transfer documents (AB Regitra). Mutable: partitioned on the
#: modification timestamp. Everything modified before the first partition month
#: is collected into it.
SANDORIS = DatasetSpec(
    name="sandoris",
    path="datasets/gov/regitra/tpsais/Sandoris",
    columns=(
        "_id",
        "dok_id",
        "veiklos_id",
        "dok_rusis",
        "isd_data",
        "salis",
        "suma",
        "valiuta",
        "mokejimo_budas",
        "iraso_mod_data",
    ),
    partition_field="iraso_mod_data",
    partition_key="mod_month",
    first_partition=date(2021, 5, 1),
    description="Vehicle ownership-transfer documents",
)

#: Periodic roadworthiness inspections (TRANSEKSTA). Append-only, dated to the
#: week: partitioned on the inspection week.
APZIURA = DatasetSpec(
    name="apziura",
    path="datasets/gov/transeksta/ctadb/Apziura",
    columns=(
        "_id",
        "vda_id",
        "tp_id",
        "tp_marke",
        "tp_modelis",
        "tp_klase",
        "tp_kebulas",
        "tp_pag_metai",
        "tp_kuras",
        "tp_rida_km",
        "ta_stoties_kodas",
        "ta_stoties_savivaldybe",
        "ta_tipas",
        "ta_isvada",
        "ar_ta_islaikyta",
        "ta_savaites_data",
        "ta_periodiskumas_men",
    ),
    partition_field="ta_savaites_data",
    partition_key="inspection_month",
    first_partition=date(2015, 1, 1),
    description="Technical (roadworthiness) inspections",
)

DATASETS: dict[str, DatasetSpec] = {spec.name: spec for spec in (SANDORIS, APZIURA)}


@dataclass(frozen=True)
class Settings:
    api_base: str = field(
        default_factory=lambda: os.getenv("LVM_API_BASE", "https://get.data.gov.lt")
    )
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("LVM_DATA_DIR", "data")))
    #: Where the raw layer lives: a local path or an ``s3://bucket/prefix`` URI.
    #: Empty means ``<data_dir>/raw``.
    raw_uri: str = field(default_factory=lambda: os.getenv("LVM_RAW_URI", ""))
    #: Endpoint of a non-AWS object store (Cloudflare R2, MinIO, ...).
    s3_endpoint_url: str | None = field(
        default_factory=lambda: os.getenv("LVM_S3_ENDPOINT_URL") or None
    )
    user_agent: str = "lt-vehicle-market-pipeline/0.3 (open-data ELT; educational project)"
    request_timeout_s: float = 600.0
    max_workers: int = field(default_factory=lambda: int(os.getenv("LVM_MAX_WORKERS", "3")))

    def dataset_url(self, spec: DatasetSpec) -> str:
        return f"{self.api_base.rstrip('/')}/{spec.path.strip('/')}"

    @property
    def raw_root(self) -> str:
        return self.raw_uri or str(self.data_dir / "raw")

    @property
    def warehouse_path(self) -> Path:
        return self.data_dir / "warehouse.duckdb"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "export"
