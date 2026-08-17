"""Point-in-time market variables for Milestone 4 Step 4.3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

TRANSFORMATION_VERSION = "4.3.0"
TRADING_DAYS_PER_YEAR = 252
REQUIRED_PRICE_OBSERVATIONS = TRADING_DAYS_PER_YEAR + 1

PERIODIC_FORMS = frozenset(
    {
        "10-K",
        "10-K/A",
        "10-KT",
        "10-KT/A",
        "10-Q",
        "10-Q/A",
        "20-F",
        "20-F/A",
        "40-F",
        "40-F/A",
    }
)


@dataclass(frozen=True)
class ShareCandidate:
    taxonomy: str
    concept: str


SHARE_CANDIDATES: tuple[ShareCandidate, ...] = (
    ShareCandidate("dei", "EntityCommonStockSharesOutstanding"),
    ShareCandidate("us-gaap", "CommonStockSharesOutstanding"),
)


def normalize_cik(value: object) -> str:
    """Return a 10-digit numeric SEC CIK."""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    digits = "".join(character for character in text if character.isdigit())
    if not digits or len(digits) > 10:
        raise ValueError(f"Invalid SEC CIK: {value!r}")
    return digits.zfill(10)


def _to_timestamp(value: object) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def normalize_price_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize daily prices to date, close, adjusted_close, and volume."""
    if frame.empty:
        return pd.DataFrame(columns=["date", "close", "adjusted_close", "volume"])

    lookup = {str(column).strip().lower(): column for column in frame.columns}
    if "date" not in lookup or "close" not in lookup:
        raise ValueError("Price history must contain Date and Close columns.")

    adjusted_key = "adj close" if "adj close" in lookup else "adjusted_close"
    adjusted_source = lookup.get(adjusted_key, lookup["close"])
    normalized = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[lookup["date"]], errors="coerce"),
            "close": pd.to_numeric(frame[lookup["close"]], errors="coerce"),
            "adjusted_close": pd.to_numeric(frame[adjusted_source], errors="coerce"),
        }
    )
    if "volume" in lookup:
        normalized["volume"] = pd.to_numeric(frame[lookup["volume"]], errors="coerce")
    else:
        normalized["volume"] = np.nan

    normalized = normalized.dropna(subset=["date", "close", "adjusted_close"])
    normalized = normalized.loc[
        (normalized["close"] > 0) & (normalized["adjusted_close"] > 0)
    ].copy()
    normalized["date"] = normalized["date"].dt.normalize()
    normalized = normalized.sort_values("date").drop_duplicates("date", keep="last")
    return normalized.reset_index(drop=True)


def _candidate_share_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    facts = payload.get("facts", {})
    if not isinstance(facts, dict):
        return rows

    for priority, candidate in enumerate(SHARE_CANDIDATES):
        taxonomy = facts.get(candidate.taxonomy, {})
        if not isinstance(taxonomy, dict):
            continue
        concept = taxonomy.get(candidate.concept, {})
        if not isinstance(concept, dict):
            continue
        units = concept.get("units", {})
        if not isinstance(units, dict):
            continue

        share_units: list[dict[str, Any]] = []
        for unit_name, values in units.items():
            if str(unit_name).strip().lower() != "shares" or not isinstance(values, list):
                continue
            share_units.extend(item for item in values if isinstance(item, dict))

        for item in share_units:
            value = pd.to_numeric(item.get("val"), errors="coerce")
            if pd.isna(value) or float(value) <= 0:
                continue
            filed = _to_timestamp(item.get("filed"))
            period_end = _to_timestamp(item.get("end"))
            form = str(item.get("form", "")).strip()
            if filed is None or period_end is None or form not in PERIODIC_FORMS:
                continue
            rows.append(
                {
                    "shares": float(value),
                    "filed_date": filed,
                    "period_end": period_end,
                    "form": form,
                    "accession": str(item.get("accn", "")).strip(),
                    "taxonomy": candidate.taxonomy,
                    "concept": candidate.concept,
                    "priority": priority,
                }
            )
    return rows


