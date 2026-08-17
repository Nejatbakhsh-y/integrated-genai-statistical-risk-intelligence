"""Finalize and freeze Milestone-4 Step-4.5 structured-X panel."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from risk_intelligence.features.structured_x_panel import (
    FEATURE_FAMILIES,
    MODEL_FEATURES,
    TRANSFORMATION_VERSION,
    build_family_coverage_by_year,
    build_feature_missingness,
    build_schema_audit,
    validate_final_panel,
)

EXPECTED_STEP_4_4_SHA256 = "6E7C3954CE1F23110B4A88E7A83E5CEC5C6B759825670DB9A90682CE5AA56ACF"
EXPECTED_ROWS = 5_934
EXPECTED_SPONSORS = 729
EXPECTED_CIKS = 729


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def assert_upstream_audits(repo: Path) -> dict[str, str]:
    specs = [
        (
            "step_4_1",
            repo / "reports" / "validation" / "milestone4_step_4_1_pension_base_audit.json",
            "step_4_1_status",
        ),
        (
            "step_4_2",
            repo / "reports" / "validation" / "milestone4_step_4_2_sec_ingestion_audit.json",
            "step_4_2_status",
        ),
        (
            "step_4_3",
            repo / "reports" / "validation" / "milestone4_step_4_3_market_ingestion_audit.json",
            "step_4_3_status",
        ),
        (
            "step_4_4",
            repo / "reports" / "validation" / "milestone4_step_4_4_macro_ingestion_audit.json",
            "step_4_4_status",
        ),
    ]
    result: dict[str, str] = {}
    for step, path, status_key in specs:
        if not path.exists():
            raise RuntimeError(f"Missing upstream audit: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        status = str(payload.get(status_key, ""))
        if status != "PASS":
            raise RuntimeError(f"Upstream audit does not report PASS: {step}={status}")
        result[step] = status
    return result


def append_once(path: Path, marker: str, text: str) -> None:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in current:
        return
    separator = "" if not current or current.endswith("\n") else "\n"
    path.write_text(current + separator + text.rstrip() + "\n", encoding="utf-8")


def upsert_status(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0]
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def update_config(
    path: Path,
    *,
    source_sha256: str,
    final_sha256: str,
    diagnostics: dict[str, Any],
) -> None:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if str(config.get("step")) != "4.4":
        raise RuntimeError(f"Step-4.5 requires config step 4.4; found {config.get('step')}")
    if config.get("status") != "step_4_4_macro_variables_frozen":
        raise RuntimeError("Step-4.4 config status is not frozen.")
    if config["step_4_4_acceptance"]["step_4_4_status"] != "PASS":
        raise RuntimeError("Step-4.4 acceptance gate is not PASS.")

    config["version"] = TRANSFORMATION_VERSION
    config["step"] = "4.5"
    config["status"] = "structured_x_panel_frozen"

    release = config.setdefault("release", {})
    release["target_tag_created"] = False
    release["release_ready"] = True
    release["release_authorized_by_step_4_5"] = True
    release["release_action_status"] = "pending_step_4_6"

    primary = config.setdefault("primary_artifact", {})
    primary.update(
        {
            "path": "data/processed/sponsor_year_X.parquet",
            "git_tracked": False,
            "status": "constructed_and_frozen",
            "expected_sha256": final_sha256,
            "expected_rows": EXPECTED_ROWS,
            "expected_unique_sponsors": EXPECTED_SPONSORS,
            "expected_unique_ciks": EXPECTED_CIKS,
            "grain": ["sponsor_id", "plan_year"],
        }
    )

    config["final_panel"] = {
        "transformation_version": TRANSFORMATION_VERSION,
        "construction_rule": (
            "byte-for-byte promotion of the frozen Step-4.4 joined pension/SEC/market/macro "
            "artifact; no Step-4.5 value transformation"
        ),
        "source_artifact": (
            "data/interim/structured_x/step_4_4/pension_sec_market_macro_sponsor_year_base.parquet"
        ),
        "source_artifact_sha256": source_sha256,
        "final_artifact_sha256": final_sha256,
        "byte_identical_to_step_4_4_joined": source_sha256 == final_sha256,
        "rows": diagnostics["rows"],
        "unique_sponsors": diagnostics["unique_sponsors"],
        "unique_ciks": diagnostics["unique_ciks"],
        "model_feature_count": diagnostics["model_feature_count"],
        "model_feature_families": FEATURE_FAMILIES,
        "missingness_preserved": True,
        "step_4_5_imputation_applied": False,
        "forecast_cutoff_policy": "OCTOBER_15_T_PLUS_1",
        "temporal_violation_count": diagnostics["temporal_violation_count"],
    }

    missingness = config.setdefault("missingness", {})
    missingness["final_imputation_policy_status"] = (
        "raw_missingness_preserved_in_frozen_panel_no_step_4_5_imputation"
    )

    config["step_4_5_artifacts"] = {
        "final_structured_x_panel": {
            "path": "data/processed/sponsor_year_X.parquet",
            "git_tracked": False,
            "expected_sha256": final_sha256,
            "expected_rows": EXPECTED_ROWS,
            "expected_unique_sponsors": EXPECTED_SPONSORS,
            "expected_unique_ciks": EXPECTED_CIKS,
            "grain": ["sponsor_id", "plan_year"],
        },
        "final_panel_audit": {
            "path": "reports/validation/milestone4_step_4_5_final_panel_audit.json",
            "git_tracked": True,
        },
    }

    config["step_4_5_acceptance"] = {
        "step_4_4_artifact_hash_verified": True,
        "all_four_data_families_complete": True,
        "final_artifact_materialized": True,
        "final_artifact_byte_identical_to_step_4_4_joined": source_sha256 == final_sha256,
        "expected_sponsor_year_rows_verified": diagnostics["rows"] == EXPECTED_ROWS,
        "expected_unique_sponsors_verified": diagnostics["unique_sponsors"] == EXPECTED_SPONSORS,
        "expected_unique_ciks_verified": diagnostics["unique_ciks"] == EXPECTED_CIKS,
        "duplicate_audit_verified": diagnostics["duplicate_sponsor_year_rows"] == 0,
        "temporal_integrity_verified": diagnostics["temporal_violation_count"] == 0,
        "missingness_preserved": True,
        "step_4_5_imputation_applied": False,
        "final_parquet_git_tracked": False,
        "release_ready": True,
        "release_executed": False,
        "step_4_5_status": "PASS",
    }

    config["next_step"] = {
        "id": "4.6",
        "name": "merge_develop_and_tag_v0_5_0_structured_panel",
    }

    path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    repo = Path(args.repo).resolve()

    source_path = (
        repo
        / "data"
        / "interim"
        / "structured_x"
        / "step_4_4"
        / "pension_sec_market_macro_sponsor_year_base.parquet"
    )
    final_path = repo / "data" / "processed" / "sponsor_year_X.parquet"
    config_path = repo / "configs" / "structured_x.yaml"
    status_path = repo / "STATUS.md"
    panel_doc = repo / "docs" / "structured_x_panel.md"
    dictionary_doc = repo / "docs" / "data_dictionary.md"
    validation_dir = repo / "reports" / "validation"
    tables_dir = repo / "reports" / "tables"
    audit_path = validation_dir / "milestone4_step_4_5_final_panel_audit.json"
    missingness_path = validation_dir / "milestone4_step_4_5_feature_missingness.csv"
    schema_path = validation_dir / "milestone4_step_4_5_schema_audit.csv"
    coverage_path = tables_dir / "milestone4_step_4_5_family_coverage_by_year.csv"

    if not source_path.exists():
        raise RuntimeError(f"Missing frozen Step-4.4 joined artifact: {source_path}")
    if not config_path.exists() or not status_path.exists():
        raise RuntimeError("Step-4.5 repository contract files are missing.")

    upstream_statuses = assert_upstream_audits(repo)
    source_sha256 = sha256_file(source_path)
    if source_sha256 != EXPECTED_STEP_4_4_SHA256:
        raise RuntimeError(
            "Step-4.4 joined-artifact hash drift: "
            f"actual={source_sha256}; expected={EXPECTED_STEP_4_4_SHA256}"
        )

    source_frame, diagnostics = validate_final_panel(pd.read_parquet(source_path))

    final_path.parent.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, final_path)
    final_sha256 = sha256_file(final_path)
    if final_sha256 != source_sha256:
        raise RuntimeError(
            "Final structured-X artifact is not byte-identical to Step-4.4 joined input."
        )

    final_frame, final_diagnostics = validate_final_panel(pd.read_parquet(final_path))
    if diagnostics != final_diagnostics:
        raise RuntimeError("Final artifact diagnostics differ from the frozen Step-4.4 source.")

    build_feature_missingness(final_frame).to_csv(
        missingness_path, index=False, lineterminator="\n"
    )
    build_schema_audit(final_frame).to_csv(schema_path, index=False, lineterminator="\n")
    build_family_coverage_by_year(final_frame).to_csv(
        coverage_path, index=False, lineterminator="\n"
    )

    audit = {
        "step_4_5_status": "PASS",
        "transformation_version": TRANSFORMATION_VERSION,
        "created_utc": datetime.now(UTC).isoformat(),
        "source_step": "4.4",
        "source_artifact": str(source_path.relative_to(repo)).replace("\\", "/"),
        "source_artifact_sha256": source_sha256,
        "expected_source_artifact_sha256": EXPECTED_STEP_4_4_SHA256,
        "final_artifact": str(final_path.relative_to(repo)).replace("\\", "/"),
        "final_artifact_sha256": final_sha256,
        "final_artifact_byte_identical_to_step_4_4_joined": final_sha256 == source_sha256,
        "final_artifact_git_tracked": False,
        "rows": final_diagnostics["rows"],
        "unique_sponsors": final_diagnostics["unique_sponsors"],
        "unique_ciks": final_diagnostics["unique_ciks"],
        "duplicate_sponsor_year_rows": final_diagnostics["duplicate_sponsor_year_rows"],
        "plan_year_start": final_diagnostics["plan_year_start"],
        "plan_year_end": final_diagnostics["plan_year_end"],
        "forecast_cutoff_policy": "OCTOBER_15_T_PLUS_1",
        "temporal_violation_count": final_diagnostics["temporal_violation_count"],
        "checked_temporal_columns": final_diagnostics["checked_temporal_columns"],
        "model_feature_count": final_diagnostics["model_feature_count"],
        "model_features": MODEL_FEATURES,
        "family_feature_counts": final_diagnostics["family_feature_counts"],
        "family_any_nonmissing": final_diagnostics["family_any_nonmissing"],
        "upstream_audit_statuses": upstream_statuses,
        "missingness_preserved": True,
        "step_4_5_imputation_applied": False,
        "release_ready": True,
        "release_executed": False,
        "release_target": "v0.5.0-structured-panel",
        "next_step": "4.6",
        "next_step_name": "MERGE_DEVELOP_AND_TAG_V0_5_0_STRUCTURED_PANEL",
        "feature_missingness_audit": str(missingness_path.relative_to(repo)).replace("\\", "/"),
        "schema_audit": str(schema_path.relative_to(repo)).replace("\\", "/"),
        "family_coverage_by_year": str(coverage_path.relative_to(repo)).replace("\\", "/"),
    }
    write_json(audit_path, audit)

    update_config(
        config_path,
        source_sha256=source_sha256,
        final_sha256=final_sha256,
        diagnostics=final_diagnostics,
    )

    panel_text = f"""
