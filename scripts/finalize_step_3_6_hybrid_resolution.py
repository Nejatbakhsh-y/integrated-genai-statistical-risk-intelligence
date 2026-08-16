"""Finalize Step 3.6 using conservative unresolved retention."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

EXPECTED_TOTAL = 2153
EXPECTED_LINKED = 6
EXPECTED_SUPPORTED_NO_MATCH = 1663
EXPECTED_UNRESOLVED = 484


def clean(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return str(value).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest().upper()


def classify_final_disposition(
    provenance: str,
    decision: str,
    method: str,
) -> tuple[str, bool]:
    provenance = clean(provenance).upper()
    decision = clean(decision).upper()
    method = clean(method).upper()

    if provenance == "HUMAN" and decision == "MATCH":
        return "LINKED_MANUAL", True

    if provenance == "HUMAN" and decision == "NO_MATCH":
        return "REJECTED_MANUAL", False

    if (
        provenance == "MACHINE_DETERMINISTIC"
        and decision == "MATCH"
        and method == "DETERMINISTIC_EXACT_EIN"
    ):
        return (
            "LINKED_DETERMINISTIC_EXACT_EIN",
            True,
        )

    if (
        provenance == "MACHINE_DETERMINISTIC"
        and decision == "NO_MATCH"
        and method == "DETERMINISTIC_ALL_SEC_EINS_DIFFER"
    ):
        return (
            "REJECTED_DETERMINISTIC_EIN_MISMATCH",
            False,
        )

    if (
        provenance == "MACHINE_DETERMINISTIC"
        and decision == "MATCH"
        and method == "DETERMINISTIC_UNIQUE_EXACT_LEGAL_NAME"
    ):
        return (
            "LINKED_DETERMINISTIC_EXACT_LEGAL_NAME",
            True,
        )

    if provenance == "UNRESOLVED":
        if decision:
            raise RuntimeError(
                "UNRESOLVED sponsor unexpectedly contains a nonblank final decision."
            )

        return (
            "RETAIN_UNMATCHED_UNRESOLVED",
            False,
        )

    raise RuntimeError(
        "Unsupported Step 3.6 state: "
        f"provenance={provenance!r}, "
        f"decision={decision!r}, "
        f"method={method!r}"
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

    hybrid_path = repo / "data" / "validation" / "sponsor_sec_hybrid_resolution.csv"

    candidates_path = (
        repo / "data" / "validation" / "sponsor_sec_secondary_identifier_candidates.csv"
    )

    disposition_path = repo / "data" / "validation" / "sponsor_sec_step_3_6_final_disposition.csv"

    accepted_path = repo / "data" / "validation" / "sponsor_sec_step_3_6_accepted_matches.csv"

    policy_path = repo / "reports" / "validation" / "step_3_6_unresolved_retention_policy.json"

    audit_path = repo / "reports" / "validation" / "step_3_6_final_audit.json"

    hybrid = pd.read_csv(
        hybrid_path,
        dtype=str,
        keep_default_na=False,
    )

    candidates = pd.read_csv(
        candidates_path,
        dtype=str,
        keep_default_na=False,
    )

    if len(hybrid) != EXPECTED_TOTAL:
        raise RuntimeError(f"Expected {EXPECTED_TOTAL} hybrid sponsors; found {len(hybrid)}.")

    if hybrid["sponsor_id"].duplicated().any():
        raise RuntimeError("Duplicate sponsor_id detected in hybrid resolution.")

    final_rows: list[dict[str, Any]] = []

    for _, source in hybrid.iterrows():
        disposition, accepted = classify_final_disposition(
            provenance=source["decision_provenance"],
            decision=source["final_decision"],
            method=source["decision_method"],
        )

        row = {column: clean(source[column]) for column in hybrid.columns}

        row["step_3_6_final_disposition"] = disposition
        row["linkage_accepted"] = accepted

        if disposition == "RETAIN_UNMATCHED_UNRESOLVED":
            row["unresolved_retention_reason"] = (
                "Identity was not established under an approved "
                "human or deterministic Step 3.6 linkage rule. "
                "The sponsor therefore remains unmatched without "
                "being reclassified as NO_MATCH."
            )
        else:
            row["unresolved_retention_reason"] = ""

        final_rows.append(row)

    final = pd.DataFrame(final_rows)

    linked_mask = final["step_3_6_final_disposition"].str.startswith("LINKED_")

    rejected_mask = final["step_3_6_final_disposition"].str.startswith("REJECTED_")

    unresolved_mask = final["step_3_6_final_disposition"].eq("RETAIN_UNMATCHED_UNRESOLVED")

    linked_count = int(linked_mask.sum())
    rejected_count = int(rejected_mask.sum())
    unresolved_count = int(unresolved_mask.sum())

    if linked_count != EXPECTED_LINKED:
        raise RuntimeError(f"Expected {EXPECTED_LINKED} linked sponsors; found {linked_count}.")

    if rejected_count != EXPECTED_SUPPORTED_NO_MATCH:
        raise RuntimeError(
            f"Expected {EXPECTED_SUPPORTED_NO_MATCH} supported "
            f"NO_MATCH sponsors; found {rejected_count}."
        )

    if unresolved_count != EXPECTED_UNRESOLVED:
        raise RuntimeError(
            f"Expected {EXPECTED_UNRESOLVED} unresolved sponsors; found {unresolved_count}."
        )

    if linked_count + rejected_count + unresolved_count != EXPECTED_TOTAL:
        raise RuntimeError("Step 3.6 final populations do not reconcile.")

    accepted = final.loc[linked_mask].copy()

    accepted_rows: list[dict[str, Any]] = []

    for _, match in accepted.iterrows():
        sponsor_id = clean(match["sponsor_id"])

        selected_rank = clean(match["final_selected_candidate_rank"])

        if not selected_rank:
            raise RuntimeError(f"Accepted sponsor {sponsor_id} has no selected candidate rank.")

        sponsor_condition = candidates["sponsor_id"].astype(str).str.strip().eq(sponsor_id)

        rank_condition = (
            candidates["manual_candidate_rank"].astype(str).str.strip().eq(selected_rank)
        )

        candidate = candidates.loc[sponsor_condition & rank_condition]

        if len(candidate) != 1:
            raise RuntimeError(
                f"Accepted sponsor {sponsor_id}, rank "
                f"{selected_rank}, resolves to "
                f"{len(candidate)} candidate rows."
            )

        evidence = candidate.iloc[0]

        sec_cik = clean(
            evidence.get(
                "sec_api_cik",
                "",
            )
        )

        if not sec_cik:
            sec_cik = clean(
                evidence.get(
                    "sec_cik",
                    "",
                )
            )

        sec_name = clean(
            evidence.get(
                "sec_api_name",
                "",
            )
        )

        if not sec_name:
            sec_name = clean(
                evidence.get(
                    "sec_name",
                    "",
                )
            )

        accepted_rows.append(
            {
                "sponsor_id": sponsor_id,
                "sponsor_name": clean(
                    match.get(
                        "sponsor_name",
                        "",
                    )
                ),
                "sponsor_ein": clean(
                    match.get(
                        "sponsor_ein",
                        "",
                    )
                ),
                "selected_candidate_rank": selected_rank,
                "sec_cik": sec_cik,
                "sec_name": sec_name,
                "sec_ein": clean(
                    evidence.get(
                        "sec_api_ein",
                        "",
                    )
                ),
                "decision_provenance": clean(match["decision_provenance"]),
                "decision_method": clean(match["decision_method"]),
                "step_3_6_final_disposition": clean(match["step_3_6_final_disposition"]),
                "candidate_row_sha256": clean(
                    evidence.get(
                        "candidate_row_sha256",
                        "",
                    )
                ),
            }
        )

    accepted_output = pd.DataFrame(accepted_rows)

    if len(accepted_output) != EXPECTED_LINKED:
        raise RuntimeError("Accepted-match artifact does not contain exactly six rows.")

    if accepted_output["sponsor_id"].duplicated().any():
        raise RuntimeError("Accepted-match artifact contains duplicate sponsors.")

    manual_links = int(accepted_output["step_3_6_final_disposition"].eq("LINKED_MANUAL").sum())

    exact_ein_links = int(
        accepted_output["step_3_6_final_disposition"].eq("LINKED_DETERMINISTIC_EXACT_EIN").sum()
    )

    exact_name_links = int(
        accepted_output["step_3_6_final_disposition"]
        .eq("LINKED_DETERMINISTIC_EXACT_LEGAL_NAME")
        .sum()
    )

    if manual_links != 2:
        raise RuntimeError(f"Expected 2 manual links; found {manual_links}.")

    if exact_ein_links != 3:
        raise RuntimeError(f"Expected 3 exact-EIN links; found {exact_ein_links}.")

    if exact_name_links != 1:
        raise RuntimeError(f"Expected 1 exact-legal-name link; found {exact_name_links}.")

    disposition_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    policy_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    final.to_csv(
        disposition_path,
        index=False,
    )

    accepted_output.to_csv(
        accepted_path,
        index=False,
    )

    policy = {
        "milestone": 3,
        "step": "3.6",
        "protocol_version": "3.6-hybrid-v1.1",
        "created_utc": datetime.now(UTC).isoformat(),
        "policy_name": ("CONSERVATIVE_UNRESOLVED_RETENTION"),
        "review_method": ("HYBRID_HUMAN_AND_DETERMINISTIC_IDENTIFIER_ADJUDICATION"),
        "population": {
            "total_sponsors": EXPECTED_TOTAL,
            "accepted_matches": EXPECTED_LINKED,
            "supported_no_match": (EXPECTED_SUPPORTED_NO_MATCH),
            "unresolved_retained_unmatched": (EXPECTED_UNRESOLVED),
        },
        "unresolved_semantics": {
            "final_disposition": ("RETAIN_UNMATCHED_UNRESOLVED"),
            "means_no_match": False,
            "means_human_reviewed": False,
            "means_machine_rejected": False,
            "means_fuzzy_rejected": False,
            "included_in_step_3_7_crosswalk": False,
        },
        "crosswalk_policy": (
            "Only Step 3.6 rows with linkage_accepted=True "
            "may enter Step 3.7 as accepted fuzzy-derived links."
        ),
        "fuzzy_auto_accept": False,
        "fuzzy_auto_reject": False,
        "unresolved_reclassified_as_no_match": False,
        "machine_decisions_labeled_as_human": False,
        "score_100_manual_review_complete": True,
        "step_3_6_complete": True,
        "step_3_7_executed": False,
    }

    policy_path.write_text(
        json.dumps(
            policy,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    audit = {
        "milestone": 3,
        "step": "3.6",
        "protocol_version": "3.6-hybrid-v1.1",
        "status": "PASS",
        "total_sponsors": EXPECTED_TOTAL,
        "accepted_matches": EXPECTED_LINKED,
        "supported_no_match": (EXPECTED_SUPPORTED_NO_MATCH),
        "unresolved_retained_unmatched": (EXPECTED_UNRESOLVED),
        "accepted_match_breakdown": {
            "manual": manual_links,
            "deterministic_exact_ein": (exact_ein_links),
            "deterministic_exact_legal_name": (exact_name_links),
        },
        "fuzzy_auto_accept": False,
        "fuzzy_auto_reject": False,
        "unresolved_reclassified_as_no_match": False,
        "machine_decisions_labeled_as_human": False,
        "score_100_manual_review_complete": True,
        "step_3_7_executed": False,
        "input_hybrid_sha256": sha256_file(hybrid_path),
        "input_candidate_evidence_sha256": sha256_file(candidates_path),
        "final_disposition_sha256": sha256_file(disposition_path),
        "accepted_matches_sha256": sha256_file(accepted_path),
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

    print("STEP_3_6_PROTOCOL_VERSION=3.6-hybrid-v1.1")
    print("STEP_3_6_REVIEW_METHOD=HYBRID_HUMAN_AND_DETERMINISTIC_IDENTIFIER_ADJUDICATION")
    print("STEP_3_6_TOTAL_SPONSORS=2153")
    print("STEP_3_6_ACCEPTED_MATCHES=6")
    print("STEP_3_6_SUPPORTED_NO_MATCH=1663")
    print("STEP_3_6_UNRESOLVED_RETAINED_UNMATCHED=484")
    print("STEP_3_6_ACCEPTED_MANUAL_MATCHES=2")
    print("STEP_3_6_ACCEPTED_EXACT_EIN_MATCHES=3")
    print("STEP_3_6_ACCEPTED_EXACT_LEGAL_NAME_MATCHES=1")
    print("FUZZY_AUTO_ACCEPT=NO")
    print("FUZZY_AUTO_REJECT=NO")
    print("UNRESOLVED_RELABELED_AS_NO_MATCH=NO")
    print("MACHINE_DECISIONS_LABELED_AS_HUMAN=NO")
    print("SCORE_100_MANUAL_REVIEW_COMPLETE=YES")
    print("ALL_STEP_3_6_SPONSORS_DISPOSITIONED=YES")
    print("STEP_3_6_STATUS=PASS")
    print("STEP_3_7_EXECUTED=NO")
    print("NEXT_STEP=3.7")


if __name__ == "__main__":
    main()
