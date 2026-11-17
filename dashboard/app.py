"""Streamlit dashboard on top of the dbt marts.

Run with:  streamlit run dashboard/app.py

The app only reads the exported aggregate marts. All business logic lives in
dbt; this file only filters, formats and draws. Where the marts come from, in
order of preference:

1. ``LVM_MARTS_URL``: a folder or HTTPS base URL, e.g. the ``marts-data`` branch
   that the daily GitHub Actions run publishes (set it as a secret when hosting);
2. ``data/export``: the output of a local ``make pipeline`` run;
3. ``dashboard/snapshot``: a small copy committed to the repository, so the
   dashboard works straight after cloning.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

SNAPSHOT = Path(__file__).resolve().parent / "snapshot"


def _hosted_setting(name: str) -> str | None:
    """An environment variable, or a Streamlit secret of the same name."""
    if os.getenv(name):
        return os.getenv(name)
    try:
        value = st.secrets.get(name)
    except Exception:  # no secrets file: running locally
        return None
    return str(value) if value else None


def resolve_marts_location() -> tuple[str, str]:
    """Return the marts location and a short label describing it."""
    url = _hosted_setting("LVM_MARTS_URL")
    if url:
        return url, "published marts"
    local = Path(os.getenv("LVM_DATA_DIR", "data")) / "export"
    if (local / "agg_pipeline_status.parquet").exists():
        return str(local), "local pipeline output"
    return str(SNAPSHOT), "snapshot committed to the repository"


MARTS, MARTS_SOURCE = resolve_marts_location()
CASH_LIMIT_DATE = pd.Timestamp("2022-11-01")

# Categorical slots are assigned to entities in a fixed order, never by rank.
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GRAY = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#a8a69f",
)  # fmt: skip
ORIGIN_COLORS = {"Domestic": BLUE, "Imported": ORANGE}
SEGMENT_COLORS = {"Above cash limit": BLUE, "At or below cash limit": ORANGE}
SEGMENT_LABELS = {"Above cash limit": "Above €5,000", "At or below cash limit": "€5,000 or less"}
POSITION_COLORS = {"Just below the limit": BLUE, "Just above the limit": ORANGE}
POSITION_LABELS = {
    "Just below the limit": "€4,900 to €4,999",
    "Just above the limit": "€5,001 to €5,100",
}
FUEL_COLORS = {
    "Diesel": BLUE,
    "Petrol": ORANGE,
    "LPG": AQUA,
    "Hybrid": YELLOW,
    "Electric": MAGENTA,
    "Not recorded": GRAY,
}
# Ordinal one-hue ramp for the price bands (low -> high).
BAND_RAMP = [
    "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#104281", "#0d366b",
]  # fmt: skip
INK, INK_MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e7e6e1", "#fcfcfb"

st.set_page_config(page_title="Lithuanian vehicle market", page_icon="🚗", layout="wide")


# ================================================================== helpers ==
@st.cache_data(ttl=3600, show_spinner=False)
def _read(path: str, version: float | None) -> pd.DataFrame:
    return pd.read_parquet(path)


def load(mart: str) -> pd.DataFrame:
    """Read one exported mart; a local file is re-read as soon as the pipeline rewrites it."""
    path = f"{MARTS.rstrip('/')}/{mart}.parquet"
    local = Path(path)
    return _read(path, local.stat().st_mtime if local.exists() else None)


def load_all(*marts: str) -> list[pd.DataFrame] | None:
    try:
        return [load(mart) for mart in marts]
    except (FileNotFoundError, OSError) as exc:
        st.error(f"Could not read the marts from `{MARTS}`. Run `make pipeline` first.\n\n{exc}")
        return None


def base_layout(fig: go.Figure, *, height: int = 360, y_title: str = "", **overrides) -> go.Figure:
    layout = dict(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(color=INK, size=13),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="white", font_size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title_text=""),
        xaxis=dict(showgrid=False, linecolor=GRID, tickfont=dict(color=INK_MUTED)),
        yaxis=dict(
            title=dict(text=y_title, font=dict(color=INK_MUTED, size=12)),
            gridcolor=GRID,
            zeroline=False,
            rangemode="tozero",
            tickfont=dict(color=INK_MUTED),
        ),
    )
    fig.update_layout(**(layout | overrides))
    return fig


def show(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def line(fig: go.Figure, x, y, name: str, color: str, hover: str, **kwargs) -> None:
    fig.add_scatter(
        x=x,
        y=y,
        name=name,
        mode="lines",
        line=dict(color=color, width=2),
        hovertemplate=hover + "<extra>" + name + "</extra>",
        **kwargs,
    )


def horizontal_bars(labels, values, hover: str, *, height: int = 420) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=BLUE, cornerradius=4),
            text=[f"{v:,.0f}" for v in values],
            textposition="outside",
            textfont=dict(color=INK_MUTED),
            cliponaxis=False,
            hovertemplate=hover + "<extra></extra>",
        )
    )
    fig = base_layout(fig, height=height, hovermode="closest")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(gridcolor=SURFACE, tickfont=dict(color=INK), rangemode="normal")
    fig.update_layout(margin=dict(r=70))
    return fig


def eur(value: float) -> str:
    return f"€{value:,.0f}"


# =================================================================== market ==
def render_market() -> None:
    frames = load_all(
        "agg_market_monthly",
        "agg_payment_methods_monthly",
        "agg_cash_limit_bunching_monthly",
        "agg_import_origins_monthly",
        "agg_price_bands_yearly",
        "agg_transaction_types_monthly",
        "agg_pipeline_status",
    )
    if frames is None:
        return
    market, payments, bunching, origins, bands, types, status_df = frames
    status = status_df.iloc[0]
    market, payments, bunching, origins, types = (
        frame.assign(transaction_month=pd.to_datetime(frame["transaction_month"])).sort_values(
            "transaction_month"
        )
        for frame in (market, payments, bunching, origins, types)
    )
    bands = bands.sort_values(["transaction_year", "band_order"])

    st.caption(
        "Every vehicle ownership transfer registered in Lithuania since 2021, from "
        "[Regitra open data](https://data.gov.lt/). Prices are the amounts buyers and "
        "sellers **declared** to the registry, not appraised market values."
    )

    years = sorted(market["transaction_month"].dt.year.unique())
    f1, f2, _ = st.columns([2, 2, 3])
    year_from, year_to = f1.select_slider("Period", options=years, value=(years[0], years[-1]))
    origin_choice = (
        f2.segmented_control("Vehicle origin", ["All", "Domestic", "Imported"], default="All")
        or "All"
    )

    def in_period(frame: pd.DataFrame) -> pd.DataFrame:
        year = frame["transaction_month"].dt.year
        return frame[(year >= year_from) & (year <= year_to)]

    period_all = in_period(market)
    market_f = (
        period_all
        if origin_choice == "All"
        else period_all[period_all["origin_type"] == origin_choice]
    )
    complete = market_f[market_f["is_complete_month"]]
    complete_months = set(market.loc[market["is_complete_month"], "transaction_month"])

    # ----------------------------------------------------------------- KPIs --
    # Counts for the newest months are understated until late registrations
    # arrive, so "recent" KPIs are averaged over the last 12 settled months and
    # never compared month against month.
    settled_months = sorted(complete["transaction_month"].unique())
    recent = complete[complete["transaction_month"].isin(settled_months[-12:])]
    recent_sales = recent.groupby("transaction_month")["transactions"].sum()
    recent_priced = recent["priced_transactions"].sum()
    typical_price = (
        (recent["median_price_eur"] * recent["priced_transactions"]).sum() / recent_priced
        if recent_priced
        else None
    )
    period_sales = period_all["transactions"].sum()
    abroad_share = (
        period_all.loc[period_all["origin_type"] == "Imported", "transactions"].sum() / period_sales
        if period_sales
        else None
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Market sales in period", f"{int(market_f['transactions'].sum()):,}")
    k2.metric(
        "Sales per month",
        f"{recent_sales.mean():,.0f}" if len(recent_sales) else "n/a",
        help="Average over the last 12 settled months in the selected period.",
    )
    k3.metric(
        "Typical declared price",
        eur(typical_price) if typical_price is not None else "n/a",
        help="Monthly median declared price, averaged over the last 12 settled months "
        "(weighted by the number of priced sales).",
    )
    k4.metric(
        "Bought abroad",
        f"{abroad_share:.1%}" if abroad_share is not None else "n/a",
        help="Share of market sales in the period recorded in a country other than Lithuania. "
        "Not affected by the origin filter.",
    )
    last_settled = pd.Timestamp(settled_months[-1]) if settled_months else None
    st.caption(
        "Latest transaction in the warehouse: "
        f"**{pd.Timestamp(status['latest_transaction_date']):%d %b %Y}** · "
        f"{int(status['documents']):,} documents loaded, of which "
        f"{int(status['market_sales']):,} are sale contracts or invoices. About one sale in ten "
        "reaches the registry more than a month after the contract date, so trend charts run "
        "from May 2021 "
        + (f"to **{last_settled:%B %Y}** " if last_settled is not None else "")
        + "and leave out the newest months, which are still filling in."
    )

    # --------------------------------------------------- volume and prices --
    left, right = st.columns(2)
    with left:
        st.subheader("How many vehicles change hands")
        st.caption("Market sales per month (sale contracts and invoices)")
        fig = go.Figure()
        for origin, color in ORIGIN_COLORS.items():
            part = complete[complete["origin_type"] == origin]
            if not part.empty:
                line(
                    fig, part["transaction_month"], part["transactions"], origin, color, "%{y:,.0f}"
                )
        show(base_layout(fig, y_title="Sales per month"))

    with right:
        st.subheader("What buyers declare paying")
        show_band = origin_choice != "All"  # two overlapping bands are unreadable
        st.caption(
            "Median declared price per month"
            + ("; the band covers the middle 50% of sales" if show_band else "")
        )
        fig = go.Figure()
        for origin, color in ORIGIN_COLORS.items():
            part = complete[complete["origin_type"] == origin]
            if part.empty:
                continue
            if show_band:
                fig.add_scatter(
                    x=pd.concat([part["transaction_month"], part["transaction_month"][::-1]]),
                    y=pd.concat([part["p75_price_eur"], part["p25_price_eur"][::-1]]),
                    fill="toself",
                    fillcolor=color,
                    opacity=0.12,
                    line=dict(width=0),
                    hoverinfo="skip",
                    showlegend=False,
                )
            line(
                fig,
                part["transaction_month"],
                part["median_price_eur"],
                origin,
                color,
                "€%{y:,.0f} (middle half €%{customdata[0]:,.0f} to €%{customdata[1]:,.0f})",
                customdata=part[["p25_price_eur", "p75_price_eur"]],
            )
        fig = base_layout(fig, y_title="Declared price, EUR")
        fig.update_yaxes(tickprefix="€", tickformat=",")
        show(fig)

    # --------------------------------------------------------- cash limit --
    st.subheader("Did the cash limit change how cars are paid for?")
    st.caption(
        "Share of market sales paid fully in cash, among documents that state a payment method. "
        "Since 1 November 2022 Lithuanian law restricts cash settlements that exceed €5,000."
    )
    # Until 2023 the payment method was optional; shares are taken over documents
    # that state one, so the field becoming mandatory does not look like a trend.
    stated = in_period(payments)
    stated = stated[
        stated["transaction_month"].isin(complete_months)
        & (stated["payment_method"] != "Not specified")
    ]
    cash = (
        stated.assign(cash=stated["transactions"].where(stated["payment_method"] == "Cash", 0))
        .groupby(["transaction_month", "price_segment"], as_index=False)
        .agg(cash=("cash", "sum"), total=("transactions", "sum"))
    )
    cash["share"] = cash["cash"] / cash["total"]
    fig = go.Figure()
    for segment, color in SEGMENT_COLORS.items():
        part = cash[cash["price_segment"] == segment]
        line(
            fig, part["transaction_month"], part["share"], SEGMENT_LABELS[segment], color,
            "%{y:.1%} paid in cash",
        )  # fmt: skip
    cash_months = cash["transaction_month"]
    law_in_range = bool(len(cash)) and cash_months.min() <= CASH_LIMIT_DATE <= cash_months.max()
    if law_in_range:
        fig.add_vline(x=CASH_LIMIT_DATE, line=dict(color=INK_MUTED, width=1, dash="dot"))
        fig.add_annotation(
            x=CASH_LIMIT_DATE, y=1, yref="paper", text="Cash limit in force", showarrow=False,
            xanchor="left", xshift=6, font=dict(color=INK_MUTED, size=12),
        )  # fmt: skip
    fig = base_layout(fig, height=340, y_title="Share paid in cash")
    fig.update_yaxes(tickformat=".0%")
    show(fig)

    st.subheader("And what people write on the contract")
    st.caption(
        "Market sales per month declared just below and just above the €5,000 limit. "
        "A sale at €4,999 can still be settled in cash."
    )
    near = in_period(bunching)
    near = near[near["transaction_month"].isin(complete_months)]
    fig = go.Figure()
    for position, color in POSITION_COLORS.items():
        part = near[near["price_position"] == position]
        line(
            fig, part["transaction_month"], part["transactions"], POSITION_LABELS[position], color,
            "%{y:,.0f} sales",
        )  # fmt: skip
    if law_in_range:
        fig.add_vline(x=CASH_LIMIT_DATE, line=dict(color=INK_MUTED, width=1, dash="dot"))
    show(base_layout(fig, height=300, y_title="Sales per month"))

    # --------------------------------------------------- origins and bands --
    left, right = st.columns(2)
    with left:
        st.subheader("Where imported vehicles come from")
        st.caption("Top 12 origin countries by market sales in the selected period")
        top = (
            in_period(origins)
            .groupby("origin_country")
            .agg(transactions=("transactions", "sum"))
            .nlargest(12, "transactions")
            .sort_values("transactions")
            .reset_index()
        )
        show(horizontal_bars(top["origin_country"], top["transactions"], "%{y}: %{x:,.0f} sales"))

    with right:
        st.subheader("Declared price bands")
        st.caption("Share of EUR market sales per declared price band, by year")
        bands_f = bands[bands["transaction_year"].between(year_from, year_to)]
        order = bands.drop_duplicates("price_band").sort_values("band_order")["price_band"]
        fig = go.Figure()
        for band, color in zip(order, BAND_RAMP, strict=False):
            part = bands_f[bands_f["price_band"] == band]
            fig.add_bar(
                x=part["transaction_year"].astype(str),
                y=part["share_of_year"],
                name=f"€{band}" if band[0].isdigit() else band.replace("Under ", "Under €"),
                marker=dict(color=color, line=dict(color=SURFACE, width=2)),
                hovertemplate="%{y:.1%}<extra>%{fullData.name}</extra>",
            )
        fig = base_layout(fig, height=420, barmode="stack", bargap=0.35)
        fig.update_yaxes(tickformat=".0%", range=[0, 1])
        fig.update_xaxes(type="category")
        fig.update_layout(
            legend=dict(orientation="v", x=1.02, y=1, yanchor="top", traceorder="reversed")
        )
        show(fig)

    # ---------------------------------------------------- transfer reasons --
    st.subheader("Why ownership changes")
    st.caption("All ownership-transfer documents in the selected period, by document type")
    reasons = (
        in_period(types)
        .groupby(["transaction_category", "document_type"])
        .agg(documents=("transactions", "sum"))
        .sort_values("documents", ascending=False)
        .reset_index()
    )
    reasons["share"] = reasons["documents"] / reasons["documents"].sum()
    st.dataframe(
        reasons.rename(
            columns={
                "transaction_category": "Category",
                "document_type": "Document type",
                "documents": "Documents",
                "share": "Share",
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Documents": st.column_config.NumberColumn(format="localized"),
            "Share": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        },
    )

    with st.expander("About the data and its limits"):
        st.markdown(
            """