## Step-4.5 Final Structured-X Freeze

Step 4.5 promotes the frozen Step-4.4 pension/SEC/market/macro joined artifact to the final
local analytical artifact:

`data/processed/sponsor_year_X.parquet`

The promotion is byte-for-byte. Step 4.5 performs no value transformation and no imputation.
The final artifact therefore has the same SHA-256 as the frozen Step-4.4 joined artifact:

`{final_sha256}`

Final gates verify 5,934 sponsor-year rows, 729 sponsors, 729 SEC CIKs, plan years 2015-2024,
zero duplicate sponsor-years, the frozen October-15-of-t+1 cutoff, zero detected temporal
violations across retained provenance dates, and the presence of all four structured-X families.
The final feature contract contains {len(MODEL_FEATURES)} prespecified model features.

Raw, interim, and final Parquet data remain local-only and are excluded from Git. Tracked
Step-4.5 evidence consists only of code, configuration, tests, documentation, and audit reports.

Step 4.5 authorizes but does not execute the Milestone-4 release. The feature branch is not
merged into `develop` and `v0.5.0-structured-panel` is not created until the separate controlled
Step-4.6 release operation.

## Step-4.5 Acceptance Gate

Step 4.5 passes only if the Step-4.4 joined-artifact hash is unchanged; all upstream Step-4.1
through Step-4.4 audits remain PASS; the final artifact is byte-identical to the Step-4.4
joined artifact; grain, temporal-integrity, feature-family, missingness, Ruff, Pytest, Git diff,
and Git data-safety gates pass; and the release remains unexecuted.

