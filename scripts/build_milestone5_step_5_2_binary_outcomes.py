"""Build Milestone 5 Step 5.2 binary pension-deterioration outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from risk_intelligence.features.binary_outcome import (
    TRANSFORMATION_VERSION,
    apply_material_deterioration_threshold,
)

EXPECTED_ROWS = 5464
EXPECTED_CONTINUOUS_AVAILABLE_ROWS = 3392
EXPECTED_THRESHOLD = 0.05


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--continuous-panel", required=True)
    parser.add_argument("--threshold-record", required=True)
    parser.add_argument("--binary-output", required=True)
    parser.add_argument("--audit-json", required=True)
    parser.add_argument("--expected-continuous-sha256", required=True)
    parser.add_argument("--expected-threshold-record-sha256", required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest().upper()


def write_json(
    path: Path,
    payload: dict[str, object],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    args = parse_args()

    continuous_path = Path(args.continuous_panel)
    threshold_path = Path(args.threshold_record)
    output_path = Path(args.binary_output)
    audit_path = Path(args.audit_json)

    continuous_sha256 = sha256_file(continuous_path)
    threshold_record_sha256 = sha256_file(threshold_path)

    if continuous_sha256 != args.expected_continuous_sha256.upper():
        raise ValueError("Frozen continuous-outcome artifact SHA-256 mismatch.")

    if threshold_record_sha256 != args.expected_threshold_record_sha256.upper():
        raise ValueError("Threshold prespecification record changed after freeze.")

    threshold_record = json.loads(threshold_path.read_text(encoding="utf-8"))

    if threshold_record["status"] != "FROZEN_BEFORE_BINARY_CONSTRUCTION":
        raise ValueError("Threshold record is not in the frozen state.")

    threshold = float(threshold_record["primary_threshold_c"])

    if threshold != EXPECTED_THRESHOLD:
        raise ValueError("Primary threshold differs from the prespecified c=0.05.")

    if threshold_record["selected_from_observed_outcome_distribution"]:
        raise ValueError("Threshold was selected from observed outcome distribution.")

    if threshold_record["selected_from_final_holdout"]:
        raise ValueError("Threshold was selected from final-holdout information.")

    if threshold_record["final_holdout_inspected_before_threshold_freeze"]:
        raise ValueError("Final holdout was inspected before threshold freeze.")

    if threshold_record["retuning_after_binary_construction_authorized"]:
        raise ValueError("Post-construction threshold retuning is authorized.")

    # ------------------------------------------------------------------
    # FIRST EXPLICIT STEP-5.2 LOAD OF CONTINUOUS OUTCOME VALUES.
    #
    # The threshold record has already been written and hash-frozen above.
    # ------------------------------------------------------------------

    continuous = pd.read_parquet(continuous_path)

    if len(continuous) != EXPECTED_ROWS:
        raise ValueError(f"Expected {EXPECTED_ROWS} continuous rows; observed {len(continuous)}.")

    continuous_available = (
        continuous["continuous_outcome_available"].astype("boolean").fillna(False).astype(bool)
    )

    if int(continuous_available.sum()) != EXPECTED_CONTINUOUS_AVAILABLE_ROWS:
        raise ValueError("Unexpected Step-5.1 continuous-outcome availability count.")

    binary = apply_material_deterioration_threshold(
        continuous,
        threshold=threshold,
    )

    # Every upstream column must remain exactly unchanged.
    assert_frame_equal(
        binary[continuous.columns].reset_index(drop=True),
        continuous.reset_index(drop=True),
        check_dtype=True,
        check_exact=True,
    )

    binary_available = binary["binary_outcome_available"].astype(bool)

    if int(binary_available.sum()) != EXPECTED_CONTINUOUS_AVAILABLE_ROWS:
        raise ValueError(
            "Binary-outcome availability differs from continuous-outcome availability."
        )

    missing_binary = int(binary["material_deterioration"].isna().sum())

    expected_missing_binary = EXPECTED_ROWS - EXPECTED_CONTINUOUS_AVAILABLE_ROWS

    if missing_binary != expected_missing_binary:
        raise ValueError("Binary missingness was not preserved.")

    if binary["primary_threshold_c"].nunique() != 1:
        raise ValueError("Multiple primary threshold values detected.")

    if float(binary["primary_threshold_c"].iloc[0]) != threshold:
        raise ValueError("Binary panel threshold column differs from frozen c.")

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.unlink(
        missing_ok=True,
    )

    binary.to_parquet(
        output_path,
        index=False,
    )

    output_sha256 = sha256_file(output_path)

    audit = {
        "step_5_2_status": "PASS",
        "transformation_version": TRANSFORMATION_VERSION,
        "input_continuous_artifact_sha256": continuous_sha256,
        "threshold_prespecification_sha256": (threshold_record_sha256),
        "primary_threshold_c": threshold,
        "primary_threshold_percentage_points": 5.0,
        "robustness_thresholds": (threshold_record["robustness_thresholds"]),
        "threshold_frozen_before_binary_construction": True,
        "threshold_selected_from_outcome_distribution": False,
        "threshold_selected_from_event_prevalence": False,
        "threshold_selected_from_quantiles": False,
        "threshold_selected_from_model_performance": False,
        "threshold_selected_from_final_holdout": False,
        "threshold_retuning_authorized": False,
        "continuous_panel_rows": int(len(continuous)),
        "continuous_outcome_available_rows": int(continuous_available.sum()),
        "binary_panel_rows": int(len(binary)),
        "binary_outcome_available_rows": int(binary_available.sum()),
        "binary_outcome_missing_rows": missing_binary,
        "binary_support_valid": True,
        "positive_class_count_recorded_for_threshold_selection": False,
        "class_prevalence_used_for_threshold_selection": False,
        "upstream_columns_preserved_exactly": True,
        "year_alignment_violation_count": int(
            binary["year_alignment_violation"].astype(bool).sum()
        ),
        "same_year_target_violation_count": int(
            binary["same_year_target_violation"].astype(bool).sum()
        ),
        "duplicate_predictor_sponsor_year_rows": int(
            binary.duplicated(
                ["sponsor_id", "predictor_plan_year"],
                keep=False,
            ).sum()
        ),
        "target_imputation_applied": False,
        "forward_fill_applied": False,
        "backfill_applied": False,
        "final_holdout_defined_or_inspected": False,
        "model_fitting_started": False,
        "binary_output_artifact_path": output_path.as_posix(),
        "binary_output_artifact_sha256": output_sha256,
        "binary_output_artifact_git_tracked": False,
        "final_processed_outcomes_artifact_constructed": False,
    }

    if audit["year_alignment_violation_count"] != 0:
        raise ValueError("Year-alignment violations detected in binary panel.")

    if audit["same_year_target_violation_count"] != 0:
        raise ValueError("Same-year target violations detected in binary panel.")

    if audit["duplicate_predictor_sponsor_year_rows"] != 0:
        raise ValueError("Duplicate predictor sponsor-year rows detected.")

    write_json(
        audit_path,
        audit,
    )

    print("MILESTONE5_STEP_5_2_BUILD=PASS")
    print("PRIMARY_THRESHOLD_C=0.05")
    print("PRIMARY_THRESHOLD_PERCENTAGE_POINTS=5")
    print("THRESHOLD_FROZEN_BEFORE_BINARY_CONSTRUCTION=YES")
    print("THRESHOLD_SELECTED_FROM_OUTCOME_DISTRIBUTION=NO")
    print("THRESHOLD_SELECTED_FROM_FINAL_HOLDOUT=NO")
    print(f"BINARY_PANEL_ROWS={audit['binary_panel_rows']}")
    print(f"BINARY_OUTCOME_AVAILABLE_ROWS={audit['binary_outcome_available_rows']}")
    print(f"BINARY_OUTCOME_MISSING_ROWS={audit['binary_outcome_missing_rows']}")
    print("YEAR_ALIGNMENT_VIOLATIONS=0")
    print("SAME_YEAR_TARGET_VIOLATIONS=0")
    print("DUPLICATE_PREDICTOR_ROWS=0")
    print("TARGET_IMPUTATION_APPLIED=NO")
    print("FINAL_HOLDOUT_INSPECTED=NO")
    print("MODEL_FITTING_STARTED=NO")
    print(f"BINARY_OUTCOME_SHA256={output_sha256}")


if __name__ == "__main__":
    main()
