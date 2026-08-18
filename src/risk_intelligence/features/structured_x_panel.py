"""Validation helpers for the frozen Milestone-4 structured-X panel."""

from __future__ import annotations

from typing import Any

import pandas as pd

TRANSFORMATION_VERSION = "4.5.0"
EXPECTED_ROWS = 5_934
EXPECTED_SPONSORS = 729
EXPECTED_CIKS = 729
EXPECTED_YEAR_START = 2015
EXPECTED_YEAR_END = 2024
EXPECTED_CUTOFF_MONTH = 10
EXPECTED_CUTOFF_DAY = 15

KEY_COLUMNS = ["sponsor_id", "sec_cik", "plan_year", "forecast_cutoff"]
REQUIRED_CONTROL_COLUMNS = [*KEY_COLUMNS, "information_date"]

FEATURE_FAMILIES: dict[str, list[str]] = {
    "pension": [
        "funded_ratio",
        "assets",
        "liabilities",
        "contributions",
        "benefit_payments",
        "participants",
        "pension_size",
        "pension_assets_to_sponsor_assets",
        "pension_liabilities_to_sponsor_assets",
        "pension_contributions_to_revenue",
    ],
    "sponsor_financials": [
        "sec_total_assets",
        "sec_total_liabilities",
        "sec_debt",
        "sec_cash",
        "sec_revenue",
        "sec_operating_income",
        "sec_operating_cash_flow",
        "sec_profitability",
        "sec_leverage",
        "sec_liquidity",
        "sec_pension_plan_assets",
        "sec_pension_projected_benefit_obligation",
        "sec_pension_employer_contributions",
    ],
    "market": [
        "market_equity_return",
        "market_equity_volatility",
        "market_equity_drawdown",
        "market_capitalization",
    ],
    "macro": [
        "macro_interest_rate_10y",
        "macro_inflation_yoy",
        "macro_credit_conditions_nfci",
        "macro_unemployment_rate",
    ],
}

MODEL_FEATURES = [field for fields in FEATURE_FAMILIES.values() for field in fields]


def _normalize_cik(value: Any) -> str:
    if pd.isna(value):
        raise RuntimeError("Final structured-X panel contains a missing SEC CIK.")
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isdigit():
        raise RuntimeError(f"Invalid SEC CIK in final panel: {value!r}")
    return text.zfill(10)


def _date_columns(frame: pd.DataFrame) -> list[str]:
    explicit = {
        "information_date",
        "sec_information_date",
        "market_price_information_date",
        "market_shares_filed_date",
        "macro_vintage_date",
        "macro_interest_rate_10y_observation_date",
        "macro_inflation_observation_date",
        "macro_inflation_prior_year_observation_date",
        "macro_credit_conditions_nfci_observation_date",
        "macro_unemployment_rate_observation_date",
    }
    suffixes = ("_filed_date", "_information_date", "_observation_date", "_period_end")
    dynamic = {column for column in frame.columns if column.endswith(suffixes)}
    return sorted((explicit | dynamic) & set(frame.columns))


