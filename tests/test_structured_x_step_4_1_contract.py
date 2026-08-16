from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "configs" / "structured_x.yaml"


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_step_4_1_cutoff_policy_is_frozen() -> None:
    config = load_config()
    policy = config["temporal_integrity"]["forecast_cutoff_policy"]
    assert policy["status"] == "frozen_step_4_1"
    assert policy["policy_id"] == "OCTOBER_15_T_PLUS_1"
    assert policy["rule"] == "October 15 of calendar year t+1"
    assert policy["month"] == 10
    assert policy["day"] == 15
    assert policy["outcome_independent"] is True


def test_step_4_1_interim_artifact_contract() -> None:
    config = load_config()
    artifact = config["step_4_1_artifact"]
    assert artifact["path"] == (
        "data/interim/structured_x/step_4_1/pension_sponsor_year_base.parquet"
    )
    assert artifact["git_tracked"] is False
    assert artifact["expected_rows"] == 5934
    assert artifact["expected_unique_sponsors"] == 729


def test_step_4_1_linked_population_is_frozen() -> None:
    config = load_config()
    population = config["frozen_inputs"]["linked_pension_population"]
    assert population["expected_plan_rows"] == 8950
    assert population["expected_unique_plans"] == 1294
    assert population["expected_unique_sponsors"] == 729
    assert population["expected_unique_sponsor_years"] == 5934


def test_step_4_1_aggregation_contract_is_point_in_time() -> None:
    config = load_config()
    aggregation = config["pension_aggregation"]
    assert aggregation["temporal_eligibility_rule"] == (
        "plan information_date <= sponsor-year forecast_cutoff"
    )
    assert aggregation["monetary_fields"]["partial_sum_if_available_plan_field_missing"] is False
    assert aggregation["funded_ratio"]["unweighted_plan_ratio_mean_allowed"] is False
    assert aggregation["participants"]["overlap_audit_required"] is True


def test_step_4_1_acceptance_is_pass() -> None:
    config = load_config()
    acceptance = config["step_4_1_acceptance"]
    assert acceptance["forecast_cutoff_policy_frozen"] is True
    assert acceptance["pension_sponsor_year_base_constructed"] is True
    assert acceptance["temporal_integrity_verified"] is True
    assert acceptance["aggregation_identity_audit_verified"] is True
    assert acceptance["interim_parquet_git_tracked"] is False
    assert acceptance["step_4_1_status"] == "PASS"