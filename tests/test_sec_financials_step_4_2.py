import pandas as pd
import pytest

from risk_intelligence.features.sec_financials import (
    FactCandidate,
    build_sec_sponsor_year_financials,
    eligible_candidate_facts,
    normalize_cik,
    select_metric_fact,
)


def payload_with_facts():
    return {
        "cik": 1234,
        "entityName": "Example Corp",
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 90,
                                "accn": "old",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            },
                            {
                                "end": "2024-12-31",
                                "val": 100,
                                "accn": "original",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-15",
                            },
                            {
                                "end": "2024-12-31",
                                "val": 101,
                                "accn": "amended",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K/A",
                                "filed": "2025-04-01",
                            },
                            {
                                "end": "2024-12-31",
                                "val": 999,
                                "accn": "future-amendment",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K/A",
                                "filed": "2025-11-01",
                            },
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 50,
                                "accn": "annual",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-15",
                            },
                            {
                                "start": "2024-10-01",
                                "end": "2024-12-31",
                                "val": 10,
                                "accn": "quarter",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-15",
                            },
                        ]
                    }
                },
            }
        },
    }


def test_normalize_cik():
    assert normalize_cik("1234") == "0000001234"
    assert normalize_cik(1234) == "0000001234"


def test_future_amendment_excluded_and_latest_eligible_amendment_selected():
    fact = select_metric_fact(
        payload_with_facts(),
        "total_assets",
        plan_year=2024,
        forecast_cutoff=pd.Timestamp("2025-10-15"),
    )
    assert fact is not None
    assert fact["value"] == 101
    assert fact["accession"] == "amended"
    assert fact["filed_date"] == pd.Timestamp("2025-04-01")


def test_duration_filter_rejects_quarterly_context():
    candidate = FactCandidate("us-gaap", "Revenues", "duration")
    facts = eligible_candidate_facts(
        payload_with_facts(),
        candidate,
        plan_year=2024,
        forecast_cutoff=pd.Timestamp("2025-10-15"),
    )
    assert len(facts) == 1
    assert facts[0]["accession"] == "annual"


def test_build_preserves_sponsor_year_grain_and_missingness():
    skeleton = pd.DataFrame(
        {
            "sponsor_id": ["S1", "S1"],
            "sec_cik": ["1234", "1234"],
            "plan_year": [2024, 2025],
            "forecast_cutoff": ["2025-10-15", "2026-10-15"],
        }
    )
    result = build_sec_sponsor_year_financials(
        skeleton,
        {"0000001234": payload_with_facts()},
    )
    assert len(result) == 2
    assert result.duplicated(["sponsor_id", "plan_year"]).sum() == 0
    assert result.loc[result["plan_year"].eq(2024), "sec_total_assets"].iloc[0] == 101
    assert pd.isna(result.loc[result["plan_year"].eq(2025), "sec_total_assets"].iloc[0])


def test_duplicate_sponsor_year_is_rejected():
    skeleton = pd.DataFrame(
        {
            "sponsor_id": ["S1", "S1"],
            "sec_cik": ["1234", "1234"],
            "plan_year": [2024, 2024],
            "forecast_cutoff": ["2025-10-15", "2025-10-15"],
        }
    )
    with pytest.raises(ValueError, match="Duplicate sponsor-year"):
        build_sec_sponsor_year_financials(
            skeleton,
            {"0000001234": payload_with_facts()},
        )