def validate_final_panel(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = set(REQUIRED_CONTROL_COLUMNS) | set(MODEL_FEATURES)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"Final structured-X panel is missing required columns: {missing}")

    work = frame.copy()
    work["sponsor_id"] = work["sponsor_id"].astype("string").str.strip()
    work["sec_cik"] = work["sec_cik"].map(_normalize_cik).astype("string")
    work["plan_year"] = pd.to_numeric(work["plan_year"], errors="raise").astype(int)
    work["forecast_cutoff"] = pd.to_datetime(work["forecast_cutoff"], errors="raise").dt.normalize()

    checks = {
        "rows": (int(len(work)), EXPECTED_ROWS),
        "unique_sponsors": (int(work["sponsor_id"].nunique()), EXPECTED_SPONSORS),
        "unique_ciks": (int(work["sec_cik"].nunique()), EXPECTED_CIKS),
        "plan_year_start": (int(work["plan_year"].min()), EXPECTED_YEAR_START),
        "plan_year_end": (int(work["plan_year"].max()), EXPECTED_YEAR_END),
        "duplicate_sponsor_year_rows": (
            int(work.duplicated(["sponsor_id", "plan_year"], keep=False).sum()),
            0,
        ),
    }
    for name, (actual, expected) in checks.items():
        if actual != expected:
            raise RuntimeError(f"Final panel drift: {name}={actual}; expected={expected}")

    expected_cutoff = pd.to_datetime(
        {
            "year": work["plan_year"] + 1,
            "month": EXPECTED_CUTOFF_MONTH,
            "day": EXPECTED_CUTOFF_DAY,
        }
    )
    cutoff_mismatch = int(work["forecast_cutoff"].ne(expected_cutoff).sum())
    if cutoff_mismatch:
        raise RuntimeError(f"Final forecast-cutoff drift: mismatch_rows={cutoff_mismatch}")

    temporal_violations: dict[str, int] = {}
    unparsable_dates: dict[str, int] = {}
    for column in _date_columns(work):
        original = work[column]
        text = original.astype("string").str.strip()
        blank = text.eq("").fillna(False)
        normalized = original.mask(blank)
        parsed = pd.to_datetime(normalized, errors="coerce").dt.normalize()
        supplied = original.notna() & ~blank
        unparsable = int((supplied & parsed.isna()).sum())
        if unparsable:
            unparsable_dates[column] = unparsable
        violations = int((parsed.notna() & parsed.gt(work["forecast_cutoff"])).sum())
        temporal_violations[column] = violations

    if unparsable_dates:
        raise RuntimeError(f"Unparsable temporal provenance values: {unparsable_dates}")
    total_temporal_violations = int(sum(temporal_violations.values()))
    if total_temporal_violations:
        raise RuntimeError(f"Final panel temporal violations: {temporal_violations}")

    if "macro_vintage_date" in work.columns:
        vintage = pd.to_datetime(work["macro_vintage_date"], errors="coerce").dt.normalize()
        mismatch = int((vintage.notna() & vintage.ne(work["forecast_cutoff"])).sum())
        if mismatch:
            raise RuntimeError(f"Macro vintage/cutoff mismatch rows={mismatch}")

    family_any_nonmissing = {
        family: int(work[fields].notna().any(axis=1).sum())
        for family, fields in FEATURE_FAMILIES.items()
    }
    if any(value == 0 for value in family_any_nonmissing.values()):
        raise RuntimeError(
            f"A structured-X family has zero usable coverage: {family_any_nonmissing}"
        )

    diagnostics = {
        "rows": int(len(work)),
        "unique_sponsors": int(work["sponsor_id"].nunique()),
        "unique_ciks": int(work["sec_cik"].nunique()),
        "duplicate_sponsor_year_rows": int(
            work.duplicated(["sponsor_id", "plan_year"], keep=False).sum()
        ),
        "plan_year_start": int(work["plan_year"].min()),
        "plan_year_end": int(work["plan_year"].max()),
        "temporal_violation_count": total_temporal_violations,
        "checked_temporal_columns": _date_columns(work),
        "model_feature_count": len(MODEL_FEATURES),
        "family_feature_counts": {
            family: len(fields) for family, fields in FEATURE_FAMILIES.items()
        },
        "family_any_nonmissing": family_any_nonmissing,
    }
    return work.sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True), diagnostics


def build_feature_missingness(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for family, fields in FEATURE_FAMILIES.items():
        for field in fields:
            missing = int(frame[field].isna().sum())
            rows.append(
                {
                    "family": family,
                    "field": field,
                    "rows": int(len(frame)),
                    "missing_count": missing,
                    "nonmissing_count": int(len(frame) - missing),
                    "missing_rate": float(missing / len(frame)),
                }
            )
    return pd.DataFrame(rows)


def build_schema_audit(frame: pd.DataFrame) -> pd.DataFrame:
    family_by_field = {
        field: family for family, fields in FEATURE_FAMILIES.items() for field in fields
    }
    rows = []
    for position, column in enumerate(frame.columns, start=1):
        rows.append(
            {
                "column_position": position,
                "column": column,
                "dtype": str(frame[column].dtype),
                "role": "model_feature" if column in MODEL_FEATURES else "control_or_provenance",
                "family": family_by_field.get(column, ""),
            }
        )
    return pd.DataFrame(rows)


def build_family_coverage_by_year(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for plan_year, group in frame.groupby("plan_year", sort=True):
        row: dict[str, Any] = {
            "plan_year": int(plan_year),
            "sponsor_year_rows": int(len(group)),
        }
        for family, fields in FEATURE_FAMILIES.items():
            row[f"{family}_any_nonmissing"] = int(group[fields].notna().any(axis=1).sum())
            row[f"{family}_all_nonmissing"] = int(group[fields].notna().all(axis=1).sum())
        rows.append(row)
    return pd.DataFrame(rows)
