import math

import pandas as pd

from risk_intelligence.features.pension_panel import (
    build_pension_sponsor_year_base,
    forecast_cutoff_for_plan_year,
)


def make_linked() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sponsor_id": "SP-A",
                "plan_id": "PL-A1",
                "plan_year": 2020,
                "assets": 100.0,
                "liabilities": 80.0,
                "contributions": 10.0,
                "benefit_payments": 5.0,
                "participants": 100.0,
                "source_file": "a.csv",
                "information_date": "2021-07-01",
            },
            {
                "sponsor_id": "SP-A",
                "plan_id": "PL-A2",
                "plan_year": 2020,
                "assets": 200.0,
                "liabilities": 170.0,
                "contributions": 20.0,
                "benefit_payments": 10.0,
                "participants": 200.0,
                "source_file": "b.csv",
                "information_date": "2021-10-10",
            },
            {
                "sponsor_id": "SP-B",
                "plan_id": "PL-B1",
                "plan_year": 2020,
                "assets": 50.0,
                "liabilities": 60.0,
                "contributions": 2.0,
                "benefit_payments": 1.0,
                "participants": 40.0,
                "source_file": "c.csv",
                "information_date": "2021-10-20",
            },
        ]
    )


def make_crosswalk() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"sponsor_id": "SP-A", "sec_cik": "0000000001"},
            {"sponsor_id": "SP-B", "sec_cik": "0000000002"},
        ]
    )


def test_forecast_cutoff_is_october_15_of_t_plus_1() -> None:
    assert forecast_cutoff_for_plan_year(2020) == pd.Timestamp("2021-10-15")


def test_multi_plan_aggregation_uses_only_point_in_time_available_filings() -> None:
    base, detail = build_pension_sponsor_year_base(
        make_linked(),
        make_crosswalk(),
        cik_column="sec_cik",
    )

    sponsor_a = base.loc[base["sponsor_id"].eq("SP-A")].iloc[0]
    assert sponsor_a["available_plan_count"] == 2
    assert sponsor_a["assets"] == 300.0
    assert sponsor_a["liabilities"] == 250.0
    assert sponsor_a["contributions"] == 30.0
    assert sponsor_a["benefit_payments"] == 15.0
    assert sponsor_a["participants"] == 300.0
    assert sponsor_a["funded_ratio"] == 1.2
    assert bool(sponsor_a["participants_overlap_risk"]) is True
    assert sponsor_a["information_date"] == pd.Timestamp("2021-10-10")
    assert sponsor_a["forecast_cutoff"] == pd.Timestamp("2021-10-15")

    sponsor_b = base.loc[base["sponsor_id"].eq("SP-B")].iloc[0]
    assert sponsor_b["available_plan_count"] == 0
    assert math.isnan(sponsor_b["assets"])
    assert math.isnan(sponsor_b["funded_ratio"])
    assert pd.isna(sponsor_b["information_date"])

    sponsor_b_audit = detail.loc[detail["sponsor_id"].eq("SP-B")].iloc[0]
    assert sponsor_b_audit["late_plan_count"] == 1
    assert bool(sponsor_b_audit["all_linked_plans_available_by_cutoff"]) is False


def test_missing_field_on_an_available_plan_does_not_create_partial_sum() -> None:
    linked = make_linked()
    linked.loc[linked["plan_id"].eq("PL-A2"), "contributions"] = None

    base, _ = build_pension_sponsor_year_base(
        linked,
        make_crosswalk(),
        cik_column="sec_cik",
    )

    sponsor_a = base.loc[base["sponsor_id"].eq("SP-A")].iloc[0]
    assert math.isnan(sponsor_a["contributions"])
    assert sponsor_a["contributions_available_plan_count"] == 1
    assert bool(sponsor_a["contributions_complete"]) is False
    assert sponsor_a["assets"] == 300.0


def test_output_has_no_information_date_after_cutoff() -> None:
    base, _ = build_pension_sponsor_year_base(
        make_linked(),
        make_crosswalk(),
        cik_column="sec_cik",
    )
    observed = base.loc[base["information_date"].notna()]
    assert observed["information_date"].le(observed["forecast_cutoff"]).all()