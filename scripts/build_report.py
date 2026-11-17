"""Regenerate docs/findings.md and the README charts from the exported marts.

Every number quoted in the README comes out of this script, so the write-up can
never drift from the data:  make figures

Reads only data/export/*.parquet (or LVM_MARTS_URL), exactly like the dashboard.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter, PercentFormatter

ROOT = Path(__file__).resolve().parents[1]
MARTS = os.getenv("LVM_MARTS_URL") or str(Path(os.getenv("LVM_DATA_DIR", ROOT / "data")) / "export")
DOCS = ROOT / "docs"
IMG = DOCS / "img"

BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GRAY = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#a8a69f",
)  # fmt: skip
FUEL_COLORS = {
    "Diesel": BLUE,
    "Petrol": ORANGE,
    "LPG": AQUA,
    "Hybrid": YELLOW,
    "Electric": MAGENTA,
    "Not recorded": GRAY,
}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e7e6e1"
CASH_LIMIT_DATE = pd.Timestamp("2022-11-01")
# a fully loaded month has about 100,000 sales
MIN_SALES_PER_MONTH = 10_000

plt.rcParams.update(
    {
        "figure.dpi": 160,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": GRID,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.axisbelow": True,
        "grid.color": GRID,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "ytick.left": False,
        "font.size": 10,
        "legend.frameon": False,
    }
)


def load(mart: str) -> pd.DataFrame:
    frame = pd.read_parquet(f"{MARTS.rstrip('/')}/{mart}.parquet")
    if "transaction_month" in frame:
        frame["transaction_month"] = pd.to_datetime(frame["transaction_month"])
    return frame


# Charts are drawn into a scratch folder first and only replace docs/img once the
# whole report has been produced, so a failed run never leaves half-new charts.
_OUT: Path = IMG


def save(fig: plt.Figure, name: str) -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(_OUT / name, bbox_inches="tight")
    plt.close(fig)


def thousands(value: float, _pos: int = 0) -> str:
    return f"{value:,.0f}"


# ================================================================== market ==
def cash_shares(payments: pd.DataFrame, complete_months: set[pd.Timestamp]) -> pd.DataFrame:
    """Share of sales paid fully in cash, among documents stating a payment method."""
    stated = payments[
        payments["transaction_month"].isin(complete_months)
        & (payments["payment_method"] != "Not specified")
    ]
    cash = (
        stated.assign(cash=stated["transactions"].where(stated["payment_method"] == "Cash", 0))
        .groupby(["transaction_month", "price_segment"], as_index=False)
        .agg(cash=("cash", "sum"), total=("transactions", "sum"))
    )
    cash["share"] = cash["cash"] / cash["total"]
    return cash


def market_findings() -> dict[str, object]:
    market = load("agg_market_monthly")
    payments = load("agg_payment_methods_monthly")
    bunching = load("agg_cash_limit_bunching_monthly")
    origins = load("agg_import_origins_monthly")
    status = load("agg_pipeline_status").iloc[0]

    complete = market[market["is_complete_month"]]
    complete_months = set(complete["transaction_month"])
    months = sorted(complete_months)
    cash = cash_shares(payments, complete_months)

    def cash_share(month: pd.Timestamp, segment: str) -> float:
        row = cash[(cash["transaction_month"] == month) & (cash["price_segment"] == segment)]
        return float(row["share"].iloc[0])

    before, after = CASH_LIMIT_DATE - pd.DateOffset(months=1), CASH_LIMIT_DATE

    def near_limit(position: str, start: pd.Timestamp, end: pd.Timestamp) -> float:
        rows = bunching[
            (bunching["price_position"] == position)
            & (bunching["transaction_month"] >= start)
            & (bunching["transaction_month"] < end)
        ]
        return float(rows["transactions"].sum() / 12)

    year = pd.DateOffset(years=1)
    below_before = near_limit("Just below the limit", CASH_LIMIT_DATE - year, CASH_LIMIT_DATE)
    below_after = near_limit("Just below the limit", CASH_LIMIT_DATE, CASH_LIMIT_DATE + year)

    def typical_price(origin: str, window: list[pd.Timestamp]) -> float:
        rows = complete[
            (complete["origin_type"] == origin) & complete["transaction_month"].isin(window)
        ]
        weights = rows["priced_transactions"]
        return float((rows["median_price_eur"] * weights).sum() / weights.sum())

    by_origin = origins.groupby("origin_country")["transactions"].sum().nlargest(5)
    total_sales = market["transactions"].sum()

    # ------------------------------------------------------------- charts --
    fig, ax = plt.subplots(figsize=(9, 3.6))
    for segment, label, color in (
        ("Above cash limit", "Sales above €5,000", BLUE),
        ("At or below cash limit", "Sales of €5,000 or less", ORANGE),
    ):
        part = cash[cash["price_segment"] == segment]
        ax.plot(part["transaction_month"], part["share"], color=color, linewidth=2, label=label)
    ax.axvline(CASH_LIMIT_DATE, color=MUTED, linewidth=1, linestyle=":")
    ax.annotate(
        "Cash limit in force\n1 Nov 2022",
        (CASH_LIMIT_DATE, 0.55),
        xytext=(8, 0),
        textcoords="offset points",
        color=MUTED,
        fontsize=9,
    )
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.set_title("Share of vehicle sales paid fully in cash")
    ax.legend(loc="center right")
    save(fig, "cash_limit.png")

    fig, ax = plt.subplots(figsize=(9, 3.2))
    near = bunching[bunching["transaction_month"].isin(complete_months)]
    for position, label, color in (
        ("Just below the limit", "Declared at €4,900 to €4,999", BLUE),
        ("Just above the limit", "Declared at €5,001 to €5,100", ORANGE),
    ):
        part = near[near["price_position"] == position].sort_values("transaction_month")
        ax.plot(
            part["transaction_month"], part["transactions"], color=color, linewidth=2, label=label
        )
    ax.axvline(CASH_LIMIT_DATE, color=MUTED, linewidth=1, linestyle=":")
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(FuncFormatter(thousands))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.set_title("Sales per month declared just under and just over the limit")
    ax.legend(loc="upper left")
    save(fig, "cash_limit_bunching.png")

    return {
        "documents": int(status["documents"]),
        "market_sales": int(status["market_sales"]),
        "first_month": months[0],
        "last_settled_month": months[-1],
        "latest_transaction": pd.Timestamp(status["latest_transaction_date"]),
        "cash_above_before": cash_share(before, "Above cash limit"),
        "cash_above_after": cash_share(after, "Above cash limit"),
        "cash_below_before": cash_share(before, "At or below cash limit"),
        "cash_below_after": cash_share(after, "At or below cash limit"),
        "cash_above_latest": cash_share(months[-1], "Above cash limit"),
        "below_limit_before": below_before,
        "below_limit_after": below_after,
        "price_domestic_first": typical_price("Domestic", months[:12]),
        "price_domestic_last": typical_price("Domestic", months[-12:]),
        "price_imported_first": typical_price("Imported", months[:12]),
        "price_imported_last": typical_price("Imported", months[-12:]),
        "abroad_share": float(
            market.loc[market["origin_type"] == "Imported", "transactions"].sum() / total_sales
        ),
        "top_origins": [(country, int(n)) for country, n in by_origin.items()],
    }


# =================================================================== fleet ==
def fleet_findings() -> dict[str, object]:
    status = load("agg_fleet_status").iloc[0]
    fuel = load("agg_fleet_fuel_yearly")
    makes = load("agg_fleet_makes_yearly")
    models = load("agg_fleet_models")
    municipalities = load("agg_fleet_municipalities")
    by_age = load("agg_pass_rate_by_age")
    mileage = load("agg_annual_mileage")
    odometer = load("agg_odometer_checks_yearly")

    full = fuel[fuel["is_complete_year"]]
    first_year, last_year = int(full["inspection_year"].min()), int(full["inspection_year"].max())

    def fuel_share(year: int, groups: list[str]) -> float:
        rows = full[(full["inspection_year"] == year) & full["fuel_group"].isin(groups)]
        return float(rows["share_of_year"].sum())

    diesel_by_year = full[full["fuel_group"] == "Diesel"].set_index("inspection_year")[
        "share_of_year"
    ]

    def pass_rate(age: int, group: str = "Diesel") -> float:
        row = by_age[(by_age["vehicle_age_years"] == age) & (by_age["fuel_group"] == group)]
        return float(row["first_pass_rate"].iloc[0])

    def annual_km(group: str, band: str = "10-14 years") -> int:
        row = mileage[(mileage["fuel_group"] == group) & (mileage["age_band"] == band)]
        return int(row["median_annual_km"].iloc[0])

    top_makes = (
        makes[
            (makes["inspection_year"] == last_year)
            & ~makes["make"].isin(["Other", "Not disclosed"])
        ]
        .nlargest(5, "vehicles")[["make", "vehicles"]]
        .itertuples(index=False)
    )
    top_models = models.nlargest(5, "vehicles")
    full_odometer = odometer[odometer["inspection_year"].between(first_year + 2, last_year)]
    rollbacks = full_odometer[full_odometer["inspection_year"] == last_year].iloc[0]
    biggest = municipalities.nlargest(1, "vehicles").iloc[0]
    youngest = (
        municipalities[municipalities["vehicles"] >= 5000].nsmallest(1, "median_age_years").iloc[0]
    )
    oldest = (
        municipalities[municipalities["vehicles"] >= 5000].nlargest(1, "median_age_years").iloc[0]
    )

    # ------------------------------------------------------------- charts --
    fig, ax = plt.subplots(figsize=(9, 3.6))
    years = sorted(full["inspection_year"].unique())
    bottom = pd.Series(0.0, index=years)
    for group, color in FUEL_COLORS.items():
        shares = (
            full[full["fuel_group"] == group]
            .set_index("inspection_year")["share_of_year"]
            .reindex(years, fill_value=0.0)
        )
        if shares.sum() == 0:
            continue
        ax.bar(
            [str(y) for y in years], shares, bottom=bottom, color=color, label=group,
            width=0.7, edgecolor="white", linewidth=1.5,
        )  # fmt: skip
        bottom = bottom + shares
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_title("Passenger cars presented for inspection, by fuel")
    ax.legend(loc="upper center", ncols=6, bbox_to_anchor=(0.5, -0.1))
    save(fig, "fuel_mix.png")

    fig, ax = plt.subplots(figsize=(9, 3.4))
    for group in ("Diesel", "Petrol", "Hybrid"):
        part = by_age[(by_age["fuel_group"] == group) & (by_age["inspections"] >= 300)]
        part = part.sort_values("vehicle_age_years")
        ax.plot(
            part["vehicle_age_years"], part["first_pass_rate"],
            color=FUEL_COLORS[group], linewidth=2, label=group,
        )  # fmt: skip
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlabel("Age of the car, years")
    ax.set_title("Share of cars passing the periodic inspection at the first attempt")
    ax.legend(loc="upper right")
    save(fig, "pass_rate_by_age.png")

    return {
        "published_rows": int(status["published_rows"]),
        "inspections": int(status["inspections"]),
        "duplicates": int(status["duplicate_rows_removed"]),
        "vehicles": int(status["vehicles"]),
        "first_week": pd.Timestamp(status["first_inspection_week"]),
        "last_week": pd.Timestamp(status["last_inspection_week"]),
        "fleet_cars": int(status["current_passenger_cars"]),
        "median_age": float(status["median_age_years"]),
        "fleet_pass_rate": float(status["first_pass_rate"]),
        "fleet_diesel_share": float(status["diesel_share"]),
        "first_year": first_year,
        "last_year": last_year,
        "diesel_first": fuel_share(first_year, ["Diesel"]),
        "diesel_last": fuel_share(last_year, ["Diesel"]),
        "electrified_first": fuel_share(first_year, ["Hybrid", "Electric"]),
        "electrified_last": fuel_share(last_year, ["Hybrid", "Electric"]),
        "top_makes": [(make, int(n)) for make, n in top_makes],
        "top_models": [
            (row.make, row.model, int(row.vehicles), int(row.median_manufacture_year))
            for row in top_models.itertuples()
        ],
        "pass_age_5": pass_rate(5),
        "pass_age_10": pass_rate(10),
        "pass_age_15": pass_rate(15),
        "pass_age_20": pass_rate(20),
        "km_diesel": annual_km("Diesel"),
        "km_petrol": annual_km("Petrol"),
        "rollback_rate": float(rollbacks["suspected_rollback_rate"]),
        "rollback_first_year": int(full_odometer["inspection_year"].min()),
        "rollback_rate_first": float(
            full_odometer.sort_values("inspection_year").iloc[0]["suspected_rollback_rate"]
        ),
        "diesel_peak_year": int(diesel_by_year.idxmax()),
        "diesel_peak": float(diesel_by_year.max()),
        "rollback_pairs": int(rollbacks["compared_pairs"]),
        "rollback_count": int(rollbacks["suspected_rollbacks"]),
        "rollback_median_km": int(rollbacks["median_rollback_km"]),
        "biggest_municipality": (biggest["municipality"], float(biggest["median_age_years"])),
        "youngest_municipality": (youngest["municipality"], float(youngest["median_age_years"])),
        "oldest_municipality": (oldest["municipality"], float(oldest["median_age_years"])),
    }


# ================================================================== report ==
def render(m: dict, f: dict) -> str:
    def pct(value: float, digits: int = 0) -> str:
        return f"{value:.{digits}%}"

    origins = ", ".join(f"{country} ({n:,})" for country, n in m["top_origins"])
    makes = ", ".join(f"{make} ({n:,})" for make, n in f["top_makes"])
    above = [pct(m[f"cash_above_{k}"]) for k in ("before", "after", "latest")]
    models = "\n".join(
        f"| {make} {model.title()} | {n:,} | {year} |" for make, model, n, year in f["top_models"]
    )
    return f"""# Findings

