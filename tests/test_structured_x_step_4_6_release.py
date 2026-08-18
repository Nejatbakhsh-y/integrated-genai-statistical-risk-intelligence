from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

EXPECTED_FINAL_SHA256 = "6E7C3954CE1F23110B4A88E7A83E5CEC5C6B759825670DB9A90682CE5AA56ACF"

EXPECTED_TAG = "v0.5.0-structured-panel"

EXPECTED_MERGE_COMMIT = "f7e8077eff9c5baa5f80d3232b7f27ef7a4de2b1"


def load_config():
    return yaml.safe_load((REPO / "configs" / "structured_x.yaml").read_text(encoding="utf-8"))


def test_step_4_6_release_metadata_is_complete() -> None:
    config = load_config()
    release = config["release"]

    assert release["target_tag"] == EXPECTED_TAG
    assert release["target_tag_created"] is True
    assert release["release_ready"] is True
    assert release["release_authorized_by_step_4_5"] is True
    assert release["release_action_status"] == "complete_step_4_6"
    assert release["release_executed"] is True
    assert "next_step" not in config


def test_step_4_6_preserves_frozen_final_panel() -> None:
    config = load_config()
    primary = config["primary_artifact"]

    assert primary["status"] == "constructed_and_frozen"
    assert primary["git_tracked"] is False
    assert primary["expected_sha256"] == EXPECTED_FINAL_SHA256
    assert primary["expected_rows"] == 5934
    assert primary["expected_unique_sponsors"] == 729
    assert primary["expected_unique_ciks"] == 729
    assert config["final_panel"]["model_feature_count"] == 31
    assert config["final_panel"]["step_4_5_imputation_applied"] is False


def test_step_4_6_release_record_matches_merge_contract() -> None:
    config = load_config()
    release_record = config["step_4_6_release"]

    assert release_record["status"] == "PASS"
    assert release_record["release_tag"] == EXPECTED_TAG
    assert release_record["source_head"] == ("ebece51619e3ae49864405efe7a0b38d9b58651f")
    assert release_record["develop_baseline"] == ("d735856ca19a32cb418a3dfd634b14fafcafc856")
    assert release_record["merge_commit"] == EXPECTED_MERGE_COMMIT
    assert release_record["merge_strategy"] == "no_ff"
    assert release_record["atomic_remote_push_required"] is True
    assert release_record["final_panel_sha256"] == EXPECTED_FINAL_SHA256
    assert release_record["final_panel_git_tracked"] is False


def test_status_preserves_milestone_4_release_after_later_advancement() -> None:
    status = (REPO / "STATUS.md").read_text(encoding="utf-8")

    assert "MILESTONE4_STRUCTURED_X=COMPLETE" in status
    assert "MILESTONE4_RELEASE_TAG_CREATED=YES" in status
    assert "MILESTONE4_RELEASE_STATUS=COMPLETE" in status
    assert f"MILESTONE4_RELEASE={EXPECTED_TAG}" in status
    assert "MILESTONE4_RELEASE_ACTION_STATUS=COMPLETE_STEP_4_6" in status
    assert f"MILESTONE4_RELEASE_MERGE_COMMIT={EXPECTED_MERGE_COMMIT}" in status

    if "PROJECT_STAGE=MILESTONE_4_STRUCTURED_X_COMPLETE" in status:
        assert "NEXT_STEP=" not in status
    else:
        assert "MILESTONE5_STEP_5_0_STATUS=PASS" in status
