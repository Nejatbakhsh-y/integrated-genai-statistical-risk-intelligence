from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "configs" / "structured_x.yaml"


def load_config() -> dict:
    return yaml.safe_load(
        CONFIG_PATH.read_text(
            encoding="utf-8",
        )
    )


def test_structured_x_contract_exists() -> None:
    assert CONFIG_PATH.exists()


def test_structured_x_target_artifact() -> None:
    config = load_config()

    assert config["primary_artifact"]["path"] == "data/processed/sponsor_year_X.parquet"

    assert config["primary_artifact"]["git_tracked"] is False


def test_structured_x_panel_grain() -> None:
    config = load_config()

    assert config["panel"]["grain"] == [
        "sponsor_id",
        "plan_year",
    ]


def test_structured_x_contains_four_data_families() -> None:
    config = load_config()

    assert set(config["data_families"]) == {
        "pension",
        "sponsor_financials",
        "market",
        "macro",
    }


def test_structured_x_temporal_columns_required() -> None:
    config = load_config()

    required = set(config["temporal_integrity"]["required_columns"])

    assert required == {
        "information_date",
        "forecast_cutoff",
    }


def test_structured_x_temporal_rule() -> None:
    config = load_config()

    assert config["temporal_integrity"]["governing_rule"] == "information_date <= forecast_cutoff"


def test_future_information_is_prohibited() -> None:
    config = load_config()

    temporal = config["temporal_integrity"]

    assert temporal["future_information_allowed"] is False
    assert temporal["forward_fill_from_future_allowed"] is False
    assert temporal["retrospective_value_substitution_allowed"] is False


def test_milestone3_crosswalk_contract_frozen() -> None:
    config = load_config()

    crosswalk = config["frozen_inputs"]["sponsor_sec_crosswalk"]

    assert crosswalk["expected_linked_sponsors"] == 729
    assert crosswalk["expected_unique_ciks"] == 729

    assert (
        crosswalk["expected_sha256"] == "264FF2DCD22223B654C122B7EE6F69B23"
        "CEA71A8885937D976C1BBCF8203D55A"
    )


def test_step_4_0_does_not_claim_panel_is_built() -> None:
    config = load_config()

    acceptance = config["step_4_0_acceptance"]

    assert acceptance["structured_x_constructed"] is False
    assert acceptance["forecast_cutoff_policy_frozen"] is False
    assert acceptance["structured_x_contract_frozen"] is True
