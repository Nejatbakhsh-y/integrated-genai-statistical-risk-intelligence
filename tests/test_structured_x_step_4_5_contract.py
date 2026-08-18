from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
EXPECTED_FINAL_SHA256 = "6E7C3954CE1F23110B4A88E7A83E5CEC5C6B759825670DB9A90682CE5AA56ACF"


def load_config():
    return yaml.safe_load((REPO / "configs" / "structured_x.yaml").read_text(encoding="utf-8"))


def load_audit():
    path = REPO / "reports" / "validation" / "milestone4_step_4_5_final_panel_audit.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_step_4_5_scientific_contract_remains_frozen() -> None:
    config = load_config()
    assert config["version"] == "4.5.0"
    assert str(config["step"]) == "4.5"
    assert config["status"] == "structured_x_panel_frozen"
    acceptance = config["step_4_5_acceptance"]
    assert acceptance["step_4_5_status"] == "PASS"
    assert acceptance["release_ready"] is True
    assert acceptance["release_executed"] is False


def test_final_artifact_hash_and_grain_are_frozen() -> None:
    config = load_config()
    audit = load_audit()
    primary = config["primary_artifact"]
    assert primary["status"] == "constructed_and_frozen"
    assert primary["git_tracked"] is False
    assert primary["expected_sha256"] == EXPECTED_FINAL_SHA256
    assert audit["final_artifact_sha256"] == EXPECTED_FINAL_SHA256
    assert audit["source_artifact_sha256"] == EXPECTED_FINAL_SHA256
    assert audit["final_artifact_byte_identical_to_step_4_4_joined"] is True
    assert audit["rows"] == 5934
    assert audit["unique_sponsors"] == 729
    assert audit["unique_ciks"] == 729
    assert audit["duplicate_sponsor_year_rows"] == 0
    assert audit["temporal_violation_count"] == 0


def test_all_four_families_are_complete() -> None:
    config = load_config()
    assert config["data_families"]["sponsor_financials"]["status"] == "step_4_2_complete"
    assert config["data_families"]["market"]["status"] == "step_4_3_complete"
    assert config["data_families"]["macro"]["status"] == "step_4_4_complete"
    final_panel = config["final_panel"]
    assert final_panel["model_feature_count"] == 31
    assert set(final_panel["model_feature_families"]) == {
        "pension",
        "sponsor_financials",
        "market",
        "macro",
    }
    assert final_panel["missingness_preserved"] is True
    assert final_panel["step_4_5_imputation_applied"] is False


def test_step_4_5_historical_release_authorization_is_preserved() -> None:
    config = load_config()
    acceptance = config["step_4_5_acceptance"]
    assert acceptance["release_ready"] is True
    assert acceptance["release_executed"] is False
    assert config["release"]["release_authorized_by_step_4_5"] is True
    assert config["release"]["release_ready"] is True


def test_status_preserves_step_4_5_pass_after_release() -> None:
    status = (REPO / "STATUS.md").read_text(encoding="utf-8")
    assert "MILESTONE4_STEP_4_5_STATUS=PASS" in status
    assert "STRUCTURED_X=COMPLETE" in status
    assert "MILESTONE4_RELEASE_READY=YES" in status
