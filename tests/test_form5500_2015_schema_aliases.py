"""Regression tests for historical Form 5500 schema aliases."""

from risk_intelligence.ingestion.form5500 import (
    I_ALIASES,
    MAIN_ALIASES,
    SB_ALIASES,
    choose_column,
)


def test_2015_main_form_aliases() -> None:
    assert choose_column(["SPONS_DFE_PN"], MAIN_ALIASES["plan_number_raw"]) == "SPONS_DFE_PN"
    assert (
        choose_column(["SPONSOR_DFE_NAME"], MAIN_ALIASES["sponsor_name_raw"]) == "SPONSOR_DFE_NAME"
    )


def test_2015_schedule_sb_aliases() -> None:
    assert (
        choose_column(["SB_ACTRL_VALUE_AST_AMT"], SB_ALIASES["sb_assets"])
        == "SB_ACTRL_VALUE_AST_AMT"
    )
    assert (
        choose_column(["SB_TOT_FNDNG_TGT_AMT"], SB_ALIASES["sb_liabilities"])
        == "SB_TOT_FNDNG_TGT_AMT"
    )
    assert (
        choose_column(
            ["SB_TOT_EMPLR_CONTRIB_AMT"],
            SB_ALIASES["sb_contributions"],
        )
        == "SB_TOT_EMPLR_CONTRIB_AMT"
    )


def test_2015_schedule_i_aliases() -> None:
    assert (
        choose_column(
            ["SMALL_TOT_ASSETS_EOY_AMT"],
            I_ALIASES["i_assets"],
        )
        == "SMALL_TOT_ASSETS_EOY_AMT"
    )
    assert (
        choose_column(
            ["SMALL_TOT_LIABILITIES_EOY_AMT"],
            I_ALIASES["i_liabilities"],
        )
        == "SMALL_TOT_LIABILITIES_EOY_AMT"
    )
