import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

CONFIG = REPO / "configs" / "outcomes.yaml"

THRESHOLD_RECORD = (
    REPO / "reports" / "validation" / "milestone5_step_5_2_threshold_prespecification.json"
)

BINARY_AUDIT = REPO / "reports" / "validation" / "milestone5_step_5_2_binary_outcome_audit.json"

EXPECTED_BINARY_SHA256 = "D66CDC3A18D2FDCE155DAF56A465AFF9F6F9F19E866B72002764CF5FB5D0869F"

EXPECTED_THRESHOLD_SHA256 = "9A275DB2FFA12E48889BC1F1FAD3C51F072D1FDDFB215E88115A69BF2B735690"


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def load_record() -> dict:
    return json.loads(THRESHOLD_RECORD.read_text(encoding="utf-8"))


def load_audit() -> dict:
    return json.loads(BINARY_AUDIT.read_text(encoding="utf-8"))


def test_step_5_2_threshold_remains_frozen() -> None:
    config = load_config()
    threshold = config["threshold_contract"]

    assert threshold["primary_value"] == 0.05
    assert threshold["status"] == "frozen_step_5_2"
    assert threshold["prespecification_sha256"] == EXPECTED_THRESHOLD_SHA256
    assert threshold["selected_from_outcome_distribution"] is False
    assert threshold["selected_from_final_holdout"] is False
    assert threshold["retuning_authorized"] is False


def test_step_5_2_acceptance_remains_frozen() -> None:
    config = load_config()
    acceptance = config["step_5_2_acceptance"]

    assert acceptance["step_5_2_status"] == "PASS"
    assert acceptance["primary_threshold_c"] == 0.05
    assert acceptance["binary_outcome_sha256"] == EXPECTED_BINARY_SHA256
    assert acceptance["binary_panel_rows"] == 5464
    assert acceptance["binary_outcome_available_rows"] == 3392
    assert acceptance["binary_outcome_missing_rows"] == 2072
    assert acceptance["year_alignment_violation_count"] == 0
    assert acceptance["same_year_target_violation_count"] == 0
    assert acceptance["duplicate_predictor_sponsor_year_rows"] == 0
    assert acceptance["target_imputation_applied"] is False


def test_step_5_2_prespecification_record_remains_clean() -> None:
    record = load_record()

    assert record["primary_threshold_c"] == 0.05
    assert record["status"] == "FROZEN_BEFORE_BINARY_CONSTRUCTION"
    assert record["selected_from_observed_outcome_distribution"] is False
    assert record["selected_from_final_holdout"] is False
    assert record["retuning_after_binary_construction_authorized"] is False


def test_step_5_2_binary_audit_remains_clean() -> None:
    audit = load_audit()

    assert audit["step_5_2_status"] == "PASS"
    assert audit["binary_output_artifact_sha256"] == EXPECTED_BINARY_SHA256
    assert audit["binary_panel_rows"] == 5464
    assert audit["binary_outcome_available_rows"] == 3392
    assert audit["binary_outcome_missing_rows"] == 2072
    assert audit["target_imputation_applied"] is False
    assert audit["final_holdout_defined_or_inspected"] is False
    assert audit["model_fitting_started"] is False


def test_step_5_2_lifecycle_can_advance() -> None:
    config = load_config()

    assert config["roadmap"]["step_5_2"]["status"] == "complete"

    current_step = str(config["step"])

    assert current_step in {
        "5.2",
        "5.3",
    }

    if current_step == "5.2":
        assert config["next_step"]["id"] == "5.3"