Generated by `scripts/build_report.py` from the exported marts. Do not edit by
hand: run `make figures` after a pipeline run.

Data: AB Regitra and TRANSEKSTA via the Lithuanian open data portal, licensed
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); cleaned,
de-duplicated and aggregated by this project.

## Vehicle market (ownership transfers)

Source: AB Regitra, {m["documents"]:,} documents, of which {m["market_sales"]:,} are sale
contracts or invoices. Trends cover {m["first_month"]:%B %Y} to {m["last_settled_month"]:%B %Y};
the newest months are left out because registrations keep arriving late. Latest transaction
loaded: {m["latest_transaction"]:%d %B %Y}.

### The cash limit changed behaviour within a month

Since 1 November 2022 cash settlements that exceed €5,000 are restricted.

| Share paid fully in cash | October 2022 | November 2022 | {m["last_settled_month"]:%B %Y} |
|---|---|---|---|
| Sales above €5,000 | {above[0]} | {above[1]} | {above[2]} |
| Sales of €5,000 or less | {pct(m["cash_below_before"])} | {pct(m["cash_below_after"])} | |

Shares are taken among documents that state a payment method.

![Cash share](img/cash_limit.png)

### ...and what people write on the contract

Sales declared at €4,900 to €4,999 averaged {m["below_limit_before"]:,.0f} a month in the year
before the limit and {m["below_limit_after"]:,.0f} a month in the year after, a
{m["below_limit_after"] / m["below_limit_before"]:.1f}-fold increase.

