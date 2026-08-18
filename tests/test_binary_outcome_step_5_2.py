import pandas as pd
import pytest

from risk_intelligence.features.binary_outcome import (
    apply_material_deterioration_threshold,
)


def base_panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sponsor_id": [
                "A",
                "B",
                "C",
            ],
            "predictor_plan_year": [
                2019,
                2019,
                2019,
            ],
            "target_plan_year": [
                2020,
                2020,
                2020,
            ],
            "continuous_outcome_available": [
                True,
                True,
                False,
            ],
            "delta_funded_ratio_t_plus_1": [
                -0.05,
                -0.049,
                None,
            ],
            "year_alignment_violation": [
                False,
                False,
                False,
            ],
            "same_year_target_violation": [
                False,
                False,
                False,
            ],
        }
    )


def test_primary_threshold_is_inclusive_at_negative_five_points() -> None:
    binary = apply_material_deterioration_threshold(
        base_panel(),
        threshold=0.05,
    )

    assert int(binary.loc[0, "material_deterioration"]) == 1

    assert int(binary.loc[1, "material_deterioration"]) == 0


def test_missing_continuous_outcome_remains_missing_binary() -> None:
    binary = apply_material_deterioration_threshold(
        base_panel(),
        threshold=0.05,
    )

    assert pd.isna(binary.loc[2, "material_deterioration"])

    assert not bool(binary.loc[2, "binary_outcome_available"])


def test_threshold_column_is_frozen_at_primary_value() -> None:
    binary = apply_material_deterioration_threshold(
        base_panel(),
        threshold=0.05,
    )

    assert binary["primary_threshold_c"].eq(0.05).all()

    assert binary["threshold_frozen_before_binary_construction"].all()


def test_nonpositive_threshold_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="threshold must be positive",
    ):
        apply_material_deterioration_threshold(
            base_panel(),
            threshold=0.0,
        )


def test_same_year_target_is_rejected() -> None:
    panel = base_panel()
    panel.loc[0, "target_plan_year"] = 2019
    panel.loc[0, "same_year_target_violation"] = True

    with pytest.raises(
        ValueError,
        match="Same-year",
    ):
        apply_material_deterioration_threshold(
            panel,
            threshold=0.05,
        )


def test_binary_missingness_cannot_differ_from_continuous_availability() -> None:
    panel = base_panel()

    panel.loc[
        2,
        "delta_funded_ratio_t_plus_1",
    ] = -0.20

    with pytest.raises(
        ValueError,
        match="Unavailable continuous outcome",
    ):
        apply_material_deterioration_threshold(
            panel,
            threshold=0.05,
        )
