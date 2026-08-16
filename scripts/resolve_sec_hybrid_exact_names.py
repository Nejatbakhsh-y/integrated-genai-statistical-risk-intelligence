"""Second-pass deterministic resolution of Step 3.6 unresolved sponsors."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

EXPECTED_TOTAL = 2153
EXPECTED_FIRST_PASS_UNRESOLVED = 485


def clean(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return str(value).strip()


def normalize_ein(value: Any) -> str:
    value = re.sub(
        r"\D",
        "",
        clean(value),
    )

    if len(value) != 9:
        return ""

    if value == "000000000":
        return ""

    return value


def normalize_name(value: Any) -> str:
    value = clean(value).upper()
    value = value.replace("&", " AND ")

    value = re.sub(
        r"[^A-Z0-9]+",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest().upper()


def exact_name_decision(
    sponsor_name: str,
    sponsor_ein: str,
    candidate_rows: list[dict[str, str]],
) -> tuple[str, str, str, str]:
    normalized_sponsor = normalize_name(sponsor_name)

    if not normalized_sponsor:
        return (
            "",
            "",
            "UNRESOLVED",
            "Sponsor legal name is blank.",
        )

    exact = [
        row for row in candidate_rows if normalize_name(row["sec_api_name"]) == normalized_sponsor
    ]

    if len(exact) == 0:
        return (
            "",
            "",
            "UNRESOLVED",
            ("No SEC API legal registrant name exactly equals the normalized sponsor legal name."),
        )

    if len(exact) > 1:
        return (
            "",
            "",
            "UNRESOLVED",
            ("Multiple SEC candidates have the same exact normalized legal name."),
        )

    candidate = exact[0]

    sec_ein = normalize_ein(candidate["sec_api_ein"])

    if sponsor_ein and sec_ein and sec_ein != sponsor_ein:
        return (
            "",
            "",
            "UNRESOLVED",
            ("Exact legal-name identity exists but the known SEC EIN contradicts the sponsor EIN."),
        )

    return (
        "MATCH",
        clean(candidate["manual_candidate_rank"]),
        "DETERMINISTIC_UNIQUE_EXACT_LEGAL_NAME",
        (
            "Exactly one SEC API legal registrant name equals "
            "the normalized Form 5500 sponsor legal name and "
            "there is no contradictory known SEC EIN."
        ),
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

    first_pass_path = (
        repo / "data" / "validation" / "sponsor_sec_secondary_identifier_resolution.csv"
    )

    candidate_path = (
        repo / "data" / "validation" / "sponsor_sec_secondary_identifier_candidates.csv"
    )

    unresolved_path = (
        repo / "data" / "validation" / "sponsor_sec_secondary_identifier_unresolved.csv"
    )

    output_path = repo / "data" / "validation" / "sponsor_sec_hybrid_resolution.csv"

    remaining_path = repo / "data" / "validation" / "sponsor_sec_hybrid_unresolved.csv"

    remaining_candidates_path = (
        repo / "data" / "validation" / "sponsor_sec_hybrid_unresolved_candidates.csv"
    )

    report_path = repo / "reports" / "validation" / "sec_hybrid_resolution_summary.json"

    first_pass = pd.read_csv(
        first_pass_path,
        dtype=str,
        keep_default_na=False,
    )

    candidates = pd.read_csv(
        candidate_path,
        dtype=str,
        keep_default_na=False,
    )

    unresolved = pd.read_csv(
        unresolved_path,
        dtype=str,
        keep_default_na=False,
    )

    if len(first_pass) != EXPECTED_TOTAL:
        raise RuntimeError("Expected 2,153 first-pass sponsors.")

    if len(unresolved) != EXPECTED_FIRST_PASS_UNRESOLVED:
        raise RuntimeError("Expected exactly 485 first-pass unresolved sponsors.")

    unresolved_ids = set(unresolved["sponsor_id"].astype(str))

    candidate_subset = candidates.loc[
        candidates["sponsor_id"].astype(str).isin(unresolved_ids)
    ].copy()

    resolution_rows: list[dict[str, str]] = []

    grouped_candidates = {
        sponsor_id: group.copy()
        for sponsor_id, group in candidate_subset.groupby(
            "sponsor_id",
            sort=False,
        )
    }

    for _, original in first_pass.iterrows():
        sponsor_id = clean(original["sponsor_id"])

        row = {column: clean(original[column]) for column in first_pass.columns}

        if clean(original["decision_provenance"]) != "UNRESOLVED":
            resolution_rows.append(row)
            continue

        group = grouped_candidates.get(sponsor_id)

        if group is None or len(group) == 0:
            raise RuntimeError(f"No candidate evidence for unresolved sponsor {sponsor_id}.")

        candidate_rows: list[dict[str, str]] = []

        for _, candidate in group.iterrows():
            candidate_rows.append(
                {
                    "manual_candidate_rank": clean(candidate["manual_candidate_rank"]),
                    "sec_api_name": clean(candidate["sec_api_name"]),
                    "sec_api_ein": clean(candidate["sec_api_ein"]),
                }
            )

        sponsor_name = clean(original["sponsor_name"])

        sponsor_ein = normalize_ein(original["sponsor_ein"])

        (
            decision,
            selected_rank,
            method,
            reason,
        ) = exact_name_decision(
            sponsor_name=sponsor_name,
            sponsor_ein=sponsor_ein,
            candidate_rows=candidate_rows,
        )

        if decision:
            row["final_decision"] = decision

            row["final_selected_candidate_rank"] = selected_rank

            row["decision_provenance"] = "MACHINE_DETERMINISTIC"

            row["decision_method"] = method

            row["decision_reason"] = reason

        else:
            row["final_decision"] = ""

            row["final_selected_candidate_rank"] = ""

            row["decision_provenance"] = "UNRESOLVED"

            row["decision_method"] = method

            row["decision_reason"] = reason

        resolution_rows.append(row)

    result = pd.DataFrame(resolution_rows)

    if len(result) != EXPECTED_TOTAL:
        raise RuntimeError("Hybrid resolution does not contain 2,153 sponsors.")

    if result["sponsor_id"].duplicated().any():
        raise RuntimeError("Duplicate sponsor in hybrid output.")

    human_mask = result["decision_provenance"].eq("HUMAN")

    deterministic_mask = result["decision_provenance"].eq("MACHINE_DETERMINISTIC")

    unresolved_mask = result["decision_provenance"].eq("UNRESOLVED")

    exact_name_mask = result["decision_method"].eq("DETERMINISTIC_UNIQUE_EXACT_LEGAL_NAME")

    # Existing decisions must survive unchanged.
    first_pass_resolved = first_pass.loc[~first_pass["decision_provenance"].eq("UNRESOLVED")].copy()

    result_index = result.set_index("sponsor_id")

    for _, old in first_pass_resolved.iterrows():
        sponsor_id = clean(old["sponsor_id"])

        current = result_index.loc[sponsor_id]

        for field in [
            "final_decision",
            "final_selected_candidate_rank",
            "decision_provenance",
            "decision_method",
        ]:
            if clean(old[field]) != clean(current[field]):
                raise RuntimeError(
                    f"Previously resolved decision changed for {sponsor_id}: field {field}."
                )

    remaining = result.loc[unresolved_mask].copy()

    remaining_ids = set(remaining["sponsor_id"].astype(str))

    remaining_candidates = candidates.loc[
        candidates["sponsor_id"].astype(str).isin(remaining_ids)
    ].copy()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        output_path,
        index=False,
    )

    remaining.to_csv(
        remaining_path,
        index=False,
    )

    remaining_candidates.to_csv(
        remaining_candidates_path,
        index=False,
    )

    first_pass_machine = int(first_pass["decision_provenance"].eq("MACHINE_DETERMINISTIC").sum())

    second_pass_exact_names = int(exact_name_mask.sum())

    final_machine = int(deterministic_mask.sum())

    final_unresolved = int(unresolved_mask.sum())

    report = {
        "step": "3.6",
        "protocol_version": "3.6-hybrid-v1",
        "total_sponsors": EXPECTED_TOTAL,
        "human_decisions_preserved": int(human_mask.sum()),
        "first_pass_machine_deterministic": (first_pass_machine),
        "second_pass_exact_legal_name_matches": (second_pass_exact_names),
        "final_machine_deterministic": (final_machine),
        "final_unresolved": (final_unresolved),
        "fuzzy_auto_accept": False,
        "fuzzy_auto_reject": False,
        "name_similarity_auto_accept": False,
        "machine_decisions_labeled_as_human": False,
        "score_100_manual_review_complete": True,
        "step_3_7_executed": False,
        "input_first_pass_sha256": sha256_file(first_pass_path),
        "output_hybrid_sha256": sha256_file(output_path),
        "remaining_unresolved_sha256": sha256_file(remaining_path),
    }

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"TOTAL_SPONSORS={len(result)}")

    print(f"HUMAN_DECISIONS_PRESERVED={int(human_mask.sum())}")

    print(f"FIRST_PASS_MACHINE_DETERMINISTIC={first_pass_machine}")

    print(f"SECOND_PASS_EXACT_LEGAL_NAME_MATCHES={second_pass_exact_names}")

    print(f"FINAL_MACHINE_DETERMINISTIC={final_machine}")

    print(f"FINAL_UNRESOLVED={final_unresolved}")

    print("FUZZY_AUTO_ACCEPT=NO")
    print("FUZZY_AUTO_REJECT=NO")
    print("NAME_SIMILARITY_AUTO_ACCEPT=NO")

    print("MACHINE_DECISIONS_LABELED_AS_HUMAN=NO")

    print("SCORE_100_MANUAL_REVIEW_COMPLETE=YES")

    print("STEP_3_7_EXECUTED=NO")

    if final_unresolved == 0:
        print("STEP_3_6_HYBRID_POPULATION_COMPLETE=YES")
        print("NEXT_ACTION=FINAL_STEP_3_6_AUDIT")
    else:
        print("STEP_3_6_HYBRID_POPULATION_COMPLETE=NO")
        print("NEXT_ACTION=TARGET_ONLY_FINAL_UNRESOLVED")


if __name__ == "__main__":
    main()