def select_point_in_time_shares(
    payload: dict[str, Any],
    forecast_cutoff: pd.Timestamp,
) -> dict[str, Any] | None:
    """Select the latest eligible shares-outstanding fact known by cutoff."""
    cutoff = pd.Timestamp(forecast_cutoff).normalize()
    eligible = [
        row
        for row in _candidate_share_rows(payload)
        if row["filed_date"] <= cutoff and row["period_end"] <= cutoff
    ]
    if not eligible:
        return None

    eligible.sort(
        key=lambda row: (
            -int(row["period_end"].value),
            -int(row["filed_date"].value),
            int(row["priority"]),
            str(row["accession"]),
        )
    )
    return eligible[0]


def compute_price_features(
    prices: pd.DataFrame,
    forecast_cutoff: pd.Timestamp,
) -> dict[str, Any]:
    """Compute frozen trailing market features using observations available by cutoff."""
    cutoff = pd.Timestamp(forecast_cutoff).normalize()
    normalized = normalize_price_history(prices)
    eligible = normalized.loc[normalized["date"] <= cutoff].copy()

    result: dict[str, Any] = {
        "price_information_date": pd.NaT,
        "close": np.nan,
        "adjusted_close": np.nan,
        "window_start_date": pd.NaT,
        "window_price_observations": 0,
        "equity_return": np.nan,
        "equity_volatility": np.nan,
        "equity_drawdown": np.nan,
    }
    if eligible.empty:
        return result

    eligible = eligible.sort_values("date").reset_index(drop=True)
    result["price_information_date"] = pd.Timestamp(eligible.iloc[-1]["date"]).normalize()
    result["close"] = float(eligible.iloc[-1]["close"])
    result["adjusted_close"] = float(eligible.iloc[-1]["adjusted_close"])

    window = eligible.tail(REQUIRED_PRICE_OBSERVATIONS).reset_index(drop=True)
    result["window_start_date"] = pd.Timestamp(window.iloc[0]["date"]).normalize()
    result["window_price_observations"] = int(len(window))

    if len(window) < REQUIRED_PRICE_OBSERVATIONS:
        return result

    closes = window["adjusted_close"].astype(float)
    first_close = float(closes.iloc[0])
    last_close = float(closes.iloc[-1])
    if first_close <= 0 or last_close <= 0:
        return result

    result["equity_return"] = (last_close / first_close) - 1.0
    log_returns = np.log(closes).diff().dropna()
    if len(log_returns) >= 2:
        result["equity_volatility"] = float(
            log_returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
        )
    running_peak = closes.cummax()
    drawdown = (closes / running_peak) - 1.0
    result["equity_drawdown"] = float(drawdown.min())
    return result


def split_basis_factor(
    split_events: list[dict[str, Any]],
    after_date: pd.Timestamp,
) -> float:
    """Convert historical share units to the provider's current split basis."""
    reference = pd.Timestamp(after_date).normalize()
    factor = 1.0
    for event in split_events:
        event_date = _to_timestamp(event.get("date"))
        ratio = pd.to_numeric(event.get("ratio"), errors="coerce")
        if event_date is None or pd.isna(ratio) or float(ratio) <= 0:
            continue
        if event_date > reference:
            factor *= float(ratio)
    return float(factor)


def _metadata_value(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key, "")
    return "" if value is None else str(value).strip()