- **Source**: AB Regitra, [*Transporto priemonių sandorių duomenys*](https://data.gov.lt/datasets/2812/),
  Lithuanian open data portal, licensed under CC BY 4.0. Cleaned and aggregated for this page.
- **Declared prices**: amounts are whatever the parties wrote on the document. They are
  not verified and are known to be understated for private sales, so read the levels
  with care and the *trends* with more confidence.
- **No vehicle attributes**: this dataset has no make, model or age and cannot be linked
  to the inspection data, so price changes also reflect changes in the mix of vehicles.
- **One row is one document**, not one vehicle: an invoice can cover several vehicles.
- **Origin** is the transaction country recorded by the registry.
- **Late registrations**: the newest three months are still filling in and are left out
  of the trend charts.
- Prices outside €100 to €500,000 and non-EUR documents are excluded from price statistics.
            """
        )


# ==================================================================== fleet ==
def render_fleet() -> None:
    frames = load_all(
        "agg_fleet_status",
        "agg_fleet_fuel_yearly",
        "agg_fleet_makes_yearly",
        "agg_fleet_models",
        "agg_fleet_municipalities",
        "agg_pass_rate_by_age",
        "agg_annual_mileage",
        "agg_odometer_checks_yearly",
    )
    if frames is None:
        return
    status_df, fuel, makes, models, municipalities, by_age, mileage, odometer = frames
    status = status_df.iloc[0]
    first_week = pd.Timestamp(status["first_inspection_week"])
    last_week = pd.Timestamp(status["last_inspection_week"])
    window_start = pd.Timestamp(status["window_start_week"])

    st.caption(
        "Every periodic roadworthiness inspection carried out in Lithuania, from "
        "[TRANSEKSTA open data](https://data.gov.lt/): make, model, age, fuel, odometer and "
        "outcome. This data cannot be linked to the transactions in the other tab."
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Passenger cars in the fleet",
        f"{int(status['current_passenger_cars']):,}",
        help=f"Distinct passenger cars inspected between {window_start:%b %Y} and "
        f"{last_week:%b %Y}. Cars are inspected every two years, so this window sees each "
        "active car about once.",
    )
    k2.metric("Median age", f"{status['median_age_years']:.0f} years")
    k3.metric("Diesel share", f"{status['diesel_share']:.0%}")
    k4.metric(
        "Pass at first attempt",
        f"{status['first_pass_rate']:.0%}",
        help="Share of periodic inspections passed without a re-inspection.",
    )
    st.caption(
        f"{int(status['inspections']):,} inspections of {int(status['vehicles']):,} vehicles, "
        f"{first_week:%B %Y} to **{last_week:%B %Y}** (the publisher has not refreshed the "
        f"dataset since). {int(status['duplicate_rows_removed']):,} rows published twice were "
        "removed. Fleet figures describe the two years up to the last inspection."
    )

    # ------------------------------------------------- fuel mix, pass rate --
    left, right = st.columns(2)
    with left:
        st.subheader("Diesel has peaked, hybrids are growing")
        st.caption("Passenger cars presented for inspection each year, by fuel")
        fuel = fuel.sort_values("inspection_year")
        partial_years = set(fuel.loc[~fuel["is_complete_year"], "inspection_year"])
        fig = go.Figure()
        for group, color in FUEL_COLORS.items():
            part = fuel[fuel["fuel_group"] == group]
            if part.empty:
                continue
            fig.add_bar(
                x=[f"{y}*" if y in partial_years else str(y) for y in part["inspection_year"]],
                y=part["share_of_year"],
                name=group,
                marker=dict(color=color, line=dict(color=SURFACE, width=2)),
                customdata=part["vehicles"],
                hovertemplate="%{y:.1%} (%{customdata:,.0f} cars)<extra>" + group + "</extra>",
            )
        fig = base_layout(fig, barmode="stack", bargap=0.3)
        fig.update_yaxes(tickformat=".0%", range=[0, 1])
        fig.update_xaxes(type="category")
        fig.update_layout(legend_traceorder="normal")
        show(fig)
        if partial_years:
            st.caption("\\* year not complete in the data")

    with right:
        st.subheader("Older cars fail more often")
        st.caption("Share passing the periodic inspection at the first attempt, by age of the car")
        fig = go.Figure()
        shown = by_age[by_age["inspections"] >= 300].sort_values("vehicle_age_years")
        for group in ("Diesel", "Petrol", "Hybrid"):
            part = shown[shown["fuel_group"] == group]
            if not part.empty:
                line(
                    fig, part["vehicle_age_years"], part["first_pass_rate"], group,
                    FUEL_COLORS[group], "%{y:.0%} pass (%{customdata:,.0f} inspections)",
                    customdata=part["inspections"],
                )  # fmt: skip
        fig = base_layout(fig, y_title="First-attempt pass rate")
        fig.update_yaxes(tickformat=".0%", range=[0, 1])
        fig.update_xaxes(title=dict(text="Vehicle age, years", font=dict(color=INK_MUTED, size=12)))
        show(fig)

    # ------------------------------------------------------ makes, models --
    left, right = st.columns([2, 3])
    with left:
        complete_years = sorted(fuel.loc[fuel["is_complete_year"], "inspection_year"].unique())
        year = complete_years[-1] if complete_years else int(makes["inspection_year"].max())
        st.subheader("Most common makes")
        st.caption(f"Passenger cars inspected in {year}")
        top = (
            makes[
                (makes["inspection_year"] == year) & ~makes["make"].isin(["Other", "Not disclosed"])
            ]
            .nlargest(15, "vehicles")
            .sort_values("vehicles")
        )
        show(horizontal_bars(top["make"], top["vehicles"], "%{y}: %{x:,.0f} cars", height=520))

    with right:
        st.subheader("Models on the road")
        make_options = ["All makes", *sorted(models["make"].unique())]
        choice = st.selectbox("Make", make_options, label_visibility="collapsed")
        table = models if choice == "All makes" else models[models["make"] == choice]
        st.caption(
            f"{len(table)} models with at least {int(models['vehicles'].min()):,} cars in the "
            "current fleet. Click a column to sort."
        )
        st.dataframe(
            table.sort_values("vehicles", ascending=False)[
                ["make", "model", "vehicles", "median_manufacture_year", "median_odometer_km",
                 "first_pass_rate", "diesel_share"]
            ].rename(
                columns={
                    "make": "Make",
                    "model": "Model",
                    "vehicles": "Cars",
                    "median_manufacture_year": "Median year",
                    "median_odometer_km": "Median odometer, km",
                    "first_pass_rate": "Pass at first attempt",
                    "diesel_share": "Diesel",
                }
            ),
            hide_index=True,
            width="stretch",
            height=470,
            column_config={
                "Cars": st.column_config.NumberColumn(format="localized"),
                "Median year": st.column_config.NumberColumn(format="%d"),
                "Median odometer, km": st.column_config.NumberColumn(format="localized"),
                "Pass at first attempt": st.column_config.ProgressColumn(
                    format="percent", min_value=0, max_value=1
                ),
                "Diesel": st.column_config.NumberColumn(format="percent"),
            },
        )  # fmt: skip

    # --------------------------------------------------- mileage, odometer --
    left, right = st.columns(2)
    with left:
        st.subheader("How far cars are driven")
        st.caption(
            "Median distance per year between two consecutive inspections of the same car, "
            "by age of the car"
        )
        fig = go.Figure()
        ordered = mileage[mileage["intervals"] >= 300].sort_values("age_band_order")
        for group in ("Diesel", "Petrol", "LPG"):
            part = ordered[ordered["fuel_group"] == group]
            if not part.empty:
                fig.add_bar(
                    x=part["age_band"],
                    y=part["median_annual_km"],
                    name=group,
                    marker=dict(color=FUEL_COLORS[group], cornerradius=4),
                    hovertemplate="%{y:,.0f} km a year<extra>" + group + "</extra>",
                )
        fig = base_layout(
            fig, barmode="group", bargap=0.25, bargroupgap=0.08, y_title="km per year"
        )
        fig.update_yaxes(tickformat=",")
        fig.update_xaxes(type="category")
        show(fig)

    with right:
        st.subheader("Odometers that went backwards")
        st.caption(
            "Share of cars arriving with a reading at least 10,000 km lower than at their "
            "previous periodic inspection"
        )
        # the first two years have too few cars with an earlier inspection to compare
        checks = odometer[odometer["compared_pairs"] >= 100_000].sort_values("inspection_year")
        fig = go.Figure(
            go.Bar(
                x=checks["inspection_year"].astype(str),
                y=checks["suspected_rollback_rate"],
                marker=dict(color=BLUE, cornerradius=4),
                customdata=checks[["suspected_rollbacks", "compared_pairs"]],
                hovertemplate="%{y:.2%} (%{customdata[0]:,.0f} of %{customdata[1]:,.0f} cars)"
                "<extra></extra>",
            )
        )
        fig = base_layout(fig, bargap=0.35, y_title="Share of cars")
        fig.update_yaxes(tickformat=".1%")
        fig.update_xaxes(type="category")
        show(fig)

    # ------------------------------------------------------ municipalities --
    st.subheader("The fleet by municipality")
    st.caption("Passenger cars by the municipality of the station that inspected them")
    st.dataframe(
        municipalities.sort_values("vehicles", ascending=False)[
            ["municipality", "vehicles", "median_age_years", "median_odometer_km",
             "first_pass_rate", "diesel_share", "electrified_share"]
        ].rename(
            columns={
                "municipality": "Municipality",
                "vehicles": "Cars",
                "median_age_years": "Median age, years",
                "median_odometer_km": "Median odometer, km",
                "first_pass_rate": "Pass at first attempt",
                "diesel_share": "Diesel",
                "electrified_share": "Hybrid or electric",
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Cars": st.column_config.NumberColumn(format="localized"),
            "Median age, years": st.column_config.NumberColumn(format="%.0f"),
            "Median odometer, km": st.column_config.NumberColumn(format="localized"),
            "Pass at first attempt": st.column_config.ProgressColumn(
                format="percent", min_value=0, max_value=1
            ),
            "Diesel": st.column_config.NumberColumn(format="percent"),
            "Hybrid or electric": st.column_config.NumberColumn(format="percent"),
        },
    )  # fmt: skip

    with st.expander("About the data and its limits"):
        st.markdown(
            """
- **Source**: TRANSEKSTA, [*Transporto priemonių techninės apžiūros duomenys*](https://data.gov.lt/datasets/2721/),
  Lithuanian open data portal, licensed under CC BY 4.0. Cleaned, de-duplicated and aggregated
  for this page. Dates are precise to the week.
- **The fleet is what gets inspected.** New cars are first inspected after three years, and
  unregistered or uninspected vehicles never appear.
- **Makes and models are typed by hand** at the station. Common spellings are mapped to one
  brand; the publisher masks some makes, shown here as "Not disclosed" and left out of the
  rankings.
- **Lower odometer readings are not proof of fraud.** They also come from typing errors,
  replaced instrument clusters and readings taken in miles. The 10,000 km threshold removes
  small slips but not these causes.
- **Municipality** is where the inspection station is, not where the owner lives.
- Odometer readings of zero or above 1,500,000 km and impossible manufacture years are
  ignored.
            """
        )


# ===================================================================== page ==
st.title("Lithuanian vehicle market")
st.caption(f"Data: {MARTS_SOURCE}.")
market_tab, fleet_tab = st.tabs(["Vehicle market", "Vehicle fleet"])
with market_tab:
    render_market()
with fleet_tab:
    render_fleet()
