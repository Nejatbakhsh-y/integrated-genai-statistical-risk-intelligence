from __future__ import annotations

from risk_intelligence.features.structured_x_panel import FEATURE_FAMILIES, MODEL_FEATURES


def test_feature_contract_has_exact_four_families() -> None:
    assert set(FEATURE_FAMILIES) == {"pension", "sponsor_financials", "market", "macro"}


def test_feature_contract_has_31_unique_fields() -> None:
    assert len(MODEL_FEATURES) == 31
    assert len(MODEL_FEATURES) == len(set(MODEL_FEATURES))


def test_feature_families_have_expected_sizes() -> None:
    assert {family: len(fields) for family, fields in FEATURE_FAMILIES.items()} == {
        "pension": 10,
        "sponsor_financials": 13,
        "market": 4,
        "macro": 4,
    }


def test_market_and_macro_core_fields_are_frozen() -> None:
    assert FEATURE_FAMILIES["market"] == [
        "market_equity_return",
        "market_equity_volatility",
        "market_equity_drawdown",
        "market_capitalization",
    ]
    assert FEATURE_FAMILIES["macro"] == [
        "macro_interest_rate_10y",
        "macro_inflation_yoy",
        "macro_credit_conditions_nfci",
        "macro_unemployment_rate",
    ]
