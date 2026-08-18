import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "configs" / "outcomes.yaml"
AUDIT = REPO / "reports" / "validation" / "milestone5_step_5_1_outcome_audit.json"

EXPECTED_PENSION_SHA256 = "2140DCC58293583A5E4877E6E03FBF919C1BAB1022BD6752F5F33C7AA2B84529"

EXPECTED_STRUCTURED_X_SHA256 = "6E7C3954CE1F23110B4A88E7A83E5CEC5C6B759825670DB9A90682CE5AA56ACF"


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def load_audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_step_5_1_contract_is_complete() -> None:
    config = load_config()

    assert config["version"] == "5.1.0"
    assert config["milestone"] == 5
    assert str(config["step"]) == "5.1"
    assert config["status"] == "continuous_outcome_panel_constructed"

    acceptance = config["step_5_1_acceptance"]

    assert acceptance["step_5_1_status"] == "PASS"
    assert acceptance["year_alignment_violation_count"] == 0
    assert acceptance["same_year_target_violation_count"] == 0
    assert acceptance["duplicate_predictor_sponsor_year_rows"] == 0


def test_step_5_1_preserves_frozen_inputs() -> None:
    audit = load_audit()

    assert audit["input_pension_base_sha256"] == EXPECTED_PENSION_SHA256
    assert audit["input_structured_x_sha256"] == EXPECTED_STRUCTURED_X_SHA256
    assert audit["input_pension_rows"] == 5934
    assert audit["input_unique_sponsors"] == 729
    assert audit["pension_only_key_count"] == 0
    assert audit["structured_x_only_key_count"] == 0


def test_step_5_1_is_exactly_one_year_ahead() -> None:
    config = load_config()
    audit = load_audit()

    contract = config["outcome_contract"]

    assert contract["horizon_years"] == 1
    assert contract["same_year_target_allowed"] is False
    assert contract["nonconsecutive_year_pairing_allowed"] is False

    assert audit["year_alignment_violation_count"] == 0
    assert audit["same_year_target_violation_count"] == 0
    assert audit["nonconsecutive_pairing_allowed"] is False


def test_step_5_1_does_not_select_threshold_or_binary_target() -> None:
    config = load_config()
    audit = load_audit()

    threshold = config["threshold_contract"]

    assert threshold["primary_value"] is None
    assert threshold["status"] == "pending_step_5_2_prespecification"
    assert threshold["final_holdout_may_select_threshold"] is False
    assert threshold["final_holdout_may_tune_threshold"] is False

    assert audit["threshold_selected"] is False
    assert audit["binary_outcome_constructed"] is False
    assert audit["outcome_distribution_inspected_for_threshold"] is False


def test_step_5_1_does_not_impute_targets() -> None:
    audit = load_audit()

    assert audit["target_imputation_applied"] is False
    assert audit["forward_fill_applied"] is False
    assert audit["backfill_applied"] is False


def test_continuous_artifact_identity_is_frozen_in_config() -> None:
    config = load_config()
    audit = load_audit()

    artifact = config["step_5_1_artifacts"]["continuous_outcome_panel"]

    assert artifact["git_tracked"] is False
    assert artifact["expected_sha256"] == audit["output_artifact_sha256"]
    assert artifact["expected_rows"] == audit["continuous_panel_rows"]
    assert artifact["grain"] == [
        "sponsor_id",
        "predictor_plan_year",
    ]


def test_step_5_2_is_the_only_authorized_next_step() -> None:
    config = load_config()

    assert config["next_step"] == {
        "id": "5.2",
        "name": ("freeze_material_deterioration_threshold_and_binary_outcome"),
    }

    status = (REPO / "STATUS.md").read_text(encoding="utf-8")

    assert "MILESTONE5_STEP_5_1_STATUS=PASS" in status
    assert "MILESTONE5_THRESHOLD_STATUS=PENDING_STEP_5_2_PRESPECIFICATION" in status
    assert "MILESTONE5_FINAL_HOLDOUT_INSPECTED=NO" in status
    assert "MILESTONE5_MODEL_FITTING_STARTED=NO" in status
    assert "NEXT_STEP=5.2" in status
