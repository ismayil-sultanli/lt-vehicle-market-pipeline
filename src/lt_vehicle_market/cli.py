"""Command line entry point: ``lvm extract``, ``lvm sample`` and ``lvm export``."""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from lt_vehicle_market.config import DATASETS
from lt_vehicle_market.export import run_export
from lt_vehicle_market.extract import run_extract
from lt_vehicle_market.sample import run_sample


def _month(value: str) -> date:
    try:
        year, month = value.split("-")
        return date(int(year), int(month), 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lvm", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    ext = sub.add_parser("extract", help="load raw data from the API into Parquet")
    ext.add_argument(
        "--dataset",
        choices=[*DATASETS, "all"],
        default="all",
        help="which source dataset to load (default: all)",
    )
    ext.add_argument(
        "--refresh-months",
        type=int,
        default=2,
        help="always re-pull this many most recent monthly partitions (default: 2)",
    )
    ext.add_argument("--full-refresh", action="store_true", help="re-pull every partition")
    ext.add_argument("--since", type=_month, metavar="YYYY-MM", help="only consider months >= this")

    smp = sub.add_parser(
        "sample", help="load the bundled sample datasets into the raw layer (no API calls)"
    )
    smp.add_argument(
        "--from",
        dest="source_dir",
        type=Path,
        default=Path("tests/fixtures"),
        help="folder with the sample CSVs (default: tests/fixtures)",
    )

    sub.add_parser("export", help="publish aggregate marts as Parquet for the dashboard")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.command == "extract":
        specs = DATASETS.values() if args.dataset == "all" else [DATASETS[args.dataset]]
        for spec in specs:
            run_extract(
                spec,
                refresh_months=args.refresh_months,
                full_refresh=args.full_refresh,
                since=args.since,
            )
    elif args.command == "sample":
        run_sample(args.source_dir)
    elif args.command == "export":
        run_export()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
