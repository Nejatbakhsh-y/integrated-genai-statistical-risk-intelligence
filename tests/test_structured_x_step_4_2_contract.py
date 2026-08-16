from pathlib import Path

import yaml

from risk_intelligence.features.sec_financials import METRIC_CANDIDATES

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "configs" / "structured_x.yaml"


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_step_4_2_contract_is_frozen() -> None:
    config = load_config()
    assert config["version"] == "4.2.0"
    assert config["step"] == "4.2"
    assert config["status"] == "step_4_2_sec_financials_frozen"
    assert config["step_4_2_acceptance"]["step_4_2_status"] == "PASS"


def test_step_4_2_artifacts_preserve_sponsor_year_grain() -> None:
    config = load_config()
    artifacts = config["step_4_2_artifacts"]
    sec = artifacts["sec_sponsor_year_financials"]
    joined = artifacts["joined_pension_sec_base"]
    assert sec["expected_rows"] == 5934
    assert sec["expected_unique_sponsors"] == 729
    assert sec["expected_unique_ciks"] == 729
    assert sec["git_tracked"] is False
    assert joined["expected_rows"] == 5934
    assert joined["grain"] == ["sponsor_id", "plan_year"]
    assert joined["git_tracked"] is False
    assert len(sec["expected_sha256"]) == 64
    assert len(joined["expected_sha256"]) == 64


def test_step_4_2_point_in_time_rules_are_strict() -> None:
    config = load_config()
    alignment = config["sponsor_financial_alignment"]
    assert alignment["fiscal_year_rule"] == "XBRL fact fy == sponsor plan_year"
    assert alignment["temporal_eligibility_rule"] == (
        "fact filed_date <= sponsor-year forecast_cutoff"
    )
    assert alignment["period_end_rule"] == "fact period_end <= sponsor-year forecast_cutoff"
    assert alignment["future_backfill_allowed"] is False
    assert alignment["retrospective_restated_value_after_cutoff_allowed"] is False
    assert alignment["non_usd_currency_conversion_allowed"] is False


def test_step_4_2_config_concept_priority_matches_implementation() -> None:
    config = load_config()
    configured = config["sponsor_financial_alignment"]["concept_priority"]
    assert set(configured) == set(METRIC_CANDIDATES)
    for metric, candidates in METRIC_CANDIDATES.items():
        expected = [f"{candidate.taxonomy}:{candidate.concept}" for candidate in candidates]
        assert configured[metric] == expected


def test_step_4_2_financial_family_is_complete_but_milestone_is_not() -> None:
    config = load_config()
    assert config["data_families"]["sponsor_financials"]["status"] == "step_4_2_complete"
    assert config["data_families"]["market"]["status"] == "next_step_4_3"
    assert config["primary_artifact"]["status"] == "not_yet_constructed"
    assert config["release"]["target_tag_created"] is False


def test_step_4_2_pension_size_definition_is_frozen() -> None:
    config = load_config()
    pension_size = config["pension_aggregation"]["pension_size"]
    assert pension_size["status"] == "defined_step_4_2"
    assert pension_size["rule"] == (
        "Form5500 aggregate pension liabilities divided by SEC total assets"
    )
    assert pension_size["require_positive_sec_total_assets"] is True


def test_step_4_2_next_step_is_market_alignment() -> None:
    config = load_config()
    assert config["next_step"] == {
        "id": "4.3",
        "name": "ingest_and_align_point_in_time_market_variables",
    }
