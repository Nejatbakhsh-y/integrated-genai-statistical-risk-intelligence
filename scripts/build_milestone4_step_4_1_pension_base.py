"""Build and audit the Milestone-4 Step-4.1 pension sponsor-year base."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from risk_intelligence.features.pension_panel import (
    PENSION_VALUE_FIELDS,
    SELECTED_CUTOFF_ID,
    TRANSFORMATION_VERSION,
    build_pension_sponsor_year_base,
    direct_expected_aggregation,
    forecast_cutoff_for_plan_year,
    numeric_equal,
)

EXPECTED_UNIVERSE_SHA256 = "ED22F81E6F6E407F0494CDBB94AB6D8FA84B9CF576C637D02E20A013735E6255"
EXPECTED_CROSSWALK_SHA256 = "264FF2DCD22223B654C122B7EE6F69B23CEA71A8885937D976C1BBCF8203D55A"
EXPECTED_LINKED_PLAN_ROWS = 8_950
EXPECTED_LINKED_PLANS = 1_294
EXPECTED_LINKED_SPONSORS = 729
EXPECTED_SPONSOR_YEARS = 5_934
EXPECTED_YEAR_START = 2015
EXPECTED_YEAR_END = 2024

CUTOFF_CANDIDATES = (
    ("JULY_31_T_PLUS_1", 7, 31),
    ("SEPTEMBER_30_T_PLUS_1", 9, 30),
    ("OCTOBER_15_T_PLUS_1", 10, 15),
    ("DECEMBER_31_T_PLUS_1", 12, 31),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def clean_identifier(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    invalid = values.str.lower().isin({"", "nan", "none", "null", "<na>"})
    return values.mask(invalid)


def cutoff_diagnostics(linked: pd.DataFrame) -> pd.DataFrame:
    work = linked[["sponsor_id", "plan_id", "plan_year", "information_date"]].copy()
    work["plan_year"] = pd.to_numeric(work["plan_year"], errors="raise").astype(int)
    work["information_date"] = pd.to_datetime(work["information_date"], errors="coerce")

    total_plan_rows = int(len(work))
    total_sponsor_years = int(work[["sponsor_id", "plan_year"]].drop_duplicates().shape[0])
    rows: list[dict[str, object]] = []

    for policy_id, month, day in CUTOFF_CANDIDATES:
        cutoffs = work["plan_year"].map(
            lambda year, month=month, day=day: forecast_cutoff_for_plan_year(
                int(year),
                month=month,
                day=day,
            )
        )
        eligible = work["information_date"].notna() & work["information_date"].le(cutoffs)

        audit = work[["sponsor_id", "plan_year"]].copy()
        audit["eligible"] = eligible.astype(int)
        audit["linked"] = 1

        grouped = audit.groupby(["sponsor_id", "plan_year"], as_index=False).agg(
            linked_plan_count=("linked", "sum"),
            eligible_plan_count=("eligible", "sum"),
        )

        rows.append(
            {
                "cutoff_policy_id": policy_id,
                "month": month,
                "day": day,
                "linked_plan_rows": total_plan_rows,
                "eligible_plan_rows": int(eligible.sum()),
                "eligible_plan_rate": float(eligible.mean()),
                "sponsor_year_rows": total_sponsor_years,
                "sponsor_years_with_any_available_plan": int(
                    grouped["eligible_plan_count"].gt(0).sum()
                ),
                "sponsor_years_with_all_linked_plans_available": int(
                    grouped["eligible_plan_count"].eq(grouped["linked_plan_count"]).sum()
                ),
                "selected_policy": policy_id == SELECTED_CUTOFF_ID,
            }
        )

    return pd.DataFrame(rows)


def build_identity_audit(linked: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    keys = ["sponsor_id", "plan_year"]
    rows: list[dict[str, object]] = []

    for field in PENSION_VALUE_FIELDS:
        expected = direct_expected_aggregation(linked, field=field)
        comparison = base[keys + [field]].merge(expected, on=keys, how="left")
        expected_column = f"expected_{field}"
        comparison[expected_column] = comparison[expected_column].astype(float)
        equal = numeric_equal(comparison[field], comparison[expected_column])

        present = comparison[field].notna() & comparison[expected_column].notna()
        if present.any():
            max_abs_diff = float(
                np.max(
                    np.abs(
                        pd.to_numeric(comparison.loc[present, field], errors="raise").astype(float)
                        - pd.to_numeric(
                            comparison.loc[present, expected_column], errors="raise"
                        ).astype(float)
                    )
                )
            )
        else:
            max_abs_diff = 0.0

        rows.append(
            {
                "identity": f"{field}_complete_sum",
                "compared_sponsor_years": int(len(comparison)),
                "mismatch_rows": int((~equal).sum()),
                "max_abs_difference": max_abs_diff,
                "status": "PASS" if bool(equal.all()) else "FAIL",
            }
        )

    ratio_expected = base["assets"] / base["liabilities"]
    ratio_expected = ratio_expected.where(base["liabilities"].gt(0))
    ratio_equal = numeric_equal(base["funded_ratio"], ratio_expected)

    present_ratio = base["funded_ratio"].notna() & ratio_expected.notna()
    if present_ratio.any():
        max_ratio_diff = float(
            np.max(
                np.abs(
                    base.loc[present_ratio, "funded_ratio"].astype(float)
                    - ratio_expected.loc[present_ratio].astype(float)
                )
            )
        )
    else:
        max_ratio_diff = 0.0

    rows.append(
        {
            "identity": "funded_ratio_equals_assets_divided_by_liabilities",
            "compared_sponsor_years": int(len(base)),
            "mismatch_rows": int((~ratio_equal).sum()),
            "max_abs_difference": max_ratio_diff,
            "status": "PASS" if bool(ratio_equal.all()) else "FAIL",
        }
    )

    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    repo = Path(args.repo).resolve()

    universe_path = repo / "data" / "processed" / "sponsor_plan_universe.parquet"
    crosswalk_path = repo / "data" / "processed" / "sponsor_sec_crosswalk.parquet"
    step40_audit_path = repo / "reports" / "validation" / "milestone4_step_4_0_input_audit.json"

    output_path = (
        repo
        / "data"
        / "interim"
        / "structured_x"
        / "step_4_1"
        / "pension_sponsor_year_base.parquet"
    )
    cutoff_path = repo / "reports" / "validation" / "milestone4_step_4_1_cutoff_diagnostics.csv"
    detail_path = repo / "reports" / "validation" / "milestone4_step_4_1_temporal_detail.csv"
    missingness_path = repo / "reports" / "validation" / "milestone4_step_4_1_missingness.csv"
    identity_path = (
        repo / "reports" / "validation" / "milestone4_step_4_1_aggregation_identity_audit.csv"
    )
    audit_path = repo / "reports" / "validation" / "milestone4_step_4_1_pension_base_audit.json"
    coverage_path = repo / "reports" / "tables" / "milestone4_step_4_1_pension_coverage_by_year.csv"

    for path in [
        output_path.parent,
        cutoff_path.parent,
        coverage_path.parent,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    for path in [universe_path, crosswalk_path, step40_audit_path]:
        if not path.exists():
            raise RuntimeError(f"Required Step-4.1 input is missing: {path}")

    step40 = json.loads(step40_audit_path.read_text(encoding="utf-8"))
    if step40.get("step_4_0_status") != "PASS":
        raise RuntimeError("Step-4.0 audit does not report PASS.")
    if int(step40.get("linked_unique_sponsor_years", -1)) != EXPECTED_SPONSOR_YEARS:
        raise RuntimeError("Step-4.0 sponsor-year contract drift detected.")

    universe_hash = sha256_file(universe_path)
    crosswalk_hash = sha256_file(crosswalk_path)

    if universe_hash != EXPECTED_UNIVERSE_SHA256:
        raise RuntimeError(f"Sponsor-universe SHA-256 drift: {universe_hash}")
    if crosswalk_hash != EXPECTED_CROSSWALK_SHA256:
        raise RuntimeError(f"Crosswalk SHA-256 drift: {crosswalk_hash}")

    universe = pd.read_parquet(universe_path)
    crosswalk = pd.read_parquet(crosswalk_path)

    required_universe = {
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
    missing = sorted(required_universe - set(universe.columns))
    if missing:
        raise RuntimeError(f"Sponsor universe missing Step-4.1 fields: {missing}")

    if "sponsor_id" not in crosswalk.columns:
        raise RuntimeError("Crosswalk missing sponsor_id.")

    cik_column = str(step40.get("crosswalk_cik_column", "sec_cik"))
    if cik_column not in crosswalk.columns:
        raise RuntimeError(f"Frozen crosswalk CIK column is absent: {cik_column}")

    universe["sponsor_id"] = clean_identifier(universe["sponsor_id"])
    universe["plan_id"] = clean_identifier(universe["plan_id"])
    crosswalk["sponsor_id"] = clean_identifier(crosswalk["sponsor_id"])

    if universe["sponsor_id"].isna().any() or universe["plan_id"].isna().any():
        raise RuntimeError("Blank sponsor_id or plan_id in sponsor universe.")
    if crosswalk["sponsor_id"].isna().any():
        raise RuntimeError("Blank sponsor_id in crosswalk.")

    universe["plan_year"] = pd.to_numeric(universe["plan_year"], errors="raise").astype(int)
    universe["information_date"] = pd.to_datetime(universe["information_date"], errors="coerce")

    linked_ids = set(crosswalk["sponsor_id"].tolist())
    linked = universe.loc[universe["sponsor_id"].isin(linked_ids)].copy()

    linked_rows = int(len(linked))
    linked_plans = int(linked["plan_id"].nunique())
    linked_sponsors = int(linked["sponsor_id"].nunique())
    sponsor_years = int(linked[["sponsor_id", "plan_year"]].drop_duplicates().shape[0])
    year_start = int(linked["plan_year"].min())
    year_end = int(linked["plan_year"].max())
    duplicate_plan_year_rows = int(linked.duplicated(["plan_id", "plan_year"], keep=False).sum())

    frozen_checks = {
        "linked_plan_rows": (linked_rows, EXPECTED_LINKED_PLAN_ROWS),
        "linked_unique_plans": (linked_plans, EXPECTED_LINKED_PLANS),
        "linked_unique_sponsors": (linked_sponsors, EXPECTED_LINKED_SPONSORS),
        "linked_unique_sponsor_years": (sponsor_years, EXPECTED_SPONSOR_YEARS),
        "plan_year_start": (year_start, EXPECTED_YEAR_START),
        "plan_year_end": (year_end, EXPECTED_YEAR_END),
        "duplicate_plan_year_rows": (duplicate_plan_year_rows, 0),
    }
    for name, (actual, expected) in frozen_checks.items():
        if actual != expected:
            raise RuntimeError(f"Frozen Step-4.1 input drift: {name}={actual}; expected={expected}")

    diagnostics = cutoff_diagnostics(linked)
    diagnostics.to_csv(cutoff_path, index=False)

    selected = diagnostics.loc[diagnostics["selected_policy"]]
    if len(selected) != 1:
        raise RuntimeError("Exactly one forecast-cutoff policy must be selected.")

    base, temporal_detail = build_pension_sponsor_year_base(
        linked,
        crosswalk,
        cik_column=cik_column,
    )

    if len(base) != EXPECTED_SPONSOR_YEARS:
        raise RuntimeError(f"Sponsor-year base row drift: {len(base)}")
    if base["sponsor_id"].nunique() != EXPECTED_LINKED_SPONSORS:
        raise RuntimeError("Sponsor count drift in Step-4.1 base.")
    if base.duplicated(["sponsor_id", "plan_year"], keep=False).any():
        raise RuntimeError("Duplicate sponsor-year rows in Step-4.1 base.")

    temporal_violations = int(
        (
            base["information_date"].notna()
            & base["information_date"].gt(base["forecast_cutoff"])
        ).sum()
    )
    if temporal_violations != 0:
        raise RuntimeError("information_date <= forecast_cutoff gate failed.")

    if base["sec_cik"].isna().any():
        raise RuntimeError("SEC CIK missing in sponsor-year base.")

    base.to_parquet(output_path, index=False)
    temporal_detail.to_csv(detail_path, index=False)

    missing_rows: list[dict[str, object]] = []
    audit_fields = [
        "information_date",
        "assets",
        "liabilities",
        "contributions",
        "benefit_payments",
        "participants",
        "funded_ratio",
    ]
    for field in audit_fields:
        missing_count = int(base[field].isna().sum())
        missing_rows.append(
            {
                "field": field,
                "sponsor_year_rows": int(len(base)),
                "missing_count": missing_count,
                "nonmissing_count": int(len(base) - missing_count),
                "missing_rate": float(missing_count / len(base)),
            }
        )
    pd.DataFrame(missing_rows).to_csv(missingness_path, index=False)

    identity = build_identity_audit(linked, base)
    identity.to_csv(identity_path, index=False)
    if not identity["status"].eq("PASS").all():
        raise RuntimeError("Aggregation identity audit failed.")

    coverage_rows: list[dict[str, object]] = []
    for plan_year, base_year in base.groupby("plan_year", sort=True):
        linked_year = linked.loc[linked["plan_year"].eq(int(plan_year))]
        detail_year = temporal_detail.loc[temporal_detail["plan_year"].eq(int(plan_year))]
        coverage_rows.append(
            {
                "plan_year": int(plan_year),
                "sponsor_year_rows": int(len(base_year)),
                "linked_plan_rows": int(len(linked_year)),
                "available_plan_rows_by_cutoff": int(base_year["available_plan_count"].sum()),
                "sponsor_years_with_any_available_plan": int(
                    base_year["available_plan_count"].gt(0).sum()
                ),
                "sponsor_years_with_no_available_plan": int(
                    base_year["available_plan_count"].eq(0).sum()
                ),
                "sponsor_years_with_all_linked_plans_available": int(
                    detail_year["all_linked_plans_available_by_cutoff"].sum()
                ),
                "assets_nonmissing": int(base_year["assets"].notna().sum()),
                "liabilities_nonmissing": int(base_year["liabilities"].notna().sum()),
                "contributions_nonmissing": int(base_year["contributions"].notna().sum()),
                "benefit_payments_nonmissing": int(base_year["benefit_payments"].notna().sum()),
                "participants_nonmissing": int(base_year["participants"].notna().sum()),
                "funded_ratio_nonmissing": int(base_year["funded_ratio"].notna().sum()),
                "multi_plan_available_sponsor_years": int(base_year["multi_plan_available"].sum()),
                "participants_overlap_risk_sponsor_years": int(
                    base_year["participants_overlap_risk"].sum()
                ),
            }
        )
    coverage = pd.DataFrame(coverage_rows)
    coverage.to_csv(coverage_path, index=False)

    output_hash = sha256_file(output_path)
    selected_row = selected.iloc[0]

    audit = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "milestone": 4,
        "step": "4.1",
        "status": "PASS",
        "transformation_version": TRANSFORMATION_VERSION,
        "forecast_cutoff_policy_id": SELECTED_CUTOFF_ID,
        "forecast_cutoff_rule": "October 15 of calendar year t+1",
        "forecast_cutoff_policy_frozen": True,
        "governing_temporal_rule": "information_date <= forecast_cutoff",
        "universe_path": str(universe_path.relative_to(repo)),
        "universe_sha256": universe_hash,
        "crosswalk_path": str(crosswalk_path.relative_to(repo)),
        "crosswalk_sha256": crosswalk_hash,
        "crosswalk_cik_column": cik_column,
        "linked_plan_rows": linked_rows,
        "linked_unique_plans": linked_plans,
        "linked_unique_sponsors": linked_sponsors,
        "linked_unique_sponsor_years": sponsor_years,
        "output_path": str(output_path.relative_to(repo)),
        "output_git_tracked": False,
        "output_sha256": output_hash,
        "output_rows": int(len(base)),
        "output_unique_sponsors": int(base["sponsor_id"].nunique()),
        "output_duplicate_sponsor_year_rows": int(
            base.duplicated(["sponsor_id", "plan_year"], keep=False).sum()
        ),
        "temporal_violation_rows": temporal_violations,
        "selected_cutoff_eligible_plan_rows": int(selected_row["eligible_plan_rows"]),
        "selected_cutoff_eligible_plan_rate": float(selected_row["eligible_plan_rate"]),
        "selected_cutoff_sponsor_years_with_any_available_plan": int(
            selected_row["sponsor_years_with_any_available_plan"]
        ),
        "selected_cutoff_sponsor_years_with_all_linked_plans_available": int(
            selected_row["sponsor_years_with_all_linked_plans_available"]
        ),
        "aggregation_identity_failures": int(identity["status"].ne("PASS").sum()),
        "participant_overlap_policy": (
            "sum available-plan participant counts; flag sponsor-years with "
            "more than one available plan"
        ),
        "pension_size_status": "PENDING_SPONSOR_FINANCIAL_DENOMINATOR_REVIEW",
        "step_4_1_status": "PASS",
        "next_step": "4.2",
        "next_step_name": "INGEST_AND_ALIGN_POINT_IN_TIME_SEC_XBRL_SPONSOR_FINANCIALS",
    }
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"UNIVERSE_SHA256={universe_hash}")
    print(f"CROSSWALK_SHA256={crosswalk_hash}")
    print(f"LINKED_PLAN_ROWS={linked_rows}")
    print(f"LINKED_UNIQUE_PLANS={linked_plans}")
    print(f"LINKED_UNIQUE_SPONSORS={linked_sponsors}")
    print(f"LINKED_UNIQUE_SPONSOR_YEARS={sponsor_years}")
    print(f"FORECAST_CUTOFF_POLICY={SELECTED_CUTOFF_ID}")
    print("FORECAST_CUTOFF_RULE=OCTOBER_15_OF_T_PLUS_1")
    print(f"OUTPUT_ROWS={len(base)}")
    print(f"OUTPUT_UNIQUE_SPONSORS={base['sponsor_id'].nunique()}")
    print(f"DUPLICATE_SPONSOR_YEAR_ROWS={base.duplicated(['sponsor_id', 'plan_year']).sum()}")
    print(f"TEMPORAL_VIOLATION_ROWS={temporal_violations}")
    print(f"OUTPUT_SHA256={output_hash}")
    print("AGGREGATION_IDENTITY_AUDIT=PASS")
    print("MISSINGNESS_AUDIT=PASS")
    print("MILESTONE4_STEP_4_1=PASS")
    print("NEXT_STEP=4.2")
    print("NEXT_STEP_NAME=INGEST_AND_ALIGN_POINT_IN_TIME_SEC_XBRL_SPONSOR_FINANCIALS")


if __name__ == "__main__":
    main()