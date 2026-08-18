from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from risk_intelligence.features.market_panel import (
    REQUIRED_PRICE_OBSERVATIONS,
    build_market_sponsor_year_features,
    compute_price_features,
    select_point_in_time_shares,
)


def make_prices(start: str = "2023-01-02", periods: int = REQUIRED_PRICE_OBSERVATIONS):
    dates = pd.bdate_range(start, periods=periods)
    closes = np.linspace(100.0, 150.0, periods)
    return pd.DataFrame({"Date": dates, "Close": closes, "Adj Close": closes, "Volume": 1_000_000})


def test_price_features_use_exact_252_session_return_window():
    prices = make_prices()
    cutoff = prices.iloc[-1]["Date"]
    result = compute_price_features(prices, cutoff)
    assert result["window_price_observations"] == REQUIRED_PRICE_OBSERVATIONS
    assert result["equity_return"] == pytest.approx(0.5)
    assert result["equity_volatility"] >= 0
    assert result["equity_drawdown"] == pytest.approx(0.0)


def test_return_uses_adjusted_close_but_market_close_stays_regular_close():
    prices = make_prices()
    prices["Close"] = np.linspace(50.0, 75.0, len(prices))
    prices["Adj Close"] = np.linspace(100.0, 200.0, len(prices))
    result = compute_price_features(prices, prices.iloc[-1]["Date"])
    assert result["close"] == pytest.approx(75.0)
    assert result["adjusted_close"] == pytest.approx(200.0)
    assert result["equity_return"] == pytest.approx(1.0)


def test_future_price_is_never_used():
    prices = make_prices()
    cutoff = pd.Timestamp(prices.iloc[-1]["Date"])
    future = pd.DataFrame(
        {
            "Date": [cutoff + pd.Timedelta(days=7)],
            "Close": [9999.0],
            "Adj Close": [9999.0],
            "Volume": [1],
        }
    )
    result = compute_price_features(pd.concat([prices, future], ignore_index=True), cutoff)
    assert result["close"] == pytest.approx(float(prices.iloc[-1]["Close"]))
    assert result["price_information_date"] == cutoff.normalize()


def test_insufficient_history_preserves_missing_trailing_metrics():
    prices = make_prices(periods=100)
    result = compute_price_features(prices, prices.iloc[-1]["Date"])
    assert result["window_price_observations"] == 100
    assert np.isnan(result["equity_return"])
    assert np.isnan(result["equity_volatility"])
    assert np.isnan(result["equity_drawdown"])
    assert result["close"] > 0


def test_share_selection_excludes_post_cutoff_filing():
    payload = {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "val": 100.0,
                                "end": "2024-06-30",
                                "filed": "2024-08-01",
                                "form": "10-Q",
                                "accn": "eligible",
                            },
                            {
                                "val": 200.0,
                                "end": "2024-09-30",
                                "filed": "2024-11-01",
                                "form": "10-Q",
                                "accn": "future",
                            },
                        ]
                    }
                }
            }
        }
    }
    selected = select_point_in_time_shares(payload, pd.Timestamp("2024-10-15"))
    assert selected is not None
    assert selected["shares"] == pytest.approx(100.0)
    assert selected["accession"] == "eligible"


def test_market_frame_preserves_sponsor_year_grain_and_market_cap():
    prices = make_prices()
    cutoff = pd.Timestamp(prices.iloc[-1]["Date"])
    base = pd.DataFrame(
        {
            "sponsor_id": ["S1"],
            "sec_cik": ["123"],
            "plan_year": [2023],
            "forecast_cutoff": [cutoff],
        }
    )
    payload = {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "val": 1_000_000.0,
                                "end": cutoff.date().isoformat(),
                                "filed": cutoff.date().isoformat(),
                                "form": "10-Q",
                                "accn": "a",
                            }
                        ]
                    }
                }
            }
        }
    }
    frame = build_market_sponsor_year_features(
        base,
        {"0000000123": prices},
        {
            "0000000123": {
                "sec_ticker": "ABC",
                "sec_exchange": "Nasdaq",
                "source_symbol": "ABC",
                "price_provider": "YAHOO_FINANCE_CHART",
                "price_currency": "USD",
                "ticker_candidate_count": 1,
            }
        },
        {"0000000123": payload},
    )
    assert len(frame) == 1
    assert frame.loc[0, "market_capitalization"] == pytest.approx(150_000_000.0)
    assert frame.loc[0, "market_information_date"] <= cutoff


def test_market_cap_split_basis_normalization_preserves_economic_units():
    prices = make_prices()
    prices["Close"] = 75.0
    prices["Adj Close"] = 75.0
    cutoff = pd.Timestamp(prices.iloc[-1]["Date"])
    base = pd.DataFrame(
        {
            "sponsor_id": ["S1"],
            "sec_cik": ["123"],
            "plan_year": [2023],
            "forecast_cutoff": [cutoff],
        }
    )
    payload = {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "val": 1_000_000.0,
                                "end": cutoff.date().isoformat(),
                                "filed": cutoff.date().isoformat(),
                                "form": "10-Q",
                                "accn": "a",
                            }
                        ]
                    }
                }
            }
        }
    }
    frame = build_market_sponsor_year_features(
        base,
        {"0000000123": prices},
        {
            "0000000123": {
                "sec_ticker": "ABC",
                "sec_exchange": "Nasdaq",
                "source_symbol": "ABC",
                "price_provider": "YAHOO_FINANCE_CHART",
                "price_currency": "USD",
                "ticker_candidate_count": 1,
            }
        },
        {"0000000123": payload},
        {"0000000123": [{"date": cutoff + pd.Timedelta(days=30), "ratio": 2.0}]},
    )
    assert frame.loc[0, "market_shares_split_basis_factor"] == pytest.approx(2.0)
    assert frame.loc[0, "market_shares_split_adjusted"] == pytest.approx(2_000_000.0)
    assert frame.loc[0, "market_capitalization"] == pytest.approx(150_000_000.0)