![Bunching below the limit](img/cash_limit_bunching.png)

### Declared prices

| Typical declared price | First 12 months | Last 12 settled months |
|---|---|---|
| Domestic sales | €{m["price_domestic_first"]:,.0f} | €{m["price_domestic_last"]:,.0f} |
| Vehicles bought abroad | €{m["price_imported_first"]:,.0f} | €{m["price_imported_last"]:,.0f} |

Monthly medians, weighted by the number of priced sales.

### Where vehicles are bought

{pct(m["abroad_share"], 1)} of market sales are recorded in a country other than Lithuania.
Largest origins: {origins}.

## Vehicle fleet (technical inspections)

Source: TRANSEKSTA, {f["published_rows"]:,} published rows from {f["first_week"]:%B %Y} to
{f["last_week"]:%B %Y}. {f["duplicates"]:,} rows that the publisher released twice were removed,
leaving {f["inspections"]:,} inspections of {f["vehicles"]:,} vehicles.

### The current fleet

{f["fleet_cars"]:,} passenger cars were inspected in the two years to {f["last_week"]:%B %Y}.
Their median age is {f["median_age"]:.0f} years, {pct(f["fleet_diesel_share"])} run on diesel and
{pct(f["fleet_pass_rate"])} pass the periodic inspection at the first attempt.

