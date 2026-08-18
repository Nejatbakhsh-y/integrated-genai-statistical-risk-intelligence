from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "configs" / "outcomes.yaml"


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_step_5_0_governance_contract_remains_frozen() -> None:
    config = load_config()

    assert config["milestone"] == 5
    assert config["release"]["base_tag"] == "v0.5.0-structured-panel"
    assert config["release"]["target_tag"] == "v0.6.0-outcomes"
    assert config["roadmap"]["step_5_0"]["status"] == "complete"

    contract = config["outcome_contract"]

    assert contract["horizon_years"] == 1
    assert contract["same_year_target_allowed"] is False
    assert contract["nonconsecutive_year_pairing_allowed"] is False
    assert contract["future_target_as_predictor_allowed"] is False
    assert contract["forward_filled_future_target_allowed"] is False
    assert contract["positive_liabilities_required"] is True
    assert contract["missing_funded_ratio_policy"] == ("preserve_missing_no_imputation")


def test_threshold_governance_remains_final_holdout_safe() -> None:
    threshold = load_config()["threshold_contract"]

    assert threshold["final_holdout_may_select_threshold"] is False
    assert threshold["final_holdout_may_tune_threshold"] is False
    assert threshold["robustness_thresholds_required"] is True


def test_model_fitting_remains_unauthorized_in_milestone_5() -> None:
    controls = load_config()["scientific_controls"]

    assert controls["outcome_code_independent_from_model_training"] is True
    assert controls["model_fitting_allowed_in_milestone_5"] is False
    assert controls["final_holdout_inspection_allowed_in_milestone_5"] is False
    assert controls["silent_target_imputation_allowed"] is False


def test_formatter_debt_exception_remains_exact_and_frozen() -> None:
    quality = load_config()["repository_quality_baseline"]

    assert quality["formatter_debt_count"] == 8
    assert len(quality["formatter_debt_paths"]) == 8
    assert quality["step_5_0_may_modify_formatter_debt"] is False
    assert quality["non_debt_python_format_check"] == "PASS"


def test_step_5_0_handoff_may_advance_within_milestone_5() -> None:
    config = load_config()
    status = (REPO / "STATUS.md").read_text(encoding="utf-8")

    assert "MILESTONE5_STEP_5_0_STATUS=PASS" in status
    assert "MILESTONE5_FINAL_HOLDOUT_INSPECTED=NO" in status
    assert "MILESTONE5_MODEL_FITTING_STARTED=NO" in status

    if str(config["step"]) == "5.0":
        assert config["next_step"]["id"] == "5.1"
        assert "NEXT_STEP=5.1" in status
    else:
        assert config["roadmap"]["step_5_0"]["status"] == "complete"
