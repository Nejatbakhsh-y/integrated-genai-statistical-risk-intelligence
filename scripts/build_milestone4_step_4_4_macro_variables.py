"""Build and audit Milestone-4 Step-4.4 point-in-time macro variables."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd
import requests

from risk_intelligence.features.macro_panel import (
    ALFRED_GRAPH_CSV_ENDPOINT,
    SERIES_SPECS,
    TRANSFORMATION_VERSION,
    latest_available_observation,
    parse_alfred_csv,
    validate_macro_snapshot,
    year_over_year_percent,
)

EXPECTED_SPONSOR_YEARS = 5_934
EXPECTED_LINKED_SPONSORS = 729
EXPECTED_UNIQUE_CIKS = 729
EXPECTED_YEAR_START = 2015
EXPECTED_YEAR_END = 2024
EXPECTED_UNIQUE_CUTOFFS = 10
EXPECTED_CUTOFF_MONTH = 10
EXPECTED_CUTOFF_DAY = 15
REQUEST_INTERVAL_SECONDS = 0.25
RETRYABLE_STATUS = {403, 408, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6


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
    if not value:
        raise RuntimeError("ALFRED User-Agent must not be blank.")
    return value


def validate_step_4_3_base(base: pd.DataFrame) -> pd.DataFrame:
    required = {"sponsor_id", "sec_cik", "plan_year", "forecast_cutoff"}
    missing = sorted(required - set(base.columns))
    if missing:
        raise RuntimeError(f"Step-4.3 base missing required fields: {missing}")

    work = base.copy()
    work["sponsor_id"] = work["sponsor_id"].astype("string").str.strip()
    work["sec_cik"] = work["sec_cik"].astype("string").str.zfill(10)
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
            raise RuntimeError(f"Step-4.3 handoff drift: {name}={actual}; expected={expected}")

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


def fetch_alfred_snapshot(
    session: requests.Session,
    *,
    series_id: str,
    cutoff: pd.Timestamp,
    lookback_days: int,
    cache_path: Path,
    refresh: bool,
    request_state: dict[str, float],
) -> tuple[bytes, dict[str, Any]]:
    cutoff = pd.Timestamp(cutoff).normalize()
    start = cutoff - pd.Timedelta(days=lookback_days)
    params = {
        "id": series_id,
        "vintage_date": cutoff.date().isoformat(),
        "cosd": start.date().isoformat(),
        "coed": cutoff.date().isoformat(),
    }
    public_url = ALFRED_GRAPH_CSV_ENDPOINT + "?" + urlencode(params)

    if cache_path.exists() and not refresh:
        content = cache_path.read_bytes()
        parsed = parse_alfred_csv(content, series_id)
        return content, {
            "series_id": series_id,
            "forecast_cutoff": cutoff.date().isoformat(),
            "endpoint": public_url,
            "source_status": "CACHE",
            "http_status": 200,
            "bytes": len(content),
            "sha256": sha256_bytes(content),
            "parsed_rows": int(len(parsed)),
        }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        elapsed = time.monotonic() - request_state["last_request"]
        if elapsed < REQUEST_INTERVAL_SECONDS:
            time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)
        try:
            response = session.get(ALFRED_GRAPH_CSV_ENDPOINT, params=params, timeout=(15, 90))
        except requests.RequestException as exc:
            if attempt >= MAX_ATTEMPTS:
                raise RuntimeError(
                    f"ALFRED request failed for {series_id} at {cutoff.date()}: {exc}"
                ) from exc
            time.sleep(min(2 ** (attempt - 1), 16))
            continue
        finally:
            request_state["last_request"] = time.monotonic()

        if response.status_code == 200:
            content = response.content
            parsed = parse_alfred_csv(content, series_id)
            if parsed.empty:
                raise RuntimeError(
                    f"ALFRED returned no parseable rows for {series_id} at {cutoff.date()}."
                )
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(cache_path.suffix + ".part")
            temporary.write_bytes(content)
            temporary.replace(cache_path)
            return content, {
                "series_id": series_id,
                "forecast_cutoff": cutoff.date().isoformat(),
                "endpoint": public_url,
                "source_status": "HTTP_200",
                "http_status": 200,
                "bytes": len(content),
                "sha256": sha256_bytes(content),
                "parsed_rows": int(len(parsed)),
            }

        if response.status_code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after is not None else 2 ** (attempt - 1)
            except ValueError:
                delay = 2 ** (attempt - 1)
            time.sleep(min(max(delay, 1.0), 30.0))
            continue

        raise RuntimeError(
            f"ALFRED request failed for {series_id} at {cutoff.date()}: "
            f"HTTP {response.status_code}."
        )

    raise RuntimeError(f"ALFRED request exhausted retries for {series_id} at {cutoff.date()}.")


def build_macro_year_snapshot(
    cutoff_table: pd.DataFrame,
    snapshots: dict[tuple[str, str], pd.DataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in cutoff_table.itertuples(index=False):
        plan_year = int(row.plan_year)
        cutoff = pd.Timestamp(row.forecast_cutoff).normalize()
        cutoff_key = cutoff.date().isoformat()
        record: dict[str, Any] = {
            "plan_year": plan_year,
            "forecast_cutoff": cutoff,
            "macro_vintage_date": cutoff,
            "macro_transformation_version": TRANSFORMATION_VERSION,
        }
        for spec in SERIES_SPECS:
            frame = snapshots[(spec.series_id, cutoff_key)]
            if spec.transform == "year_over_year_percent":
                value, current_date, prior_date = year_over_year_percent(frame, cutoff)
                record[spec.feature] = value
                record["macro_inflation_observation_date"] = current_date
                record["macro_inflation_prior_year_observation_date"] = prior_date
            else:
                value, observation_date = latest_available_observation(frame, cutoff)
                record[spec.feature] = value
                record[f"{spec.feature}_observation_date"] = observation_date
        rows.append(record)

    result = pd.DataFrame(rows).sort_values("plan_year").reset_index(drop=True)
    validate_macro_snapshot(result)
    return result


def build_temporal_audit(snapshot: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    observation_columns = [
        "macro_interest_rate_10y_observation_date",
        "macro_inflation_observation_date",
        "macro_inflation_prior_year_observation_date",
        "macro_credit_conditions_nfci_observation_date",
        "macro_unemployment_rate_observation_date",
    ]
    rows: list[dict[str, Any]] = []
    total_violations = 0
    for record in snapshot.itertuples(index=False):
        values = record._asdict()
        cutoff = pd.Timestamp(values["forecast_cutoff"]).normalize()
        vintage = pd.Timestamp(values["macro_vintage_date"]).normalize()
        violations = int(vintage != cutoff)
        latest_observation: pd.Timestamp | None = None
        for column in observation_columns:
            value = values.get(column)
            if pd.isna(value):
                continue
            observed = pd.Timestamp(value).normalize()
            if latest_observation is None or observed > latest_observation:
                latest_observation = observed
            if observed > cutoff:
                violations += 1
        total_violations += violations
        rows.append(
            {
                "plan_year": int(values["plan_year"]),
                "forecast_cutoff": cutoff.date().isoformat(),
                "macro_vintage_date": vintage.date().isoformat(),
                "latest_selected_observation_date": (
                    latest_observation.date().isoformat() if latest_observation else ""
                ),
                "temporal_violation_count": violations,
                "status": "PASS" if violations == 0 else "FAIL",
            }
        )
    return pd.DataFrame(rows), total_violations


def build_missingness_audit(joined: pd.DataFrame) -> pd.DataFrame:
    fields = [spec.feature for spec in SERIES_SPECS]
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
    for plan_year, group in joined.groupby("plan_year", sort=True):
        row: dict[str, Any] = {
            "plan_year": int(plan_year),
            "sponsor_year_rows": int(len(group)),
        }
        for spec in SERIES_SPECS:
            row[f"{spec.feature}_nonmissing"] = int(group[spec.feature].notna().sum())
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    repo = Path(args.repo).resolve()
    user_agent = validate_user_agent(args.user_agent)

    input_path = (
        repo
        / "data"
        / "interim"
        / "structured_x"
        / "step_4_3"
        / "pension_sec_market_sponsor_year_base.parquet"
    )
    step_4_3_audit_path = (
        repo / "reports" / "validation" / "milestone4_step_4_3_market_ingestion_audit.json"
    )
    raw_dir = repo / "data" / "raw" / "macro" / "alfred"
    output_dir = repo / "data" / "interim" / "structured_x" / "step_4_4"
    macro_output_path = output_dir / "macro_sponsor_year_features.parquet"
    joined_output_path = output_dir / "pension_sec_market_macro_sponsor_year_base.parquet"

    validation_dir = repo / "reports" / "validation"
    tables_dir = repo / "reports" / "tables"
    raw_manifest_path = validation_dir / "milestone4_step_4_4_macro_raw_manifest.csv"
    temporal_path = validation_dir / "milestone4_step_4_4_macro_temporal_audit.csv"
    missingness_path = validation_dir / "milestone4_step_4_4_macro_missingness.csv"
    audit_path = validation_dir / "milestone4_step_4_4_macro_ingestion_audit.json"
    coverage_path = tables_dir / "milestone4_step_4_4_macro_coverage_by_year.csv"

    for directory in [raw_dir, output_dir, validation_dir, tables_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise RuntimeError(f"Missing frozen Step-4.3 joined artifact: {input_path}")
    if not step_4_3_audit_path.exists():
        raise RuntimeError(f"Missing Step-4.3 audit: {step_4_3_audit_path}")

    step_4_3_audit = json.loads(step_4_3_audit_path.read_text(encoding="utf-8"))
    if step_4_3_audit.get("step_4_3_status") != "PASS":
        raise RuntimeError("Step-4.3 audit does not report PASS.")

    step_4_3_sha256 = sha256_file(input_path)
    base = validate_step_4_3_base(pd.read_parquet(input_path))
    cutoff_table = (
        base[["plan_year", "forecast_cutoff"]]
        .drop_duplicates()
        .sort_values("plan_year")
        .reset_index(drop=True)
    )
    if len(cutoff_table) != EXPECTED_UNIQUE_CUTOFFS:
        raise RuntimeError(
            f"Expected {EXPECTED_UNIQUE_CUTOFFS} unique cutoffs; found {len(cutoff_table)}."
        )
    if cutoff_table["plan_year"].duplicated().any():
        raise RuntimeError("A plan year maps to multiple macro cutoffs.")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/csv,text/plain,*/*",
            "Accept-Encoding": "gzip, deflate",
        }
    )
    request_state = {"last_request": 0.0}
    snapshots: dict[tuple[str, str], pd.DataFrame] = {}
    manifest_rows: list[dict[str, Any]] = []

    for cutoff_row in cutoff_table.itertuples(index=False):
        cutoff = pd.Timestamp(cutoff_row.forecast_cutoff).normalize()
        cutoff_key = cutoff.date().isoformat()
        for spec in SERIES_SPECS:
            cache_path = raw_dir / spec.series_id / f"{cutoff_key}.csv"
            content, manifest = fetch_alfred_snapshot(
                session,
                series_id=spec.series_id,
                cutoff=cutoff,
                lookback_days=spec.lookback_days,
                cache_path=cache_path,
                refresh=bool(args.refresh),
                request_state=request_state,
            )
            frame = parse_alfred_csv(content, spec.series_id)
            snapshots[(spec.series_id, cutoff_key)] = frame
            manifest_rows.append(
                {
                    "feature": spec.feature,
                    "source": spec.source,
                    "release": spec.release,
                    "frequency": spec.frequency,
                    "units": spec.units,
                    **manifest,
                }
            )

    manifest_df = pd.DataFrame(manifest_rows)
    expected_manifest_rows = EXPECTED_UNIQUE_CUTOFFS * len(SERIES_SPECS)
    if len(manifest_df) != expected_manifest_rows:
        raise RuntimeError(
            f"Macro raw manifest rows={len(manifest_df)}; expected={expected_manifest_rows}."
        )
    manifest_df.to_csv(raw_manifest_path, index=False, lineterminator="\n")

    macro_year = build_macro_year_snapshot(cutoff_table, snapshots)
    feature_keys = ["plan_year", "forecast_cutoff"]
    sponsor_keys = base[["sponsor_id", "sec_cik", *feature_keys]].copy()
    macro_frame = sponsor_keys.merge(
        macro_year,
        on=feature_keys,
        how="left",
        validate="many_to_one",
        sort=False,
    )
    macro_frame = macro_frame.sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)
    if len(macro_frame) != EXPECTED_SPONSOR_YEARS:
        raise RuntimeError("Macro sponsor-year frame changed the frozen row count.")
    macro_frame.to_parquet(macro_output_path, index=False)

    macro_columns = [column for column in macro_frame.columns if column not in sponsor_keys.columns]
    joined = base.merge(
        macro_frame[["sponsor_id", "sec_cik", *feature_keys, *macro_columns]],
        on=["sponsor_id", "sec_cik", *feature_keys],
        how="left",
        validate="one_to_one",
        sort=False,
    )
    joined = joined.sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)
    if len(joined) != EXPECTED_SPONSOR_YEARS:
        raise RuntimeError("Step-4.4 join changed sponsor-year row count.")
    duplicate_rows = int(joined.duplicated(["sponsor_id", "plan_year"], keep=False).sum())
    if duplicate_rows:
        raise RuntimeError("Step-4.4 join created duplicate sponsor-year rows.")
    joined.to_parquet(joined_output_path, index=False)

    temporal_df, temporal_violations = build_temporal_audit(macro_year)
    temporal_df.to_csv(temporal_path, index=False, lineterminator="\n")
    if temporal_violations != 0 or not temporal_df["status"].eq("PASS").all():
        raise RuntimeError(f"Step-4.4 temporal audit failed: violations={temporal_violations}")

    missingness_df = build_missingness_audit(joined)
    missingness_df.to_csv(missingness_path, index=False, lineterminator="\n")

    coverage_df = build_coverage_by_year(joined)
    coverage_df.to_csv(coverage_path, index=False, lineterminator="\n")

    nonmissing = {spec.feature: int(joined[spec.feature].notna().sum()) for spec in SERIES_SPECS}
    if any(value == 0 for value in nonmissing.values()):
        raise RuntimeError(f"At least one Step-4.4 macro feature has zero coverage: {nonmissing}")

    macro_sha256 = sha256_file(macro_output_path)
    joined_sha256 = sha256_file(joined_output_path)
    audit = {
        "step_4_4_status": "PASS",
        "transformation_version": TRANSFORMATION_VERSION,
        "created_utc": datetime.now(UTC).isoformat(),
        "source_family": "ALFRED_VINTAGE_GRAPH_CSV",
        "source_endpoint": ALFRED_GRAPH_CSV_ENDPOINT,
        "authentication_required": False,
        "vintage_alignment_rule": "vintage_date equals sponsor-year forecast_cutoff",
        "observation_alignment_rule": "latest valid observation on or before forecast_cutoff",
        "inflation_rule": (
            "100 * (latest CPIAUCNS level / same-month prior-year CPIAUCNS level - 1) "
            "within the same forecast-cutoff vintage"
        ),
        "future_information_allowed": False,
        "future_backfill_allowed": False,
        "step_4_3_artifact": str(input_path.relative_to(repo)).replace("\\", "/"),
        "step_4_3_artifact_sha256": step_4_3_sha256,
        "step_4_3_rows": int(len(base)),
        "step_4_3_unique_sponsors": int(base["sponsor_id"].nunique()),
        "step_4_3_unique_ciks": int(base["sec_cik"].nunique()),
        "unique_forecast_cutoffs": int(len(cutoff_table)),
        "raw_snapshot_requests": int(len(manifest_df)),
        "macro_year_rows": int(len(macro_year)),
        "macro_sponsor_year_rows": int(len(macro_frame)),
        "joined_sponsor_year_rows": int(len(joined)),
        "joined_unique_sponsors": int(joined["sponsor_id"].nunique()),
        "joined_unique_ciks": int(joined["sec_cik"].nunique()),
        "duplicate_sponsor_year_rows": duplicate_rows,
        "temporal_violation_count": int(temporal_violations),
        "interest_rate_nonmissing": nonmissing["macro_interest_rate_10y"],
        "inflation_nonmissing": nonmissing["macro_inflation_yoy"],
        "credit_conditions_nonmissing": nonmissing["macro_credit_conditions_nfci"],
        "unemployment_nonmissing": nonmissing["macro_unemployment_rate"],
        "macro_artifact": str(macro_output_path.relative_to(repo)).replace("\\", "/"),
        "macro_artifact_sha256": macro_sha256,
        "joined_artifact": str(joined_output_path.relative_to(repo)).replace("\\", "/"),
        "joined_artifact_sha256": joined_sha256,
        "raw_manifest": str(raw_manifest_path.relative_to(repo)).replace("\\", "/"),
        "temporal_audit": str(temporal_path.relative_to(repo)).replace("\\", "/"),
        "missingness_audit": str(missingness_path.relative_to(repo)).replace("\\", "/"),
        "coverage_by_year": str(coverage_path.relative_to(repo)).replace("\\", "/"),
        "series": [
            {
                "feature": spec.feature,
                "series_id": spec.series_id,
                "source": spec.source,
                "release": spec.release,
                "units": spec.units,
                "frequency": spec.frequency,
                "transform": spec.transform,
            }
            for spec in SERIES_SPECS
        ],
    }
    write_json(audit_path, audit)

    print("STEP_4_4_STATUS=PASS")
    print(f"UNIQUE_FORECAST_CUTOFFS={len(cutoff_table)}")
    print(f"RAW_SNAPSHOT_REQUESTS={len(manifest_df)}")
    print(f"MACRO_YEAR_ROWS={len(macro_year)}")
    print(f"MACRO_SPONSOR_YEAR_ROWS={len(macro_frame)}")
    print(f"JOINED_SPONSOR_YEAR_ROWS={len(joined)}")
    print(f"TEMPORAL_VIOLATION_COUNT={temporal_violations}")
    print(f"INTEREST_RATE_NONMISSING={nonmissing['macro_interest_rate_10y']}")
    print(f"INFLATION_NONMISSING={nonmissing['macro_inflation_yoy']}")
    print(f"CREDIT_CONDITIONS_NONMISSING={nonmissing['macro_credit_conditions_nfci']}")
    print(f"UNEMPLOYMENT_NONMISSING={nonmissing['macro_unemployment_rate']}")
    print(f"STEP_4_3_ARTIFACT_SHA256={step_4_3_sha256}")
    print(f"MACRO_ARTIFACT_SHA256={macro_sha256}")
    print(f"JOINED_ARTIFACT_SHA256={joined_sha256}")


if __name__ == "__main__":
    main()
