import numpy as np
import pandas as pd
import pytest

from risk_intelligence.features.outcome_panel import (
    build_continuous_outcome_panel,
    validate_pension_base,
)


def row(
    sponsor_id: str,
    year: int,
    assets: float | None,
    liabilities: float | None,
) -> dict[str, object]:
    available = assets is not None and liabilities is not None and liabilities > 0

    funded_ratio = float(assets) / float(liabilities) if available else np.nan

    return {
        "sponsor_id": sponsor_id,
        "sec_cik": f"CIK-{sponsor_id}",
        "plan_year": year,
        "forecast_cutoff": pd.Timestamp(year + 1, 10, 15),
        "information_date": pd.Timestamp(year + 1, 6, 1),
        "assets": assets,
        "liabilities": liabilities,
        "funded_ratio": funded_ratio,
        "funded_ratio_available": available,
    }


def test_exact_one_year_pair_constructs_delta() -> None:
    base = pd.DataFrame(
        [
            row("A", 2019, 90.0, 100.0),
            row("A", 2020, 80.0, 100.0),
        ]
    )

    panel = build_continuous_outcome_panel(
        base,
        max_target_plan_year=2020,
    )

    assert len(panel) == 1
    assert panel.loc[0, "predictor_plan_year"] == 2019
    assert panel.loc[0, "target_plan_year"] == 2020
    assert bool(panel.loc[0, "has_consecutive_target_row"])
    assert bool(panel.loc[0, "continuous_outcome_available"])
    assert panel.loc[
        0,
        "delta_funded_ratio_t_plus_1",
    ] == pytest.approx(-0.1)


def test_nonconsecutive_year_is_not_relabelled_as_one_year() -> None:
    base = pd.DataFrame(
        [
            row("A", 2019, 90.0, 100.0),
            row("A", 2021, 80.0, 100.0),
        ]
    )

    panel = build_continuous_outcome_panel(
        base,
        max_target_plan_year=2021,
    )

    first = panel.loc[panel["predictor_plan_year"].eq(2019)].iloc[0]

    assert not bool(first["has_consecutive_target_row"])
    assert not bool(first["continuous_outcome_available"])
    assert pd.isna(first["delta_funded_ratio_t_plus_1"])


def test_missing_or_invalid_target_ratio_remains_missing() -> None:
    base = pd.DataFrame(
        [
            row("A", 2019, 90.0, 100.0),
            row("A", 2020, 80.0, 0.0),
        ]
    )

    panel = build_continuous_outcome_panel(
        base,
        max_target_plan_year=2020,
    )

    assert bool(panel.loc[0, "has_consecutive_target_row"])
    assert not bool(panel.loc[0, "target_funded_ratio_available"])
    assert not bool(panel.loc[0, "continuous_outcome_available"])
    assert pd.isna(panel.loc[0, "delta_funded_ratio_t_plus_1"])


def test_duplicate_sponsor_year_is_rejected() -> None:
    duplicate = row("A", 2019, 90.0, 100.0)

    base = pd.DataFrame(
        [
            duplicate,
            duplicate.copy(),
        ]
    )

    with pytest.raises(ValueError, match="Duplicate sponsor-year"):
        validate_pension_base(base)


def test_funded_ratio_identity_mismatch_is_rejected() -> None:
    bad = row("A", 2019, 90.0, 100.0)
    bad["funded_ratio"] = 0.5

    base = pd.DataFrame([bad])

    with pytest.raises(
        ValueError,
        match="independent assets/liabilities ratio",
    ):
        validate_pension_base(base)