def build_market_sponsor_year_features(
    base: pd.DataFrame,
    price_by_cik: dict[str, pd.DataFrame],
    symbol_metadata_by_cik: dict[str, dict[str, Any]],
    companyfacts_by_cik: dict[str, dict[str, Any]],
    split_events_by_cik: dict[str, list[dict[str, Any]]] | None = None,
) -> pd.DataFrame:
    """Build one point-in-time market row for each frozen sponsor-year."""
    required = {"sponsor_id", "sec_cik", "plan_year", "forecast_cutoff"}
    missing = sorted(required - set(base.columns))
    if missing:
        raise ValueError(f"Base frame missing required fields: {missing}")

    rows: list[dict[str, Any]] = []
    split_events_by_cik = split_events_by_cik or {}
    for record in base.itertuples(index=False):
        sponsor_id = str(record.sponsor_id).strip()
        cik = normalize_cik(record.sec_cik)
        plan_year = int(record.plan_year)
        cutoff = pd.Timestamp(record.forecast_cutoff).normalize()
        prices = price_by_cik.get(cik, pd.DataFrame())
        price_features = compute_price_features(prices, cutoff)
        metadata = symbol_metadata_by_cik.get(cik, {})
        shares = select_point_in_time_shares(companyfacts_by_cik.get(cik, {}), cutoff)

        close = price_features["close"]
        market_capitalization = np.nan
        split_factor = np.nan
        split_adjusted_shares = np.nan
        ticker_candidate_count = int(metadata.get("ticker_candidate_count", 0) or 0)
        if shares is not None:
            split_factor = split_basis_factor(
                split_events_by_cik.get(cik, []),
                pd.Timestamp(shares["period_end"]),
            )
            split_adjusted_shares = float(shares["shares"]) * split_factor
        if shares is not None and pd.notna(close) and ticker_candidate_count == 1:
            market_capitalization = float(close) * split_adjusted_shares

        information_dates: list[pd.Timestamp] = []
        price_date = price_features["price_information_date"]
        if pd.notna(price_date):
            information_dates.append(pd.Timestamp(price_date).normalize())
        if shares is not None:
            information_dates.append(pd.Timestamp(shares["filed_date"]).normalize())
        market_information_date = max(information_dates) if information_dates else pd.NaT

        rows.append(
            {
                "sponsor_id": sponsor_id,
                "sec_cik": cik,
                "plan_year": plan_year,
                "forecast_cutoff": cutoff,
                "market_sec_ticker": _metadata_value(metadata, "sec_ticker"),
                "market_sec_exchange": _metadata_value(metadata, "sec_exchange"),
                "market_source_symbol": _metadata_value(metadata, "source_symbol"),
                "market_price_provider": _metadata_value(metadata, "price_provider"),
                "market_price_currency": _metadata_value(metadata, "price_currency"),
                "market_ticker_candidate_count": ticker_candidate_count,
                "market_price_information_date": price_features["price_information_date"],
                "market_information_date": market_information_date,
                "market_close": close,
                "market_adjusted_close": price_features["adjusted_close"],
                "market_window_start_date": price_features["window_start_date"],
                "market_window_price_observations": price_features["window_price_observations"],
                "market_equity_return": price_features["equity_return"],
                "market_equity_volatility": price_features["equity_volatility"],
                "market_equity_drawdown": price_features["equity_drawdown"],
                "market_shares_outstanding": (
                    np.nan if shares is None else float(shares["shares"])
                ),
                "market_shares_split_basis_factor": split_factor,
                "market_shares_split_adjusted": split_adjusted_shares,
                "market_shares_filed_date": (pd.NaT if shares is None else shares["filed_date"]),
                "market_shares_period_end": (pd.NaT if shares is None else shares["period_end"]),
                "market_shares_taxonomy": "" if shares is None else shares["taxonomy"],
                "market_shares_concept": "" if shares is None else shares["concept"],
                "market_shares_form": "" if shares is None else shares["form"],
                "market_shares_accession": "" if shares is None else shares["accession"],
                "market_capitalization": market_capitalization,
                "market_transformation_version": TRANSFORMATION_VERSION,
            }
        )

    output = pd.DataFrame(rows)
    output = output.sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)
    if output.duplicated(["sponsor_id", "plan_year"], keep=False).any():
        raise ValueError("Market feature construction created duplicate sponsor-year rows.")
    return output