## Next Step

Step 4.6 will merge the fully frozen Milestone-4 feature branch into `develop`, verify the
post-merge repository state, and create/push `v0.5.0-structured-panel` only if every release
gate remains satisfied.
"""
    append_once(panel_doc, "## Step-4.5 Final Structured-X Freeze", panel_text)

    dictionary_text = f"""
## Milestone 4 Step 4.5 Final Structured-X Panel

Final local artifact: `data/processed/sponsor_year_X.parquet`

Grain: `sponsor_id x plan_year`; rows: 5,934; sponsors: 729; SEC CIKs: 729; plan years:
2015-2024. The final artifact is a byte-identical promotion of the frozen Step-4.4 joined
pension/SEC/market/macro artifact. SHA-256: `{final_sha256}`.

The frozen model-feature contract contains {len(MODEL_FEATURES)} fields across four families:
pension, sponsor financials, market, and macro. Missing values are preserved exactly as they
exist after the point-in-time family-specific construction steps; Step 4.5 performs no global
imputation or zero fill. Control and provenance columns are retained in the final Parquet but
are not automatically model features.
"""
    append_once(
        dictionary_doc,
        "## Milestone 4 Step 4.5 Final Structured-X Panel",
        dictionary_text,
    )

    upsert_status(
        status_path,
        {
            "PROJECT_STAGE": "MILESTONE_4_STRUCTURED_X_FROZEN_RELEASE_PENDING",
            "MILESTONE4_STRUCTURED_X": "COMPLETE_RELEASE_PENDING",
            "MILESTONE4_STEP_4_5_STATUS": "PASS",
            "MILESTONE4_FINAL_PANEL_ROWS": str(final_diagnostics["rows"]),
            "MILESTONE4_FINAL_PANEL_UNIQUE_SPONSORS": str(final_diagnostics["unique_sponsors"]),
            "MILESTONE4_FINAL_PANEL_UNIQUE_CIKS": str(final_diagnostics["unique_ciks"]),
            "MILESTONE4_FINAL_PANEL_TEMPORAL_VIOLATIONS": str(
                final_diagnostics["temporal_violation_count"]
            ),
            "MILESTONE4_FINAL_MODEL_FEATURE_COUNT": str(final_diagnostics["model_feature_count"]),
            "MILESTONE4_FINAL_PANEL_SHA256": final_sha256,
            "MILESTONE4_STEP_4_4_JOINED_ARTIFACT_SHA256": source_sha256,
            "MILESTONE4_FINAL_PANEL_GIT_TRACKED": "NO",
            "MILESTONE4_STEP_4_5_IMPUTATION_APPLIED": "NO",
            "STRUCTURED_X": "COMPLETE",
            "MILESTONE4_RELEASE_READY": "YES",
            "MILESTONE4_RELEASE_TAG_CREATED": "NO",
            "NEXT_REQUIRED_STAGE": "MILESTONE_4_STEP_4_6_RELEASE",
            "NEXT_STEP": "4.6",
            "NEXT_STEP_NAME": "MERGE_DEVELOP_AND_TAG_V0_5_0_STRUCTURED_PANEL",
        },
    )

    print("STEP_4_5_STATUS=PASS")
    print(f"FINAL_PANEL_ROWS={final_diagnostics['rows']}")
    print(f"FINAL_PANEL_UNIQUE_SPONSORS={final_diagnostics['unique_sponsors']}")
    print(f"FINAL_PANEL_UNIQUE_CIKS={final_diagnostics['unique_ciks']}")
    print(f"FINAL_PANEL_TEMPORAL_VIOLATIONS={final_diagnostics['temporal_violation_count']}")
    print(f"FINAL_MODEL_FEATURE_COUNT={final_diagnostics['model_feature_count']}")
    print(f"STEP_4_4_ARTIFACT_SHA256={source_sha256}")
    print(f"FINAL_PANEL_SHA256={final_sha256}")
    print("FINAL_PANEL_BYTE_IDENTICAL_TO_STEP_4_4=YES")
    print("STEP_4_5_IMPUTATION_APPLIED=NO")
    print("RELEASE_READY=YES")
    print("RELEASE_EXECUTED=NO")


if __name__ == "__main__":
    main()
