from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
EXPECTED_STEP_4_2_SHA256 = "09F93E43AA169CE95A7AF98E923C0E6FF6DFEEE8E987564A90E9A86BD7EC7883"
EXPECTED_STEP_4_3_JOINED_SHA256 = "0A3F6922EA0FE3D83058EC980B19174C5213EE1188CAA8BED8ADE69657D8F9EB"


def load_config():
    return yaml.safe_load((REPO / "configs" / "structured_x.yaml").read_text(encoding="utf-8"))


def load_audit():
    path = REPO / "reports" / "validation" / "milestone4_step_4_3_market_ingestion_audit.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_step_4_3_historical_acceptance_remains_frozen() -> None:
    config = load_config()
    assert config["step_4_2_acceptance"]["step_4_2_status"] == "PASS"
    assert config["step_4_3_acceptance"]["step_4_3_status"] == "PASS"
    assert config["step_4_3_acceptance"]["temporal_violation_count"] == 0
    assert config["data_families"]["market"]["status"] == "step_4_3_complete"


def test_step_4_3_artifact_hashes_remain_frozen() -> None:
    config = load_config()
    audit = load_audit()
    assert audit["step_4_2_artifact_sha256"] == EXPECTED_STEP_4_2_SHA256
    assert audit["joined_artifact_sha256"] == EXPECTED_STEP_4_3_JOINED_SHA256
    artifacts = config["step_4_3_artifacts"]
    assert (
        artifacts["joined_pension_sec_market_base"]["expected_sha256"]
        == EXPECTED_STEP_4_3_JOINED_SHA256
    )


def test_step_4_3_market_contract_remains_frozen() -> None:
    config = load_config()
    market = config["data_families"]["market"]
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


def test_step_4_3_grain_and_temporal_audit_remain_valid() -> None:
    audit = load_audit()
    assert audit["step_4_3_status"] == "PASS"
    assert audit["target_ciks"] == 729
    assert audit["sponsor_year_rows"] == 5934
    assert audit["joined_sponsor_year_rows"] == 5934
    assert audit["duplicate_sponsor_year_rows"] == 0
    assert audit["temporal_violation_count"] == 0


def test_step_4_3_handoff_may_advance_after_macro_integration() -> None:
    config = load_config()
    current_step = str(config["step"])
    if current_step == "4.3":
        assert str(config["next_step"]["id"]) == "4.4"
        assert config["next_step"]["name"] == "ingest_and_align_point_in_time_macro_variables"
    else:
        assert config["step_4_3_acceptance"]["step_4_3_status"] == "PASS"
        assert config["data_families"]["macro"]["status"] == "step_4_4_complete"
