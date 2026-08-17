from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
EXPECTED_STEP_4_2_SHA256 = "09F93E43AA169CE95A7AF98E923C0E6FF6DFEEE8E987564A90E9A86BD7EC7883"


def load_config():
    return yaml.safe_load((REPO / "configs" / "structured_x.yaml").read_text(encoding="utf-8"))


def load_audit():
    path = REPO / "reports" / "validation" / "milestone4_step_4_3_market_ingestion_audit.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_step_4_3_contract_and_handoff():
    config = load_config()
    assert config["version"] == "4.3.0"
    assert str(config["step"]) == "4.3"
    assert config["status"] == "step_4_3_market_variables_frozen"
    assert config["step_4_2_acceptance"]["step_4_2_status"] == "PASS"
    assert config["step_4_3_acceptance"]["step_4_3_status"] == "PASS"
    assert config["step_4_3_acceptance"]["temporal_violation_count"] == 0
    assert str(config["next_step"]["id"]) == "4.4"
    assert config["next_step"]["name"] == "ingest_and_align_point_in_time_macro_variables"


def test_step_4_2_hash_is_frozen_and_step_4_3_hashes_match_audit():
    config = load_config()
    audit = load_audit()
    assert audit["step_4_2_artifact_sha256"] == EXPECTED_STEP_4_2_SHA256
    frozen = config["frozen_inputs"]["step_4_2_joined_base"]
    assert frozen["expected_sha256"] == EXPECTED_STEP_4_2_SHA256
    artifacts = config["step_4_3_artifacts"]
    assert (
        artifacts["market_sponsor_year_features"]["expected_sha256"]
        == audit["market_artifact_sha256"]
    )
    assert (
        artifacts["joined_pension_sec_market_base"]["expected_sha256"]
        == audit["joined_artifact_sha256"]
    )


def test_market_family_and_temporal_controls_are_frozen():
    config = load_config()
    market = config["data_families"]["market"]
    assert market["status"] == "step_4_3_complete"
    assert set(market["fields"]) == {
        "market_equity_return",
        "market_equity_volatility",
        "market_equity_drawdown",
        "market_capitalization",
    }
    alignment = config["market_alignment"]
    assert alignment["price_source_family"] == "YAHOO_FINANCE_CHART_DAILY"
    assert alignment["return_price_basis"] == "adjusted close"
    assert alignment["market_cap_price_basis"] == "regular close on provider split basis"
    assert alignment["trailing_window_price_observations"] == 253
    assert alignment["trailing_window_trading_intervals"] == 252
    assert alignment["future_price_backfill_allowed"] is False
    assert alignment["future_share_filing_backfill_allowed"] is False
    assert alignment["manual_ticker_inference_allowed"] is False
    availability = config["temporal_integrity"]["analytical_availability"]
    assert availability["market_prices_after_cutoff_excluded"] is True
    assert availability["market_shares_filed_after_cutoff_excluded"] is True


def test_step_4_3_audit_preserves_grain_and_zero_temporal_violations():
    audit = load_audit()
    assert audit["step_4_3_status"] == "PASS"
    assert audit["target_ciks"] == 729
    assert audit["sponsor_year_rows"] == 5934
    assert audit["joined_sponsor_year_rows"] == 5934
    assert audit["duplicate_sponsor_year_rows"] == 0
    assert audit["temporal_violation_count"] == 0
    assert audit["equity_return_nonmissing"] > 0
    assert audit["equity_volatility_nonmissing"] > 0
    assert audit["equity_drawdown_nonmissing"] > 0
    assert audit["market_capitalization_nonmissing"] > 0


def test_status_hands_off_to_step_4_4_without_releasing_milestone_4():
    status = (REPO / "STATUS.md").read_text(encoding="utf-8")
    assert "MILESTONE4_STEP_4_3_STATUS=PASS" in status
    assert "STRUCTURED_X=NOT_YET_COMPLETE" in status
    assert "MILESTONE4_RELEASE_TAG_CREATED=NO" in status
    assert "NEXT_STEP=4.4" in status
    assert "NEXT_STEP_NAME=INGEST_AND_ALIGN_POINT_IN_TIME_MACRO_VARIABLES" in status
