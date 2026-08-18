"""One-year-ahead continuous pension-outcome construction for Milestone 5."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRANSFORMATION_VERSION = "5.1.0"

REQUIRED_COLUMNS = {
    "sponsor_id",
    "sec_cik",
    "plan_year",
    "forecast_cutoff",
    "information_date",
    "assets",
    "liabilities",
    "funded_ratio",
    "funded_ratio_available",
}


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def validate_pension_base(base: pd.DataFrame) -> pd.DataFrame:
    """Validate the frozen sponsor-year pension base before target construction."""
    missing = sorted(REQUIRED_COLUMNS - set(base.columns))
    if missing:
        raise ValueError(f"Missing pension-base columns: {missing}")

    work = base.copy()

    work["sponsor_id"] = work["sponsor_id"].astype("string").str.strip()
    work["sec_cik"] = work["sec_cik"].astype("string").str.strip()
    work["plan_year"] = _numeric(work["plan_year"]).astype(int)

    work["assets"] = _numeric(work["assets"])
    work["liabilities"] = _numeric(work["liabilities"])
    work["funded_ratio"] = _numeric(work["funded_ratio"])

    work["funded_ratio_available"] = (
        work["funded_ratio_available"].astype("boolean").fillna(False).astype(bool)
    )

    if work["sponsor_id"].isna().any():
        raise ValueError("Blank sponsor_id detected in pension base.")

    if work["sec_cik"].isna().any():
        raise ValueError("Blank sec_cik detected in pension base.")

    duplicate_rows = int(work.duplicated(["sponsor_id", "plan_year"], keep=False).sum())
    if duplicate_rows:
        raise ValueError("Duplicate sponsor-year rows detected in pension base.")

    denominator_valid = work["liabilities"].notna() & work["liabilities"].gt(0.0)
    numerator_valid = work["assets"].notna()
    independently_available = numerator_valid & denominator_valid

    declared_available = work["funded_ratio_available"]

    availability_mismatch = independently_available.ne(declared_available)
    if availability_mismatch.any():
        raise ValueError(
            "funded_ratio_available disagrees with independent asset/liability validity."
        )

    declared_ratio_presence = work["funded_ratio"].notna()
    if declared_ratio_presence.ne(declared_available).any():
        raise ValueError("funded_ratio presence disagrees with funded_ratio_available.")

    expected_ratio = pd.Series(np.nan, index=work.index, dtype=float)
    expected_ratio.loc[independently_available] = work.loc[
        independently_available, "assets"
    ].astype(float) / work.loc[independently_available, "liabilities"].astype(float)

    present = expected_ratio.notna() & work["funded_ratio"].notna()

    if present.any():
        close = np.isclose(
            expected_ratio.loc[present].to_numpy(dtype=float),
            work.loc[present, "funded_ratio"].to_numpy(dtype=float),
            atol=1e-12,
            rtol=1e-10,
        )
        if not bool(close.all()):
            raise ValueError(
                "Frozen funded_ratio disagrees with independent assets/liabilities ratio."
            )

    return work


def build_continuous_outcome_panel(
    base: pd.DataFrame,
    *,
    max_target_plan_year: int,
) -> pd.DataFrame:
    """Construct exact t -> t+1 continuous funded-ratio changes."""
    work = validate_pension_base(base)

    predictor = work.loc[work["plan_year"].lt(int(max_target_plan_year))].copy()

    predictor = predictor[
        [
            "sponsor_id",
            "sec_cik",
            "plan_year",
            "forecast_cutoff",
            "information_date",
            "assets",
            "liabilities",
            "funded_ratio",
            "funded_ratio_available",
        ]
    ].rename(
        columns={
            "plan_year": "predictor_plan_year",
            "forecast_cutoff": "predictor_forecast_cutoff",
            "information_date": "predictor_information_date",
            "assets": "predictor_assets",
            "liabilities": "predictor_liabilities",
            "funded_ratio": "predictor_funded_ratio",
            "funded_ratio_available": "predictor_funded_ratio_available",
        }
    )

    predictor["target_plan_year"] = predictor["predictor_plan_year"] + 1

    target = work[
        [
            "sponsor_id",
            "sec_cik",
            "plan_year",
            "forecast_cutoff",
            "information_date",
            "assets",
            "liabilities",
            "funded_ratio",
            "funded_ratio_available",
        ]
    ].rename(
        columns={
            "sec_cik": "target_sec_cik",
            "plan_year": "target_plan_year",
            "forecast_cutoff": "target_forecast_cutoff",
            "information_date": "target_information_date",
            "assets": "target_assets",
            "liabilities": "target_liabilities",
            "funded_ratio": "target_funded_ratio",
            "funded_ratio_available": "target_funded_ratio_available",
        }
    )

    target["target_row_present"] = True

    panel = predictor.merge(
        target,
        on=["sponsor_id", "target_plan_year"],
        how="left",
        validate="one_to_one",
    )

    panel["has_consecutive_target_row"] = panel["target_row_present"].fillna(False).astype(bool)

    panel["target_funded_ratio_available"] = (
        panel["target_funded_ratio_available"].astype("boolean").fillna(False).astype(bool)
    )

    panel["predictor_funded_ratio_available"] = (
        panel["predictor_funded_ratio_available"].astype("boolean").fillna(False).astype(bool)
    )

    target_present = panel["has_consecutive_target_row"]

    cik_mismatch = (
        target_present
        & panel["target_sec_cik"].notna()
        & panel["sec_cik"].ne(panel["target_sec_cik"])
    )
    if cik_mismatch.any():
        raise ValueError("SEC CIK changed within a sponsor's consecutive-year pair.")

    panel["predictor_liabilities_positive"] = panel["predictor_liabilities"].notna() & panel[
        "predictor_liabilities"
    ].gt(0.0)

    panel["target_liabilities_positive"] = (
        target_present & panel["target_liabilities"].notna() & panel["target_liabilities"].gt(0.0)
    )

    panel["continuous_outcome_available"] = (
        target_present
        & panel["predictor_funded_ratio_available"]
        & panel["target_funded_ratio_available"]
    )

    panel["delta_funded_ratio_t_plus_1"] = np.where(
        panel["continuous_outcome_available"],
        panel["target_funded_ratio"] - panel["predictor_funded_ratio"],
        np.nan,
    )

    panel["year_alignment_violation"] = panel["target_plan_year"].ne(
        panel["predictor_plan_year"] + 1
    )

    panel["same_year_target_violation"] = panel["target_plan_year"].eq(panel["predictor_plan_year"])

    if panel["year_alignment_violation"].any():
        raise ValueError("Year-alignment violation detected.")

    if panel["same_year_target_violation"].any():
        raise ValueError("Same-year outcome pairing detected.")

    duplicate_rows = int(
        panel.duplicated(
            ["sponsor_id", "predictor_plan_year"],
            keep=False,
        ).sum()
    )
    if duplicate_rows:
        raise ValueError("Duplicate predictor sponsor-year rows detected.")

    available = panel["continuous_outcome_available"]

    if available.any():
        independently_recomputed = panel.loc[available, "target_funded_ratio"].astype(
            float
        ) - panel.loc[available, "predictor_funded_ratio"].astype(float)

        close = np.isclose(
            independently_recomputed.to_numpy(dtype=float),
            panel.loc[
                available,
                "delta_funded_ratio_t_plus_1",
            ].to_numpy(dtype=float),
            atol=1e-12,
            rtol=1e-10,
        )

        if not bool(close.all()):
            raise ValueError("Continuous outcome identity check failed.")

    unavailable_with_value = (
        ~panel["continuous_outcome_available"] & panel["delta_funded_ratio_t_plus_1"].notna()
    )
    if unavailable_with_value.any():
        raise ValueError("Unavailable outcome row received an imputed target value.")

    panel["transformation_version"] = TRANSFORMATION_VERSION

    drop_columns = ["target_row_present"]

    panel = panel.drop(columns=drop_columns).sort_values(["sponsor_id", "predictor_plan_year"])

    return panel.reset_index(drop=True)
