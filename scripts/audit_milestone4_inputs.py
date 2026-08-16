"""Audit the frozen Milestone-4 input population."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

EXPECTED_UNIVERSE_ROWS = 79_782
EXPECTED_UNIVERSE_SPONSORS = 11_520
EXPECTED_UNIVERSE_PLANS = 13_527
EXPECTED_YEAR_START = 2015
EXPECTED_YEAR_END = 2024

EXPECTED_CROSSWALK_ROWS = 729
EXPECTED_LINKED_SPONSORS = 729
EXPECTED_UNIQUE_CIKS = 729
EXPECTED_LINKED_PLAN_ROWS = 8_950
EXPECTED_LINKED_PLANS = 1_294

EXPECTED_CROSSWALK_SHA256 = "264FF2DCD22223B654C122B7EE6F69B23CEA71A8885937D976C1BBCF8203D55A"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest().upper()


def clean_identifier(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()

    invalid = values.str.lower().isin(
        {
            "",
            "nan",
            "none",
            "null",
            "<na>",
        }
    )

    return values.mask(invalid)


def find_cik_column(crosswalk: pd.DataFrame) -> str:
    candidates = [column for column in crosswalk.columns if "cik" in column.lower()]

    if not candidates:
        raise RuntimeError("Crosswalk does not contain a CIK-like column.")

    diagnostics: list[str] = []

    for column in candidates:
        values = clean_identifier(crosswalk[column]).dropna()

        nonmissing = len(values)
        unique = values.nunique()

        diagnostics.append(f"{column}:nonmissing={nonmissing}:unique={unique}")

        if nonmissing == EXPECTED_LINKED_SPONSORS and unique == EXPECTED_UNIQUE_CIKS:
            return column

    raise RuntimeError(
        "No CIK column satisfies the frozen Milestone-3 contract. " + " | ".join(diagnostics)
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--repo",
        required=True,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    repo = Path(args.repo).resolve()

    universe_path = repo / "data" / "processed" / "sponsor_plan_universe.parquet"

    crosswalk_path = repo / "data" / "processed" / "sponsor_sec_crosswalk.parquet"

    audit_path = repo / "reports" / "validation" / "milestone4_step_4_0_input_audit.json"

    year_summary_path = repo / "reports" / "tables" / "milestone4_linked_population_by_year.csv"

    audit_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    year_summary_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not universe_path.exists():
        raise RuntimeError(f"Missing sponsor universe: {universe_path}")

    if not crosswalk_path.exists():
        raise RuntimeError(f"Missing sponsor-SEC crosswalk: {crosswalk_path}")

    crosswalk_hash = sha256_file(crosswalk_path)

    if crosswalk_hash != EXPECTED_CROSSWALK_SHA256:
        raise RuntimeError("Milestone-3 crosswalk SHA-256 drift detected.")

    universe = pd.read_parquet(universe_path)
    crosswalk = pd.read_parquet(crosswalk_path)

    required_universe = [
        "sponsor_id",
        "plan_id",
        "plan_year",
        "assets",
        "liabilities",
        "contributions",
        "benefit_payments",
        "participants",
        "information_date",
    ]

    missing_universe = [column for column in required_universe if column not in universe.columns]

    if missing_universe:
        raise RuntimeError(f"Missing universe fields: {missing_universe}")

    if "sponsor_id" not in crosswalk.columns:
        raise RuntimeError("Crosswalk does not contain sponsor_id.")

    universe["sponsor_id"] = clean_identifier(universe["sponsor_id"])

    universe["plan_id"] = clean_identifier(universe["plan_id"])

    crosswalk["sponsor_id"] = clean_identifier(crosswalk["sponsor_id"])

    if universe["sponsor_id"].isna().any():
        raise RuntimeError("Sponsor universe contains blank sponsor_id.")

    if universe["plan_id"].isna().any():
        raise RuntimeError("Sponsor universe contains blank plan_id.")

    if crosswalk["sponsor_id"].isna().any():
        raise RuntimeError("Crosswalk contains blank sponsor_id.")

    universe["plan_year"] = pd.to_numeric(
        universe["plan_year"],
        errors="raise",
    ).astype(int)

    universe_rows = len(universe)

    universe_sponsors = universe["sponsor_id"].nunique()
    universe_plans = universe["plan_id"].nunique()

    year_start = int(universe["plan_year"].min())
    year_end = int(universe["plan_year"].max())

    duplicate_plan_year_rows = int(
        universe.duplicated(
            ["plan_id", "plan_year"],
            keep=False,
        ).sum()
    )

    if universe_rows != EXPECTED_UNIVERSE_ROWS:
        raise RuntimeError(f"Universe row drift: {universe_rows}")

    if universe_sponsors != EXPECTED_UNIVERSE_SPONSORS:
        raise RuntimeError(f"Universe sponsor drift: {universe_sponsors}")

    if universe_plans != EXPECTED_UNIVERSE_PLANS:
        raise RuntimeError(f"Universe plan drift: {universe_plans}")

    if year_start != EXPECTED_YEAR_START:
        raise RuntimeError(f"Unexpected minimum plan year: {year_start}")

    if year_end != EXPECTED_YEAR_END:
        raise RuntimeError(f"Unexpected maximum plan year: {year_end}")

    if duplicate_plan_year_rows != 0:
        raise RuntimeError("Duplicate plan-year observations detected.")

    if len(crosswalk) != EXPECTED_CROSSWALK_ROWS:
        raise RuntimeError(f"Crosswalk row drift: {len(crosswalk)}")

    crosswalk_sponsors = crosswalk["sponsor_id"].nunique()

    if crosswalk_sponsors != EXPECTED_LINKED_SPONSORS:
        raise RuntimeError(f"Crosswalk sponsor drift: {crosswalk_sponsors}")

    duplicate_crosswalk_sponsors = int(
        crosswalk.duplicated(
            ["sponsor_id"],
            keep=False,
        ).sum()
    )

    if duplicate_crosswalk_sponsors != 0:
        raise RuntimeError("Duplicate sponsor rows detected in crosswalk.")

    cik_column = find_cik_column(crosswalk)

    cik_values = clean_identifier(crosswalk[cik_column])

    unique_ciks = cik_values.nunique(dropna=True)

    duplicate_cik_rows = int(cik_values[cik_values.notna()].duplicated(keep=False).sum())

    if unique_ciks != EXPECTED_UNIQUE_CIKS:
        raise RuntimeError(f"CIK count drift: {unique_ciks}")

    if duplicate_cik_rows != 0:
        raise RuntimeError("Duplicate SEC CIKs detected in final crosswalk.")

    linked_sponsor_ids = set(crosswalk["sponsor_id"].tolist())

    linked = universe.loc[universe["sponsor_id"].isin(linked_sponsor_ids)].copy()

    linked_plan_rows = len(linked)

    linked_sponsors = linked["sponsor_id"].nunique()
    linked_plans = linked["plan_id"].nunique()

    if linked_plan_rows != EXPECTED_LINKED_PLAN_ROWS:
        raise RuntimeError(f"Linked plan-row drift: {linked_plan_rows}")

    if linked_sponsors != EXPECTED_LINKED_SPONSORS:
        raise RuntimeError(f"Linked sponsor drift: {linked_sponsors}")

    if linked_plans != EXPECTED_LINKED_PLANS:
        raise RuntimeError(f"Linked plan drift: {linked_plans}")

    sponsor_year_count = (
        linked[
            [
                "sponsor_id",
                "plan_year",
            ]
        ]
        .drop_duplicates()
        .shape[0]
    )

    year_summary = (
        linked.groupby(
            "plan_year",
            as_index=False,
        )
        .agg(
            plan_rows=("plan_id", "size"),
            unique_sponsors=(
                "sponsor_id",
                "nunique",
            ),
            unique_plans=(
                "plan_id",
                "nunique",
            ),
            assets_nonmissing=(
                "assets",
                "count",
            ),
            liabilities_nonmissing=(
                "liabilities",
                "count",
            ),
            contributions_nonmissing=(
                "contributions",
                "count",
            ),
            benefit_payments_nonmissing=(
                "benefit_payments",
                "count",
            ),
            participants_nonmissing=(
                "participants",
                "count",
            ),
            information_date_nonmissing=(
                "information_date",
                "count",
            ),
        )
        .sort_values("plan_year")
    )

    year_summary.to_csv(
        year_summary_path,
        index=False,
    )

    audit = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "milestone": 4,
        "step": "4.0",
        "base_release": "v0.4.0-entity-linkage",
        "target_release": "v0.5.0-structured-panel",
        "sponsor_universe_path": str(universe_path.relative_to(repo)),
        "sponsor_universe_sha256": sha256_file(universe_path),
        "crosswalk_path": str(crosswalk_path.relative_to(repo)),
        "crosswalk_sha256": crosswalk_hash,
        "crosswalk_cik_column": cik_column,
        "universe_rows": universe_rows,
        "universe_unique_sponsors": int(universe_sponsors),
        "universe_unique_plans": int(universe_plans),
        "plan_year_start": year_start,
        "plan_year_end": year_end,
        "duplicate_plan_year_rows": (duplicate_plan_year_rows),
        "crosswalk_rows": int(len(crosswalk)),
        "crosswalk_unique_sponsors": int(crosswalk_sponsors),
        "crosswalk_unique_ciks": int(unique_ciks),
        "duplicate_crosswalk_sponsor_rows": (duplicate_crosswalk_sponsors),
        "duplicate_cik_rows": duplicate_cik_rows,
        "linked_plan_rows": linked_plan_rows,
        "linked_unique_sponsors": int(linked_sponsors),
        "linked_unique_plans": int(linked_plans),
        "linked_unique_sponsor_years": int(sponsor_year_count),
        "structured_x_constructed": False,
        "forecast_cutoff_policy_frozen": False,
        "step_4_0_status": "PASS",
        "next_step": "4.1",
    }

    audit_path.write_text(
        json.dumps(
            audit,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"UNIVERSE_ROWS={universe_rows}")
    print(f"UNIVERSE_UNIQUE_SPONSORS={universe_sponsors}")
    print(f"UNIVERSE_UNIQUE_PLANS={universe_plans}")
    print(f"PLAN_YEAR_START={year_start}")
    print(f"PLAN_YEAR_END={year_end}")
    print(f"DUPLICATE_PLAN_YEAR_ROWS={duplicate_plan_year_rows}")
    print(f"CROSSWALK_ROWS={len(crosswalk)}")
    print(f"CROSSWALK_UNIQUE_SPONSORS={crosswalk_sponsors}")
    print(f"CROSSWALK_CIK_COLUMN={cik_column}")
    print(f"CROSSWALK_UNIQUE_CIKS={unique_ciks}")
    print(f"LINKED_PLAN_ROWS={linked_plan_rows}")
    print(f"LINKED_UNIQUE_SPONSORS={linked_sponsors}")
    print(f"LINKED_UNIQUE_PLANS={linked_plans}")
    print(f"LINKED_UNIQUE_SPONSOR_YEARS={sponsor_year_count}")
    print(f"CROSSWALK_SHA256={crosswalk_hash}")
    print("MILESTONE4_INPUT_RECONCILIATION=PASS")
    print("MILESTONE4_STEP_4_0_INPUT_AUDIT=PASS")


if __name__ == "__main__":
    main()
