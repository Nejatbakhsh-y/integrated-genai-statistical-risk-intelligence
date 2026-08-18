import hashlib
import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

CONFIG = REPO / "configs" / "outcomes.yaml"

FINAL_AUDIT = REPO / "reports" / "validation" / "milestone5_step_5_3_final_outcome_audit.json"

EXPECTED_FINAL_SHA256 = "D66CDC3A18D2FDCE155DAF56A465AFF9F6F9F19E866B72002764CF5FB5D0869F"

EXPECTED_THRESHOLD_SHA256 = "9A275DB2FFA12E48889BC1F1FAD3C51F072D1FDDFB215E88115A69BF2B735690"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest().upper()


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def load_audit() -> dict:
    return json.loads(FINAL_AUDIT.read_text(encoding="utf-8"))


def test_step_5_3_contract_is_complete() -> None:
    config = load_config()

    assert config["version"] == "5.3.0"
    assert str(config["step"]) == "5.3"
    assert config["status"] == "outcome_artifact_finalized_and_frozen"

    assert config["roadmap"]["step_5_0"]["status"] == "complete"
    assert config["roadmap"]["step_5_1"]["status"] == "complete"
    assert config["roadmap"]["step_5_2"]["status"] == "complete"
    assert config["roadmap"]["step_5_3"]["status"] == "complete"
    assert config["roadmap"]["step_5_4"]["status"] == "next"


def test_primary_artifact_is_frozen() -> None:
    config = load_config()
    artifact = config["primary_artifact"]

    assert artifact["path"] == "data/processed/outcomes.parquet"
    assert artifact["status"] == "constructed_and_frozen"
    assert artifact["git_tracked"] is False
    assert artifact["expected_sha256"] == EXPECTED_FINAL_SHA256
    assert artifact["expected_rows"] == 5464
    assert artifact["binary_available_rows"] == 3392
    assert artifact["binary_missing_rows"] == 2072
    assert artifact["primary_threshold_c"] == 0.05
    assert artifact["byte_identical_to_step_5_2_binary_panel"] is True
    assert artifact["semantic_identity_to_step_5_2_binary_panel"] is True


def test_final_audit_is_clean() -> None:
    audit = load_audit()

    assert audit["step_5_3_status"] == "PASS"
    assert audit["source_binary_artifact_sha256"] == EXPECTED_FINAL_SHA256
    assert audit["final_outcome_artifact_sha256"] == EXPECTED_FINAL_SHA256
    assert audit["byte_identical_to_step_5_2_binary_panel"] is True
    assert audit["semantic_identity_to_step_5_2_binary_panel"] is True
    assert audit["final_artifact_rows"] == 5464
    assert audit["binary_outcome_available_rows"] == 3392
    assert audit["binary_outcome_missing_rows"] == 2072
    assert audit["year_alignment_violation_count"] == 0
    assert audit["same_year_target_violation_count"] == 0
    assert audit["duplicate_predictor_sponsor_year_rows"] == 0
    assert audit["target_imputation_applied"] is False
    assert audit["threshold_retuning_applied"] is False
    assert audit["final_holdout_defined_or_inspected"] is False
    assert audit["model_fitting_started"] is False


def test_threshold_contract_remains_frozen() -> None:
    config = load_config()
    threshold = config["threshold_contract"]

    assert threshold["primary_value"] == 0.05
    assert threshold["status"] == "frozen_step_5_2"
    assert threshold["prespecification_sha256"] == EXPECTED_THRESHOLD_SHA256
    assert threshold["retuning_authorized"] is False


def test_final_audit_hash_is_recorded() -> None:
    config = load_config()

    audit_meta = config["step_5_3_artifacts"]["final_audit"]

    assert audit_meta["git_tracked"] is True
    assert audit_meta["expected_sha256"] == sha256_file(FINAL_AUDIT)


def test_step_5_4_is_only_authorized_next_step() -> None:
    config = load_config()

    assert config["release"]["release_ready"] is True
    assert config["release"]["release_authorized_by_step_5_3"] is True
    assert config["release"]["target_tag_created"] is False

    assert config["next_step"] == {
        "id": "5.4",
        "name": "merge_develop_and_tag_v0_6_0_outcomes",
    }

    status = (REPO / "STATUS.md").read_text(encoding="utf-8")

    assert "MILESTONE5_STEP_5_3_STATUS=PASS" in status
    assert "MILESTONE5_PRIMARY_ARTIFACT_STATUS=CONSTRUCTED_AND_FROZEN" in status
    assert f"MILESTONE5_PRIMARY_ARTIFACT_SHA256={EXPECTED_FINAL_SHA256}" in status
    assert "MILESTONE5_RELEASE_READY=YES" in status
    assert "MILESTONE5_RELEASE_TAG_CREATED=NO" in status
    assert "NEXT_STEP=5.4" in status
