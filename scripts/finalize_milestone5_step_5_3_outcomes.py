"""Finalize the canonical Milestone-5 outcome artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

EXPECTED_ROWS = 5464
EXPECTED_AVAILABLE_ROWS = 3392
EXPECTED_MISSING_ROWS = 2072
EXPECTED_THRESHOLD = 0.05


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest().upper()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument("--binary-input", required=True)
    parser.add_argument("--continuous-input", required=True)
    parser.add_argument("--threshold-record", required=True)
    parser.add_argument("--binary-audit", required=True)
    parser.add_argument("--final-output", required=True)
    parser.add_argument("--final-audit", required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--expected-continuous-sha256", required=True)
    parser.add_argument("--expected-threshold-sha256", required=True)

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    binary_path = Path(args.binary_input)
    continuous_path = Path(args.continuous_input)
    threshold_path = Path(args.threshold_record)
    binary_audit_path = Path(args.binary_audit)
    final_path = Path(args.final_output)
    final_audit_path = Path(args.final_audit)

    binary_sha = sha256_file(binary_path)
    continuous_sha = sha256_file(continuous_path)
    threshold_sha = sha256_file(threshold_path)

    if binary_sha != args.expected_binary_sha256.upper():
        raise ValueError("Frozen binary artifact SHA-256 mismatch.")

    if continuous_sha != args.expected_continuous_sha256.upper():
        raise ValueError("Frozen continuous artifact SHA-256 mismatch.")

    if threshold_sha != args.expected_threshold_sha256.upper():
        raise ValueError("Frozen threshold-record SHA-256 mismatch.")

    threshold_record = json.loads(threshold_path.read_text(encoding="utf-8"))

    binary_audit = json.loads(binary_audit_path.read_text(encoding="utf-8"))

    if threshold_record["primary_threshold_c"] != EXPECTED_THRESHOLD:
        raise ValueError("Frozen primary threshold is not c=0.05.")

    if threshold_record["status"] != "FROZEN_BEFORE_BINARY_CONSTRUCTION":
        raise ValueError("Threshold freeze state is invalid.")

    if threshold_record["selected_from_observed_outcome_distribution"]:
        raise ValueError("Threshold was selected from outcome distribution.")

    if threshold_record["selected_from_final_holdout"]:
        raise ValueError("Threshold was selected from final holdout.")

    if threshold_record["retuning_after_binary_construction_authorized"]:
        raise ValueError("Threshold retuning is unexpectedly authorized.")

    if binary_audit["step_5_2_status"] != "PASS":
        raise ValueError("Step-5.2 binary audit is not PASS.")

    if binary_audit["final_holdout_defined_or_inspected"]:
        raise ValueError("Final holdout was inspected before finalization.")

    if binary_audit["model_fitting_started"]:
        raise ValueError("Model fitting started before finalization.")

    binary = pd.read_parquet(binary_path)

    required = {
        "sponsor_id",
        "predictor_plan_year",
        "target_plan_year",
        "continuous_outcome_available",
        "delta_funded_ratio_t_plus_1",
        "binary_outcome_available",
        "material_deterioration",
        "primary_threshold_c",
        "threshold_frozen_before_binary_construction",
        "year_alignment_violation",
        "same_year_target_violation",
    }

    missing = sorted(required - set(binary.columns))

    if missing:
        raise ValueError(f"Missing binary-panel columns: {missing}")

    if len(binary) != EXPECTED_ROWS:
        raise ValueError("Unexpected binary-panel row count.")

    if binary.duplicated(
        ["sponsor_id", "predictor_plan_year"],
        keep=False,
    ).any():
        raise ValueError("Duplicate predictor sponsor-year rows detected.")

    predictor_year = pd.to_numeric(
        binary["predictor_plan_year"],
        errors="raise",
    ).astype(int)

    target_year = pd.to_numeric(
        binary["target_plan_year"],
        errors="raise",
    ).astype(int)

    if not target_year.eq(predictor_year + 1).all():
        raise ValueError("Target year is not predictor year + 1.")

    if binary["year_alignment_violation"].astype(bool).any():
        raise ValueError("Year-alignment violation detected.")

    if binary["same_year_target_violation"].astype(bool).any():
        raise ValueError("Same-year target violation detected.")

    threshold_values = pd.to_numeric(
        binary["primary_threshold_c"],
        errors="raise",
    )

    if not threshold_values.eq(EXPECTED_THRESHOLD).all():
        raise ValueError("Binary panel contains a non-frozen threshold.")

    frozen = (
        binary["threshold_frozen_before_binary_construction"]
        .astype("boolean")
        .fillna(False)
        .astype(bool)
    )

    if not frozen.all():
        raise ValueError("Threshold-freeze provenance is incomplete.")

    continuous_available = (
        binary["continuous_outcome_available"].astype("boolean").fillna(False).astype(bool)
    )

    binary_available = (
        binary["binary_outcome_available"].astype("boolean").fillna(False).astype(bool)
    )

    if not continuous_available.equals(binary_available):
        raise ValueError("Binary missingness does not preserve continuous availability.")

    if int(binary_available.sum()) != EXPECTED_AVAILABLE_ROWS:
        raise ValueError("Unexpected binary available-row count.")

    if int((~binary_available).sum()) != EXPECTED_MISSING_ROWS:
        raise ValueError("Unexpected binary missing-row count.")

    delta = pd.to_numeric(
        binary["delta_funded_ratio_t_plus_1"],
        errors="coerce",
    )

    outcome = binary["material_deterioration"]

    if (continuous_available & delta.isna()).any():
        raise ValueError("Available continuous target has missing DeltaFR.")

    if (~continuous_available & delta.notna()).any():
        raise ValueError("Unavailable continuous target contains DeltaFR.")

    if (binary_available & outcome.isna()).any():
        raise ValueError("Available binary target is missing.")

    if (~binary_available & outcome.notna()).any():
        raise ValueError("Unavailable binary target contains a value.")

    support = set(outcome.dropna().astype(int).unique().tolist())

    if not support.issubset({0, 1}):
        raise ValueError("Binary outcome support is outside {0,1}.")

    expected_binary = delta.loc[binary_available].le(-EXPECTED_THRESHOLD).astype("int8")

    actual_binary = outcome.loc[binary_available].astype("int8")

    if not expected_binary.equals(actual_binary):
        raise ValueError("Binary target violates frozen c=0.05 identity.")

    final_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copyfile(
        binary_path,
        final_path,
    )

    final_sha = sha256_file(final_path)

    if final_sha != binary_sha:
        raise ValueError("Canonical artifact is not byte-identical to Step-5.2 binary panel.")

    final = pd.read_parquet(final_path)

    assert_frame_equal(
        final,
        binary,
        check_dtype=True,
        check_exact=True,
    )

    audit = {
        "step_5_3_status": "PASS",
        "final_artifact_status": "CONSTRUCTED_AND_FROZEN",
        "source_binary_artifact_sha256": binary_sha,
        "source_continuous_artifact_sha256": continuous_sha,
        "threshold_prespecification_sha256": threshold_sha,
        "final_outcome_artifact_sha256": final_sha,
        "byte_identical_to_step_5_2_binary_panel": True,
        "semantic_identity_to_step_5_2_binary_panel": True,
        "final_artifact_rows": int(len(final)),
        "final_unique_sponsors": int(final["sponsor_id"].nunique(dropna=True)),
        "continuous_outcome_available_rows": int(continuous_available.sum()),
        "binary_outcome_available_rows": int(binary_available.sum()),
        "binary_outcome_missing_rows": int((~binary_available).sum()),
        "primary_threshold_c": EXPECTED_THRESHOLD,
        "primary_threshold_percentage_points": 5.0,
        "threshold_status": "FROZEN_STEP_5_2",
        "threshold_identity_pass": True,
        "threshold_retuning_applied": False,
        "threshold_selected_from_outcome_distribution": False,
        "threshold_selected_from_final_holdout": False,
        "year_alignment_violation_count": 0,
        "same_year_target_violation_count": 0,
        "duplicate_predictor_sponsor_year_rows": 0,
        "target_imputation_applied": False,
        "forward_fill_applied": False,
        "backfill_applied": False,
        "missingness_preserved": True,
        "class_prevalence_computed_for_threshold_selection": False,
        "final_holdout_defined_or_inspected": False,
        "model_fitting_started": False,
        "final_artifact_git_tracked": False,
        "release_tag_created": False,
        "release_ready_for_step_5_4": True,
        "final_artifact_path": "data/processed/outcomes.parquet",
    }

    final_audit_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    final_audit_path.write_text(
        json.dumps(
            audit,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print("MILESTONE5_STEP_5_3_FINALIZATION=PASS")
    print(f"FINAL_OUTCOME_ROWS={audit['final_artifact_rows']}")
    print(f"FINAL_BINARY_OUTCOME_AVAILABLE_ROWS={audit['binary_outcome_available_rows']}")
    print(f"FINAL_BINARY_OUTCOME_MISSING_ROWS={audit['binary_outcome_missing_rows']}")
    print(f"FINAL_OUTCOME_SHA256={final_sha}")
    print("BYTE_IDENTICAL_TO_STEP_5_2_BINARY_PANEL=YES")
    print("SEMANTIC_IDENTITY_TO_STEP_5_2_BINARY_PANEL=YES")
    print("PRIMARY_THRESHOLD_C=0.05")
    print("THRESHOLD_RETUNING_APPLIED=NO")
    print("TARGET_IMPUTATION_APPLIED=NO")
    print("FINAL_HOLDOUT_INSPECTED=NO")
    print("MODEL_FITTING_STARTED=NO")
    print("RELEASE_READY_FOR_STEP_5_4=YES")


if __name__ == "__main__":
    main()
