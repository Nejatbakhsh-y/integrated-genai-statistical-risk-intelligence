"""Build and audit Milestone 5 Step 5.1 continuous outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from risk_intelligence.features.outcome_panel import (
    TRANSFORMATION_VERSION,
    build_continuous_outcome_panel,
)

EXPECTED_INPUT_ROWS = 5934
EXPECTED_INPUT_SPONSORS = 729
MAX_TARGET_PLAN_YEAR = 2024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pension-base", required=True)
    parser.add_argument("--structured-x", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-json", required=True)
    parser.add_argument("--missingness-csv", required=True)
    parser.add_argument("--pairing-audit-csv", required=True)
    parser.add_argument("--coverage-csv", required=True)
    parser.add_argument("--expected-pension-sha256", required=True)
    parser.add_argument("--expected-structured-x-sha256", required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest().upper()


def clean_keys(frame: pd.DataFrame) -> pd.DataFrame:
    keys = frame[["sponsor_id", "plan_year"]].copy()
    keys["sponsor_id"] = keys["sponsor_id"].astype("string").str.strip()
    keys["plan_year"] = pd.to_numeric(
        keys["plan_year"],
        errors="raise",
    ).astype(int)

    if keys.duplicated(["sponsor_id", "plan_year"]).any():
        raise ValueError("Duplicate sponsor-year key detected.")

    return keys.sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    args = parse_args()

    pension_path = Path(args.pension_base)
    structured_x_path = Path(args.structured_x)
    output_path = Path(args.output)
    audit_path = Path(args.audit_json)
    missingness_path = Path(args.missingness_csv)
    pairing_path = Path(args.pairing_audit_csv)
    coverage_path = Path(args.coverage_csv)

    pension_sha256 = sha256_file(pension_path)
    structured_x_sha256 = sha256_file(structured_x_path)

    if pension_sha256 != args.expected_pension_sha256.upper():
        raise ValueError("Pension-base SHA-256 mismatch.")

    if structured_x_sha256 != args.expected_structured_x_sha256.upper():
        raise ValueError("Structured-X SHA-256 mismatch.")

    pension = pd.read_parquet(pension_path)
    structured_x = pd.read_parquet(structured_x_path)

    if len(pension) != EXPECTED_INPUT_ROWS:
        raise ValueError(f"Expected {EXPECTED_INPUT_ROWS} pension rows; observed {len(pension)}.")

    unique_sponsors = int(pension["sponsor_id"].nunique(dropna=True))

    if unique_sponsors != EXPECTED_INPUT_SPONSORS:
        raise ValueError(f"Unexpected unique sponsor count in pension base: {unique_sponsors}.")

    pension_keys = clean_keys(pension)
    structured_x_keys = clean_keys(structured_x)

    key_compare = pension_keys.merge(
        structured_x_keys,
        on=["sponsor_id", "plan_year"],
        how="outer",
        indicator=True,
    )

    pension_only_keys = int(key_compare["_merge"].eq("left_only").sum())
    structured_x_only_keys = int(key_compare["_merge"].eq("right_only").sum())

    if pension_only_keys or structured_x_only_keys:
        raise ValueError("Pension-base and structured-X sponsor-year keys differ.")

    panel = build_continuous_outcome_panel(
        pension,
        max_target_plan_year=MAX_TARGET_PLAN_YEAR,
    )

    year_alignment_violations = int(panel["year_alignment_violation"].sum())

    same_year_violations = int(panel["same_year_target_violation"].sum())

    duplicate_rows = int(
        panel.duplicated(
            ["sponsor_id", "predictor_plan_year"],
            keep=False,
        ).sum()
    )

    if year_alignment_violations:
        raise ValueError("Year-alignment violations remain in final panel.")

    if same_year_violations:
        raise ValueError("Same-year target violations remain in final panel.")

    if duplicate_rows:
        raise ValueError("Duplicate predictor sponsor-year rows remain.")

    terminal_input_rows = int(
        pd.to_numeric(
            pension["plan_year"],
            errors="raise",
        )
        .eq(MAX_TARGET_PLAN_YEAR)
        .sum()
    )

    expected_output_rows = len(pension) - terminal_input_rows

    if len(panel) != expected_output_rows:
        raise ValueError("Unexpected predictor-row count after terminal-year exclusion.")

    available = panel["continuous_outcome_available"]

    recomputed = panel.loc[available, "target_funded_ratio"].astype(float) - panel.loc[
        available, "predictor_funded_ratio"
    ].astype(float)

    if not recomputed.equals(
        panel.loc[
            available,
            "delta_funded_ratio_t_plus_1",
        ].astype(float)
    ):
        difference = (
            recomputed
            - panel.loc[
                available,
                "delta_funded_ratio_t_plus_1",
            ].astype(float)
        ).abs()

        if bool(difference.gt(1e-12).any()):
            raise ValueError("Independent continuous-outcome audit failed.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)

    panel.to_parquet(
        output_path,
        index=False,
    )

    output_sha256 = sha256_file(output_path)

    pairing_columns = [
        "sponsor_id",
        "sec_cik",
        "predictor_plan_year",
        "target_plan_year",
        "has_consecutive_target_row",
        "predictor_funded_ratio_available",
        "target_funded_ratio_available",
        "predictor_liabilities_positive",
        "target_liabilities_positive",
        "continuous_outcome_available",
        "year_alignment_violation",
        "same_year_target_violation",
    ]

    pairing = panel[pairing_columns].copy()

    pairing_path.parent.mkdir(parents=True, exist_ok=True)
    pairing.to_csv(
        pairing_path,
        index=False,
        lineterminator="\n",
    )

    missingness_fields = [
        "predictor_funded_ratio",
        "target_funded_ratio",
        "delta_funded_ratio_t_plus_1",
        "predictor_assets",
        "predictor_liabilities",
        "target_assets",
        "target_liabilities",
        "predictor_information_date",
        "target_information_date",
    ]

    missingness_rows: list[dict[str, object]] = []

    for field in missingness_fields:
        missing_count = int(panel[field].isna().sum())
        nonmissing_count = int(panel[field].notna().sum())

        missingness_rows.append(
            {
                "field": field,
                "rows": int(len(panel)),
                "missing_count": missing_count,
                "nonmissing_count": nonmissing_count,
                "missing_rate": (float(missing_count / len(panel)) if len(panel) else 0.0),
            }
        )

    missingness = pd.DataFrame(missingness_rows)

    missingness_path.parent.mkdir(parents=True, exist_ok=True)
    missingness.to_csv(
        missingness_path,
        index=False,
        lineterminator="\n",
    )

    coverage = (
        panel.groupby(
            "predictor_plan_year",
            sort=True,
            dropna=False,
        )
        .agg(
            predictor_rows=("sponsor_id", "size"),
            consecutive_target_rows=(
                "has_consecutive_target_row",
                "sum",
            ),
            predictor_funded_ratio_available=(
                "predictor_funded_ratio_available",
                "sum",
            ),
            target_funded_ratio_available=(
                "target_funded_ratio_available",
                "sum",
            ),
            continuous_outcome_available=(
                "continuous_outcome_available",
                "sum",
            ),
        )
        .reset_index()
    )

    coverage["target_plan_year"] = coverage["predictor_plan_year"] + 1

    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(
        coverage_path,
        index=False,
        lineterminator="\n",
    )

    target_present = panel["has_consecutive_target_row"]

    audit = {
        "step_5_1_status": "PASS",
        "transformation_version": TRANSFORMATION_VERSION,
        "input_pension_base_sha256": pension_sha256,
        "input_structured_x_sha256": structured_x_sha256,
        "input_pension_rows": int(len(pension)),
        "input_unique_sponsors": unique_sponsors,
        "input_plan_year_min": int(pension["plan_year"].min()),
        "input_plan_year_max": int(pension["plan_year"].max()),
        "pension_only_key_count": pension_only_keys,
        "structured_x_only_key_count": structured_x_only_keys,
        "terminal_input_rows_excluded": terminal_input_rows,
        "continuous_panel_rows": int(len(panel)),
        "continuous_panel_unique_sponsors": int(panel["sponsor_id"].nunique(dropna=True)),
        "predictor_plan_year_min": int(panel["predictor_plan_year"].min()),
        "predictor_plan_year_max": int(panel["predictor_plan_year"].max()),
        "target_plan_year_min": int(panel["target_plan_year"].min()),
        "target_plan_year_max": int(panel["target_plan_year"].max()),
        "consecutive_target_rows": int(panel["has_consecutive_target_row"].sum()),
        "missing_consecutive_target_rows": int((~panel["has_consecutive_target_row"]).sum()),
        "predictor_funded_ratio_available_rows": int(
            panel["predictor_funded_ratio_available"].sum()
        ),
        "target_funded_ratio_available_rows": int(panel["target_funded_ratio_available"].sum()),
        "continuous_outcome_available_rows": int(panel["continuous_outcome_available"].sum()),
        "missing_predictor_funded_ratio_rows": int(
            (~panel["predictor_funded_ratio_available"]).sum()
        ),
        "missing_target_funded_ratio_rows_among_present_targets": int(
            (target_present & ~panel["target_funded_ratio_available"]).sum()
        ),
        "predictor_missing_liabilities_rows": int(panel["predictor_liabilities"].isna().sum()),
        "predictor_nonpositive_liabilities_rows": int(
            (panel["predictor_liabilities"].notna() & panel["predictor_liabilities"].le(0.0)).sum()
        ),
        "target_missing_liabilities_rows_among_present_targets": int(
            (target_present & panel["target_liabilities"].isna()).sum()
        ),
        "target_nonpositive_liabilities_rows_among_present_targets": int(
            (
                target_present
                & panel["target_liabilities"].notna()
                & panel["target_liabilities"].le(0.0)
            ).sum()
        ),
        "duplicate_predictor_sponsor_year_rows": duplicate_rows,
        "year_alignment_violation_count": year_alignment_violations,
        "same_year_target_violation_count": same_year_violations,
        "target_imputation_applied": False,
        "forward_fill_applied": False,
        "backfill_applied": False,
        "nonconsecutive_pairing_allowed": False,
        "threshold_selected": False,
        "binary_outcome_constructed": False,
        "outcome_distribution_inspected_for_threshold": False,
        "final_holdout_defined_or_inspected": False,
        "model_fitting_started": False,
        "output_artifact_path": output_path.as_posix(),
        "output_artifact_sha256": output_sha256,
        "output_artifact_git_tracked": False,
    }

    write_json(audit_path, audit)

    print("MILESTONE5_STEP_5_1_BUILD=PASS")
    print(f"INPUT_PENSION_ROWS={audit['input_pension_rows']}")
    print(f"PREDICTOR_ROWS={audit['continuous_panel_rows']}")
    print(f"CONSECUTIVE_TARGET_ROWS={audit['consecutive_target_rows']}")
    print(f"CONTINUOUS_OUTCOME_AVAILABLE_ROWS={audit['continuous_outcome_available_rows']}")
    print(f"MISSING_CONSECUTIVE_TARGET_ROWS={audit['missing_consecutive_target_rows']}")
    print(f"YEAR_ALIGNMENT_VIOLATIONS={audit['year_alignment_violation_count']}")
    print(f"SAME_YEAR_TARGET_VIOLATIONS={audit['same_year_target_violation_count']}")
    print(f"DUPLICATE_PREDICTOR_ROWS={audit['duplicate_predictor_sponsor_year_rows']}")
    print(f"CONTINUOUS_OUTCOME_SHA256={output_sha256}")
    print("THRESHOLD_SELECTED=NO")
    print("BINARY_OUTCOME_CONSTRUCTED=NO")
    print("FINAL_HOLDOUT_INSPECTED=NO")
    print("MODEL_FITTING_STARTED=NO")


if __name__ == "__main__":
    main()
