"""Build and audit Milestone-4 Step-4.2 point-in-time SEC/XBRL sponsor financials."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from risk_intelligence.features.sec_financials import (
    ALL_BASE_METRICS,
    CORE_METRICS,
    MONETARY_UNIT,
    TRANSFORMATION_VERSION,
    build_sec_sponsor_year_financials,
    normalize_cik,
    safe_ratio,
)

EXPECTED_SPONSOR_YEARS = 5_934
EXPECTED_LINKED_SPONSORS = 729
EXPECTED_UNIQUE_CIKS = 729
EXPECTED_YEAR_START = 2015
EXPECTED_YEAR_END = 2024
EXPECTED_CUTOFF_MONTH = 10
EXPECTED_CUTOFF_DAY = 15
SEC_COMPANYFACTS_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
REQUEST_INTERVAL_SECONDS = 0.15
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}
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
    if not value or "@" not in value or len(value) < 8:
        raise RuntimeError(
            "SEC User-Agent must identify the requester and include a contact email address."
        )
    return value


def load_companyfacts_cache(path: Path) -> tuple[dict[str, Any], bytes]:
    content = path.read_bytes()
    payload = json.loads(content.decode("utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("facts", {}), dict):
        raise RuntimeError(f"Malformed cached companyfacts JSON: {path}")
    return payload, content


def fetch_companyfacts(
    session: requests.Session,
    *,
    cik: str,
    cache_path: Path,
    refresh: bool,
    request_state: dict[str, float],
) -> tuple[dict[str, Any], dict[str, Any]]:
    url = SEC_COMPANYFACTS_TEMPLATE.format(cik=cik)

    if cache_path.exists() and not refresh:
        payload, content = load_companyfacts_cache(cache_path)
        return payload, {
            "sec_cik": cik,
            "endpoint": url,
            "source_status": "CACHE",
            "http_status": 200,
            "bytes": len(content),
            "sha256": sha256_bytes(content),
            "entity_name": str(payload.get("entityName", "")).strip(),
            "taxonomy_count": int(len(payload.get("facts", {}))),
            "concept_count": int(
                sum(
                    len(value)
                    for value in payload.get("facts", {}).values()
                    if isinstance(value, dict)
                )
            ),
        }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        elapsed = time.monotonic() - request_state["last_request"]
        if elapsed < REQUEST_INTERVAL_SECONDS:
            time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)

        try:
            response = session.get(url, timeout=(15, 90))
        except requests.RequestException as exc:
            if attempt >= MAX_ATTEMPTS:
                raise RuntimeError(f"SEC companyfacts request failed for CIK {cik}: {exc}") from exc
            time.sleep(min(2 ** (attempt - 1), 16))
            continue
        finally:
            request_state["last_request"] = time.monotonic()

        if response.status_code == 404:
            if cache_path.exists():
                cache_path.unlink()
            return {"cik": int(cik), "entityName": "", "facts": {}}, {
                "sec_cik": cik,
                "endpoint": url,
                "source_status": "HTTP_404_NO_COMPANYFACTS",
                "http_status": 404,
                "bytes": 0,
                "sha256": "",
                "entity_name": "",
                "taxonomy_count": 0,
                "concept_count": 0,
            }

        if response.status_code == 200:
            content = response.content
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError(f"SEC returned non-JSON companyfacts for CIK {cik}.") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("facts", {}), dict):
                raise RuntimeError(f"SEC returned malformed companyfacts for CIK {cik}.")

            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(cache_path.suffix + ".part")
            temporary.write_bytes(content)
            temporary.replace(cache_path)

            return payload, {
                "sec_cik": cik,
                "endpoint": url,
                "source_status": "HTTP_200",
                "http_status": 200,
                "bytes": len(content),
                "sha256": sha256_bytes(content),
                "entity_name": str(payload.get("entityName", "")).strip(),
                "taxonomy_count": int(len(payload.get("facts", {}))),
                "concept_count": int(
                    sum(
                        len(value)
                        for value in payload.get("facts", {}).values()
                        if isinstance(value, dict)
                    )
                ),
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
            f"SEC companyfacts request failed for CIK {cik}: HTTP {response.status_code}."
        )

    raise RuntimeError(f"SEC companyfacts request exhausted retries for CIK {cik}.")


def validate_step_4_1_base(base: pd.DataFrame) -> pd.DataFrame:
    required = {"sponsor_id", "sec_cik", "plan_year", "forecast_cutoff", "liabilities"}
    missing = sorted(required - set(base.columns))
    if missing:
        raise RuntimeError(f"Step-4.1 base missing required fields: {missing}")

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
            raise RuntimeError(f"Step-4.1 handoff drift: {name}={actual}; expected={expected}")

    expected_cutoff = pd.to_datetime(
        {
            "year": work["plan_year"] + 1,
            "month": EXPECTED_CUTOFF_MONTH,
            "day": EXPECTED_CUTOFF_DAY,
        }
    )
    cutoff_mismatch = int(work["forecast_cutoff"].ne(expected_cutoff).sum())
    if cutoff_mismatch:
        raise RuntimeError(f"Frozen forecast_cutoff drift: mismatch_rows={cutoff_mismatch}")

    sponsor_cik_counts = work.groupby("sponsor_id")["sec_cik"].nunique(dropna=False)
    if not sponsor_cik_counts.eq(1).all():
        raise RuntimeError("A sponsor maps to more than one SEC CIK in the Step-4.1 skeleton.")

    return work.sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)


def build_temporal_audit(sec_frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    rows: list[dict[str, Any]] = []
    total_violations = 0
    for record in sec_frame.itertuples(index=False):
        record_dict = record._asdict()
        cutoff = pd.Timestamp(record_dict["forecast_cutoff"]).normalize()
        selected = 0
        violations = 0
        selected_dates: list[pd.Timestamp] = []
        for metric in ALL_BASE_METRICS:
            filed = record_dict[f"sec_{metric}_filed_date"]
            if pd.isna(filed):
                continue
            selected += 1
            filed_date = pd.Timestamp(filed).normalize()
            selected_dates.append(filed_date)
            if filed_date > cutoff:
                violations += 1
        total_violations += violations
        rows.append(
            {
                "sponsor_id": record_dict["sponsor_id"],
                "sec_cik": record_dict["sec_cik"],
                "plan_year": int(record_dict["plan_year"]),
                "forecast_cutoff": cutoff.date().isoformat(),
                "selected_metric_count": selected,
                "latest_selected_filed_date": (
                    max(selected_dates).date().isoformat() if selected_dates else ""
                ),
                "temporal_violation_count": violations,
                "status": "PASS" if violations == 0 else "FAIL",
            }
        )
    return pd.DataFrame(rows), total_violations


def build_concept_selection_audit(sec_frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for metric in ALL_BASE_METRICS:
        taxonomy_col = f"sec_{metric}_taxonomy"
        concept_col = f"sec_{metric}_concept"
        form_col = f"sec_{metric}_form"
        selected = sec_frame.loc[sec_frame[f"sec_{metric}"].notna()].copy()
        if selected.empty:
            rows.append(
                {
                    "metric": metric,
                    "taxonomy": "",
                    "concept": "",
                    "form": "",
                    "selection_count": 0,
                    "selection_rate": 0.0,
                }
            )
            continue
        grouped = (
            selected.groupby([taxonomy_col, concept_col, form_col], dropna=False)
            .size()
            .reset_index(name="selection_count")
        )
        for item in grouped.itertuples(index=False):
            rows.append(
                {
                    "metric": metric,
                    "taxonomy": (
                        getattr(item, taxonomy_col) if pd.notna(getattr(item, taxonomy_col)) else ""
                    ),
                    "concept": (
                        getattr(item, concept_col) if pd.notna(getattr(item, concept_col)) else ""
                    ),
                    "form": getattr(item, form_col) if pd.notna(getattr(item, form_col)) else "",
                    "selection_count": int(item.selection_count),
                    "selection_rate": float(item.selection_count / len(sec_frame)),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["metric", "selection_count", "taxonomy", "concept"],
        ascending=[True, False, True, True],
    )


def build_missingness_audit(joined: pd.DataFrame) -> pd.DataFrame:
    fields = [
        *(f"sec_{metric}" for metric in ALL_BASE_METRICS),
        "sec_profitability",
        "sec_leverage",
        "sec_liquidity",
        "pension_size",
        "pension_assets_to_sponsor_assets",
        "pension_liabilities_to_sponsor_assets",
        "pension_contributions_to_revenue",
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
    for plan_year, group in joined.groupby("plan_year", sort=True):
        core_columns = [f"sec_{metric}" for metric in CORE_METRICS]
        row: dict[str, Any] = {
            "plan_year": int(plan_year),
            "sponsor_year_rows": int(len(group)),
            "sponsor_years_with_any_core_financial": int(
                group[core_columns].notna().any(axis=1).sum()
            ),
            "sponsor_years_with_all_core_financials": int(
                group[core_columns].notna().all(axis=1).sum()
            ),
        }
        for metric in CORE_METRICS:
            row[f"{metric}_nonmissing"] = int(group[f"sec_{metric}"].notna().sum())
        row["pension_size_nonmissing"] = int(group["pension_size"].notna().sum())
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    repo = Path(args.repo).resolve()
    user_agent = validate_user_agent(args.user_agent)

    step_4_1_path = (
        repo
        / "data"
        / "interim"
        / "structured_x"
        / "step_4_1"
        / "pension_sponsor_year_base.parquet"
    )
    step_4_1_audit_path = (
        repo / "reports" / "validation" / "milestone4_step_4_1_pension_base_audit.json"
    )
    raw_dir = repo / "data" / "raw" / "sec_xbrl" / "companyfacts"
    output_dir = repo / "data" / "interim" / "structured_x" / "step_4_2"
    sec_output_path = output_dir / "sec_sponsor_year_financials.parquet"
    joined_output_path = output_dir / "pension_sec_sponsor_year_base.parquet"

    validation_dir = repo / "reports" / "validation"
    tables_dir = repo / "reports" / "tables"
    raw_manifest_path = validation_dir / "milestone4_step_4_2_raw_companyfacts_manifest.csv"
    temporal_path = validation_dir / "milestone4_step_4_2_temporal_audit.csv"
    concept_path = validation_dir / "milestone4_step_4_2_concept_selection.csv"
    missingness_path = validation_dir / "milestone4_step_4_2_missingness.csv"
    audit_path = validation_dir / "milestone4_step_4_2_sec_ingestion_audit.json"
    coverage_path = tables_dir / "milestone4_step_4_2_financial_coverage_by_year.csv"

    for directory in [raw_dir, output_dir, validation_dir, tables_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    if not step_4_1_path.exists():
        raise RuntimeError(f"Missing frozen Step-4.1 artifact: {step_4_1_path}")
    if not step_4_1_audit_path.exists():
        raise RuntimeError(f"Missing Step-4.1 audit: {step_4_1_audit_path}")

    step_4_1_audit = json.loads(step_4_1_audit_path.read_text(encoding="utf-8"))
    if step_4_1_audit.get("step_4_1_status") != "PASS":
        raise RuntimeError("Step-4.1 audit does not report PASS.")

    step_4_1_sha256 = sha256_file(step_4_1_path)
    base = validate_step_4_1_base(pd.read_parquet(step_4_1_path))
    unique_ciks = sorted(set(base["sec_cik"].astype(str)))
    if len(unique_ciks) != EXPECTED_UNIQUE_CIKS:
        raise RuntimeError(f"Expected {EXPECTED_UNIQUE_CIKS} CIKs; found {len(unique_ciks)}")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }
    )
    request_state = {"last_request": 0.0}
    payload_by_cik: dict[str, dict[str, Any]] = {}
    manifest_rows: list[dict[str, Any]] = []

    for index, cik in enumerate(unique_ciks, start=1):
        cache_path = raw_dir / f"CIK{cik}.json"
        payload, manifest = fetch_companyfacts(
            session,
            cik=cik,
            cache_path=cache_path,
            refresh=bool(args.refresh),
            request_state=request_state,
        )
        payload_by_cik[cik] = payload
        manifest_rows.append({"cik_sequence": index, **manifest})

    manifest_df = pd.DataFrame(manifest_rows).sort_values("sec_cik").reset_index(drop=True)
    if len(manifest_df) != EXPECTED_UNIQUE_CIKS:
        raise RuntimeError("Raw companyfacts manifest does not contain all linked CIKs.")
    manifest_df.to_csv(raw_manifest_path, index=False, lineterminator="\n")

    sec_frame = build_sec_sponsor_year_financials(base, payload_by_cik)
    sec_frame.to_parquet(sec_output_path, index=False)

    join_keys = ["sponsor_id", "sec_cik", "plan_year", "forecast_cutoff"]
    joined = base.merge(sec_frame, on=join_keys, how="left", validate="one_to_one", sort=False)
    joined = joined.sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)
    if len(joined) != EXPECTED_SPONSOR_YEARS:
        raise RuntimeError(f"Step-4.2 join changed sponsor-year row count: {len(joined)}")
    if joined.duplicated(["sponsor_id", "plan_year"], keep=False).any():
        raise RuntimeError("Step-4.2 join created duplicate sponsor-year rows.")

    joined["pension_size"] = [
        safe_ratio(liability, sponsor_assets, positive_denominator=True)
        for liability, sponsor_assets in zip(
            joined["liabilities"], joined["sec_total_assets"], strict=True
        )
    ]
    if "assets" not in joined.columns or "contributions" not in joined.columns:
        raise RuntimeError(
            "Step-4.1 pension base lacks assets or contributions for Step-4.2 ratios."
        )
    joined["pension_assets_to_sponsor_assets"] = [
        safe_ratio(pension_assets, sponsor_assets, positive_denominator=True)
        for pension_assets, sponsor_assets in zip(
            joined["assets"], joined["sec_total_assets"], strict=True
        )
    ]
    joined["pension_liabilities_to_sponsor_assets"] = joined["pension_size"]
    joined["pension_contributions_to_revenue"] = [
        safe_ratio(contributions, revenue, positive_denominator=False)
        for contributions, revenue in zip(
            joined["contributions"], joined["sec_revenue"], strict=True
        )
    ]
    joined.to_parquet(joined_output_path, index=False)

    temporal_df, temporal_violations = build_temporal_audit(sec_frame)
    temporal_df.to_csv(temporal_path, index=False, lineterminator="\n")
    if temporal_violations != 0 or not temporal_df["status"].eq("PASS").all():
        raise RuntimeError(f"Step-4.2 temporal audit failed: violations={temporal_violations}")

    concept_df = build_concept_selection_audit(sec_frame)
    concept_df.to_csv(concept_path, index=False, lineterminator="\n")

    missingness_df = build_missingness_audit(joined)
    missingness_df.to_csv(missingness_path, index=False, lineterminator="\n")

    coverage_df = build_coverage_by_year(joined)
    coverage_df.to_csv(coverage_path, index=False, lineterminator="\n")

    total_assets_nonmissing = int(joined["sec_total_assets"].notna().sum())
    revenue_nonmissing = int(joined["sec_revenue"].notna().sum())
    any_core_nonmissing = int(
        joined[[f"sec_{metric}" for metric in CORE_METRICS]].notna().any(axis=1).sum()
    )
    if total_assets_nonmissing == 0 or revenue_nonmissing == 0 or any_core_nonmissing == 0:
        raise RuntimeError(
            "SEC/XBRL extraction produced no usable core sponsor-financial coverage."
        )

    sec_frame_sha256 = sha256_file(sec_output_path)
    joined_sha256 = sha256_file(joined_output_path)
    raw_200 = int(manifest_df["http_status"].eq(200).sum())
    raw_404 = int(manifest_df["http_status"].eq(404).sum())

    audit = {
        "step_4_2_status": "PASS",
        "transformation_version": TRANSFORMATION_VERSION,
        "created_utc": datetime.now(UTC).isoformat(),
        "source_family": "SEC_EDGAR_XBRL_COMPANYFACTS",
        "source_endpoint_template": SEC_COMPANYFACTS_TEMPLATE,
        "source_authentication_required": False,
        "sec_user_agent_declared": True,
        "request_interval_seconds": REQUEST_INTERVAL_SECONDS,
        "monetary_unit": MONETARY_UNIT,
        "annual_fact_alignment_rule": (
            "form in annual-form allowlist; fy == plan_year; filed_date <= forecast_cutoff; "
            "period_end <= forecast_cutoff; annual-duration facts restricted to 250-450 days; "
            "selection ordered by latest period_end, latest filed_date, then concept priority"
        ),
        "future_information_allowed": False,
        "future_backfill_allowed": False,
        "step_4_1_artifact": str(step_4_1_path.relative_to(repo)).replace("\\", "/"),
        "step_4_1_artifact_sha256": step_4_1_sha256,
        "step_4_1_rows": int(len(base)),
        "step_4_1_unique_sponsors": int(base["sponsor_id"].nunique()),
        "step_4_1_unique_ciks": int(base["sec_cik"].nunique()),
        "companyfacts_ciks_attempted": int(len(manifest_df)),
        "companyfacts_http_200_or_cache": raw_200,
        "companyfacts_http_404_no_xbrl": raw_404,
        "sec_sponsor_year_rows": int(len(sec_frame)),
        "joined_sponsor_year_rows": int(len(joined)),
        "joined_unique_sponsors": int(joined["sponsor_id"].nunique()),
        "joined_unique_ciks": int(joined["sec_cik"].nunique()),
        "duplicate_sponsor_year_rows": int(
            joined.duplicated(["sponsor_id", "plan_year"], keep=False).sum()
        ),
        "temporal_violation_count": int(temporal_violations),
        "total_assets_nonmissing": total_assets_nonmissing,
        "revenue_nonmissing": revenue_nonmissing,
        "any_core_financial_nonmissing": any_core_nonmissing,
        "pension_size_definition": "Form5500 pension liabilities / SEC total assets",
        "pension_size_nonmissing": int(joined["pension_size"].notna().sum()),
        "sec_financial_artifact": str(sec_output_path.relative_to(repo)).replace("\\", "/"),
        "sec_financial_artifact_sha256": sec_frame_sha256,
        "joined_artifact": str(joined_output_path.relative_to(repo)).replace("\\", "/"),
        "joined_artifact_sha256": joined_sha256,
        "raw_companyfacts_manifest": str(raw_manifest_path.relative_to(repo)).replace("\\", "/"),
        "temporal_audit": str(temporal_path.relative_to(repo)).replace("\\", "/"),
        "concept_selection_audit": str(concept_path.relative_to(repo)).replace("\\", "/"),
        "missingness_audit": str(missingness_path.relative_to(repo)).replace("\\", "/"),
        "coverage_by_year": str(coverage_path.relative_to(repo)).replace("\\", "/"),
    }
    write_json(audit_path, audit)

    print(f"STEP_4_2_STATUS={audit['step_4_2_status']}")
    print(f"COMPANYFACTS_CIKS_ATTEMPTED={audit['companyfacts_ciks_attempted']}")
    print(f"COMPANYFACTS_HTTP_200_OR_CACHE={audit['companyfacts_http_200_or_cache']}")
    print(f"COMPANYFACTS_HTTP_404_NO_XBRL={audit['companyfacts_http_404_no_xbrl']}")
    print(f"SEC_SPONSOR_YEAR_ROWS={audit['sec_sponsor_year_rows']}")
    print(f"JOINED_SPONSOR_YEAR_ROWS={audit['joined_sponsor_year_rows']}")
    print(f"TEMPORAL_VIOLATION_COUNT={audit['temporal_violation_count']}")
    print(f"TOTAL_ASSETS_NONMISSING={audit['total_assets_nonmissing']}")
    print(f"REVENUE_NONMISSING={audit['revenue_nonmissing']}")
    print(f"PENSION_SIZE_NONMISSING={audit['pension_size_nonmissing']}")
    print(f"STEP_4_1_ARTIFACT_SHA256={audit['step_4_1_artifact_sha256']}")
    print(f"SEC_FINANCIAL_ARTIFACT_SHA256={audit['sec_financial_artifact_sha256']}")
    print(f"JOINED_ARTIFACT_SHA256={audit['joined_artifact_sha256']}")


if __name__ == "__main__":
    main()
