"""Build the final Step 3.7 sponsor-to-SEC crosswalk."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

TOTAL_SPONSORS = 11520

STEP34_HIGH_CONFIDENCE = 723
STEP34_MANUAL_REVIEW = 132
STEP34_UNMATCHED = 10665

STEP36_REVIEWED = 2153
STEP36_LINKED = 6
STEP36_SUPPORTED_NO_MATCH = 1663
STEP36_UNRESOLVED = 484
STEP36_NO_CANDIDATE = 8512

EXPECTED_FINAL_LINKED = 729
EXPECTED_FINAL_UNLINKED = 10791


def clean(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return str(value).strip()


def normalize_cik(value: Any) -> str:
    value = clean(value)

    digits = re.sub(
        r"\D",
        "",
        value,
    )

    if not digits:
        return ""

    return f"{int(digits):010d}"


def sponsor_ein(sponsor_id: Any) -> str:
    value = clean(sponsor_id)

    match = re.fullmatch(
        r"SP-(\d{9})",
        value,
    )

    if match is None:
        return ""

    return match.group(1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest().upper()


def optional(
    row: pd.Series,
    column: str,
) -> str:
    if column not in row.index:
        return ""

    return clean(row[column])


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

    step34_path = (
        repo
        / "data"
        / "interim"
        / "linkage"
        / "20260816T004352Z"
        / "step_3_4"
        / "sponsor_sec_deterministic_names.parquet"
    )

    step36_disposition_path = (
        repo / "data" / "validation" / "sponsor_sec_step_3_6_final_disposition.csv"
    )

    step36_accepted_path = (
        repo / "data" / "validation" / "sponsor_sec_step_3_6_accepted_matches.csv"
    )

    crosswalk_path = repo / "data" / "processed" / "sponsor_sec_crosswalk.parquet"

    crosswalk_audit_path = repo / "data" / "validation" / "sponsor_sec_crosswalk_audit.csv"

    full_disposition_path = (
        repo / "data" / "validation" / "sponsor_sec_step_3_7_full_disposition.csv"
    )

    summary_path = repo / "reports" / "validation" / "step_3_7_crosswalk_summary.json"

    step34 = pd.read_parquet(step34_path)

    step36 = pd.read_csv(
        step36_disposition_path,
        dtype=str,
        keep_default_na=False,
    )

    accepted36 = pd.read_csv(
        step36_accepted_path,
        dtype=str,
        keep_default_na=False,
    )

    # ------------------------------------------------------------------
    # Step 3.4 validation
    # ------------------------------------------------------------------

    required34 = {
        "sponsor_id",
        "sec_cik",
        "sec_name",
        "match_state_after_deterministic",
    }

    missing34 = required34 - set(step34.columns)

    if missing34:
        raise RuntimeError(f"Missing Step 3.4 columns: {sorted(missing34)}")

    if len(step34) != TOTAL_SPONSORS:
        raise RuntimeError(f"Expected {TOTAL_SPONSORS} Step 3.4 rows; found {len(step34)}.")

    if step34["sponsor_id"].astype(str).str.strip().nunique() != TOTAL_SPONSORS:
        raise RuntimeError("Step 3.4 does not contain exactly 11,520 unique sponsor IDs.")

    step34_state = step34["match_state_after_deterministic"].astype(str).str.strip().str.upper()

    high34 = step34.loc[step34_state.eq("HIGH_CONFIDENCE_MATCH")].copy()

    manual34 = step34.loc[step34_state.eq("MANUAL_REVIEW")].copy()

    unmatched34 = step34.loc[step34_state.eq("UNMATCHED")].copy()

    if len(high34) != STEP34_HIGH_CONFIDENCE:
        raise RuntimeError("Step 3.4 HIGH_CONFIDENCE_MATCH count is not 723.")

    if len(manual34) != STEP34_MANUAL_REVIEW:
        raise RuntimeError("Step 3.4 MANUAL_REVIEW count is not 132.")

    if len(unmatched34) != STEP34_UNMATCHED:
        raise RuntimeError("Step 3.4 UNMATCHED count is not 10,665.")

    # ------------------------------------------------------------------
    # Step 3.6 validation
    # ------------------------------------------------------------------

    if len(step36) != STEP36_REVIEWED:
        raise RuntimeError("Step 3.6 final disposition count is not 2,153.")

    if step36["sponsor_id"].astype(str).str.strip().nunique() != STEP36_REVIEWED:
        raise RuntimeError("Step 3.6 final disposition contains duplicate sponsor IDs.")

    if len(accepted36) != STEP36_LINKED:
        raise RuntimeError("Step 3.6 accepted-match count is not six.")

    if accepted36["sponsor_id"].astype(str).str.strip().nunique() != STEP36_LINKED:
        raise RuntimeError("Step 3.6 accepted matches contain duplicate sponsor IDs.")

    unmatched34_ids = set(unmatched34["sponsor_id"].astype(str).str.strip())

    step36_ids = set(step36["sponsor_id"].astype(str).str.strip())

    if not step36_ids.issubset(unmatched34_ids):
        invalid = sorted(step36_ids - unmatched34_ids)

        raise RuntimeError(
            f"One or more Step 3.6 sponsors were not Step 3.4 UNMATCHED sponsors: {invalid[:10]}"
        )

    accepted36_ids = set(accepted36["sponsor_id"].astype(str).str.strip())

    high34_ids = set(high34["sponsor_id"].astype(str).str.strip())

    overlap = accepted36_ids & high34_ids

    if overlap:
        raise RuntimeError(
            f"Step 3.4 and Step 3.6 accepted sponsor sets overlap unexpectedly: {sorted(overlap)}"
        )

    # ------------------------------------------------------------------
    # Build Step 3.4 accepted links
    # ------------------------------------------------------------------

    crosswalk_rows: list[dict[str, Any]] = []

    for _, row in high34.iterrows():
        sponsor_id = clean(row["sponsor_id"])

        cik = normalize_cik(row["sec_cik"])

        if not cik:
            raise RuntimeError(f"Step 3.4 accepted sponsor {sponsor_id} has blank SEC CIK.")

        crosswalk_rows.append(
            {
                "sponsor_id": sponsor_id,
                "sponsor_ein": sponsor_ein(sponsor_id),
                "sponsor_name": optional(
                    row,
                    "sponsor_name",
                ),
                "sec_cik": cik,
                "sec_name": clean(row["sec_name"]),
                "linkage_source": ("STEP_3_4_DETERMINISTIC"),
                "linkage_provenance": ("DETERMINISTIC"),
                "linkage_method": optional(
                    row,
                    "match_method",
                ),
                "linkage_tier": optional(
                    row,
                    "match_tier",
                ),
                "source_state": ("HIGH_CONFIDENCE_MATCH"),
                "step_3_6_final_disposition": "",
            }
        )

    # ------------------------------------------------------------------
    # Build Step 3.6 accepted links
    # ------------------------------------------------------------------

    for _, row in accepted36.iterrows():
        sponsor_id = clean(row["sponsor_id"])

        cik = normalize_cik(row["sec_cik"])

        if not cik:
            raise RuntimeError(f"Step 3.6 accepted sponsor {sponsor_id} has blank SEC CIK.")

        crosswalk_rows.append(
            {
                "sponsor_id": sponsor_id,
                "sponsor_ein": clean(row["sponsor_ein"]),
                "sponsor_name": clean(row["sponsor_name"]),
                "sec_cik": cik,
                "sec_name": clean(row["sec_name"]),
                "linkage_source": ("STEP_3_6_HYBRID"),
                "linkage_provenance": clean(row["decision_provenance"]),
                "linkage_method": clean(row["decision_method"]),
                "linkage_tier": "",
                "source_state": "STEP_3_6_ACCEPTED",
                "step_3_6_final_disposition": clean(row["step_3_6_final_disposition"]),
            }
        )

    crosswalk = pd.DataFrame(crosswalk_rows)

    if len(crosswalk) != EXPECTED_FINAL_LINKED:
        raise RuntimeError(
            f"Expected {EXPECTED_FINAL_LINKED} crosswalk rows; found {len(crosswalk)}."
        )

    if crosswalk["sponsor_id"].duplicated().any():
        duplicates = (
            crosswalk.loc[
                crosswalk["sponsor_id"].duplicated(keep=False),
                "sponsor_id",
            ]
            .astype(str)
            .tolist()
        )

        raise RuntimeError(f"Crosswalk has duplicate sponsor IDs: {duplicates[:20]}")

    if crosswalk["sec_cik"].astype(str).str.strip().eq("").any():
        raise RuntimeError("Crosswalk contains blank SEC CIKs.")

    invalid_cik = ~crosswalk["sec_cik"].astype(str).str.fullmatch(r"\d{10}")

    if invalid_cik.any():
        raise RuntimeError("Crosswalk contains a malformed SEC CIK.")

    # ------------------------------------------------------------------
    # Construct all-11,520 sponsor disposition audit
    # ------------------------------------------------------------------

    step36_lookup = step36.set_index("sponsor_id").to_dict("index")

    crosswalk_lookup = crosswalk.set_index("sponsor_id").to_dict("index")

    full_rows: list[dict[str, Any]] = []

    for _, row in step34.iterrows():
        sponsor_id = clean(row["sponsor_id"])

        state = clean(row["match_state_after_deterministic"]).upper()

        final_status = ""
        final_reason = ""
        final_cik = ""
        final_sec_name = ""
        final_source = ""

        if state == "HIGH_CONFIDENCE_MATCH":
            linked = crosswalk_lookup[sponsor_id]

            final_status = "LINKED"
            final_reason = "STEP_3_4_HIGH_CONFIDENCE_MATCH"
            final_cik = clean(linked["sec_cik"])
            final_sec_name = clean(linked["sec_name"])
            final_source = clean(linked["linkage_source"])

        elif state == "MANUAL_REVIEW":
            final_status = "UNLINKED"
            final_reason = "STEP_3_4_MANUAL_REVIEW_RETAINED"

        elif state == "UNMATCHED":
            step36_row = step36_lookup.get(sponsor_id)

            if step36_row is None:
                final_status = "UNLINKED"
                final_reason = "NO_QUALIFYING_FUZZY_CANDIDATE"

            else:
                disposition = clean(step36_row["step_3_6_final_disposition"])

                if disposition.startswith("LINKED_"):
                    linked = crosswalk_lookup[sponsor_id]

                    final_status = "LINKED"
                    final_reason = disposition
                    final_cik = clean(linked["sec_cik"])
                    final_sec_name = clean(linked["sec_name"])
                    final_source = clean(linked["linkage_source"])

                elif disposition.startswith("REJECTED_"):
                    final_status = "UNLINKED"
                    final_reason = "STEP_3_6_SUPPORTED_NO_MATCH"

                elif disposition == "RETAIN_UNMATCHED_UNRESOLVED":
                    final_status = "UNLINKED"
                    final_reason = "STEP_3_6_UNRESOLVED_RETAINED"

                else:
                    raise RuntimeError(
                        f"Unexpected Step 3.6 disposition for {sponsor_id}: {disposition}"
                    )

        else:
            raise RuntimeError(f"Unexpected Step 3.4 state: {state}")

        full_rows.append(
            {
                "sponsor_id": sponsor_id,
                "sponsor_ein": sponsor_ein(sponsor_id),
                "sponsor_name": optional(
                    row,
                    "sponsor_name",
                ),
                "step_3_4_state": state,
                "final_linkage_status": final_status,
                "final_linkage_reason": final_reason,
                "sec_cik": final_cik,
                "sec_name": final_sec_name,
                "linkage_source": final_source,
            }
        )

    full = pd.DataFrame(full_rows)

    if len(full) != TOTAL_SPONSORS:
        raise RuntimeError("Full Step 3.7 disposition does not contain 11,520 sponsors.")

    if full["sponsor_id"].duplicated().any():
        raise RuntimeError("Full Step 3.7 disposition contains duplicate sponsors.")

    linked_mask = full["final_linkage_status"].eq("LINKED")

    no_candidate_mask = full["final_linkage_reason"].eq("NO_QUALIFYING_FUZZY_CANDIDATE")

    manual_review_mask = full["final_linkage_reason"].eq("STEP_3_4_MANUAL_REVIEW_RETAINED")

    supported_no_match_mask = full["final_linkage_reason"].eq("STEP_3_6_SUPPORTED_NO_MATCH")

    unresolved_mask = full["final_linkage_reason"].eq("STEP_3_6_UNRESOLVED_RETAINED")

    step34_linked_mask = linked_mask & full["linkage_source"].eq("STEP_3_4_DETERMINISTIC")

    step36_linked_mask = linked_mask & full["linkage_source"].eq("STEP_3_6_HYBRID")

    assert int(linked_mask.sum()) == EXPECTED_FINAL_LINKED

    assert int(step34_linked_mask.sum()) == STEP34_HIGH_CONFIDENCE

    assert int(step36_linked_mask.sum()) == STEP36_LINKED

    assert int(manual_review_mask.sum()) == STEP34_MANUAL_REVIEW

    assert int(supported_no_match_mask.sum()) == STEP36_SUPPORTED_NO_MATCH

    assert int(unresolved_mask.sum()) == STEP36_UNRESOLVED

    assert int(no_candidate_mask.sum()) == STEP36_NO_CANDIDATE

    assert (
        int(linked_mask.sum())
        + int(manual_review_mask.sum())
        + int(supported_no_match_mask.sum())
        + int(unresolved_mask.sum())
        + int(no_candidate_mask.sum())
        == TOTAL_SPONSORS
    )

    # ------------------------------------------------------------------
    # Persist Step 3.7 artifacts
    # ------------------------------------------------------------------

    crosswalk_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    crosswalk_audit_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    crosswalk = crosswalk.sort_values(
        [
            "sponsor_id",
        ],
        kind="stable",
    ).reset_index(drop=True)

    full = full.sort_values(
        [
            "sponsor_id",
        ],
        kind="stable",
    ).reset_index(drop=True)

    crosswalk.to_parquet(
        crosswalk_path,
        index=False,
    )

    crosswalk.to_csv(
        crosswalk_audit_path,
        index=False,
    )

    full.to_csv(
        full_disposition_path,
        index=False,
    )

    unique_ciks = int(crosswalk["sec_cik"].nunique())

    duplicate_cik_rows = int(crosswalk["sec_cik"].duplicated(keep=False).sum())

    summary = {
        "milestone": 3,
        "step": "3.7",
        "status": "PASS",
        "created_utc": datetime.now(UTC).isoformat(),
        "source_step_3_4": {
            "rows": TOTAL_SPONSORS,
            "high_confidence_match": (STEP34_HIGH_CONFIDENCE),
            "manual_review": (STEP34_MANUAL_REVIEW),
            "unmatched": (STEP34_UNMATCHED),
            "sha256": sha256_file(step34_path),
        },
        "source_step_3_6": {
            "review_population": (STEP36_REVIEWED),
            "accepted_matches": (STEP36_LINKED),
            "supported_no_match": (STEP36_SUPPORTED_NO_MATCH),
            "unresolved_retained_unmatched": (STEP36_UNRESOLVED),
            "no_qualifying_fuzzy_candidate": (STEP36_NO_CANDIDATE),
            "accepted_matches_sha256": (sha256_file(step36_accepted_path)),
            "final_disposition_sha256": (sha256_file(step36_disposition_path)),
        },
        "final_crosswalk": {
            "linked_sponsors": (EXPECTED_FINAL_LINKED),
            "step_3_4_links": (STEP34_HIGH_CONFIDENCE),
            "step_3_6_links": (STEP36_LINKED),
            "unique_sec_ciks": (unique_ciks),
            "rows_in_duplicate_cik_groups": (duplicate_cik_rows),
            "crosswalk_sha256": (sha256_file(crosswalk_path)),
            "crosswalk_audit_sha256": (sha256_file(crosswalk_audit_path)),
        },
        "full_disposition": {
            "total_sponsors": (TOTAL_SPONSORS),
            "linked": (EXPECTED_FINAL_LINKED),
            "unlinked": (EXPECTED_FINAL_UNLINKED),
            "step_3_4_manual_review_retained": (STEP34_MANUAL_REVIEW),
            "step_3_6_supported_no_match": (STEP36_SUPPORTED_NO_MATCH),
            "step_3_6_unresolved_retained": (STEP36_UNRESOLVED),
            "no_qualifying_fuzzy_candidate": (STEP36_NO_CANDIDATE),
            "sha256": sha256_file(full_disposition_path),
        },
        "policies": {
            "step_3_4_manual_review_auto_linked": False,
            "step_3_6_unresolved_auto_linked": False,
            "step_3_6_unresolved_reclassified_no_match": False,
            "fuzzy_score_auto_accept": False,
            "fuzzy_score_auto_reject": False,
        },
    }

    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("STEP_3_7_TOTAL_SPONSORS=11520")
    print("STEP_3_7_STEP_3_4_LINKS=723")
    print("STEP_3_7_STEP_3_6_LINKS=6")
    print("STEP_3_7_FINAL_LINKED_SPONSORS=729")
    print("STEP_3_7_FINAL_UNLINKED_SPONSORS=10791")
    print("STEP_3_7_STEP_3_4_MANUAL_REVIEW_RETAINED=132")
    print("STEP_3_7_STEP_3_6_SUPPORTED_NO_MATCH=1663")
    print("STEP_3_7_STEP_3_6_UNRESOLVED_RETAINED=484")
    print("STEP_3_7_NO_QUALIFYING_FUZZY_CANDIDATE=8512")
    print(f"STEP_3_7_UNIQUE_SEC_CIKS={unique_ciks}")
    print(f"STEP_3_7_ROWS_IN_DUPLICATE_CIK_GROUPS={duplicate_cik_rows}")
    print("FUZZY_AUTO_ACCEPT=NO")
    print("FUZZY_AUTO_REJECT=NO")
    print("STEP_3_4_MANUAL_REVIEW_AUTO_LINKED=NO")
    print("STEP_3_6_UNRESOLVED_AUTO_LINKED=NO")
    print("STEP_3_7_POPULATION_RECONCILIATION=PASS")
    print("STEP_3_7_CROSSWALK_INTEGRITY=PASS")
    print("STEP_3_7_STATUS=PASS")


if __name__ == "__main__":
    main()
