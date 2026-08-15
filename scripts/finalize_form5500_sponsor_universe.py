"""Finalize the Milestone-2 Form 5500 sponsor-plan universe."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    config = yaml.safe_load((repo / "configs" / "form5500.yaml").read_text(encoding="utf-8"))
    population = config["milestone_2_population"]
    start_year = int(population["plan_year_start"])
    end_year = int(population["plan_year_end"])
    processed = repo / "data" / "processed" / "sponsor_plan_universe.parquet"
    interim = repo / "data" / "interim" / "sponsor_plan_universe_all_available.parquet"
    interim.parent.mkdir(parents=True, exist_ok=True)
    reports_tables = repo / "reports" / "tables"
    reports_validation = repo / "reports" / "validation"
    reports_tables.mkdir(parents=True, exist_ok=True)
    reports_validation.mkdir(parents=True, exist_ok=True)
    if interim.exists():
        candidate = pd.read_parquet(interim)
    else:
        candidate = pd.read_parquet(processed)
        candidate.to_parquet(interim, index=False)
    if len(candidate) != 80045:
        raise RuntimeError(f"Expected 80,045 candidate rows; found {len(candidate):,}.")
    candidate["plan_year"] = pd.to_numeric(candidate["plan_year"], errors="raise").astype(int)
    candidate["information_date"] = pd.to_datetime(candidate["information_date"], errors="coerce")
    eligible = candidate.loc[candidate["plan_year"].between(start_year, end_year)].copy()
    if len(eligible) != 79782:
        raise RuntimeError(f"Expected 79,782 final rows; found {len(eligible):,}.")
    dups = int(eligible.duplicated(["plan_id", "plan_year"], keep=False).sum())
    if dups != 0:
        raise RuntimeError(f"Duplicate plan-year rows remain: {dups}")
    for field in ["sponsor_id", "plan_id", "ein", "plan_number", "sponsor_name"]:
        if eligible[field].isna().any() or eligible[field].astype(str).str.strip().eq("").any():
            raise RuntimeError(f"Missing or blank identifier field: {field}")
    status = pd.Series("MILESTONE2_PLAN_YEAR_ELIGIBLE", index=candidate.index)
    status.loc[candidate["plan_year"] < start_year] = "EXCLUDED_PRE_TARGET_HORIZON"
    status.loc[candidate["plan_year"] > end_year] = "EXCLUDED_PROVISIONAL_OR_POST_HORIZON"
    horizon = (
        candidate.assign(population_status=status)
        .groupby(["plan_year", "population_status"], dropna=False)
        .agg(
            rows=("plan_id", "size"),
            unique_plans=("plan_id", "nunique"),
            unique_sponsors=("sponsor_id", "nunique"),
        )
        .reset_index()
        .sort_values("plan_year")
    )
    horizon.to_csv(reports_validation / "sponsor_universe_horizon_audit.csv", index=False)
    audit_fields = [
        "ein",
        "plan_number",
        "sponsor_name",
        "assets",
        "liabilities",
        "contributions",
        "benefit_payments",
        "participants",
        "information_date",
    ]
    missing_rows = []
    for field in audit_fields:
        series = eligible[field]
        missing = int(series.isna().sum())
        if field in {"ein", "plan_number", "sponsor_name"}:
            missing += int(series.astype(str).str.strip().eq("").sum())
        missing_rows.append(
            {
                "field": field,
                "rows": len(eligible),
                "missing_count": missing,
                "missing_rate": missing / len(eligible),
            }
        )
    pd.DataFrame(missing_rows).to_csv(
        reports_validation / "sponsor_universe_missingness.csv", index=False
    )
    names = (
        eligible.groupby("ein", dropna=False)
        .agg(sponsor_name_variants=("sponsor_name", "nunique"), observations=("plan_id", "size"))
        .reset_index()
    )
    names["manual_review_candidate"] = names["sponsor_name_variants"] > 1
    names.sort_values(
        ["manual_review_candidate", "sponsor_name_variants", "observations"],
        ascending=[False, False, False],
    ).to_csv(reports_validation / "sponsor_name_variation_audit.csv", index=False)
    unit_rows = []
    for field in ["assets", "liabilities", "contributions", "benefit_payments", "participants"]:
        values = pd.to_numeric(eligible[field], errors="coerce")
        unit_rows.append(
            {
                "field": field,
                "unit": "COUNT" if field == "participants" else "USD_NEAREST_DOLLAR",
                "nonmissing_count": int(values.notna().sum()),
                "missing_count": int(values.isna().sum()),
                "negative_count": int((values < 0).fillna(False).sum()),
                "minimum": values.min(),
                "maximum": values.max(),
            }
        )
    pd.DataFrame(unit_rows).to_csv(
        reports_validation / "sponsor_universe_unit_audit.csv", index=False
    )
    summary = (
        eligible.groupby("plan_year")
        .agg(
            plan_rows=("plan_id", "size"),
            unique_plans=("plan_id", "nunique"),
            unique_sponsors=("sponsor_id", "nunique"),
            assets_nonmissing=("assets", "count"),
            liabilities_nonmissing=("liabilities", "count"),
            contributions_nonmissing=("contributions", "count"),
            benefit_payments_nonmissing=("benefit_payments", "count"),
            participants_nonmissing=("participants", "count"),
            information_date_nonmissing=("information_date", "count"),
        )
        .reset_index()
    )
    summary.to_csv(reports_tables / "sponsor_universe_summary.csv", index=False)
    eligible = eligible.sort_values(["plan_year", "sponsor_id", "plan_id"]).reset_index(drop=True)
    eligible.to_parquet(processed, index=False)
    roundtrip = pd.read_parquet(processed)
    if len(roundtrip) != 79782 or roundtrip.duplicated(["plan_id", "plan_year"]).any():
        raise RuntimeError("Final Parquet verification failed.")
    counts = candidate.groupby("plan_year").size()
    pre_rows = int((candidate["plan_year"] < start_year).sum())
    post_rows = int((candidate["plan_year"] > end_year).sum())
    provisional_rows = int(counts.get(2025, 0))
    prior_rows = int(counts.get(2024, 0))
    audit = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "candidate_rows": int(len(candidate)),
        "candidate_unique_sponsors": int(candidate["sponsor_id"].nunique()),
        "candidate_unique_plans": int(candidate["plan_id"].nunique()),
        "eligible_rows": int(len(eligible)),
        "eligible_unique_sponsors": int(eligible["sponsor_id"].nunique()),
        "eligible_unique_plans": int(eligible["plan_id"].nunique()),
        "plan_year_start": start_year,
        "plan_year_end": end_year,
        "excluded_pre_target_rows": pre_rows,
        "excluded_post_horizon_rows": post_rows,
        "provisional_year": 2025,
        "provisional_year_rows": provisional_rows,
        "prior_complete_year_rows": prior_rows,
        "provisional_to_prior_row_ratio": provisional_rows / prior_rows if prior_rows else None,
        "duplicate_plan_year_rows": dups,
        "public_corporation_filter_applied": False,
        "public_corporation_filter_stage": "Milestone 3 SEC/Form 5500 entity resolution",
        "candidate_parquet_sha256": sha256_file(interim),
        "final_parquet_sha256": sha256_file(processed),
    }
    (reports_validation / "sponsor_universe_population_audit.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )
    print(f"CANDIDATE_ROWS={len(candidate)}")
    print(f"FINAL_ROWS={len(eligible)}")
    print(f"FINAL_UNIQUE_SPONSORS={eligible.sponsor_id.nunique()}")
    print(f"FINAL_UNIQUE_PLANS={eligible.plan_id.nunique()}")
    print(f"EXCLUDED_PRE_TARGET_ROWS={pre_rows}")
    print(f"EXCLUDED_POST_HORIZON_ROWS={post_rows}")
    print(f"PROVISIONAL_YEAR_ROWS={provisional_rows}")
    print(f"FINAL_PARQUET_SHA256={sha256_file(processed)}")
    print("SCIENTIFIC_POPULATION_AUDIT=PASS")


if __name__ == "__main__":
    main()
