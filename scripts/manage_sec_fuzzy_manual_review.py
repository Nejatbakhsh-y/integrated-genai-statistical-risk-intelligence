"""Prepare and validate Step 3.6 fuzzy-linkage manual adjudication."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

EXPECTED_CANDIDATE_ROWS = 2489
EXPECTED_REVIEW_SPONSORS = 2153
EXPECTED_SCORE_100_ROWS = 2
MINIMUM_FUZZY_SCORE = 90.0
MAXIMUM_CANDIDATES_PER_SPONSOR = 5

VALID_MANUAL_DECISIONS = {
    "",
    "MATCH",
    "NO_MATCH",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("prepare", "validate"),
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest().upper()


def canonical_value(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    return str(value).strip()


def pick_column(
    frame: pd.DataFrame,
    preferred_names: list[str],
) -> str | None:
    lower_lookup = {column.lower(): column for column in frame.columns}

    for preferred in preferred_names:
        if preferred.lower() in lower_lookup:
            return lower_lookup[preferred.lower()]

    return None


def detect_score_column(frame: pd.DataFrame) -> str:
    preferred = [
        "fuzzy_score",
        "candidate_score",
        "match_score",
        "similarity_score",
        "wratio_score",
        "score",
    ]

    for column in preferred:
        actual = pick_column(frame, [column])

        if actual is None:
            continue

        values = pd.to_numeric(
            frame[actual],
            errors="coerce",
        )

        if (
            values.notna().all()
            and float(values.min()) >= MINIMUM_FUZZY_SCORE
            and float(values.max()) <= 100.0
        ):
            return actual

    for column in frame.columns:
        if "score" not in column.lower():
            continue

        values = pd.to_numeric(
            frame[column],
            errors="coerce",
        )

        if (
            values.notna().all()
            and float(values.min()) >= MINIMUM_FUZZY_SCORE
            and float(values.max()) <= 100.0
        ):
            return column

    raise RuntimeError("Could not identify the qualifying fuzzy-score column.")


def row_sha256(
    row: pd.Series,
    source_columns: list[str],
) -> str:
    payload = {column: canonical_value(row[column]) for column in source_columns}

    payload["manual_candidate_rank"] = int(row["manual_candidate_rank"])

    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest().upper()


def build_evidence(
    candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    if "sponsor_id" not in candidates.columns:
        raise RuntimeError("Step 3.5 candidates do not contain sponsor_id.")

    if len(candidates) != EXPECTED_CANDIDATE_ROWS:
        raise RuntimeError(
            f"Expected {EXPECTED_CANDIDATE_ROWS:,} candidate rows; found {len(candidates):,}."
        )

    sponsor_ids = candidates["sponsor_id"].astype(str).str.strip()

    if sponsor_ids.eq("").any():
        raise RuntimeError("Blank sponsor_id found in Step 3.5 candidates.")

    if sponsor_ids.nunique() != EXPECTED_REVIEW_SPONSORS:
        raise RuntimeError(
            "Expected "
            f"{EXPECTED_REVIEW_SPONSORS:,} candidate sponsors; "
            f"found {sponsor_ids.nunique():,}."
        )

    score_column = detect_score_column(candidates)

    frame = candidates.copy()
    frame["sponsor_id"] = sponsor_ids

    frame["_manual_score_numeric"] = pd.to_numeric(
        frame[score_column],
        errors="raise",
    ).astype(float)

    if frame["_manual_score_numeric"].lt(MINIMUM_FUZZY_SCORE).any():
        raise RuntimeError("Candidate evidence contains a score below 90.")

    if frame["_manual_score_numeric"].gt(100.0).any():
        raise RuntimeError("Candidate evidence contains a score above 100.")

    score_100_rows = int(frame["_manual_score_numeric"].round(10).eq(100.0).sum())

    if score_100_rows != EXPECTED_SCORE_100_ROWS:
        raise RuntimeError(
            f"Expected exactly {EXPECTED_SCORE_100_ROWS} score-100 rows; found {score_100_rows}."
        )

    cik_column = pick_column(
        frame,
        [
            "sec_cik",
            "candidate_sec_cik",
            "candidate_cik",
            "matched_sec_cik",
        ],
    )

    sec_name_column = pick_column(
        frame,
        [
            "sec_name_norm",
            "sec_name",
            "candidate_sec_name_norm",
            "candidate_sec_name",
            "candidate_name_norm",
            "candidate_name",
        ],
    )

    frame["_manual_cik_sort"] = (
        frame[cik_column].map(canonical_value) if cik_column is not None else ""
    )

    frame["_manual_name_sort"] = (
        frame[sec_name_column].map(canonical_value) if sec_name_column is not None else ""
    )

    frame = frame.sort_values(
        [
            "sponsor_id",
            "_manual_score_numeric",
            "_manual_cik_sort",
            "_manual_name_sort",
        ],
        ascending=[True, False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)

    frame["manual_candidate_rank"] = (
        frame.groupby(
            "sponsor_id",
            sort=False,
        )
        .cumcount()
        .add(1)
        .astype(int)
    )

    maximum_rank = int(frame["manual_candidate_rank"].max())

    if maximum_rank > MAXIMUM_CANDIDATES_PER_SPONSOR:
        raise RuntimeError("More than five fuzzy candidates found for a sponsor.")

    source_columns = [column for column in candidates.columns]

    frame["candidate_row_sha256"] = frame.apply(
        lambda row: row_sha256(
            row,
            source_columns,
        ),
        axis=1,
    )

    if frame["candidate_row_sha256"].duplicated().any():
        raise RuntimeError("Candidate review row identifiers are not unique.")

    frame["human_review_required"] = True
    frame["fuzzy_auto_accept"] = False
    frame["score_100_requires_manual_review"] = frame["_manual_score_numeric"].round(10).eq(100.0)

    frame = frame.drop(
        columns=[
            "_manual_score_numeric",
            "_manual_cik_sort",
            "_manual_name_sort",
        ],
    )

    return frame, score_column


def build_adjudication(
    evidence: pd.DataFrame,
    score_column: str,
) -> pd.DataFrame:
    sponsor_name_column = pick_column(
        evidence,
        [
            "sponsor_name",
            "sponsor_name_norm",
            "form5500_sponsor_name",
            "form5500_sponsor_name_norm",
        ],
    )

    cik_column = pick_column(
        evidence,
        [
            "sec_cik",
            "candidate_sec_cik",
            "candidate_cik",
            "matched_sec_cik",
        ],
    )

    sec_name_column = pick_column(
        evidence,
        [
            "sec_name_norm",
            "sec_name",
            "candidate_sec_name_norm",
            "candidate_sec_name",
            "candidate_name_norm",
            "candidate_name",
        ],
    )

    rows: list[dict[str, Any]] = []

    grouped = evidence.groupby(
        "sponsor_id",
        sort=True,
    )

    for sequence, (sponsor_id, group) in enumerate(
        grouped,
        start=1,
    ):
        group = group.sort_values(
            "manual_candidate_rank",
            kind="mergesort",
        )

        numeric_scores = pd.to_numeric(
            group[score_column],
            errors="raise",
        ).astype(float)

        best_score = float(numeric_scores.iloc[0])

        second_score: float | None = None
        best_minus_second: float | None = None

        if len(numeric_scores) >= 2:
            second_score = float(numeric_scores.iloc[1])
            best_minus_second = best_score - second_score

        sponsor_name = ""

        if sponsor_name_column is not None:
            sponsor_name = canonical_value(group.iloc[0][sponsor_name_column])

        candidate_options: list[str] = []

        for _, candidate in group.iterrows():
            rank = int(candidate["manual_candidate_rank"])

            score = float(candidate[score_column])

            cik = canonical_value(candidate[cik_column]) if cik_column is not None else ""

            sec_name = (
                canonical_value(candidate[sec_name_column]) if sec_name_column is not None else ""
            )

            candidate_key = canonical_value(candidate["candidate_row_sha256"])

            candidate_options.append(
                f"R{rank}|SCORE={score:.4f}|CIK={cik}|NAME={sec_name}|KEY={candidate_key[:12]}"
            )

        bundle_source = "||".join(group["candidate_row_sha256"].astype(str).tolist())

        bundle_sha256 = hashlib.sha256(bundle_source.encode("utf-8")).hexdigest().upper()

        has_score_100 = bool(numeric_scores.round(10).eq(100.0).any())

        rows.append(
            {
                "manual_review_sequence": sequence,
                "sponsor_id": sponsor_id,
                "sponsor_name": sponsor_name,
                "candidate_count": int(len(group)),
                "best_score": best_score,
                "second_best_score": second_score,
                "best_minus_second": best_minus_second,
                "contains_score_100_candidate": (has_score_100),
                "candidate_bundle_sha256": (bundle_sha256),
                "candidate_options": (" || ".join(candidate_options)),
                "review_method": ("MANUAL_ADJUDICATION"),
                "auto_accept_permitted": False,
                "score_100_bypass_permitted": False,
                "manual_decision": "",
                "selected_candidate_rank": "",
                "reviewer": "",
                "review_evidence_reference": "",
                "review_notes": "",
            }
        )

    result = pd.DataFrame(rows)

    if len(result) != EXPECTED_REVIEW_SPONSORS:
        raise RuntimeError(
            f"Expected {EXPECTED_REVIEW_SPONSORS:,} adjudication rows; found {len(result):,}."
        )

    if result["sponsor_id"].duplicated().any():
        raise RuntimeError("Duplicate sponsor_id found in adjudication form.")

    return result


def validate_existing_evidence(
    existing_path: Path,
    expected: pd.DataFrame,
) -> None:
    existing = pd.read_csv(
        existing_path,
        dtype=str,
        keep_default_na=False,
    )

    if len(existing) != EXPECTED_CANDIDATE_ROWS:
        raise RuntimeError("Existing manual evidence file has row-count drift.")

    if "sponsor_id" not in existing.columns:
        raise RuntimeError("Existing manual evidence file lacks sponsor_id.")

    if "candidate_row_sha256" not in existing.columns:
        raise RuntimeError("Existing manual evidence file lacks candidate_row_sha256.")

    if existing["sponsor_id"].astype(str).str.strip().nunique() != EXPECTED_REVIEW_SPONSORS:
        raise RuntimeError("Existing manual evidence sponsor-count drift.")

    existing_keys = set(existing["candidate_row_sha256"].astype(str).str.strip())

    expected_keys = set(expected["candidate_row_sha256"].astype(str).str.strip())

    if existing_keys != expected_keys:
        raise RuntimeError(
            "Existing manual evidence does not match the verified Step 3.5 candidate population."
        )


def validate_existing_adjudication(
    existing_path: Path,
    expected: pd.DataFrame,
) -> None:
    existing = pd.read_csv(
        existing_path,
        dtype=str,
        keep_default_na=False,
    )

    if len(existing) != EXPECTED_REVIEW_SPONSORS:
        raise RuntimeError("Existing adjudication form has sponsor-count drift.")

    required = [
        "sponsor_id",
        "candidate_bundle_sha256",
        "manual_decision",
        "selected_candidate_rank",
        "reviewer",
        "review_evidence_reference",
        "review_notes",
    ]

    missing = [column for column in required if column not in existing.columns]

    if missing:
        raise RuntimeError(f"Existing adjudication form is missing columns: {missing}")

    if existing["sponsor_id"].duplicated().any():
        raise RuntimeError("Existing adjudication form contains duplicate sponsors.")

    expected_contract = (
        expected[
            [
                "sponsor_id",
                "candidate_bundle_sha256",
            ]
        ]
        .astype(str)
        .set_index("sponsor_id")["candidate_bundle_sha256"]
        .to_dict()
    )

    existing_contract = (
        existing[
            [
                "sponsor_id",
                "candidate_bundle_sha256",
            ]
        ]
        .astype(str)
        .set_index("sponsor_id")["candidate_bundle_sha256"]
        .to_dict()
    )

    if existing_contract != expected_contract:
        raise RuntimeError(
            "Existing adjudication form is not based on the current Step 3.5 evidence packet."
        )


def prepare(repo: Path) -> None:
    candidate_path = repo / "data" / "validation" / "sponsor_sec_fuzzy_candidates.parquet"

    evidence_path = repo / "data" / "validation" / "sponsor_sec_fuzzy_manual_review_evidence.csv"

    adjudication_path = repo / "data" / "validation" / "sponsor_sec_fuzzy_manual_adjudication.csv"

    setup_report_path = repo / "reports" / "validation" / "sec_fuzzy_manual_review_setup.json"

    if not candidate_path.exists():
        raise RuntimeError("Step 3.5 fuzzy candidate Parquet is missing.")

    candidates = pd.read_parquet(candidate_path)

    evidence, score_column = build_evidence(candidates)

    adjudication = build_adjudication(
        evidence,
        score_column,
    )

    evidence_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    setup_report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if evidence_path.exists():
        validate_existing_evidence(
            evidence_path,
            evidence,
        )
        evidence_action = "PRESERVED_EXISTING"
    else:
        evidence.to_csv(
            evidence_path,
            index=False,
        )
        evidence_action = "CREATED"

    if adjudication_path.exists():
        validate_existing_adjudication(
            adjudication_path,
            adjudication,
        )
        adjudication_action = "PRESERVED_EXISTING_MANUAL_WORK"
    else:
        adjudication.to_csv(
            adjudication_path,
            index=False,
        )
        adjudication_action = "CREATED"

    score_values = pd.to_numeric(
        evidence[score_column],
        errors="raise",
    )

    score_100_rows = int(score_values.round(10).eq(100.0).sum())

    score_100_sponsors = int(
        evidence.loc[
            score_values.round(10).eq(100.0),
            "sponsor_id",
        ].nunique()
    )

    setup_report = {
        "step": "3.6",
        "input_artifact": ("data/validation/sponsor_sec_fuzzy_candidates.parquet"),
        "input_sha256": sha256_file(candidate_path),
        "input_candidate_rows": int(len(evidence)),
        "input_sponsors": int(evidence["sponsor_id"].nunique()),
        "score_column": score_column,
        "minimum_candidate_score": (MINIMUM_FUZZY_SCORE),
        "score_100_candidate_rows": (score_100_rows),
        "score_100_sponsors": (score_100_sponsors),
        "review_method": ("MANUAL_ADJUDICATION"),
        "fuzzy_auto_accept": False,
        "score_100_requires_manual_review": True,
        "no_candidate_sponsors_from_step_3_5": 8512,
        "no_candidate_sponsor_policy": ("REMAIN_UNMATCHED"),
        "evidence_artifact": ("data/validation/sponsor_sec_fuzzy_manual_review_evidence.csv"),
        "adjudication_artifact": ("data/validation/sponsor_sec_fuzzy_manual_adjudication.csv"),
        "step_3_7_executed": False,
        "status": ("READY_FOR_MANUAL_ADJUDICATION"),
    }

    setup_report_path.write_text(
        json.dumps(
            setup_report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"FUZZY_SCORE_COLUMN={score_column}")
    print(f"STEP_3_6_INPUT_CANDIDATE_ROWS={len(evidence)}")
    print(f"STEP_3_6_INPUT_SPONSORS={evidence['sponsor_id'].nunique()}")
    print(f"STEP_3_6_SCORE_100_CANDIDATE_ROWS={score_100_rows}")
    print(f"STEP_3_6_SCORE_100_SPONSORS={score_100_sponsors}")
    print("STEP_3_6_REVIEW_METHOD=MANUAL_ADJUDICATION")
    print("FUZZY_AUTO_ACCEPT=NO")
    print("SCORE_100_REQUIRES_MANUAL_REVIEW=YES")
    print("NO_CANDIDATE_SPONSORS_REMAIN_UNMATCHED=8512")
    print(f"MANUAL_EVIDENCE_ACTION={evidence_action}")
    print(f"MANUAL_ADJUDICATION_ACTION={adjudication_action}")
    print("STEP_3_6_PREPARATION_STATUS=PASS")


def validate(repo: Path) -> None:
    evidence_path = repo / "data" / "validation" / "sponsor_sec_fuzzy_manual_review_evidence.csv"

    adjudication_path = repo / "data" / "validation" / "sponsor_sec_fuzzy_manual_adjudication.csv"

    if not evidence_path.exists():
        raise RuntimeError("Manual-review evidence file is missing.")

    if not adjudication_path.exists():
        raise RuntimeError("Manual-adjudication form is missing.")

    evidence = pd.read_csv(
        evidence_path,
        dtype=str,
        keep_default_na=False,
    )

    adjudication = pd.read_csv(
        adjudication_path,
        dtype=str,
        keep_default_na=False,
    )

    if len(evidence) != EXPECTED_CANDIDATE_ROWS:
        raise RuntimeError("Manual evidence candidate-row drift.")

    if evidence["sponsor_id"].astype(str).str.strip().nunique() != EXPECTED_REVIEW_SPONSORS:
        raise RuntimeError("Manual evidence sponsor-count drift.")

    if len(adjudication) != EXPECTED_REVIEW_SPONSORS:
        raise RuntimeError("Manual adjudication sponsor-count drift.")

    if adjudication["sponsor_id"].duplicated().any():
        raise RuntimeError("Duplicate sponsor in manual adjudication.")

    score_column = detect_score_column(evidence)

    score_values = pd.to_numeric(
        evidence[score_column],
        errors="raise",
    )

    score_100_mask = score_values.round(10).eq(100.0)

    score_100_rows = int(score_100_mask.sum())

    if score_100_rows != EXPECTED_SCORE_100_ROWS:
        raise RuntimeError("Score-100 candidate population drift.")

    if "fuzzy_auto_accept" in evidence.columns:
        auto_values = evidence["fuzzy_auto_accept"].astype(str).str.strip().str.lower()

        if auto_values.isin({"true", "1", "yes"}).any():
            raise RuntimeError("A fuzzy candidate is marked auto-accepted.")

    if "score_100_requires_manual_review" in evidence.columns:
        score_100_review_flags = (
            evidence.loc[
                score_100_mask,
                "score_100_requires_manual_review",
            ]
            .astype(str)
            .str.strip()
            .str.lower()
        )

        if not score_100_review_flags.isin({"true", "1", "yes"}).all():
            raise RuntimeError("A score-100 candidate is not marked for manual review.")

    required_columns = [
        "sponsor_id",
        "candidate_count",
        "manual_decision",
        "selected_candidate_rank",
        "reviewer",
    ]

    missing = [column for column in required_columns if column not in adjudication.columns]

    if missing:
        raise RuntimeError(f"Manual adjudication form is missing: {missing}")

    decisions = adjudication["manual_decision"].astype(str).str.strip().str.upper()

    invalid_decisions = sorted(set(decisions) - VALID_MANUAL_DECISIONS)

    if invalid_decisions:
        raise RuntimeError(
            f"Invalid manual_decision values: {invalid_decisions}. Use MATCH, NO_MATCH, or blank."
        )

    completed_mask = decisions.ne("")
    pending_mask = decisions.eq("")

    completed_rows = int(completed_mask.sum())

    pending_rows = int(pending_mask.sum())

    match_rows = int(decisions.eq("MATCH").sum())

    no_match_rows = int(decisions.eq("NO_MATCH").sum())

    candidate_rank_lookup: dict[
        str,
        set[int],
    ] = {}

    for sponsor_id, group in evidence.groupby(
        "sponsor_id",
        sort=False,
    ):
        candidate_rank_lookup[str(sponsor_id)] = {
            int(value)
            for value in pd.to_numeric(
                group["manual_candidate_rank"],
                errors="raise",
            )
        }

    integrity_errors: list[str] = []

    for _, row in adjudication.iterrows():
        sponsor_id = str(row["sponsor_id"]).strip()

        decision = str(row["manual_decision"]).strip().upper()

        rank_text = str(row["selected_candidate_rank"]).strip()

        reviewer = str(row["reviewer"]).strip()

        if decision == "":
            if rank_text != "":
                integrity_errors.append(
                    f"{sponsor_id}: pending sponsor has selected_candidate_rank."
                )

            continue

        if reviewer == "":
            integrity_errors.append(f"{sponsor_id}: completed decision is missing reviewer.")

        if decision == "MATCH":
            if rank_text == "":
                integrity_errors.append(f"{sponsor_id}: MATCH is missing selected_candidate_rank.")
                continue

            try:
                rank = int(rank_text)
            except ValueError:
                integrity_errors.append(f"{sponsor_id}: invalid candidate rank '{rank_text}'.")
                continue

            valid_ranks = candidate_rank_lookup.get(
                sponsor_id,
                set(),
            )

            if rank not in valid_ranks:
                integrity_errors.append(
                    f"{sponsor_id}: selected rank {rank} is not a valid candidate."
                )

        if decision == "NO_MATCH" and rank_text != "":
            integrity_errors.append(
                f"{sponsor_id}: NO_MATCH must not specify selected_candidate_rank."
            )

    if integrity_errors:
        preview = "\n".join(integrity_errors[:20])

        raise RuntimeError(f"Manual-adjudication integrity failure. First errors:\n{preview}")

    score_100_sponsors = set(
        evidence.loc[
            score_100_mask,
            "sponsor_id",
        ]
        .astype(str)
        .str.strip()
    )

    adjudication_decisions = {
        str(row["sponsor_id"]).strip(): str(row["manual_decision"]).strip().upper()
        for _, row in adjudication.iterrows()
    }

    pending_score_100_sponsors = sorted(
        sponsor_id
        for sponsor_id in score_100_sponsors
        if adjudication_decisions.get(
            sponsor_id,
            "",
        )
        == ""
    )

    score_100_review_complete = len(pending_score_100_sponsors) == 0

    print(f"STEP_3_6_INPUT_SPONSORS={EXPECTED_REVIEW_SPONSORS}")
    print(f"STEP_3_6_INPUT_CANDIDATE_ROWS={EXPECTED_CANDIDATE_ROWS}")
    print(f"STEP_3_6_COMPLETED_SPONSORS={completed_rows}")
    print(f"STEP_3_6_REMAINING_SPONSORS={pending_rows}")
    print(f"STEP_3_6_MATCH_DECISIONS={match_rows}")
    print(f"STEP_3_6_NO_MATCH_DECISIONS={no_match_rows}")
    print(f"STEP_3_6_SCORE_100_CANDIDATE_ROWS={score_100_rows}")
    print("SCORE_100_REQUIRES_MANUAL_REVIEW=YES")
    print("SCORE_100_MANUAL_REVIEW_COMPLETE=" + ("YES" if score_100_review_complete else "NO"))
    print("FUZZY_AUTO_ACCEPT=NO")

    if pending_rows == 0:
        if not score_100_review_complete:
            raise RuntimeError(
                "All sponsors are marked complete but score-100 review is incomplete."
            )

        print("STEP_3_6_REVIEW_METHOD=MANUAL_ADJUDICATION")
        print("STEP_3_6_FINAL_INTEGRITY_STATUS=PASS")
        print("STEP_3_6_STATUS=PASS")
        print("NEXT_STEP=3.7")
    else:
        print("STEP_3_6_REVIEW_METHOD=MANUAL_ADJUDICATION")
        print("STEP_3_6_FINAL_INTEGRITY_STATUS=PENDING_MANUAL_REVIEW")
        print("STEP_3_6_STATUS=IN_PROGRESS")
        print("NEXT_ACTION=COMPLETE_MANUAL_ADJUDICATION")


def main() -> None:
    args = parse_args()
    repo = Path(args.repo).resolve()

    if args.mode == "prepare":
        prepare(repo)
    else:
        validate(repo)


if __name__ == "__main__":
    main()
