import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

CONFIG = REPO / "configs" / "outcomes.yaml"

THRESHOLD_RECORD = (
    REPO / "reports" / "validation" / "milestone5_step_5_2_threshold_prespecification.json"
)

BINARY_AUDIT = REPO / "reports" / "validation" / "milestone5_step_5_2_binary_outcome_audit.json"

EXPECTED_CONTINUOUS_SHA256 = "1AE8A3E29F878D52DE09A3E1011DAF60C56922CF55EABC01CF32EB01959FAE0E"


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def load_threshold_record() -> dict:
    return json.loads(THRESHOLD_RECORD.read_text(encoding="utf-8"))


def load_audit() -> dict:
    return json.loads(BINARY_AUDIT.read_text(encoding="utf-8"))


def test_step_5_2_contract_is_complete() -> None:
    config = load_config()

    assert config["version"] == "5.2.0"
    assert config["milestone"] == 5
    assert str(config["step"]) == "5.2"

    assert config["status"] == ("binary_outcome_constructed_threshold_frozen")

    assert config["roadmap"]["step_5_0"]["status"] == "complete"
    assert config["roadmap"]["step_5_1"]["status"] == "complete"
    assert config["roadmap"]["step_5_2"]["status"] == "complete"
    assert config["roadmap"]["step_5_3"]["status"] == "next"


def test_primary_threshold_is_frozen_at_point_zero_five() -> None:
    config = load_config()
    threshold = config["threshold_contract"]

    assert threshold["primary_value"] == 0.05

    assert threshold["status"] == "frozen_step_5_2"

    assert threshold["unit"] == ("absolute_funded_ratio_change")

    assert threshold["primary_percentage_points"] == 5.0

    assert threshold["robustness_thresholds"] == [
        0.025,
        0.10,
    ]

    assert threshold["selected_from_outcome_distribution"] is False

    assert threshold["selected_from_final_holdout"] is False

    assert threshold["retuning_authorized"] is False


def test_threshold_was_frozen_before_binary_construction() -> None:
    record = load_threshold_record()
    audit = load_audit()

    assert record["status"] == ("FROZEN_BEFORE_BINARY_CONSTRUCTION")

    assert record["primary_threshold_c"] == 0.05

    assert record["outcome_values_explicitly_loaded_by_step_5_2_before_freeze"] is False

    assert record["selected_from_observed_outcome_distribution"] is False

    assert record["selected_from_final_holdout"] is False

    assert audit["threshold_frozen_before_binary_construction"] is True


def test_binary_outcome_preserves_continuous_missingness() -> None:
    audit = load_audit()

    assert audit["input_continuous_artifact_sha256"] == EXPECTED_CONTINUOUS_SHA256

    assert audit["continuous_panel_rows"] == 5464
    assert audit["binary_panel_rows"] == 5464

    assert audit["continuous_outcome_available_rows"] == 3392

    assert audit["binary_outcome_available_rows"] == 3392
    assert audit["binary_outcome_missing_rows"] == 2072

    assert audit["target_imputation_applied"] is False
    assert audit["forward_fill_applied"] is False
    assert audit["backfill_applied"] is False


def test_binary_outcome_preserves_temporal_contract() -> None:
    audit = load_audit()

    assert audit["year_alignment_violation_count"] == 0
    assert audit["same_year_target_violation_count"] == 0
    assert audit["duplicate_predictor_sponsor_year_rows"] == 0
    assert audit["upstream_columns_preserved_exactly"] is True


def test_final_holdout_and_models_remain_locked() -> None:
    config = load_config()
    audit = load_audit()

    threshold = config["threshold_contract"]
    controls = config["scientific_controls"]

    assert threshold["final_holdout_may_select_threshold"] is False
    assert threshold["final_holdout_may_tune_threshold"] is False

    assert controls["final_holdout_inspection_allowed_in_milestone_5"] is False

    assert controls["model_fitting_allowed_in_milestone_5"] is False

    assert audit["final_holdout_defined_or_inspected"] is False
    assert audit["model_fitting_started"] is False


def test_binary_interim_artifact_is_frozen_in_config() -> None:
    config = load_config()
    audit = load_audit()

    artifact = config["step_5_2_artifacts"]["binary_outcome_panel"]

    assert artifact["git_tracked"] is False

    assert artifact["expected_sha256"] == audit["binary_output_artifact_sha256"]

    assert artifact["expected_rows"] == 5464

    assert artifact["binary_available_rows"] == 3392

    assert artifact["primary_threshold_c"] == 0.05


def test_step_5_3_is_the_only_authorized_next_step() -> None:
    config = load_config()

    assert config["next_step"] == {
        "id": "5.3",
        "name": "finalize_and_freeze_outcome_artifact",
    }

    status = (REPO / "STATUS.md").read_text(encoding="utf-8")

    assert "MILESTONE5_STEP_5_2_STATUS=PASS" in status
    assert "MILESTONE5_PRIMARY_THRESHOLD_C=0.05" in status

    assert "MILESTONE5_THRESHOLD_STATUS=FROZEN_STEP_5_2" in status

    assert "MILESTONE5_FINAL_HOLDOUT_INSPECTED=NO" in status
    assert "MILESTONE5_MODEL_FITTING_STARTED=NO" in status

    assert "NEXT_STEP=5.3" in status
    assert "NEXT_STEP_NAME=FINALIZE_AND_FREEZE_OUTCOME_ARTIFACT" in status
