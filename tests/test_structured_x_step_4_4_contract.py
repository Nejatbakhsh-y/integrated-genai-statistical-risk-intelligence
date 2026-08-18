from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
EXPECTED_STEP_4_3_SHA256 = "0A3F6922EA0FE3D83058EC980B19174C5213EE1188CAA8BED8ADE69657D8F9EB"
EXPECTED_STEP_4_4_SHA256 = "6E7C3954CE1F23110B4A88E7A83E5CEC5C6B759825670DB9A90682CE5AA56ACF"


def load_config():
    return yaml.safe_load((REPO / "configs" / "structured_x.yaml").read_text(encoding="utf-8"))


def load_audit():
    path = REPO / "reports" / "validation" / "milestone4_step_4_4_macro_ingestion_audit.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_step_4_4_historical_acceptance_remains_frozen() -> None:
    config = load_config()
    assert config["step_4_3_acceptance"]["step_4_3_status"] == "PASS"
    assert config["step_4_4_acceptance"]["step_4_4_status"] == "PASS"
    assert config["step_4_4_acceptance"]["temporal_violation_count"] == 0
    assert config["data_families"]["macro"]["status"] == "step_4_4_complete"
    assert config["macro_alignment"]["transformation_version"] == "4.4.0"


def test_step_4_4_artifact_hashes_remain_frozen() -> None:
    config = load_config()
    audit = load_audit()
    assert audit["step_4_3_artifact_sha256"] == EXPECTED_STEP_4_3_SHA256
    assert audit["joined_artifact_sha256"] == EXPECTED_STEP_4_4_SHA256
    artifacts = config["step_4_4_artifacts"]
    assert (
        artifacts["joined_pension_sec_market_macro_base"]["expected_sha256"]
        == EXPECTED_STEP_4_4_SHA256
    )


def test_macro_family_and_alfred_vintage_controls_remain_frozen() -> None:
    config = load_config()
    macro = config["data_families"]["macro"]
    assert set(macro["fields"]) == {
        "macro_interest_rate_10y",
        "macro_inflation_yoy",
        "macro_credit_conditions_nfci",
        "macro_unemployment_rate",
    }
    alignment = config["macro_alignment"]
    assert alignment["source_family"] == "ALFRED_VINTAGE_GRAPH_CSV"
    assert alignment["vintage_date_rule"] == "vintage_date == forecast_cutoff"
    assert alignment["interest_rate_series"] == "DGS10"
    assert alignment["inflation_series"] == "CPIAUCNS"
    assert alignment["credit_conditions_series"] == "NFCI"
    assert alignment["unemployment_series"] == "UNRATE"
    assert alignment["future_vintage_backfill_allowed"] is False
    assert alignment["future_observation_backfill_allowed"] is False


def test_step_4_4_audit_preserves_grain_and_zero_temporal_violations() -> None:
    audit = load_audit()
    assert audit["step_4_4_status"] == "PASS"
    assert audit["unique_forecast_cutoffs"] == 10
    assert audit["raw_snapshot_requests"] == 40
    assert audit["macro_year_rows"] == 10
    assert audit["macro_sponsor_year_rows"] == 5934
    assert audit["joined_sponsor_year_rows"] == 5934
    assert audit["duplicate_sponsor_year_rows"] == 0
    assert audit["temporal_violation_count"] == 0


def test_step_4_4_handoff_may_advance_to_final_freeze() -> None:
    config = load_config()
    status = (REPO / "STATUS.md").read_text(encoding="utf-8")
    if str(config["step"]) == "4.4":
        assert config["primary_artifact"]["status"] == "not_yet_constructed"
        assert str(config["next_step"]["id"]) == "4.5"
        assert config["next_step"]["name"] == "finalize_and_freeze_structured_x_panel"
    else:
        assert config["primary_artifact"]["status"] == "constructed_and_frozen"
        assert config["step_4_5_acceptance"]["step_4_5_status"] == "PASS"
        assert "STRUCTURED_X=COMPLETE" in status
    assert config["release"]["target_tag_created"] is False