### Fuel mix

| Share of inspected passenger cars | {f["first_year"]} | {f["last_year"]} |
|---|---|---|
| Diesel | {pct(f["diesel_first"])} | {pct(f["diesel_last"])} |
| Hybrid or electric | {pct(f["electrified_first"], 1)} | {pct(f["electrified_last"], 1)} |

Diesel peaked at {pct(f["diesel_peak"])} in {f["diesel_peak_year"]} and has been falling since.

![Fuel mix](img/fuel_mix.png)

### Makes and models

Most common makes in {f["last_year"]}: {makes}.

| Most common models | Cars | Median year |
|---|---|---|
{models}

### Age and roadworthiness

A diesel car passes at the first attempt {pct(f["pass_age_5"])} of the time at 5 years old,
{pct(f["pass_age_10"])} at 10, {pct(f["pass_age_15"])} at 15 and {pct(f["pass_age_20"])} at 20.

![Pass rate by age](img/pass_rate_by_age.png)

### Mileage

A 10 to 14 year old diesel car covers a median of {f["km_diesel"]:,} km a year, a petrol car of
the same age {f["km_petrol"]:,} km.

In {f["last_year"]}, {f["rollback_count"]:,} of {f["rollback_pairs"]:,} cars
({pct(f["rollback_rate"], 2)}) arrived with an odometer reading at least 10,000 km lower than at
their previous periodic inspection; the median gap was {f["rollback_median_km"]:,} km. In
{f["rollback_first_year"]} the share was {pct(f["rollback_rate_first"], 2)}. Typing errors, replaced
instrument clusters and readings taken in miles produce such gaps too, so these are anomalies
worth a second look, not proven tampering.

