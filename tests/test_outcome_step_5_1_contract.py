import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

CONFIG = REPO / "configs" / "outcomes.yaml"

AUDIT = REPO / "reports" / "validation" / "milestone5_step_5_1_outcome_audit.json"

EXPECTED_SHA256 = "1AE8A3E29F878D52DE09A3E1011DAF60C56922CF55EABC01CF32EB01959FAE0E"


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def load_audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_step_5_1_acceptance_remains_frozen() -> None:
    config = load_config()
    acceptance = config["step_5_1_acceptance"]

    assert acceptance["step_5_1_status"] == "PASS"
    assert acceptance["continuous_outcome_sha256"] == EXPECTED_SHA256
    assert acceptance["continuous_panel_rows"] == 5464
    assert acceptance["continuous_outcome_available_rows"] == 3392
    assert acceptance["year_alignment_violation_count"] == 0
    assert acceptance["same_year_target_violation_count"] == 0
    assert acceptance["duplicate_predictor_sponsor_year_rows"] == 0
    assert acceptance["target_imputation_applied"] is False


def test_step_5_1_audit_remains_scientifically_clean() -> None:
    audit = load_audit()

    assert audit["output_artifact_sha256"] == EXPECTED_SHA256
    assert audit["threshold_selected"] is False
    assert audit["binary_outcome_constructed"] is False
    assert audit["outcome_distribution_inspected_for_threshold"] is False
    assert audit["final_holdout_defined_or_inspected"] is False
    assert audit["model_fitting_started"] is False


def test_step_5_1_lifecycle_can_advance() -> None:
    config = load_config()

    assert config["roadmap"]["step_5_1"]["status"] == "complete"

    current_step = str(config["step"])

    assert current_step in {
        "5.1",
        "5.2",
        "5.3",
    }

    if current_step == "5.1":
        assert config["next_step"]["id"] == "5.2"
