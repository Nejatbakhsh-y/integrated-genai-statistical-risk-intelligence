"""Binary pension-deterioration outcome construction for Milestone 5 Step 5.2."""

from __future__ import annotations

import pandas as pd

TRANSFORMATION_VERSION = "5.2.0"

REQUIRED_CONTINUOUS_COLUMNS = {
    "sponsor_id",
    "predictor_plan_year",
    "target_plan_year",
    "continuous_outcome_available",
    "delta_funded_ratio_t_plus_1",
    "year_alignment_violation",
    "same_year_target_violation",
}


def apply_material_deterioration_threshold(
    continuous_panel: pd.DataFrame,
    *,
    threshold: float,
) -> pd.DataFrame:
    """Apply a frozen positive threshold to the continuous outcome.

    Missing continuous outcomes remain missing binary outcomes.
    """
    if threshold <= 0:
        raise ValueError("Material-deterioration threshold must be positive.")

    missing = sorted(REQUIRED_CONTINUOUS_COLUMNS - set(continuous_panel.columns))

    if missing:
        raise ValueError(f"Missing continuous-outcome columns: {missing}")

    panel = continuous_panel.copy()

    if panel.duplicated(
        ["sponsor_id", "predictor_plan_year"],
        keep=False,
    ).any():
        raise ValueError("Duplicate predictor sponsor-year rows detected.")

    if panel["year_alignment_violation"].astype(bool).any():
        raise ValueError("Year-alignment violation detected.")

    if panel["same_year_target_violation"].astype(bool).any():
        raise ValueError("Same-year target violation detected.")

    expected_target_year = (
        pd.to_numeric(
            panel["predictor_plan_year"],
            errors="raise",
        ).astype(int)
        + 1
    )

    observed_target_year = pd.to_numeric(
        panel["target_plan_year"],
        errors="raise",
    ).astype(int)

    if not observed_target_year.eq(expected_target_year).all():
        raise ValueError("Target year does not equal predictor year + 1.")

    continuous_available = (
        panel["continuous_outcome_available"].astype("boolean").fillna(False).astype(bool)
    )

    delta = pd.to_numeric(
        panel["delta_funded_ratio_t_plus_1"],
        errors="coerce",
    )

    if (continuous_available & delta.isna()).any():
        raise ValueError("Available continuous outcome has missing DeltaFR.")

    if (~continuous_available & delta.notna()).any():
        raise ValueError("Unavailable continuous outcome contains a DeltaFR value.")

    binary = pd.Series(
        pd.NA,
        index=panel.index,
        dtype="Int8",
    )

    binary.loc[continuous_available] = (
        delta.loc[continuous_available].le(-float(threshold)).astype("int8")
    )

    panel["binary_outcome_available"] = continuous_available
    panel["material_deterioration"] = binary
    panel["primary_threshold_c"] = float(threshold)
    panel["threshold_frozen_before_binary_construction"] = True
    panel["binary_transformation_version"] = TRANSFORMATION_VERSION

    observed_values = set(panel["material_deterioration"].dropna().astype(int).unique().tolist())

    if not observed_values.issubset({0, 1}):
        raise ValueError("Binary material-deterioration outcome is not in {0,1}.")

    if (panel["binary_outcome_available"] != panel["material_deterioration"].notna()).any():
        raise ValueError("Binary outcome missingness does not match availability.")

    expected_binary = delta.loc[continuous_available].le(-float(threshold)).astype("int8")

    actual_binary = panel.loc[
        continuous_available,
        "material_deterioration",
    ].astype("int8")

    if not actual_binary.equals(expected_binary):
        raise ValueError("Binary outcome identity check failed.")

    return panel
