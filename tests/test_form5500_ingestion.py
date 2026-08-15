from risk_intelligence.ingestion.form5500 import (
    classify_resource,
    make_plan_id,
    make_sponsor_id,
    normalize_ein,
    normalize_plan_number,
    normalize_sponsor_name,
)


def test_normalize_ein() -> None:
    assert normalize_ein("12-3456789") == "123456789"


def test_normalize_plan_number() -> None:
    assert normalize_plan_number("1") == "001"


def test_normalize_sponsor_name() -> None:
    assert normalize_sponsor_name("  Example   Corp.  ") == "EXAMPLE CORP."


def test_stable_sponsor_id() -> None:
    assert make_sponsor_id("123456789", "EXAMPLE CORP") == "SP-123456789"


def test_stable_plan_id() -> None:
    assert make_plan_id("123456789", "001", "EXAMPLE CORP") == "PL-123456789-001"


def test_classify_schedule_sb_latest() -> None:
    assert (
        classify_resource("2024 Latest Schedule SB f_sch_sb_2024_latest.zip")
        == "schedule_sb_latest"
    )


def test_classify_form5500_latest() -> None:
    assert classify_resource("2024 Latest Form 5500 f_5500_2024_latest.zip") == "form5500_latest"


def test_all_dataset_is_not_selected() -> None:
    assert classify_resource("2024 All Form 5500") is None
