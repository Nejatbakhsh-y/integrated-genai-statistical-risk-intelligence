"""Point-in-time pension sponsor-year aggregation for Milestone 4 Step 4.1."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRANSFORMATION_VERSION = "4.1.0"
SELECTED_CUTOFF_ID = "OCTOBER_15_T_PLUS_1"
SELECTED_CUTOFF_MONTH = 10
SELECTED_CUTOFF_DAY = 15

PENSION_VALUE_FIELDS = (
    "assets",
    "liabilities",
    "contributions",
    "benefit_payments",
    "participants",
)


@dataclass(frozen=True)
class CutoffPolicy:
    policy_id: str = SELECTED_CUTOFF_ID
    month: int = SELECTED_CUTOFF_MONTH
    day: int = SELECTED_CUTOFF_DAY


def forecast_cutoff_for_plan_year(
    plan_year: int,
    *,
    month: int = SELECTED_CUTOFF_MONTH,
    day: int = SELECTED_CUTOFF_DAY,
) -> pd.Timestamp:
    """Return the common point-in-time cutoff for sponsor-year t."""
    return pd.Timestamp(year=int(plan_year) + 1, month=month, day=day)


def clean_identifier(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    invalid = values.str.lower().isin({"", "nan", "none", "null", "<na>"})
    return values.mask(invalid)


def _complete_sum(series: pd.Series, expected_count: int) -> tuple[float, int, bool]:
    values = pd.to_numeric(series, errors="coerce")
    nonmissing = int(values.notna().sum())
    complete = expected_count > 0 and nonmissing == expected_count
    if not complete:
        return float("nan"), nonmissing, False
    return float(values.sum()), nonmissing, True


def build_pension_sponsor_year_base(
    linked: pd.DataFrame,
    crosswalk: pd.DataFrame,
    *,
    cik_column: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the Step-4.1 sponsor-year pension base and retrospective audit detail.

    Analytical values are constructed only from plan filings whose information_date
    is on or before the frozen forecast cutoff. Retrospective knowledge about late or
    missing filings is confined to the returned audit-detail frame and is not exposed
    as an analytical feature in the sponsor-year base.
    """
    required = {
        "sponsor_id",
        "plan_id",
        "plan_year",
        "assets",
        "liabilities",
        "contributions",
        "benefit_payments",
        "participants",
        "source_file",
        "information_date",
    }
    missing = sorted(required - set(linked.columns))
    if missing:
        raise ValueError(f"Missing linked pension columns: {missing}")

    if "sponsor_id" not in crosswalk.columns or cik_column not in crosswalk.columns:
        raise ValueError("Crosswalk lacks sponsor_id or the selected SEC CIK column.")

    work = linked.copy()
    work["sponsor_id"] = clean_identifier(work["sponsor_id"])
    work["plan_id"] = clean_identifier(work["plan_id"])
    work["plan_year"] = pd.to_numeric(work["plan_year"], errors="raise").astype(int)
    work["information_date"] = pd.to_datetime(work["information_date"], errors="coerce")

    if work["sponsor_id"].isna().any() or work["plan_id"].isna().any():
        raise ValueError("Blank sponsor_id or plan_id detected in linked pension data.")

    cross = crosswalk[["sponsor_id", cik_column]].copy()
    cross["sponsor_id"] = clean_identifier(cross["sponsor_id"])
    cross[cik_column] = clean_identifier(cross[cik_column])

    if cross["sponsor_id"].isna().any() or cross[cik_column].isna().any():
        raise ValueError("Blank sponsor_id or CIK detected in crosswalk.")

    if cross["sponsor_id"].duplicated().any():
        raise ValueError("Duplicate sponsor_id detected in crosswalk.")

    sponsor_to_cik = cross.set_index("sponsor_id")[cik_column].to_dict()

    base_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []

    grouped = work.groupby(["sponsor_id", "plan_year"], sort=True, dropna=False)

    for (sponsor_id, plan_year), group in grouped:
        group = group.sort_values(["plan_id", "information_date"], na_position="last").copy()
        cutoff = forecast_cutoff_for_plan_year(int(plan_year))

        known_date = group["information_date"].notna()
        eligible_mask = known_date & group["information_date"].le(cutoff)
        late_mask = known_date & group["information_date"].gt(cutoff)
        missing_date_mask = ~known_date

        eligible = group.loc[eligible_mask].copy()
        eligible_count = int(len(eligible))
        linked_count = int(len(group))

        row: dict[str, object] = {
            "sponsor_id": str(sponsor_id),
            "sec_cik": sponsor_to_cik.get(str(sponsor_id)),
            "plan_year": int(plan_year),
            "forecast_cutoff": cutoff,
            "information_date": (
                eligible["information_date"].max() if eligible_count else pd.NaT
            ),
            "available_plan_count": eligible_count,
            "multi_plan_available": eligible_count > 1,
            "participants_overlap_risk": eligible_count > 1,
            "source_files": "|".join(
                sorted(
                    {
                        str(value).strip()
                        for value in eligible["source_file"].dropna().tolist()
                        if str(value).strip()
                    }
                )
            ),
            "transformation_version": TRANSFORMATION_VERSION,
        }

        completeness: dict[str, bool] = {}

        for field in PENSION_VALUE_FIELDS:
            value, nonmissing, complete = _complete_sum(eligible[field], eligible_count)
            row[field] = value
            row[f"{field}_available_plan_count"] = nonmissing
            row[f"{field}_complete"] = complete
            completeness[field] = complete

        liabilities = row["liabilities"]
        assets = row["assets"]
        ratio_available = (
            completeness["assets"]
            and completeness["liabilities"]
            and pd.notna(liabilities)
            and float(liabilities) > 0.0
        )

        row["funded_ratio"] = (
            float(assets) / float(liabilities) if ratio_available else float("nan")
        )
        row["funded_ratio_available"] = bool(ratio_available)

        base_rows.append(row)

        audit_rows.append(
            {
                "sponsor_id": str(sponsor_id),
                "plan_year": int(plan_year),
                "linked_plan_count": linked_count,
                "eligible_plan_count": eligible_count,
                "late_plan_count": int(late_mask.sum()),
                "missing_information_date_plan_count": int(missing_date_mask.sum()),
                "all_linked_plans_available_by_cutoff": eligible_count == linked_count,
                "forecast_cutoff": cutoff,
                "latest_linked_information_date": group["information_date"].max(),
            }
        )

    base = pd.DataFrame(base_rows).sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)
    detail = (
        pd.DataFrame(audit_rows)
        .sort_values(["sponsor_id", "plan_year"])
        .reset_index(drop=True)
    )

    if base["sec_cik"].isna().any():
        raise ValueError("At least one linked sponsor-year failed SEC CIK attachment.")

    duplicate_rows = int(base.duplicated(["sponsor_id", "plan_year"], keep=False).sum())
    if duplicate_rows:
        raise ValueError("Duplicate sponsor-year rows were created.")

    temporal_violation = base["information_date"].notna() & base["information_date"].gt(
        base["forecast_cutoff"]
    )
    if temporal_violation.any():
        raise ValueError("Temporal-integrity violation in sponsor-year pension base.")

    return base, detail


