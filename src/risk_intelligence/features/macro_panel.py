"""Point-in-time macro feature utilities for Milestone 4 Step 4.4."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Final

import pandas as pd

TRANSFORMATION_VERSION: Final[str] = "4.4.0"
ALFRED_GRAPH_CSV_ENDPOINT: Final[str] = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"


@dataclass(frozen=True)
class MacroSeriesSpec:
    feature: str
    series_id: str
    source: str
    release: str
    units: str
    frequency: str
    lookback_days: int
    transform: str = "latest"


SERIES_SPECS: Final[tuple[MacroSeriesSpec, ...]] = (
    MacroSeriesSpec(
        feature="macro_interest_rate_10y",
        series_id="DGS10",
        source="Board of Governors of the Federal Reserve System (US)",
        release="H.15 Selected Interest Rates",
        units="percent",
        frequency="daily",
        lookback_days=45,
    ),
    MacroSeriesSpec(
        feature="macro_inflation_yoy",
        series_id="CPIAUCNS",
        source="U.S. Bureau of Labor Statistics",
        release="Consumer Price Index",
        units="percent_change_from_year_ago",
        frequency="monthly",
        lookback_days=550,
        transform="year_over_year_percent",
    ),
    MacroSeriesSpec(
        feature="macro_credit_conditions_nfci",
        series_id="NFCI",
        source="Federal Reserve Bank of Chicago",
        release="Chicago Fed National Financial Conditions Index",
        units="index",
        frequency="weekly_ending_friday",
        lookback_days=90,
    ),
    MacroSeriesSpec(
        feature="macro_unemployment_rate",
        series_id="UNRATE",
        source="U.S. Bureau of Labor Statistics",
        release="Employment Situation",
        units="percent",
        frequency="monthly",
        lookback_days=180,
    ),
)


def parse_alfred_csv(content: bytes, series_id: str) -> pd.DataFrame:
    """Parse one ALFRED graph CSV snapshot into normalized date/value rows."""
    frame = pd.read_csv(BytesIO(content))
    if frame.shape[1] < 2:
        raise ValueError(f"ALFRED CSV for {series_id} has fewer than two columns.")

    date_column = frame.columns[0]
    candidate_columns = [
        column
        for column in frame.columns[1:]
        if str(column).upper() == series_id.upper()
        or str(column).upper().startswith(series_id.upper() + "_")
    ]
    if not candidate_columns:
        candidate_columns = list(frame.columns[1:2])
    value_column = candidate_columns[0]

    result = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(frame[date_column], errors="coerce"),
            "value": pd.to_numeric(frame[value_column].replace(".", pd.NA), errors="coerce"),
        }
    )
    result = result.dropna(subset=["observation_date"]).copy()
    result["observation_date"] = result["observation_date"].dt.normalize()
    return result.sort_values("observation_date").reset_index(drop=True)


def latest_available_observation(
    frame: pd.DataFrame,
    cutoff: pd.Timestamp,
) -> tuple[float | None, pd.Timestamp | None]:
    cutoff = pd.Timestamp(cutoff).normalize()
    eligible = frame.loc[frame["observation_date"].le(cutoff) & frame["value"].notna()].copy()
    if eligible.empty:
        return None, None
    row = eligible.iloc[-1]
    return float(row["value"]), pd.Timestamp(row["observation_date"]).normalize()


def year_over_year_percent(
    frame: pd.DataFrame,
    cutoff: pd.Timestamp,
) -> tuple[float | None, pd.Timestamp | None, pd.Timestamp | None]:
    current_value, current_date = latest_available_observation(frame, cutoff)
    if current_value is None or current_date is None:
        return None, None, None

    prior_target = current_date - pd.DateOffset(years=1)
    prior_rows = frame.loc[frame["observation_date"].eq(prior_target) & frame["value"].notna()]
    if prior_rows.empty:
        same_month = frame.loc[
            frame["value"].notna()
            & frame["observation_date"].dt.year.eq(prior_target.year)
            & frame["observation_date"].dt.month.eq(prior_target.month)
        ]
        if same_month.empty:
            return None, current_date, None
        prior_row = same_month.iloc[-1]
    else:
        prior_row = prior_rows.iloc[-1]

    prior_value = float(prior_row["value"])
    prior_date = pd.Timestamp(prior_row["observation_date"]).normalize()
    if prior_value == 0:
        return None, current_date, prior_date
    result = (current_value / prior_value - 1.0) * 100.0
    return float(result), current_date, prior_date


def validate_macro_snapshot(snapshot: pd.DataFrame) -> None:
    required = {
        "plan_year",
        "forecast_cutoff",
        "macro_vintage_date",
        "macro_interest_rate_10y",
        "macro_interest_rate_10y_observation_date",
        "macro_inflation_yoy",
        "macro_inflation_observation_date",
        "macro_inflation_prior_year_observation_date",
        "macro_credit_conditions_nfci",
        "macro_credit_conditions_nfci_observation_date",
        "macro_unemployment_rate",
        "macro_unemployment_rate_observation_date",
    }
    missing = sorted(required - set(snapshot.columns))
    if missing:
        raise ValueError(f"Macro snapshot missing required columns: {missing}")

    if snapshot["plan_year"].duplicated().any():
        raise ValueError("Macro snapshot contains duplicate plan years.")

    cutoff = pd.to_datetime(snapshot["forecast_cutoff"], errors="raise").dt.normalize()
    vintage = pd.to_datetime(snapshot["macro_vintage_date"], errors="raise").dt.normalize()
    if not vintage.eq(cutoff).all():
        raise ValueError("Macro vintage dates must equal the frozen forecast cutoff.")

    observation_columns = [
        "macro_interest_rate_10y_observation_date",
        "macro_inflation_observation_date",
        "macro_inflation_prior_year_observation_date",
        "macro_credit_conditions_nfci_observation_date",
        "macro_unemployment_rate_observation_date",
    ]
    for column in observation_columns:
        observed = pd.to_datetime(snapshot[column], errors="coerce").dt.normalize()
        violation = observed.notna() & observed.gt(cutoff)
        if violation.any():
            raise ValueError(f"Macro observation after cutoff in {column}.")
