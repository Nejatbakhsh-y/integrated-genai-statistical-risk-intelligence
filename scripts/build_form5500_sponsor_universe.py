"""Build the controlled Form 5500 DB sponsor-plan universe."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from risk_intelligence.ingestion.form5500 import (
    build_year,
    choose_resources,
    discover_resources,
    download_resource,
    extract_if_zip,
    fetch_html,
    sha256_file,
    write_manifest,
)

SOURCE_PAGE = (
    "https://www.dol.gov/agencies/ebsa/about-ebsa/our-activities/"
    "public-disclosure/foia/form-5500-datasets"
)

GUIDE_URL = "https://www.dol.gov/sites/dolgov/files/ebsa/pdf_files/form-5500-datasets-guide.pdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2025)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    repo = Path(args.repo).resolve()

    raw_root = repo / "data" / "raw" / "form5500"
    work_root = repo / "work" / "form5500"

    reports_tables = repo / "reports" / "tables"
    reports_validation = repo / "reports" / "validation"

    processed_root = repo / "data" / "processed"

    for path in [
        raw_root,
        work_root,
        reports_tables,
        reports_validation,
        processed_root,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    years = list(range(args.start_year, args.end_year + 1))

    retrieved_utc = datetime.now(UTC).isoformat()

    print("=" * 78)
    print("FORM 5500 SOURCE DISCOVERY")
    print("=" * 78)

    source_snapshot = work_root / "form5500_datasets_source.html"

    try:
        html = fetch_html(
            SOURCE_PAGE,
            source_snapshot,
        )
        print("SOURCE_DISCOVERY_MODE=DOL_LANDING_PAGE")
    except RuntimeError as exc:
        print(f"SOURCE_PAGE_FETCH_WARNING={exc}")
        print("SOURCE_DISCOVERY_MODE=OFFICIAL_ASKEBSA_FALLBACK")

        fallback_lines = [
            "<html>",
            "<body>",
            "<!-- Generated fallback index using official DOL/Ask EBSA "
            "Form 5500 Latest dataset URL structure. -->",
        ]

        for year in years:
            base = f"https://askebsa.dol.gov/FOIA%20Files/{year}/Latest"

            fallback_lines.extend(
                [
                    f"<h2>{year} Form 5500</h2>",
                    (f'<a href="{base}/F_5500_{year}_Latest.zip">{year} Latest Form 5500</a>'),
                    (f'<a href="{base}/F_SCH_H_{year}_Latest.zip">{year} Latest Schedule H</a>'),
                    (f'<a href="{base}/F_SCH_I_{year}_Latest.zip">{year} Latest Schedule I</a>'),
                    (f'<a href="{base}/F_SCH_SB_{year}_Latest.zip">{year} Latest Schedule SB</a>'),
                ]
            )

        fallback_lines.extend(["</body>", "</html>"])
        html = "\n".join(fallback_lines)

        source_snapshot.write_text(
            html,
            encoding="utf-8",
        )

    resources = discover_resources(
        html,
        SOURCE_PAGE,
        args.start_year,
        args.end_year,
    )

    if not resources:
        raise RuntimeError("No DOL Form 5500 dataset links were discovered.")

    discovery_frame = pd.DataFrame(
        [
            {
                "year": resource.year,
                "dataset": resource.dataset,
                "url": resource.url,
                "link_text": resource.link_text,
            }
            for resource in resources
        ]
    )

    discovery_path = reports_validation / "form5500_source_discovery.csv"

    discovery_frame.to_csv(discovery_path, index=False)

    selected = choose_resources(resources)

    selected_frame = pd.DataFrame(
        [
            {
                "year": resource.year,
                "dataset": resource.dataset,
                "url": resource.url,
                "link_text": resource.link_text,
            }
            for resource in selected
        ]
    )

    selected_path = reports_validation / "form5500_selected_sources.csv"
    selected_frame.to_csv(selected_path, index=False)

    required = {"form5500_latest", "schedule_sb_latest"}

    failures: list[str] = []

    for year in years:
        available = {resource.dataset for resource in selected if resource.year == year}

        missing = required - available

        if missing:
            failures.append(f"{year}: missing authoritative source categories {sorted(missing)}")

    if failures:
        for failure in failures:
            print(f"SOURCE_DISCOVERY_FAILURE={failure}")

        raise RuntimeError(
            "DOL resource discovery was incomplete. No sponsor universe will be certified."
        )

    print(f"DISCOVERED_RESOURCE_COUNT={len(resources)}")
    print(f"SELECTED_RESOURCE_COUNT={len(selected)}")
    print("SOURCE_DISCOVERY=PASS")

    print("")
    print("=" * 78)
    print("RAW DATA ACQUISITION")
    print("=" * 78)

    manifest_rows: list[dict[str, object]] = []

    for number, resource in enumerate(selected, start=1):
        print(f"[{number}/{len(selected)}] {resource.year} {resource.dataset}")

        path, downloaded = download_resource(
            resource,
            raw_root,
        )

        extract_if_zip(path)

        relative = path.relative_to(repo)

        manifest_rows.append(
            {
                "year": resource.year,
                "dataset": resource.dataset,
                "source_url": resource.url,
                "retrieved_utc": retrieved_utc,
                "local_path": relative.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "source_page": SOURCE_PAGE,
                "status": ("DOWNLOADED" if downloaded else "EXISTING_FILE_REHASHED"),
            }
        )

    manifest_path = repo / "data" / "raw_data_manifest.csv"

    write_manifest(
        manifest_path,
        manifest_rows,
    )

    if not manifest_path.exists():
        raise RuntimeError("Raw-data manifest was not created.")

    print(f"RAW_MANIFEST={manifest_path}")
    print(f"RAW_MANIFEST_ROWS={len(manifest_rows)}")
    print("RAW_DATA_ACQUISITION=PASS")

    print("")
    print("=" * 78)
    print("SPONSOR-PLAN UNIVERSE CONSTRUCTION")
    print("=" * 78)

    yearly: list[pd.DataFrame] = []
    mapping_rows: list[dict[str, object]] = []

    for year in years:
        print(f"BUILD_YEAR={year}")

        frame, mappings = build_year(
            raw_root=raw_root,
            year=year,
        )

        if frame.empty:
            raise RuntimeError(f"{year}: sponsor universe is empty.")

        yearly.append(frame)
        mapping_rows.extend(mappings)

        print(f"YEAR={year};DB_PLAN_ROWS={len(frame)}")

    universe = pd.concat(
        yearly,
        ignore_index=True,
    )

    universe["information_date"] = pd.to_datetime(
        universe["information_date"],
        errors="coerce",
    )

    # ------------------------------------------------------------------
    # Pre-deduplication audit
    # ------------------------------------------------------------------

    duplicate_mask = universe.duplicated(
        subset=["plan_id", "plan_year"],
        keep=False,
    )

    duplicate_audit = universe.loc[duplicate_mask].copy()

    duplicate_audit_path = reports_validation / "sponsor_universe_duplicate_audit.csv"

    duplicate_audit.to_csv(
        duplicate_audit_path,
        index=False,
    )

    # Latest information date wins only when a duplicate plan-year
    # remains after use of the DOL Latest datasets.
    universe = universe.sort_values(
        ["plan_id", "plan_year", "information_date", "ack_id"],
        na_position="first",
    )

    universe = universe.drop_duplicates(
        subset=["plan_id", "plan_year"],
        keep="last",
    ).reset_index(drop=True)

    remaining_duplicates = int(
        universe.duplicated(
            subset=["plan_id", "plan_year"],
            keep=False,
        ).sum()
    )

    if remaining_duplicates != 0:
        raise RuntimeError("Plan-year uniqueness gate failed after duplicate resolution.")

    # ------------------------------------------------------------------
    # Identifier audit
    # ------------------------------------------------------------------

    universe["ein_valid"] = universe["ein"].astype(str).str.fullmatch(r"\d{9}")

    universe["plan_number_valid"] = universe["plan_number"].astype(str).str.fullmatch(r"\d{3}")

    identifier_audit = (
        universe.groupby("plan_year", dropna=False)
        .agg(
            rows=("plan_id", "size"),
            invalid_ein=("ein_valid", lambda s: int((~s).sum())),
            invalid_plan_number=(
                "plan_number_valid",
                lambda s: int((~s).sum()),
            ),
        )
        .reset_index()
    )

    identifier_audit.to_csv(
        reports_validation / "sponsor_universe_identifier_audit.csv",
        index=False,
    )

    # ------------------------------------------------------------------
    # Missingness
    # ------------------------------------------------------------------

    core_fields = [
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

    for field in core_fields:
        missing_count = int(universe[field].isna().sum())

        if field in {"ein", "plan_number", "sponsor_name"}:
            missing_count += int(universe[field].astype(str).str.strip().eq("").sum())

        missing_rows.append(
            {
                "field": field,
                "rows": len(universe),
                "missing_count": missing_count,
                "missing_rate": (missing_count / len(universe) if len(universe) else None),
            }
        )

    missingness = pd.DataFrame(missing_rows)

    missingness.to_csv(
        reports_validation / "sponsor_universe_missingness.csv",
        index=False,
    )

    # ------------------------------------------------------------------
    # Field mapping audit
    # ------------------------------------------------------------------

    pd.DataFrame(mapping_rows).to_csv(
        reports_validation / "form5500_field_mapping.csv",
        index=False,
    )

    # ------------------------------------------------------------------
    # Summary by plan year
    # ------------------------------------------------------------------

    summary = (
        universe.groupby("plan_year")
        .agg(
            plan_rows=("plan_id", "size"),
            unique_plans=("plan_id", "nunique"),
            unique_sponsors=("sponsor_id", "nunique"),
            assets_nonmissing=("assets", "count"),
            liabilities_nonmissing=("liabilities", "count"),
            contributions_nonmissing=("contributions", "count"),
            benefit_payments_nonmissing=(
                "benefit_payments",
                "count",
            ),
            participants_nonmissing=("participants", "count"),
            information_date_nonmissing=(
                "information_date",
                "count",
            ),
        )
        .reset_index()
    )

    total = pd.DataFrame(
        [
            {
                "plan_year": "TOTAL",
                "plan_rows": len(universe),
                "unique_plans": universe["plan_id"].nunique(),
                "unique_sponsors": universe["sponsor_id"].nunique(),
                "assets_nonmissing": universe["assets"].notna().sum(),
                "liabilities_nonmissing": universe["liabilities"].notna().sum(),
                "contributions_nonmissing": universe["contributions"].notna().sum(),
                "benefit_payments_nonmissing": universe["benefit_payments"].notna().sum(),
                "participants_nonmissing": universe["participants"].notna().sum(),
                "information_date_nonmissing": universe["information_date"].notna().sum(),
            }
        ]
    )

    summary_output = pd.concat(
        [summary.astype({"plan_year": str}), total],
        ignore_index=True,
    )

    summary_path = reports_tables / "sponsor_universe_summary.csv"

    summary_output.to_csv(
        summary_path,
        index=False,
    )

    # ------------------------------------------------------------------
    # Acceptance checks
    # ------------------------------------------------------------------

    represented_years = set(universe["plan_year"].dropna().astype(int))

    requested_years = set(years)

    absent_years = requested_years - represented_years

    if absent_years:
        raise RuntimeError(
            f"Requested plan years absent from final universe: {sorted(absent_years)}"
        )

    if universe["assets"].notna().sum() == 0:
        raise RuntimeError("No plan asset values were mapped.")

    if universe["liabilities"].notna().sum() == 0:
        raise RuntimeError("No plan liability values were mapped.")

    if universe["sponsor_id"].isna().any():
        raise RuntimeError("Sponsor ID missingness gate failed.")

    if universe["plan_id"].isna().any():
        raise RuntimeError("Plan ID missingness gate failed.")

    # ------------------------------------------------------------------
    # Save primary artifact
    # ------------------------------------------------------------------

    final_columns = [
        "sponsor_id",
        "plan_id",
        "ein",
        "plan_number",
        "sponsor_name",
        "plan_year",
        "assets",
        "liabilities",
        "contributions",
        "benefit_payments",
        "participants",
        "source_file",
        "information_date",
        "ack_id",
        "db_identification_method",
    ]

    output = universe[final_columns].copy()

    output_path = processed_root / "sponsor_plan_universe.parquet"

    output.to_parquet(
        output_path,
        index=False,
    )

    verification = pd.read_parquet(output_path)

    if len(verification) != len(output):
        raise RuntimeError("Parquet round-trip row-count mismatch.")

    if verification.duplicated(["plan_id", "plan_year"]).any():
        raise RuntimeError("Parquet uniqueness verification failed.")

    metadata = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "source": "U.S. Department of Labor Form 5500 datasets",
        "source_page": SOURCE_PAGE,
        "dataset_policy": "Latest",
        "db_identification": "Schedule SB linked by ACK_ID",
        "start_year": args.start_year,
        "end_year": args.end_year,
        "rows": int(len(output)),
        "unique_plans": int(output["plan_id"].nunique()),
        "unique_sponsors": int(output["sponsor_id"].nunique()),
        "duplicate_plan_years": 0,
        "primary_artifact": str(output_path.relative_to(repo)),
    }

    metadata_path = reports_validation / "sponsor_universe_build_metadata.json"

    metadata_path.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    print("")
    print("=" * 78)
    print("MILESTONE 2 ACCEPTANCE")
    print("=" * 78)
    print(f"SPONSOR_UNIVERSE_ROWS={len(output)}")
    print(f"UNIQUE_PLANS={output['plan_id'].nunique()}")
    print(f"UNIQUE_SPONSORS={output['sponsor_id'].nunique()}")
    print("DUPLICATE_PLAN_YEAR_ROWS=0")
    print(f"OUTPUT={output_path}")
    print(f"SUMMARY={summary_path}")
    print("FORM5500_SPONSOR_UNIVERSE_RESULT=PASS")


if __name__ == "__main__":
    main()
