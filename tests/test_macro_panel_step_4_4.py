from __future__ import annotations

import pandas as pd
import pytest

from risk_intelligence.features.macro_panel import (
    SERIES_SPECS,
    latest_available_observation,
    parse_alfred_csv,
    validate_macro_snapshot,
    year_over_year_percent,
)


def test_series_registry_is_frozen() -> None:
    mapping = {spec.feature: spec.series_id for spec in SERIES_SPECS}
    assert mapping == {
        "macro_interest_rate_10y": "DGS10",
        "macro_inflation_yoy": "CPIAUCNS",
        "macro_credit_conditions_nfci": "NFCI",
        "macro_unemployment_rate": "UNRATE",
    }


def test_parse_alfred_csv_accepts_vintage_suffix_column() -> None:
    content = b"DATE,UNRATE_20241015\n2024-08-01,4.2\n2024-09-01,4.1\n"
    frame = parse_alfred_csv(content, "UNRATE")
    assert list(frame.columns) == ["observation_date", "value"]
    assert frame.iloc[-1]["value"] == pytest.approx(4.1)


def test_latest_observation_never_uses_future_date() -> None:
    frame = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(["2024-10-11", "2024-10-15", "2024-10-16"]),
            "value": [4.1, 4.2, 9.9],
        }
    )
    value, date = latest_available_observation(frame, pd.Timestamp("2024-10-15"))
    assert value == pytest.approx(4.2)
    assert date == pd.Timestamp("2024-10-15")


def test_year_over_year_inflation_uses_same_month_prior_year() -> None:
    frame = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(["2023-09-01", "2024-08-01", "2024-09-01"]),
            "value": [300.0, 308.0, 309.0],
        }
    )
    value, current_date, prior_date = year_over_year_percent(
        frame,
        pd.Timestamp("2024-10-15"),
    )
    assert value == pytest.approx(3.0)
    assert current_date == pd.Timestamp("2024-09-01")
    assert prior_date == pd.Timestamp("2023-09-01")


def test_validate_macro_snapshot_accepts_cutoff_vintage() -> None:
    frame = pd.DataFrame(
        {
            "plan_year": [2023],
            "forecast_cutoff": pd.to_datetime(["2024-10-15"]),
            "macro_vintage_date": pd.to_datetime(["2024-10-15"]),
            "macro_interest_rate_10y": [4.1],
            "macro_interest_rate_10y_observation_date": pd.to_datetime(["2024-10-15"]),
            "macro_inflation_yoy": [3.0],
            "macro_inflation_observation_date": pd.to_datetime(["2024-09-01"]),
            "macro_inflation_prior_year_observation_date": pd.to_datetime(["2023-09-01"]),
            "macro_credit_conditions_nfci": [-0.4],
            "macro_credit_conditions_nfci_observation_date": pd.to_datetime(["2024-10-11"]),
            "macro_unemployment_rate": [4.1],
            "macro_unemployment_rate_observation_date": pd.to_datetime(["2024-09-01"]),
        }
    )
    validate_macro_snapshot(frame)


def test_validate_macro_snapshot_rejects_future_observation() -> None:
    frame = pd.DataFrame(
        {
            "plan_year": [2023],
            "forecast_cutoff": pd.to_datetime(["2024-10-15"]),
            "macro_vintage_date": pd.to_datetime(["2024-10-15"]),
            "macro_interest_rate_10y": [4.1],
            "macro_interest_rate_10y_observation_date": pd.to_datetime(["2024-10-16"]),
            "macro_inflation_yoy": [3.0],
            "macro_inflation_observation_date": pd.to_datetime(["2024-09-01"]),
            "macro_inflation_prior_year_observation_date": pd.to_datetime(["2023-09-01"]),
            "macro_credit_conditions_nfci": [-0.4],
            "macro_credit_conditions_nfci_observation_date": pd.to_datetime(["2024-10-11"]),
            "macro_unemployment_rate": [4.1],
            "macro_unemployment_rate_observation_date": pd.to_datetime(["2024-09-01"]),
        }
    )
    with pytest.raises(ValueError, match="after cutoff"):
        validate_macro_snapshot(frame)
