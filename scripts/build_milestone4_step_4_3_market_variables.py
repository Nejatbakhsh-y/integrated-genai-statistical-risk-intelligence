"""Build and audit Milestone-4 Step-4.3 point-in-time market variables."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

from risk_intelligence.features.market_panel import (
    REQUIRED_PRICE_OBSERVATIONS,
    TRANSFORMATION_VERSION,
    build_market_sponsor_year_features,
    normalize_cik,
    normalize_price_history,
)

EXPECTED_SPONSOR_YEARS = 5_934
EXPECTED_LINKED_SPONSORS = 729
EXPECTED_UNIQUE_CIKS = 729
EXPECTED_YEAR_START = 2015
EXPECTED_YEAR_END = 2024
EXPECTED_CUTOFF_MONTH = 10
EXPECTED_CUTOFF_DAY = 15
EXPECTED_STEP_4_2_SHA256 = "09F93E43AA169CE95A7AF98E923C0E6FF6DFEEE8E987564A90E9A86BD7EC7883"
SEC_TICKER_REFERENCE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
YAHOO_CHART_TEMPLATE = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
PRICE_START_DATE = "2015-01-01"
PRICE_END_EXCLUSIVE = "2026-08-18"
SEC_REQUEST_INTERVAL_SECONDS = 0.15
MARKET_REQUEST_INTERVAL_SECONDS = 0.20
MAX_ATTEMPTS = 6
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def validate_user_agent(user_agent: str) -> str:
    value = user_agent.strip()
    if not value or "@" not in value or len(value) < 8:
        raise RuntimeError(
            "SEC User-Agent must identify the requester and include a contact email address."
        )
    return value


def wait_for_interval(request_state: dict[str, float], interval: float) -> None:
    elapsed = time.monotonic() - request_state["last_request"]
    if elapsed < interval:
        time.sleep(interval - elapsed)


def fetch_json_reference(
    session: requests.Session,
    *,
    url: str,
    cache_path: Path,
    refresh: bool,
    request_state: dict[str, float],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if cache_path.exists() and not refresh:
        content = cache_path.read_bytes()
        payload = json.loads(content.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"Malformed cached SEC reference JSON: {cache_path}")
        return payload, {
            "endpoint": url,
            "source_status": "CACHE",
            "http_status": 200,
            "bytes": len(content),
            "sha256": sha256_bytes(content),
        }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        wait_for_interval(request_state, SEC_REQUEST_INTERVAL_SECONDS)
        try:
            response = session.get(url, timeout=(15, 90))
        except requests.RequestException as exc:
            if attempt >= MAX_ATTEMPTS:
                raise RuntimeError(f"SEC ticker-reference request failed: {exc}") from exc
            time.sleep(min(2 ** (attempt - 1), 16))
            continue
        finally:
            request_state["last_request"] = time.monotonic()

        if response.status_code == 200:
            content = response.content
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("SEC ticker reference returned non-JSON content.") from exc
            if not isinstance(payload, dict):
                raise RuntimeError("SEC ticker reference returned malformed JSON.")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(cache_path.suffix + ".part")
            temporary.write_bytes(content)
            temporary.replace(cache_path)
            return payload, {
                "endpoint": url,
                "source_status": "HTTP_200",
                "http_status": 200,
                "bytes": len(content),
                "sha256": sha256_bytes(content),
            }

        if response.status_code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
            time.sleep(min(2 ** (attempt - 1), 30))
            continue
        raise RuntimeError(f"SEC ticker-reference request failed: HTTP {response.status_code}.")

    raise RuntimeError("SEC ticker-reference request exhausted retries.")


def parse_sec_ticker_reference(payload: dict[str, Any]) -> pd.DataFrame:
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise RuntimeError("SEC ticker-reference JSON lacks fields/data arrays.")
    names = [str(value).strip().lower() for value in fields]
    required = {"name", "cik", "ticker", "exchange"}
    if not required.issubset(names):
        raise RuntimeError(f"Unexpected SEC ticker-reference fields: {fields}")

    rows: list[dict[str, Any]] = []
    for values in data:
        if not isinstance(values, list) or len(values) != len(names):
            continue
        record = dict(zip(names, values, strict=True))
        try:
            cik = normalize_cik(record.get("cik"))
        except ValueError:
            continue
        ticker = str(record.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        rows.append(
            {
                "sec_cik": cik,
                "sec_entity_name": str(record.get("name", "")).strip(),
                "sec_ticker": ticker,
                "sec_exchange": str(record.get("exchange", "")).strip(),
            }
        )
    if not rows:
        raise RuntimeError("SEC ticker-reference JSON produced zero ticker associations.")
    return pd.DataFrame(rows)


def build_target_ticker_mapping(
    reference: pd.DataFrame,
    target_ciks: list[str],
) -> tuple[dict[str, list[dict[str, Any]]], pd.DataFrame]:
    target_set = set(target_ciks)
    subset = reference.loc[reference["sec_cik"].isin(target_set)].copy()
    subset["ticker_length"] = subset["sec_ticker"].str.len()
    subset = subset.sort_values(
        ["sec_cik", "ticker_length", "sec_ticker", "sec_exchange"],
        kind="mergesort",
    )
    subset = subset.drop_duplicates(["sec_cik", "sec_ticker"], keep="first")

    mapping: dict[str, list[dict[str, Any]]] = {cik: [] for cik in target_ciks}
    rows: list[dict[str, Any]] = []
    for cik in target_ciks:
        group = subset.loc[subset["sec_cik"].eq(cik)].copy()
        if group.empty:
            rows.append(
                {
                    "sec_cik": cik,
                    "candidate_rank": 0,
                    "sec_entity_name": "",
                    "sec_ticker": "",
                    "sec_exchange": "",
                    "mapping_status": "NO_SEC_TICKER_ASSOCIATION",
                }
            )
            continue
        for rank, item in enumerate(group.itertuples(index=False), start=1):
            candidate = {
                "sec_cik": cik,
                "sec_entity_name": str(item.sec_entity_name),
                "sec_ticker": str(item.sec_ticker),
                "sec_exchange": str(item.sec_exchange),
                "candidate_rank": rank,
            }
            mapping[cik].append(candidate)
            rows.append({**candidate, "mapping_status": "SEC_ASSOCIATION_AVAILABLE"})
    return mapping, pd.DataFrame(rows)


def yahoo_symbols_for_ticker(ticker: str) -> list[str]:
    value = ticker.strip().upper()
    if not value:
        return []
    transformed = value.replace(".", "-").replace("/", "-")
    symbols: list[str] = []
    for symbol in [transformed, value]:
        clean = symbol.strip()
        if clean and clean not in symbols:
            symbols.append(clean)
    return symbols


def _epoch_seconds(date_text: str) -> int:
    value = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=UTC)
    return int(value.timestamp())


def parse_yahoo_chart(
    payload: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise RuntimeError("Yahoo Finance chart response lacks a chart object.")

    error = chart.get("error")
    results = chart.get("result")
    if error and not results:
        description = str(error.get("description", "")) if isinstance(error, dict) else str(error)
        lowered = description.lower()
        if "not found" in lowered or "no data" in lowered or "delisted" in lowered:
            return (
                pd.DataFrame(),
                {
                    "price_currency": "",
                    "provider_symbol": "",
                    "provider_exchange": "",
                    "provider_error": description,
                },
                [],
            )
        raise RuntimeError(f"Yahoo Finance chart error: {description}")

    if not isinstance(results, list) or not results:
        return (
            pd.DataFrame(),
            {
                "price_currency": "",
                "provider_symbol": "",
                "provider_exchange": "",
                "provider_error": "NO_RESULT",
            },
            [],
        )

    result = results[0]
    if not isinstance(result, dict):
        raise RuntimeError("Yahoo Finance chart result is malformed.")
    timestamps = result.get("timestamp")
    indicators = result.get("indicators", {})
    quotes = indicators.get("quote", []) if isinstance(indicators, dict) else []
    adjusted = indicators.get("adjclose", []) if isinstance(indicators, dict) else []
    if (
        not isinstance(timestamps, list)
        or not timestamps
        or not isinstance(quotes, list)
        or not quotes
    ):
        return (
            pd.DataFrame(),
            {
                "price_currency": "",
                "provider_symbol": "",
                "provider_exchange": "",
                "provider_error": "NO_DAILY_QUOTES",
            },
            [],
        )

    quote_values = quotes[0] if isinstance(quotes[0], dict) else {}
    close_values = quote_values.get("close", [])
    volume_values = quote_values.get("volume", [])
    adjusted_values: list[Any] = []
    if isinstance(adjusted, list) and adjusted and isinstance(adjusted[0], dict):
        candidate = adjusted[0].get("adjclose", [])
        if isinstance(candidate, list):
            adjusted_values = candidate
    if not adjusted_values:
        adjusted_values = close_values

    length = len(timestamps)
    if len(close_values) != length or len(adjusted_values) != length:
        raise RuntimeError("Yahoo Finance chart arrays have inconsistent lengths.")
    if len(volume_values) != length:
        volume_values = [None] * length

    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None),
            "Close": close_values,
            "Adj Close": adjusted_values,
            "Volume": volume_values,
        }
    )
    meta = result.get("meta", {}) if isinstance(result.get("meta", {}), dict) else {}
    metadata = {
        "price_currency": str(meta.get("currency", "")).strip().upper(),
        "provider_symbol": str(meta.get("symbol", "")).strip(),
        "provider_exchange": str(meta.get("exchangeName", "")).strip(),
        "provider_error": "",
    }
    split_events: list[dict[str, Any]] = []
    events = result.get("events", {}) if isinstance(result.get("events", {}), dict) else {}
    splits = events.get("splits", {}) if isinstance(events, dict) else {}
    if isinstance(splits, dict):
        for item in splits.values():
            if not isinstance(item, dict):
                continue
            event_date = pd.to_datetime(item.get("date"), unit="s", utc=True, errors="coerce")
            numerator = pd.to_numeric(item.get("numerator"), errors="coerce")
            denominator = pd.to_numeric(item.get("denominator"), errors="coerce")
            if pd.isna(event_date) or pd.isna(numerator) or pd.isna(denominator):
                continue
            if float(numerator) <= 0 or float(denominator) <= 0:
                continue
            split_events.append(
                {
                    "date": pd.Timestamp(event_date).tz_convert(None).normalize(),
                    "ratio": float(numerator) / float(denominator),
                }
            )
    split_events.sort(key=lambda item: item["date"])
    return normalize_price_history(frame), metadata, split_events


def fetch_yahoo_history(
    session: requests.Session,
    *,
    symbol: str,
    cache_path: Path,
    refresh: bool,
    request_state: dict[str, float],
) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    url = YAHOO_CHART_TEMPLATE.format(symbol=quote(symbol, safe="-._"))
    params = {
        "period1": _epoch_seconds(PRICE_START_DATE),
        "period2": _epoch_seconds(PRICE_END_EXCLUSIVE),
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    }
    endpoint = str(requests.Request("GET", url, params=params).prepare().url)

    if cache_path.exists() and not refresh:
        content = cache_path.read_bytes()
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Malformed cached Yahoo Finance JSON: {cache_path}") from exc
        frame, metadata, split_events = parse_yahoo_chart(payload)
        if not frame.empty and metadata["price_currency"] == "USD":
            return (
                frame,
                {
                    "price_provider": "YAHOO_FINANCE_CHART",
                    "endpoint": endpoint,
                    "source_status": "CACHE",
                    "http_status": 200,
                    "bytes": len(content),
                    "sha256": sha256_bytes(content),
                    "price_rows": int(len(frame)),
                    "min_date": frame["date"].min().date().isoformat(),
                    "max_date": frame["date"].max().date().isoformat(),
                    **metadata,
                },
                split_events,
            )
        cache_path.unlink(missing_ok=True)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        wait_for_interval(request_state, MARKET_REQUEST_INTERVAL_SECONDS)
        try:
            response = session.get(url, params=params, timeout=(15, 90))
        except requests.RequestException as exc:
            if attempt >= MAX_ATTEMPTS:
                raise RuntimeError(f"Yahoo Finance request failed for {symbol}: {exc}") from exc
            time.sleep(min(2 ** (attempt - 1), 16))
            continue
        finally:
            request_state["last_request"] = time.monotonic()

        if response.status_code in {404, 422}:
            return (
                pd.DataFrame(),
                {
                    "price_provider": "YAHOO_FINANCE_CHART",
                    "endpoint": endpoint,
                    "source_status": f"HTTP_{response.status_code}_NO_DATA",
                    "http_status": int(response.status_code),
                    "bytes": len(response.content),
                    "sha256": sha256_bytes(response.content),
                    "price_rows": 0,
                    "min_date": "",
                    "max_date": "",
                    "price_currency": "",
                    "provider_symbol": symbol,
                    "provider_exchange": "",
                    "provider_error": "NO_DATA",
                },
                [],
            )

        if response.status_code == 200:
            content = response.content
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError(
                    f"Yahoo Finance returned non-JSON history for {symbol}."
                ) from exc
            if not isinstance(payload, dict):
                raise RuntimeError(f"Yahoo Finance returned malformed history for {symbol}.")
            frame, metadata, split_events = parse_yahoo_chart(payload)
            currency = metadata["price_currency"]
            if frame.empty:
                return (
                    frame,
                    {
                        "price_provider": "YAHOO_FINANCE_CHART",
                        "endpoint": endpoint,
                        "source_status": "HTTP_200_NO_DATA",
                        "http_status": 200,
                        "bytes": len(content),
                        "sha256": sha256_bytes(content),
                        "price_rows": 0,
                        "min_date": "",
                        "max_date": "",
                        **metadata,
                    },
                    split_events,
                )
            if currency != "USD":
                return (
                    pd.DataFrame(),
                    {
                        "price_provider": "YAHOO_FINANCE_CHART",
                        "endpoint": endpoint,
                        "source_status": "HTTP_200_NON_USD_EXCLUDED",
                        "http_status": 200,
                        "bytes": len(content),
                        "sha256": sha256_bytes(content),
                        "price_rows": int(len(frame)),
                        "min_date": frame["date"].min().date().isoformat(),
                        "max_date": frame["date"].max().date().isoformat(),
                        **metadata,
                    },
                    split_events,
                )

            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(cache_path.suffix + ".part")
            temporary.write_bytes(content)
            temporary.replace(cache_path)
            return (
                frame,
                {
                    "price_provider": "YAHOO_FINANCE_CHART",
                    "endpoint": endpoint,
                    "source_status": "HTTP_200",
                    "http_status": 200,
                    "bytes": len(content),
                    "sha256": sha256_bytes(content),
                    "price_rows": int(len(frame)),
                    "min_date": frame["date"].min().date().isoformat(),
                    "max_date": frame["date"].max().date().isoformat(),
                    **metadata,
                },
                split_events,
            )

        if response.status_code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after is not None else 2 ** (attempt - 1)
            except ValueError:
                delay = 2 ** (attempt - 1)
            time.sleep(min(max(delay, 1.0), 30.0))
            continue
        raise RuntimeError(
            f"Yahoo Finance request failed for {symbol}: HTTP {response.status_code}."
        )

    raise RuntimeError(f"Yahoo Finance request exhausted retries for {symbol}.")


def validate_step_4_2_base(base: pd.DataFrame) -> pd.DataFrame:
    required = {"sponsor_id", "sec_cik", "plan_year", "forecast_cutoff"}
    missing = sorted(required - set(base.columns))
    if missing:
        raise RuntimeError(f"Step-4.2 base missing required fields: {missing}")

    work = base.copy()
    work["sponsor_id"] = work["sponsor_id"].astype("string").str.strip()
    work["sec_cik"] = work["sec_cik"].map(normalize_cik).astype("string")
    work["plan_year"] = pd.to_numeric(work["plan_year"], errors="raise").astype(int)
    work["forecast_cutoff"] = pd.to_datetime(work["forecast_cutoff"], errors="raise").dt.normalize()

    checks = {
        "sponsor_year_rows": (int(len(work)), EXPECTED_SPONSOR_YEARS),
        "unique_sponsors": (int(work["sponsor_id"].nunique()), EXPECTED_LINKED_SPONSORS),
        "unique_ciks": (int(work["sec_cik"].nunique()), EXPECTED_UNIQUE_CIKS),
        "plan_year_start": (int(work["plan_year"].min()), EXPECTED_YEAR_START),
        "plan_year_end": (int(work["plan_year"].max()), EXPECTED_YEAR_END),
        "duplicate_sponsor_year_rows": (
            int(work.duplicated(["sponsor_id", "plan_year"], keep=False).sum()),
            0,
        ),
    }
    for name, (actual, expected) in checks.items():
        if actual != expected:
            raise RuntimeError(f"Step-4.2 handoff drift: {name}={actual}; expected={expected}")

    expected_cutoff = pd.to_datetime(
        {
            "year": work["plan_year"] + 1,
            "month": EXPECTED_CUTOFF_MONTH,
            "day": EXPECTED_CUTOFF_DAY,
        }
    )
    mismatch = int(work["forecast_cutoff"].ne(expected_cutoff).sum())
    if mismatch:
        raise RuntimeError(f"Frozen forecast_cutoff drift: mismatch_rows={mismatch}")
    return work.sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)


def load_companyfacts(raw_dir: Path, target_ciks: list[str]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for cik in target_ciks:
        path = raw_dir / f"CIK{cik}.json"
        if not path.exists():
            payloads[cik] = {}
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"Malformed cached Company Facts JSON: {path}")
        payloads[cik] = payload
    return payloads


def build_temporal_audit(market: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    rows: list[dict[str, Any]] = []
    total_violations = 0
    date_columns = (
        "market_price_information_date",
        "market_information_date",
        "market_shares_filed_date",
        "market_shares_period_end",
    )
    for record in market.itertuples(index=False):
        values = record._asdict()
        cutoff = pd.Timestamp(values["forecast_cutoff"]).normalize()
        violations = 0
        for column in date_columns:
            value = values[column]
            if pd.isna(value):
                continue
            if pd.Timestamp(value).normalize() > cutoff:
                violations += 1
        total_violations += violations
        rows.append(
            {
                "sponsor_id": values["sponsor_id"],
                "sec_cik": values["sec_cik"],
                "plan_year": int(values["plan_year"]),
                "forecast_cutoff": cutoff.date().isoformat(),
                "market_price_information_date": (
                    ""
                    if pd.isna(values["market_price_information_date"])
                    else pd.Timestamp(values["market_price_information_date"]).date().isoformat()
                ),
                "market_shares_filed_date": (
                    ""
                    if pd.isna(values["market_shares_filed_date"])
                    else pd.Timestamp(values["market_shares_filed_date"]).date().isoformat()
                ),
                "temporal_violation_count": violations,
                "status": "PASS" if violations == 0 else "FAIL",
            }
        )
    return pd.DataFrame(rows), total_violations


def build_missingness_audit(joined: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "market_close",
        "market_equity_return",
        "market_equity_volatility",
        "market_equity_drawdown",
        "market_shares_outstanding",
        "market_capitalization",
    ]
    rows: list[dict[str, Any]] = []
    for field in fields:
        missing_count = int(joined[field].isna().sum())
        rows.append(
            {
                "field": field,
                "sponsor_year_rows": int(len(joined)),
                "missing_count": missing_count,
                "nonmissing_count": int(len(joined) - missing_count),
                "missing_rate": float(missing_count / len(joined)),
            }
        )
    return pd.DataFrame(rows)


def build_coverage_by_year(joined: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    fields = [
        "market_close",
        "market_equity_return",
        "market_equity_volatility",
        "market_equity_drawdown",
        "market_capitalization",
    ]
    for plan_year, group in joined.groupby("plan_year", sort=True):
        row: dict[str, Any] = {
            "plan_year": int(plan_year),
            "sponsor_year_rows": int(len(group)),
        }
        for field in fields:
            row[f"{field}_nonmissing"] = int(group[field].notna().sum())
        rows.append(row)
    return pd.DataFrame(rows)


def validate_market_values(market: pd.DataFrame) -> None:
    numeric_fields = [
        "market_close",
        "market_equity_return",
        "market_equity_volatility",
        "market_equity_drawdown",
        "market_shares_outstanding",
        "market_capitalization",
    ]
    for field in numeric_fields:
        values = pd.to_numeric(market[field], errors="coerce")
        observed = values.dropna()
        if not np.isfinite(observed.to_numpy()).all():
            raise RuntimeError(f"Non-finite values detected in {field}.")
    volatility = market["market_equity_volatility"].dropna()
    if (volatility < 0).any():
        raise RuntimeError("Negative annualized market volatility detected.")
    drawdown = market["market_equity_drawdown"].dropna()
    if ((drawdown > 1e-12) | (drawdown < -1.0000001)).any():
        raise RuntimeError("Market drawdown lies outside the frozen [-1, 0] range.")
    market_cap = market["market_capitalization"].dropna()
    if (market_cap <= 0).any():
        raise RuntimeError("Nonpositive market capitalization detected.")


def main() -> None:
    args = parse_args()
    repo = Path(args.repo).resolve()
    user_agent = validate_user_agent(args.user_agent)

    step_4_2_path = (
        repo
        / "data"
        / "interim"
        / "structured_x"
        / "step_4_2"
        / "pension_sec_sponsor_year_base.parquet"
    )
    step_4_2_audit_path = (
        repo / "reports" / "validation" / "milestone4_step_4_2_sec_ingestion_audit.json"
    )
    raw_companyfacts_dir = repo / "data" / "raw" / "sec_xbrl" / "companyfacts"
    raw_sec_reference_dir = repo / "data" / "raw" / "sec_reference"
    raw_market_dir = repo / "data" / "raw" / "market" / "yahoo_finance"
    ticker_reference_path = raw_sec_reference_dir / "company_tickers_exchange.json"
    output_dir = repo / "data" / "interim" / "structured_x" / "step_4_3"
    market_output_path = output_dir / "market_sponsor_year_features.parquet"
    joined_output_path = output_dir / "pension_sec_market_sponsor_year_base.parquet"

    validation_dir = repo / "reports" / "validation"
    tables_dir = repo / "reports" / "tables"
    ticker_mapping_path = validation_dir / "milestone4_step_4_3_sec_ticker_mapping.csv"
    raw_manifest_path = validation_dir / "milestone4_step_4_3_market_raw_manifest.csv"
    temporal_path = validation_dir / "milestone4_step_4_3_temporal_audit.csv"
    missingness_path = validation_dir / "milestone4_step_4_3_market_missingness.csv"
    audit_path = validation_dir / "milestone4_step_4_3_market_ingestion_audit.json"
    coverage_path = tables_dir / "milestone4_step_4_3_market_coverage_by_year.csv"

    for directory in [
        raw_sec_reference_dir,
        raw_market_dir,
        output_dir,
        validation_dir,
        tables_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    if not step_4_2_path.exists():
        raise RuntimeError(f"Missing frozen Step-4.2 artifact: {step_4_2_path}")
    if not step_4_2_audit_path.exists():
        raise RuntimeError(f"Missing Step-4.2 audit: {step_4_2_audit_path}")

    step_4_2_sha256 = sha256_file(step_4_2_path)
    if step_4_2_sha256 != EXPECTED_STEP_4_2_SHA256:
        raise RuntimeError(
            "Step-4.2 joined artifact hash drift: "
            f"{step_4_2_sha256}; expected {EXPECTED_STEP_4_2_SHA256}"
        )
    step_4_2_audit = json.loads(step_4_2_audit_path.read_text(encoding="utf-8"))
    if step_4_2_audit.get("step_4_2_status") != "PASS":
        raise RuntimeError("Step-4.2 audit does not report PASS.")
    if str(step_4_2_audit.get("joined_artifact_sha256", "")) != step_4_2_sha256:
        raise RuntimeError("Step-4.2 audit hash does not match the frozen joined artifact.")

    base = validate_step_4_2_base(pd.read_parquet(step_4_2_path))
    target_ciks = sorted(set(base["sec_cik"].astype(str)))
    if len(target_ciks) != EXPECTED_UNIQUE_CIKS:
        raise RuntimeError(f"Expected {EXPECTED_UNIQUE_CIKS} CIKs; found {len(target_ciks)}")

    sec_session = requests.Session()
    sec_session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }
    )
    sec_request_state = {"last_request": 0.0}
    ticker_payload, ticker_source = fetch_json_reference(
        sec_session,
        url=SEC_TICKER_REFERENCE_URL,
        cache_path=ticker_reference_path,
        refresh=bool(args.refresh),
        request_state=sec_request_state,
    )
    ticker_reference = parse_sec_ticker_reference(ticker_payload)
    ticker_mapping, ticker_audit = build_target_ticker_mapping(ticker_reference, target_ciks)
    ticker_audit.to_csv(ticker_mapping_path, index=False, lineterminator="\n")

    market_session = requests.Session()
    market_session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Encoding": "gzip, deflate",
        }
    )
    market_request_state = {"last_request": 0.0}
    price_by_cik: dict[str, pd.DataFrame] = {}
    split_events_by_cik: dict[str, list[dict[str, Any]]] = {}
    symbol_metadata_by_cik: dict[str, dict[str, Any]] = {}
    raw_manifest_rows: list[dict[str, Any]] = []
    attempt_sequence = 0

    for cik in target_ciks:
        candidates = ticker_mapping.get(cik, [])
        ticker_candidate_count = len(candidates)
        if not candidates:
            raw_manifest_rows.append(
                {
                    "attempt_sequence": 0,
                    "sec_cik": cik,
                    "sec_ticker": "",
                    "sec_exchange": "",
                    "source_symbol": "",
                    "price_provider": "YAHOO_FINANCE_CHART",
                    "selected_for_cik": False,
                    "source_status": "NO_SEC_TICKER_ASSOCIATION",
                    "http_status": 0,
                    "endpoint": "",
                    "bytes": 0,
                    "sha256": "",
                    "price_rows": 0,
                    "min_date": "",
                    "max_date": "",
                    "price_currency": "",
                    "provider_symbol": "",
                    "provider_exchange": "",
                    "provider_error": "",
                }
            )
            price_by_cik[cik] = pd.DataFrame()
            split_events_by_cik[cik] = []
            symbol_metadata_by_cik[cik] = {"ticker_candidate_count": 0}
            continue

        selected = False
        for candidate in candidates:
            for source_symbol in yahoo_symbols_for_ticker(candidate["sec_ticker"]):
                attempt_sequence += 1
                safe_symbol = "".join(
                    char if char.isalnum() or char in "._-" else "_" for char in source_symbol
                )
                cache_path = raw_market_dir / f"CIK{cik}_{safe_symbol}.json"
                frame, manifest, split_events = fetch_yahoo_history(
                    market_session,
                    symbol=source_symbol,
                    cache_path=cache_path,
                    refresh=bool(args.refresh),
                    request_state=market_request_state,
                )
                selected_for_cik = not frame.empty
                raw_manifest_rows.append(
                    {
                        "attempt_sequence": attempt_sequence,
                        "sec_cik": cik,
                        "sec_ticker": candidate["sec_ticker"],
                        "sec_exchange": candidate["sec_exchange"],
                        "source_symbol": source_symbol,
                        "selected_for_cik": selected_for_cik,
                        **manifest,
                    }
                )
                if selected_for_cik:
                    price_by_cik[cik] = frame
                    split_events_by_cik[cik] = split_events
                    symbol_metadata_by_cik[cik] = {
                        "sec_ticker": candidate["sec_ticker"],
                        "sec_exchange": candidate["sec_exchange"],
                        "source_symbol": source_symbol,
                        "price_provider": manifest["price_provider"],
                        "price_currency": manifest["price_currency"],
                        "ticker_candidate_count": ticker_candidate_count,
                    }
                    selected = True
                    break
            if selected:
                break
        if not selected:
            price_by_cik[cik] = pd.DataFrame()
            split_events_by_cik[cik] = []
            symbol_metadata_by_cik[cik] = {
                "sec_ticker": candidates[0]["sec_ticker"],
                "sec_exchange": candidates[0]["sec_exchange"],
                "source_symbol": "",
                "price_provider": "YAHOO_FINANCE_CHART",
                "price_currency": "",
                "ticker_candidate_count": ticker_candidate_count,
            }

    raw_manifest = pd.DataFrame(raw_manifest_rows)
    raw_manifest.to_csv(raw_manifest_path, index=False, lineterminator="\n")

    companyfacts_by_cik = load_companyfacts(raw_companyfacts_dir, target_ciks)
    market = build_market_sponsor_year_features(
        base,
        price_by_cik,
        symbol_metadata_by_cik,
        companyfacts_by_cik,
        split_events_by_cik,
    )
    if len(market) != EXPECTED_SPONSOR_YEARS:
        raise RuntimeError(f"Market frame changed sponsor-year row count: {len(market)}")
    market.to_parquet(market_output_path, index=False)

    join_keys = ["sponsor_id", "sec_cik", "plan_year", "forecast_cutoff"]
    joined = base.merge(market, on=join_keys, how="left", validate="one_to_one", sort=False)
    joined = joined.sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)
    if len(joined) != EXPECTED_SPONSOR_YEARS:
        raise RuntimeError(f"Step-4.3 join changed sponsor-year row count: {len(joined)}")
    if joined.duplicated(["sponsor_id", "plan_year"], keep=False).any():
        raise RuntimeError("Step-4.3 join created duplicate sponsor-year rows.")
    joined.to_parquet(joined_output_path, index=False)

    temporal_audit, temporal_violations = build_temporal_audit(market)
    temporal_audit.to_csv(temporal_path, index=False, lineterminator="\n")
    if temporal_violations != 0 or not temporal_audit["status"].eq("PASS").all():
        raise RuntimeError(f"Step-4.3 temporal audit failed: violations={temporal_violations}")

    validate_market_values(market)
    missingness = build_missingness_audit(joined)
    missingness.to_csv(missingness_path, index=False, lineterminator="\n")
    coverage = build_coverage_by_year(joined)
    coverage.to_csv(coverage_path, index=False, lineterminator="\n")

    ciks_with_ticker = int(
        ticker_audit.loc[
            ticker_audit["sec_ticker"].astype(str).str.len().gt(0), "sec_cik"
        ].nunique()
    )
    ciks_with_price_history = int(sum(not frame.empty for frame in price_by_cik.values()))
    close_nonmissing = int(joined["market_close"].notna().sum())
    return_nonmissing = int(joined["market_equity_return"].notna().sum())
    volatility_nonmissing = int(joined["market_equity_volatility"].notna().sum())
    drawdown_nonmissing = int(joined["market_equity_drawdown"].notna().sum())
    market_cap_nonmissing = int(joined["market_capitalization"].notna().sum())
    if ciks_with_ticker <= 0 or ciks_with_price_history <= 0:
        raise RuntimeError("Step-4.3 resolved no usable SEC-ticker/Yahoo Finance price histories.")
    if return_nonmissing <= 0 or volatility_nonmissing <= 0 or drawdown_nonmissing <= 0:
        raise RuntimeError("Step-4.3 produced no usable trailing equity-risk features.")
    if market_cap_nonmissing <= 0:
        raise RuntimeError("Step-4.3 produced no usable market-capitalization observations.")

    market_sha256 = sha256_file(market_output_path)
    joined_sha256 = sha256_file(joined_output_path)
    audit = {
        "step_4_3_status": "PASS",
        "transformation_version": TRANSFORMATION_VERSION,
        "created_utc": datetime.now(UTC).isoformat(),
        "step_4_2_artifact": str(step_4_2_path.relative_to(repo)).replace("\\", "/"),
        "step_4_2_artifact_sha256": step_4_2_sha256,
        "step_4_2_rows": int(len(base)),
        "step_4_2_unique_sponsors": int(base["sponsor_id"].nunique()),
        "step_4_2_unique_ciks": int(base["sec_cik"].nunique()),
        "sec_ticker_reference_endpoint": SEC_TICKER_REFERENCE_URL,
        "sec_ticker_reference_status": ticker_source["source_status"],
        "sec_ticker_reference_sha256": ticker_source["sha256"],
        "sec_ticker_reference_authentication_required": False,
        "ticker_mapping_role": "identifier metadata only; not a model feature",
        "ticker_mapping_future_backfill_allowed": False,
        "target_ciks": int(len(target_ciks)),
        "ciks_with_sec_ticker_association": ciks_with_ticker,
        "price_source_family": "YAHOO_FINANCE_CHART_DAILY",
        "yahoo_chart_endpoint_template": YAHOO_CHART_TEMPLATE,
        "market_price_start_date": PRICE_START_DATE,
        "market_source_retrieval_end_exclusive": PRICE_END_EXCLUSIVE,
        "analytical_price_cutoff_rule": "price_date <= sponsor forecast_cutoff",
        "market_price_authentication_required": False,
        "price_return_basis": "adjusted_close",
        "market_cap_price_basis": "regular_close_plus_split_basis_normalized_shares",
        "split_basis_normalization_role": (
            "unit normalization only; split metadata is not retained as a model feature"
        ),
        "price_currency_required": "USD",
        "ciks_with_usable_price_history": ciks_with_price_history,
        "price_attempt_rows": int(len(raw_manifest)),
        "price_window_observations_required": REQUIRED_PRICE_OBSERVATIONS,
        "trading_intervals": 252,
        "volatility_annualization_factor": "sqrt(252)",
        "return_definition": "adjusted_close_t / adjusted_close_t_minus_252_intervals - 1",
        "drawdown_definition": "minimum(adjusted_close / running_peak - 1) over window",
        "market_capitalization_definition": (
            "latest regular close on or before cutoff multiplied by SEC shares outstanding "
            "normalized to the provider split basis; constructed only for a CIK with one "
            "SEC ticker association"
        ),
        "future_price_observations_allowed": False,
        "future_share_filings_allowed": False,
        "sponsor_year_rows": int(len(market)),
        "joined_sponsor_year_rows": int(len(joined)),
        "joined_unique_sponsors": int(joined["sponsor_id"].nunique()),
        "joined_unique_ciks": int(joined["sec_cik"].nunique()),
        "duplicate_sponsor_year_rows": int(
            joined.duplicated(["sponsor_id", "plan_year"], keep=False).sum()
        ),
        "temporal_violation_count": int(temporal_violations),
        "market_close_nonmissing": close_nonmissing,
        "equity_return_nonmissing": return_nonmissing,
        "equity_volatility_nonmissing": volatility_nonmissing,
        "equity_drawdown_nonmissing": drawdown_nonmissing,
        "market_capitalization_nonmissing": market_cap_nonmissing,
        "market_artifact": str(market_output_path.relative_to(repo)).replace("\\", "/"),
        "market_artifact_sha256": market_sha256,
        "joined_artifact": str(joined_output_path.relative_to(repo)).replace("\\", "/"),
        "joined_artifact_sha256": joined_sha256,
        "ticker_mapping_audit": str(ticker_mapping_path.relative_to(repo)).replace("\\", "/"),
        "raw_market_manifest": str(raw_manifest_path.relative_to(repo)).replace("\\", "/"),
        "temporal_audit": str(temporal_path.relative_to(repo)).replace("\\", "/"),
        "missingness_audit": str(missingness_path.relative_to(repo)).replace("\\", "/"),
        "coverage_by_year": str(coverage_path.relative_to(repo)).replace("\\", "/"),
    }
    write_json(audit_path, audit)

    print("STEP_4_3_STATUS=PASS")
    print(f"TARGET_CIKS={len(target_ciks)}")
    print(f"CIKS_WITH_SEC_TICKER_ASSOCIATION={ciks_with_ticker}")
    print(f"CIKS_WITH_USABLE_PRICE_HISTORY={ciks_with_price_history}")
    print(f"MARKET_SPONSOR_YEAR_ROWS={len(market)}")
    print(f"JOINED_SPONSOR_YEAR_ROWS={len(joined)}")
    print(f"TEMPORAL_VIOLATION_COUNT={temporal_violations}")
    print(f"MARKET_CLOSE_NONMISSING={close_nonmissing}")
    print(f"EQUITY_RETURN_NONMISSING={return_nonmissing}")
    print(f"EQUITY_VOLATILITY_NONMISSING={volatility_nonmissing}")
    print(f"EQUITY_DRAWDOWN_NONMISSING={drawdown_nonmissing}")
    print(f"MARKET_CAPITALIZATION_NONMISSING={market_cap_nonmissing}")
    print(f"STEP_4_2_ARTIFACT_SHA256={step_4_2_sha256}")
    print(f"MARKET_ARTIFACT_SHA256={market_sha256}")
    print(f"JOINED_ARTIFACT_SHA256={joined_sha256}")


if __name__ == "__main__":
    main()