### Municipalities

Among municipalities with at least 5,000 inspected cars, the youngest fleet is in
{f["youngest_municipality"][0]} (median {f["youngest_municipality"][1]:.0f} years) and the oldest
in {f["oldest_municipality"][0]} (median {f["oldest_municipality"][1]:.0f} years). The largest,
{f["biggest_municipality"][0]}, has a median of {f["biggest_municipality"][1]:.0f} years. The
municipality is that of the inspection station, not of the owner.
"""


class IncompleteData(RuntimeError):
    """The marts do not cover the periods the report talks about."""


def check_coverage() -> None:
    """Fail early, before anything is written, if the marts are not complete.

    The report compares October with November 2022 and the years around the
    cash limit, so it needs the full history, not a `--since` or demo run.
    """
    market = load("agg_market_monthly")
    complete = market[market["is_complete_month"]]
    # a month counts only if it is really loaded: a partial extract still puts a
    # few late-edited documents into old months
    volume = complete.groupby("transaction_month")["transactions"].sum()
    months = set(volume[volume >= MIN_SALES_PER_MONTH].index)
    needed = pd.date_range(CASH_LIMIT_DATE - pd.DateOffset(years=1), periods=24, freq="MS")
    missing = [f"{m:%Y-%m}" for m in needed if m not in months]
    fuel = load("agg_fleet_fuel_yearly")
    complete_years = fuel.loc[fuel["is_complete_year"], "inspection_year"].nunique()
    problems = []
    if missing:
        problems.append(f"transactions are missing {len(missing)} months ({missing[0]}...)")
    if complete_years < 3:
        problems.append(f"inspections cover {complete_years} complete years, at least 3 needed")
    if problems:
        raise IncompleteData("; ".join(problems))


def main() -> None:
    global _OUT
    try:
        check_coverage()
        DOCS.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=DOCS) as scratch:
            _OUT = Path(scratch)
            report = render(market_findings(), fleet_findings())
            IMG.mkdir(exist_ok=True)
            for chart in sorted(_OUT.glob("*.png")):
                os.replace(chart, IMG / chart.name)
            (DOCS / "findings.md").write_text(report, encoding="utf-8")
    except (IncompleteData, FileNotFoundError, KeyError, IndexError, ValueError) as exc:
        raise SystemExit(
            f"make figures needs the marts of a complete pipeline run ({exc}).\n"
            "Run `make pipeline` first. Nothing in docs/ was changed."
        ) from exc
    print(f"wrote {DOCS / 'findings.md'} and {len(list(IMG.glob('*.png')))} charts in {IMG}")


if __name__ == "__main__":
    main()