def direct_expected_aggregation(
    linked: pd.DataFrame,
    *,
    field: str,
) -> pd.DataFrame:
    """Independently derive point-in-time complete-field sums for identity audits."""
    if field not in PENSION_VALUE_FIELDS:
        raise ValueError(f"Unsupported pension field: {field}")

    work = linked[["sponsor_id", "plan_id", "plan_year", "information_date", field]].copy()
    work["plan_year"] = pd.to_numeric(work["plan_year"], errors="raise").astype(int)
    work["information_date"] = pd.to_datetime(work["information_date"], errors="coerce")
    work["forecast_cutoff"] = work["plan_year"].map(forecast_cutoff_for_plan_year)
    work = work.loc[
        work["information_date"].notna()
        & work["information_date"].le(work["forecast_cutoff"])
    ].copy()
    work[field] = pd.to_numeric(work[field], errors="coerce")

    rows: list[dict[str, object]] = []
    for (sponsor_id, plan_year), group in work.groupby(
        ["sponsor_id", "plan_year"], sort=True, dropna=False
    ):
        expected_count = int(len(group))
        value, nonmissing, complete = _complete_sum(group[field], expected_count)
        rows.append(
            {
                "sponsor_id": sponsor_id,
                "plan_year": int(plan_year),
                f"expected_{field}": value,
                f"expected_{field}_available_plan_count": nonmissing,
                f"expected_{field}_complete": complete,
            }
        )

    return pd.DataFrame(rows)


def numeric_equal(left: pd.Series, right: pd.Series, *, atol: float = 1e-9) -> pd.Series:
    """NaN-aware numeric equality helper for audit assertions."""
    left_values = pd.to_numeric(left, errors="coerce")
    right_values = pd.to_numeric(right, errors="coerce")
    both_missing = left_values.isna() & right_values.isna()
    both_present = left_values.notna() & right_values.notna()
    close = pd.Series(False, index=left.index)
    if both_present.any():
        close.loc[both_present] = np.isclose(
            left_values.loc[both_present].astype(float),
            right_values.loc[both_present].astype(float),
            atol=atol,
            rtol=1e-10,
        )
    return both_missing | close