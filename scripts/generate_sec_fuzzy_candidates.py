"""Generate Step 3.5 fuzzy SEC candidates for unresolved sponsors only.

Governance rule: fuzzy evidence never auto-accepts a sponsor-to-SEC match.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

EXPECTED_INPUT_POPULATION = 10_665
MAX_CANDIDATES_PER_SPONSOR = 5
MINIMUM_CANDIDATE_SCORE = 90.0
STRONG_CANDIDATE_SCORE = 95.0
MINIMUM_BEST_VS_SECOND_MARGIN = 5.0
FUZZY_METHOD = "RapidFuzz WRatio"

SPONSOR_ID_ALIASES = (
    "sponsor_id",
    "sponsor_key",
    "form5500_sponsor_id",
)

SPONSOR_NAME_ALIASES = (
    "normalized_sponsor_name",
    "sponsor_name_normalized",
    "sponsor_normalized_name",
    "canonical_sponsor_name",
    "sponsor_name",
)

STATUS_ALIASES = (
    "match_state_after_deterministic",
    "match_state",
    "linkage_state",
    "resolution_state",
    "match_status",
    "classification_state",
    "review_state",
    "status",
    "state",
)

CIK_ALIASES = (
    "sec_cik",
    "cik",
    "cik_str",
    "cik10",
)

SEC_NAME_ALIASES = (
    "sec_name_norm",
    "sec_normalized_name",
    "sec_name_normalized",
    "normalized_company_name",
    "company_name_normalized",
    "normalized_legal_name",
    "legal_name_normalized",
    "normalized_name",
    "canonical_name",
    "company_name",
    "legal_name",
    "entity_name",
    "title",
    "name",
)

EXCLUDED_DISCOVERY_TOKENS = (
    "fuzzy",
    "review_queue",
    "sponsor_sec_crosswalk",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest().upper()


def normalize_name(value: object) -> str:
    if value is None or pd.isna(value):
        return ""

    text = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    text = "".join(character for character in text if not unicodedata.combining(character))

    text = text.upper().replace("&", " AND ")

    text = re.sub(
        r"[^A-Z0-9]+",
        " ",
        text,
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def normalize_cik(value: object) -> str:
    if value is None or pd.isna(value):
        return ""

    digits = re.sub(
        r"\D",
        "",
        str(value),
    )

    if not digits:
        return ""

    return digits.zfill(10)[-10:]


def find_alias(
    columns: Iterable[str],
    aliases: tuple[str, ...],
) -> str | None:
    lower_to_actual = {str(column).lower(): str(column) for column in columns}

    for alias in aliases:
        if alias in lower_to_actual:
            return lower_to_actual[alias]

    return None


def read_columns(path: Path) -> list[str]:
    suffix = path.suffix.lower()

    if suffix == ".parquet":
        import pyarrow.parquet as pq

        return list(pq.ParquetFile(path).schema.names)

    if suffix == ".csv":
        return list(
            pd.read_csv(
                path,
                nrows=0,
            ).columns
        )

    return []


def read_selected(
    path: Path,
    columns: list[str],
) -> pd.DataFrame:
    suffix = path.suffix.lower()

    if suffix == ".parquet":
        return pd.read_parquet(
            path,
            columns=columns,
        )

    if suffix == ".csv":
        return pd.read_csv(
            path,
            usecols=columns,
            low_memory=False,
        )

    raise ValueError(f"Unsupported table type: {path}")


def candidate_files(repo: Path) -> list[Path]:
    roots = (
        repo / "data" / "interim",
        repo / "data" / "validation",
        repo / "data" / "processed",
        repo / "reports" / "validation",
    )

    files: list[Path] = []

    for root in roots:
        if not root.exists():
            continue

        for pattern in (
            "*.parquet",
            "*.csv",
        ):
            files.extend(root.rglob(pattern))

    return sorted({path.resolve() for path in files if path.is_file()})


def discovery_path_allowed(
    path: Path,
) -> bool:
    lower = path.name.lower()

    return not any(token in lower for token in EXCLUDED_DISCOVERY_TOKENS)


def source_priority(
    path: Path,
    role: str,
) -> tuple[int, float, str]:
    text = str(path).lower()

    if role == "sponsor":
        hints = (
            "deterministic",
            "resolution",
            "linkage",
            "step3_4",
            "step_3_4",
            "unmatched",
        )
    else:
        hints = (
            "sec_corporation_reference",
            "corporation_reference",
            "sec_reference",
            "normalized_sec",
            "company_reference",
        )

    score = sum(1 for hint in hints if hint in text)

    return (
        score,
        path.stat().st_mtime,
        str(path),
    )


def discover_unmatched_sponsor_source(
    repo: Path,
) -> tuple[
    Path,
    pd.DataFrame,
    dict[str, str],
]:
    matches: list[
        tuple[
            Path,
            pd.DataFrame,
            dict[str, str],
        ]
    ] = []

    for path in candidate_files(repo):
        if not discovery_path_allowed(path):
            continue

        try:
            columns = read_columns(path)
        except Exception:
            continue

        sponsor_id_col = find_alias(
            columns,
            SPONSOR_ID_ALIASES,
        )

        sponsor_name_col = find_alias(
            columns,
            SPONSOR_NAME_ALIASES,
        )

        status_col = find_alias(
            columns,
            STATUS_ALIASES,
        )

        if not (sponsor_id_col and sponsor_name_col and status_col):
            continue

        try:
            frame = read_selected(
                path,
                [
                    sponsor_id_col,
                    sponsor_name_col,
                    status_col,
                ],
            )
        except Exception:
            continue

        state = frame[status_col].astype("string").str.strip().str.upper()

        unmatched = frame.loc[state.eq("UNMATCHED")].copy()

        if unmatched.empty:
            continue

        unique_count = unmatched[sponsor_id_col].astype("string").nunique(dropna=True)

        if unique_count != EXPECTED_INPUT_POPULATION:
            continue

        mapping = {
            "sponsor_id": sponsor_id_col,
            "sponsor_name": sponsor_name_col,
            "status": status_col,
        }

        matches.append(
            (
                path,
                unmatched,
                mapping,
            )
        )

    if not matches:
        raise RuntimeError(
            "No local Step-3.4 deterministic-resolution "
            "table contains exactly "
            f"{EXPECTED_INPUT_POPULATION} unique sponsors "
            "in state UNMATCHED."
        )

    matches.sort(
        key=lambda item: source_priority(
            item[0],
            "sponsor",
        ),
        reverse=True,
    )

    return matches[0]


def collapse_sponsors(
    frame: pd.DataFrame,
    mapping: dict[str, str],
) -> pd.DataFrame:
    sponsor_id_col = mapping["sponsor_id"]
    sponsor_name_col = mapping["sponsor_name"]

    working = frame[
        [
            sponsor_id_col,
            sponsor_name_col,
        ]
    ].copy()

    working[sponsor_id_col] = working[sponsor_id_col].astype("string").str.strip()

    working = working.loc[working[sponsor_id_col].notna() & working[sponsor_id_col].ne("")]

    rows: list[dict[str, str]] = []

    for (
        sponsor_id,
        group,
    ) in working.groupby(
        sponsor_id_col,
        sort=True,
        dropna=False,
    ):
        names = [
            str(value).strip() for value in group[sponsor_name_col].dropna() if str(value).strip()
        ]

        if names:
            counts = Counter(names)

            sponsor_name = sorted(
                counts,
                key=lambda value: (
                    -counts[value],
                    value,
                ),
            )[0]
        else:
            sponsor_name = ""

        rows.append(
            {
                "sponsor_id": str(sponsor_id),
                "sponsor_name": (sponsor_name),
                "sponsor_normalized_name": (normalize_name(sponsor_name)),
            }
        )

    result = (
        pd.DataFrame(rows)
        .sort_values(
            "sponsor_id",
            kind="stable",
        )
        .reset_index(drop=True)
    )

    if len(result) != EXPECTED_INPUT_POPULATION:
        raise RuntimeError(
            "FUZZY_INPUT_POPULATION drift after "
            "sponsor deduplication: expected "
            f"{EXPECTED_INPUT_POPULATION}, "
            f"found {len(result)}."
        )

    return result


def discover_sec_reference(
    repo: Path,
    sponsor_source: Path,
) -> tuple[
    Path,
    pd.DataFrame,
    dict[str, str],
]:
    matches: list[
        tuple[
            Path,
            pd.DataFrame,
            dict[str, str],
        ]
    ] = []

    for path in candidate_files(repo):
        if path == sponsor_source or not discovery_path_allowed(path):
            continue

        try:
            columns = read_columns(path)
        except Exception:
            continue

        cik_col = find_alias(
            columns,
            CIK_ALIASES,
        )

        name_col = find_alias(
            columns,
            SEC_NAME_ALIASES,
        )

        if not (cik_col and name_col):
            continue

        try:
            frame = read_selected(
                path,
                [
                    cik_col,
                    name_col,
                ],
            )
        except Exception:
            continue

        cik = frame[cik_col].map(normalize_cik)

        names = frame[name_col].map(normalize_name)

        valid = cik.ne("") & names.ne("")

        if int(valid.sum()) < 1_000:
            continue

        frame = frame.loc[valid].copy()

        mapping = {
            "cik": cik_col,
            "sec_name": name_col,
        }

        matches.append(
            (
                path,
                frame,
                mapping,
            )
        )

    if not matches:
        raise RuntimeError(
            "No normalized local SEC corporation "
            "reference table with CIK and "
            "company-name fields was found."
        )

    matches.sort(
        key=lambda item: source_priority(
            item[0],
            "sec",
        ),
        reverse=True,
    )

    return matches[0]


def prepare_sec_choices(
    frame: pd.DataFrame,
    mapping: dict[str, str],
) -> pd.DataFrame:
    cik_col = mapping["cik"]
    name_col = mapping["sec_name"]

    result = pd.DataFrame(
        {
            "sec_cik": frame[cik_col].map(normalize_cik),
            "sec_name": (frame[name_col].astype("string").fillna("").str.strip()),
        }
    )

    result["sec_normalized_name"] = result["sec_name"].map(normalize_name)

    result = result.loc[result["sec_cik"].ne("") & result["sec_normalized_name"].ne("")]

    result = (
        result.drop_duplicates(
            [
                "sec_cik",
                "sec_normalized_name",
            ],
            keep="first",
        )
        .sort_values(
            [
                "sec_cik",
                "sec_normalized_name",
            ],
            kind="stable",
        )
        .reset_index(drop=True)
    )

    if result.empty:
        raise RuntimeError("SEC choice table is empty after normalization.")

    return result


def manual_review_disposition(
    candidate_count: int,
) -> str:
    if candidate_count > 0:
        return "MANUAL_REVIEW"

    return "UNMATCHED"


def generate_candidates(
    sponsors: pd.DataFrame,
    sec_choices: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    choice_names = sec_choices["sec_normalized_name"].tolist()

    alias_counts = sec_choices.groupby(
        "sec_cik",
        sort=False,
    ).size()

    max_aliases_per_cik = int(alias_counts.max()) if not alias_counts.empty else 1

    extraction_limit = min(
        len(choice_names),
        max(
            100,
            (MAX_CANDIDATES_PER_SPONSOR * max_aliases_per_cik + 10),
        ),
    )

    candidate_rows: list[dict[str, object]] = []

    queue_rows: list[dict[str, object]] = []

    total_sponsors = len(sponsors)

    for (
        position,
        sponsor,
    ) in enumerate(
        sponsors.itertuples(index=False),
        start=1,
    ):
        query = sponsor.sponsor_normalized_name

        distinct: list[
            tuple[
                int,
                float,
            ]
        ] = []

        if query:
            raw_matches = process.extract(
                query,
                choice_names,
                scorer=fuzz.WRatio,
                processor=None,
                limit=extraction_limit,
            )

            seen_ciks: set[str] = set()

            for (
                _choice,
                score,
                index,
            ) in raw_matches:
                cik = str(sec_choices.iloc[index]["sec_cik"])

                if cik in seen_ciks:
                    continue

                seen_ciks.add(cik)

                distinct.append(
                    (
                        int(index),
                        float(score),
                    )
                )

                if len(distinct) >= MAX_CANDIDATES_PER_SPONSOR:
                    break

        best_score = distinct[0][1] if distinct else None

        second_score = distinct[1][1] if len(distinct) >= 2 else None

        margin = (
            best_score - second_score
            if (best_score is not None and second_score is not None)
            else None
        )

        qualifying = [item for item in distinct if (item[1] >= MINIMUM_CANDIDATE_SCORE)]

        candidate_count = len(qualifying)

        strong_flag = bool(best_score is not None and best_score >= STRONG_CANDIDATE_SCORE)

        margin_flag = bool(margin is not None and margin >= MINIMUM_BEST_VS_SECOND_MARGIN)

        if candidate_count == 0:
            review_bucket = "NO_FUZZY_CANDIDATE_AT_OR_ABOVE_90"
        elif strong_flag and margin_flag:
            review_bucket = "STRONG_AND_SEPARATED_MANUAL_REVIEW"
        elif strong_flag:
            review_bucket = "STRONG_BUT_NOT_SEPARATED_MANUAL_REVIEW"
        else:
            review_bucket = "STANDARD_MANUAL_REVIEW"

        queue_rows.append(
            {
                "sponsor_id": (sponsor.sponsor_id),
                "sponsor_name": (sponsor.sponsor_name),
                "sponsor_normalized_name": (query),
                "fuzzy_method": (FUZZY_METHOD),
                "candidate_count": (candidate_count),
                "best_score": (best_score),
                "second_score": (second_score),
                "best_vs_second_margin": (margin),
                "strong_candidate_flag": (strong_flag),
                "minimum_margin_pass_flag": (margin_flag),
                "review_bucket": (review_bucket),
                "linkage_state": (manual_review_disposition(candidate_count)),
                "manual_review_required": (candidate_count > 0),
                "fuzzy_auto_accept": (False),
                "review_status": ("PENDING_STEP_3_6" if candidate_count > 0 else "NO_CANDIDATE"),
            }
        )

        for (
            rank,
            candidate,
        ) in enumerate(
            qualifying,
            start=1,
        ):
            index = candidate[0]
            score = candidate[1]

            sec = sec_choices.iloc[index]

            candidate_rows.append(
                {
                    "sponsor_id": (sponsor.sponsor_id),
                    "sponsor_name": (sponsor.sponsor_name),
                    "sponsor_normalized_name": (query),
                    "candidate_rank": rank,
                    "sec_cik": sec["sec_cik"],
                    "sec_name": sec["sec_name"],
                    "sec_normalized_name": sec["sec_normalized_name"],
                    "fuzzy_method": (FUZZY_METHOD),
                    "match_score": (float(score)),
                    "best_score": (best_score),
                    "second_score": (second_score),
                    "best_vs_second_margin": (margin),
                    "strong_candidate_flag": (strong_flag),
                    "minimum_margin_pass_flag": (margin_flag),
                    "manual_review_required": (True),
                    "fuzzy_auto_accept": (False),
                    "proposed_state": ("MANUAL_REVIEW"),
                    "review_status": ("PENDING_STEP_3_6"),
                }
            )

        if position % 250 == 0 or position == total_sponsors:
            print(
                f"FUZZY_PROGRESS={position}/{total_sponsors}",
                flush=True,
            )

    candidates = pd.DataFrame(candidate_rows)

    queue = pd.DataFrame(queue_rows)

    if not candidates.empty:
        candidates = candidates.sort_values(
            [
                "sponsor_id",
                "candidate_rank",
                "sec_cik",
            ],
            kind="stable",
        ).reset_index(drop=True)

    queue = queue.sort_values(
        "sponsor_id",
        kind="stable",
    ).reset_index(drop=True)

    return (
        candidates,
        queue,
    )


def validate_outputs(
    candidates: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    if len(queue) != EXPECTED_INPUT_POPULATION:
        raise RuntimeError("Review queue does not contain exactly one row per fuzzy-input sponsor.")

    if queue["sponsor_id"].nunique(dropna=True) != EXPECTED_INPUT_POPULATION:
        raise RuntimeError("Review queue sponsor IDs are not unique.")

    if not candidates.empty:
        max_per_sponsor = int(candidates.groupby("sponsor_id").size().max())

        if max_per_sponsor > MAX_CANDIDATES_PER_SPONSOR:
            raise RuntimeError("MAX_CANDIDATES_PER_SPONSOR gate failed.")

        if float(candidates["match_score"].min()) < MINIMUM_CANDIDATE_SCORE:
            raise RuntimeError("MINIMUM_CANDIDATE_SCORE gate failed.")

        if not candidates["proposed_state"].eq("MANUAL_REVIEW").all():
            raise RuntimeError("Every fuzzy candidate must have proposed_state=MANUAL_REVIEW.")

        if not candidates["manual_review_required"].all():
            raise RuntimeError("Every fuzzy candidate must require manual review.")

        if candidates["fuzzy_auto_accept"].any():
            raise RuntimeError("FUZZY_AUTO_ACCEPT gate failed.")

        high_confidence = int(candidates["proposed_state"].eq("HIGH_CONFIDENCE_MATCH").sum())

        if high_confidence != 0:
            raise RuntimeError("FUZZY_HIGH_CONFIDENCE_MATCH_COUNT must be zero.")

        score_100 = candidates.loc[candidates["match_score"].ge(100.0)]

        if not score_100.empty and not score_100["proposed_state"].eq("MANUAL_REVIEW").all():
            raise RuntimeError("A fuzzy score of 100 was incorrectly auto-accepted.")

    invalid_queue_states = set(queue["linkage_state"].dropna().unique()) - {
        "MANUAL_REVIEW",
        "UNMATCHED",
    }

    if invalid_queue_states:
        raise RuntimeError(f"Invalid Step-3.5 queue states: {sorted(invalid_queue_states)}")


def main() -> None:
    args = parse_args()

    repo = Path(args.repo).resolve()

    output_candidates = repo / "data" / "validation" / "sponsor_sec_fuzzy_candidates.parquet"

    output_queue = repo / "data" / "validation" / "sponsor_sec_fuzzy_review_queue.parquet"

    audit_path = repo / "reports" / "validation" / "sec_fuzzy_candidate_generation.json"

    summary_path = repo / "reports" / "validation" / "sec_fuzzy_candidate_summary.csv"

    for path in (
        output_candidates,
        output_queue,
        audit_path,
        summary_path,
    ):
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    (
        sponsor_path,
        unmatched_frame,
        sponsor_mapping,
    ) = discover_unmatched_sponsor_source(repo)

    sponsors = collapse_sponsors(
        unmatched_frame,
        sponsor_mapping,
    )

    (
        sec_path,
        sec_frame,
        sec_mapping,
    ) = discover_sec_reference(
        repo,
        sponsor_path,
    )

    sec_choices = prepare_sec_choices(
        sec_frame,
        sec_mapping,
    )

    print(f"SPONSOR_SOURCE={sponsor_path.relative_to(repo)}")

    print(f"SEC_REFERENCE_SOURCE={sec_path.relative_to(repo)}")

    print(f"FUZZY_INPUT_POPULATION={len(sponsors)}")

    print(f"SEC_REFERENCE_ALIAS_ROWS={len(sec_choices)}")

    print(f"SEC_REFERENCE_UNIQUE_CIKS={sec_choices['sec_cik'].nunique()}")

    print(f"FUZZY_METHOD={FUZZY_METHOD}")

    print(f"MAX_CANDIDATES_PER_SPONSOR={MAX_CANDIDATES_PER_SPONSOR}")

    print(f"MINIMUM_CANDIDATE_SCORE={int(MINIMUM_CANDIDATE_SCORE)}")

    print(f"STRONG_CANDIDATE_SCORE={int(STRONG_CANDIDATE_SCORE)}")

    print(f"MINIMUM_BEST_VS_SECOND_MARGIN={int(MINIMUM_BEST_VS_SECOND_MARGIN)}")

    print("FUZZY_AUTO_ACCEPT=NO")

    (
        candidates,
        queue,
    ) = generate_candidates(
        sponsors,
        sec_choices,
    )

    validate_outputs(
        candidates,
        queue,
    )

    candidates.to_parquet(
        output_candidates,
        index=False,
    )

    queue.to_parquet(
        output_queue,
        index=False,
    )

    candidate_sponsors = int(queue["candidate_count"].gt(0).sum())

    no_candidate_sponsors = int(queue["candidate_count"].eq(0).sum())

    strong_best_count = int(queue["strong_candidate_flag"].sum())

    strong_and_margin_count = int(
        (queue["strong_candidate_flag"] & queue["minimum_margin_pass_flag"]).sum()
    )

    if candidates.empty:
        score_100_rows = 0
        max_generated = 0
    else:
        score_100_rows = int(candidates["match_score"].ge(100.0).sum())

        max_generated = int(candidates.groupby("sponsor_id").size().max())

    audit = {
        "step": "3.5",
        "generated_at_utc": (datetime.now(UTC).isoformat()),
        "fuzzy_input_population": (len(sponsors)),
        "fuzzy_method": (FUZZY_METHOD),
        "max_candidates_per_sponsor": (MAX_CANDIDATES_PER_SPONSOR),
        "minimum_candidate_score": (MINIMUM_CANDIDATE_SCORE),
        "strong_candidate_score": (STRONG_CANDIDATE_SCORE),
        "minimum_best_vs_second_margin": (MINIMUM_BEST_VS_SECOND_MARGIN),
        "fuzzy_auto_accept": False,
        "fuzzy_high_confidence_match_count": 0,
        "sponsor_source": str(sponsor_path.relative_to(repo)),
        "sponsor_source_sha256": (sha256_file(sponsor_path)),
        "sec_reference_source": str(sec_path.relative_to(repo)),
        "sec_reference_source_sha256": (sha256_file(sec_path)),
        "sec_reference_alias_rows": (len(sec_choices)),
        "sec_reference_unique_ciks": int(sec_choices["sec_cik"].nunique()),
        "candidate_rows": (len(candidates)),
        "candidate_sponsors": (candidate_sponsors),
        "no_candidate_sponsors": (no_candidate_sponsors),
        "strong_best_sponsors": (strong_best_count),
        "strong_and_margin_sponsors": (strong_and_margin_count),
        "score_100_candidate_rows": (score_100_rows),
        "max_generated_candidates_per_sponsor": (max_generated),
        "candidate_output": str(output_candidates.relative_to(repo)),
        "review_queue_output": str(output_queue.relative_to(repo)),
        "candidate_output_sha256": (sha256_file(output_candidates)),
        "review_queue_output_sha256": (sha256_file(output_queue)),
        "next_step": "3.6",
        "next_action": ("MANUAL_REVIEW_OF_FUZZY_EVIDENCE"),
    }

    audit_path.write_text(
        (
            json.dumps(
                audit,
                indent=2,
            )
            + "\n"
        ),
        encoding="utf-8",
    )

    summary = pd.DataFrame(
        [
            {
                "fuzzy_input_population": (len(sponsors)),
                "candidate_rows": (len(candidates)),
                "candidate_sponsors": (candidate_sponsors),
                "no_candidate_sponsors": (no_candidate_sponsors),
                "strong_best_sponsors": (strong_best_count),
                "strong_and_margin_sponsors": (strong_and_margin_count),
                "score_100_candidate_rows": (score_100_rows),
                "fuzzy_high_confidence_match_count": 0,
                "fuzzy_auto_accept": "NO",
            }
        ]
    )

    summary.to_csv(
        summary_path,
        index=False,
    )

    print(f"FUZZY_CANDIDATE_ROWS={len(candidates)}")

    print(f"FUZZY_CANDIDATE_SPONSORS={candidate_sponsors}")

    print(f"FUZZY_NO_CANDIDATE_SPONSORS={no_candidate_sponsors}")

    print(f"FUZZY_STRONG_BEST_SPONSORS={strong_best_count}")

    print(f"FUZZY_STRONG_AND_MARGIN_SPONSORS={strong_and_margin_count}")

    print(f"FUZZY_SCORE_100_CANDIDATE_ROWS={score_100_rows}")

    print(f"FUZZY_MAX_GENERATED_CANDIDATES_PER_SPONSOR={max_generated}")

    print("FUZZY_HIGH_CONFIDENCE_MATCH_COUNT=0")

    print("FUZZY_AUTO_ACCEPT=NO")

    print("STEP_3_5_CANDIDATE_ONLY_GATE=PASS")

    print("MILESTONE3_STEP_3_5_STATUS=PASS")

    print("MILESTONE3_REMAINING_STEPS=4")

    print("NEXT_STEP=3.6")

    print("NEXT_ACTION=MANUAL_REVIEW_OF_FUZZY_EVIDENCE")


if __name__ == "__main__":
    main()
