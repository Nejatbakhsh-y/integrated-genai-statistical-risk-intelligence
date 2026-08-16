"""Resolve Step 3.6 fuzzy candidates using deterministic SEC EIN evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

EXPECTED_SPONSORS = 2153
EXPECTED_CANDIDATES = 2489
EXPECTED_HUMAN_COMPLETE = 5
EXPECTED_HUMAN_MATCH = 2
EXPECTED_HUMAN_NO_MATCH = 3

MINIMUM_SECONDS_BETWEEN_REQUESTS = 0.25
MAX_FETCH_ATTEMPTS = 5


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
    digits = re.sub(r"\D", "", clean(value))

    if len(digits) != 9:
        return ""

    if digits == "000000000":
        return ""

    return digits


def sponsor_ein_from_id(sponsor_id: Any) -> str:
    value = clean(sponsor_id)

    match = re.fullmatch(
        r"SP-(\d{9})",
        value,
    )

    if match is None:
        return ""

    return match.group(1)


def normalize_cik(value: Any) -> str:
    digits = re.sub(r"\D", "", clean(value))

    if not digits:
        return ""

    return f"{int(digits):010d}"


def normalize_name(value: Any) -> str:
    value = clean(value).upper()
    value = value.replace("&", " AND ")
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest().upper()


def pick_column(
    frame: pd.DataFrame,
    choices: list[str],
) -> str:
    lookup = {column.lower(): column for column in frame.columns}

    for choice in choices:
        found = lookup.get(choice.lower())

        if found is not None:
            return found

    raise RuntimeError(f"Required column not found. Tried: {choices}")


def classify_secondary_identifier(
    sponsor_ein: str,
    candidate_ranks: list[int],
    candidate_eins: list[str],
    fetch_statuses: list[str],
) -> tuple[str, str, str, str]:
    """Return decision, selected rank, method, reason."""

    if not sponsor_ein:
        return (
            "",
            "",
            "UNRESOLVED",
            "Sponsor EIN could not be derived from sponsor_id.",
        )

    matching_positions = [
        index
        for index, candidate_ein in enumerate(candidate_eins)
        if candidate_ein and candidate_ein == sponsor_ein
    ]

    if len(matching_positions) == 1:
        selected_rank = str(candidate_ranks[matching_positions[0]])

        return (
            "MATCH",
            selected_rank,
            "DETERMINISTIC_EXACT_EIN",
            ("Exactly one candidate SEC EIN equals the Form 5500 sponsor EIN."),
        )

    if len(matching_positions) > 1:
        return (
            "",
            "",
            "UNRESOLVED",
            ("Multiple candidate SEC registrants have the sponsor EIN."),
        )

    all_fetches_successful = all(
        status
        in {
            "FETCHED",
            "CACHE",
        }
        for status in fetch_statuses
    )

    all_eins_known = all(bool(candidate_ein) for candidate_ein in candidate_eins)

    if candidate_eins and all_fetches_successful and all_eins_known:
        return (
            "NO_MATCH",
            "",
            "DETERMINISTIC_ALL_SEC_EINS_DIFFER",
            (
                "Every candidate has a known SEC EIN and "
                "every candidate EIN differs from the "
                "Form 5500 sponsor EIN."
            ),
        )

    return (
        "",
        "",
        "UNRESOLVED",
        (
            "No exact EIN match and at least one candidate "
            "SEC EIN is unavailable or not safely resolved."
        ),
    )


class SecClient:
    def __init__(
        self,
        user_agent: str,
        cache_directory: Path,
    ) -> None:
        self.user_agent = user_agent
        self.cache_directory = cache_directory
        self.cache_directory.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.last_request_time = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self.last_request_time

        remaining = MINIMUM_SECONDS_BETWEEN_REQUESTS - elapsed

        if remaining > 0:
            time.sleep(remaining)

    def fetch(
        self,
        cik: str,
    ) -> tuple[dict[str, Any] | None, str, str]:
        cache_path = self.cache_directory / f"CIK{cik}.json"

        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))

                cached_cik = normalize_cik(payload.get("cik", ""))

                if cached_cik == cik:
                    return payload, "CACHE", ""
            except (
                json.JSONDecodeError,
                OSError,
            ):
                pass

        url = f"https://data.sec.gov/submissions/CIK{cik}.json"

        error_message = ""

        for attempt in range(
            1,
            MAX_FETCH_ATTEMPTS + 1,
        ):
            self._wait()

            request = Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                },
                method="GET",
            )

            try:
                with urlopen(
                    request,
                    timeout=30,
                ) as response:
                    body = response.read()

                self.last_request_time = time.monotonic()

                payload = json.loads(body.decode("utf-8"))

                returned_cik = normalize_cik(payload.get("cik", ""))

                if returned_cik != cik:
                    raise RuntimeError(f"SEC response CIK does not match requested CIK {cik}.")

                cache_path.write_text(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

                return payload, "FETCHED", ""

            except HTTPError as exc:
                self.last_request_time = time.monotonic()

                error_message = f"HTTP {exc.code}: {exc.reason}"

                if exc.code not in {
                    403,
                    429,
                    500,
                    502,
                    503,
                    504,
                }:
                    break

            except (
                URLError,
                TimeoutError,
                json.JSONDecodeError,
                RuntimeError,
                OSError,
            ) as exc:
                self.last_request_time = time.monotonic()
                error_message = str(exc)

            if attempt < MAX_FETCH_ATTEMPTS:
                time.sleep(
                    min(
                        2**attempt,
                        20,
                    )
                )

        return None, "FETCH_FAILED", error_message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--repo",
        required=True,
    )

    parser.add_argument(
        "--user-agent",
        required=True,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    repo = Path(args.repo).resolve()

    evidence_path = repo / "data" / "validation" / "sponsor_sec_fuzzy_manual_review_evidence.csv"

    adjudication_path = repo / "data" / "validation" / "sponsor_sec_fuzzy_manual_adjudication.csv"

    candidate_output_path = (
        repo / "data" / "validation" / "sponsor_sec_secondary_identifier_candidates.csv"
    )

    summary_output_path = (
        repo / "data" / "validation" / "sponsor_sec_secondary_identifier_resolution.csv"
    )

    unresolved_output_path = (
        repo / "data" / "validation" / "sponsor_sec_secondary_identifier_unresolved.csv"
    )

    unresolved_candidates_path = (
        repo / "data" / "validation" / "sponsor_sec_secondary_identifier_unresolved_candidates.csv"
    )

    report_path = repo / "reports" / "validation" / "sec_secondary_identifier_resolution.json"

    cache_directory = repo / "data" / "interim" / "sec_submissions_step36_cache"

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

    if len(evidence) != EXPECTED_CANDIDATES:
        raise RuntimeError(f"Expected {EXPECTED_CANDIDATES} candidates; found {len(evidence)}.")

    if evidence["sponsor_id"].astype(str).str.strip().nunique() != EXPECTED_SPONSORS:
        raise RuntimeError("Expected exactly 2,153 evidence sponsors.")

    if len(adjudication) != EXPECTED_SPONSORS:
        raise RuntimeError("Expected exactly 2,153 adjudication rows.")

    decisions = adjudication["manual_decision"].astype(str).str.strip().str.upper()

    if int(decisions.ne("").sum()) != EXPECTED_HUMAN_COMPLETE:
        raise RuntimeError("Expected exactly five existing human decisions.")

    if int(decisions.eq("MATCH").sum()) != EXPECTED_HUMAN_MATCH:
        raise RuntimeError("Expected exactly two human MATCH decisions.")

    if int(decisions.eq("NO_MATCH").sum()) != EXPECTED_HUMAN_NO_MATCH:
        raise RuntimeError("Expected exactly three human NO_MATCH decisions.")

    cik_column = pick_column(
        evidence,
        [
            "sec_cik",
            "candidate_sec_cik",
            "candidate_cik",
            "matched_sec_cik",
        ],
    )

    sponsor_name_column = pick_column(
        evidence,
        [
            "sponsor_name",
            "sponsor_name_norm",
            "form5500_sponsor_name",
        ],
    )

    sec_name_column = pick_column(
        evidence,
        [
            "sec_name",
            "sec_name_norm",
            "candidate_sec_name",
            "candidate_name",
        ],
    )

    score_column = pick_column(
        evidence,
        [
            "match_score",
            "fuzzy_score",
            "candidate_score",
            "similarity_score",
            "score",
        ],
    )

    if "manual_candidate_rank" not in evidence.columns:
        raise RuntimeError("manual_candidate_rank is missing.")

    sponsor_ids = evidence["sponsor_id"].astype(str).str.strip()

    invalid_sponsor_ids = [
        sponsor_id for sponsor_id in sponsor_ids.unique() if sponsor_ein_from_id(sponsor_id) == ""
    ]

    if invalid_sponsor_ids:
        raise RuntimeError("One or more sponsor IDs do not follow SP-######### encoding.")

    client = SecClient(
        user_agent=args.user_agent,
        cache_directory=cache_directory,
    )

    unique_ciks = sorted(
        {normalize_cik(value) for value in evidence[cik_column] if normalize_cik(value)}
    )

    print(
        f"UNIQUE_SEC_CIKS_TO_RESOLVE={len(unique_ciks)}",
        flush=True,
    )

    sec_metadata: dict[
        str,
        dict[str, str],
    ] = {}

    fetched = 0
    cached = 0
    failed = 0

    for sequence, cik in enumerate(
        unique_ciks,
        start=1,
    ):
        payload, status, error = client.fetch(cik)

        if status == "FETCHED":
            fetched += 1
        elif status == "CACHE":
            cached += 1
        else:
            failed += 1

        if payload is None:
            sec_metadata[cik] = {
                "sec_api_name": "",
                "sec_api_ein": "",
                "sec_api_fetch_status": status,
                "sec_api_error": error,
            }
        else:
            sec_metadata[cik] = {
                "sec_api_name": clean(payload.get("name", "")),
                "sec_api_ein": normalize_ein(payload.get("ein", "")),
                "sec_api_fetch_status": status,
                "sec_api_error": "",
            }

        if sequence == 1 or sequence % 100 == 0 or sequence == len(unique_ciks):
            print(
                "SEC_FETCH_PROGRESS="
                f"{sequence}/{len(unique_ciks)}"
                "|FETCHED="
                f"{fetched}"
                "|CACHE="
                f"{cached}"
                "|FAILED="
                f"{failed}",
                flush=True,
            )

    enriched_rows: list[dict[str, Any]] = []

    for _, row in evidence.iterrows():
        cik = normalize_cik(row[cik_column])

        metadata = sec_metadata.get(
            cik,
            {
                "sec_api_name": "",
                "sec_api_ein": "",
                "sec_api_fetch_status": "NO_CIK",
                "sec_api_error": "",
            },
        )

        sponsor_id = clean(row["sponsor_id"])

        sponsor_ein = sponsor_ein_from_id(sponsor_id)

        sec_ein = metadata["sec_api_ein"]

        if sec_ein:
            if sec_ein == sponsor_ein:
                ein_relation = "EXACT"
            else:
                ein_relation = "DIFFERENT"
        else:
            ein_relation = "UNKNOWN"

        enriched = {column: clean(row[column]) for column in evidence.columns}

        enriched.update(
            {
                "sponsor_ein_from_id": sponsor_ein,
                "sec_api_cik": cik,
                "sec_api_name": metadata["sec_api_name"],
                "sec_api_name_normalized": normalize_name(metadata["sec_api_name"]),
                "sec_api_ein": sec_ein,
                "sec_api_fetch_status": metadata["sec_api_fetch_status"],
                "sec_api_error": metadata["sec_api_error"],
                "sponsor_sec_ein_relation": ein_relation,
            }
        )

        enriched_rows.append(enriched)

    enriched_candidates = pd.DataFrame(enriched_rows)

    adjudication_lookup = adjudication.set_index("sponsor_id").to_dict("index")

    summary_rows: list[dict[str, Any]] = []

    for sponsor_id, group in enriched_candidates.groupby(
        "sponsor_id",
        sort=True,
    ):
        sponsor_id = clean(sponsor_id)

        manual = adjudication_lookup[sponsor_id]

        manual_decision = clean(manual.get("manual_decision", "")).upper()

        manual_rank = clean(manual.get("selected_candidate_rank", ""))

        manual_reviewer = clean(manual.get("reviewer", ""))

        sponsor_ein = sponsor_ein_from_id(sponsor_id)

        ranks = [
            int(value)
            for value in pd.to_numeric(
                group["manual_candidate_rank"],
                errors="raise",
            )
        ]

        candidate_eins = [clean(value) for value in group["sec_api_ein"]]

        fetch_statuses = [clean(value) for value in group["sec_api_fetch_status"]]

        candidate_names = [clean(value) for value in group[sec_name_column]]

        scores = [clean(value) for value in group[score_column]]

        if manual_decision in {
            "MATCH",
            "NO_MATCH",
        }:
            final_decision = manual_decision
            selected_rank = manual_rank
            method = "MANUAL_ADJUDICATION"
            reason = "Existing independently recorded Step 3.6 human decision preserved."
            provenance = "HUMAN"
        else:
            (
                final_decision,
                selected_rank,
                method,
                reason,
            ) = classify_secondary_identifier(
                sponsor_ein=sponsor_ein,
                candidate_ranks=ranks,
                candidate_eins=candidate_eins,
                fetch_statuses=fetch_statuses,
            )

            provenance = "MACHINE_DETERMINISTIC" if final_decision else "UNRESOLVED"

        sponsor_name = clean(group.iloc[0][sponsor_name_column])

        summary_rows.append(
            {
                "sponsor_id": sponsor_id,
                "sponsor_ein": sponsor_ein,
                "sponsor_name": sponsor_name,
                "candidate_count": len(group),
                "candidate_ranks": "|".join(str(value) for value in ranks),
                "candidate_scores": "|".join(scores),
                "candidate_sec_names": " || ".join(candidate_names),
                "candidate_sec_eins": "|".join(candidate_eins),
                "candidate_fetch_statuses": "|".join(fetch_statuses),
                "existing_manual_decision": (manual_decision),
                "existing_manual_selected_rank": (manual_rank),
                "existing_manual_reviewer": (manual_reviewer),
                "final_decision": final_decision,
                "final_selected_candidate_rank": (selected_rank),
                "decision_provenance": provenance,
                "decision_method": method,
                "decision_reason": reason,
            }
        )

    summary = pd.DataFrame(summary_rows)

    if len(summary) != EXPECTED_SPONSORS:
        raise RuntimeError("Summary does not contain 2,153 sponsors.")

    if summary["sponsor_id"].duplicated().any():
        raise RuntimeError("Duplicate sponsor in resolution summary.")

    human_mask = summary["decision_provenance"].eq("HUMAN")

    machine_mask = summary["decision_provenance"].eq("MACHINE_DETERMINISTIC")

    unresolved_mask = summary["decision_provenance"].eq("UNRESOLVED")

    machine_match_mask = machine_mask & summary["final_decision"].eq("MATCH")

    machine_no_match_mask = machine_mask & summary["final_decision"].eq("NO_MATCH")

    if int(human_mask.sum()) != EXPECTED_HUMAN_COMPLETE:
        raise RuntimeError("Existing human decision count was not preserved.")

    unresolved = summary.loc[unresolved_mask].copy()

    unresolved_sponsor_ids = set(unresolved["sponsor_id"].astype(str))

    unresolved_candidates = enriched_candidates.loc[
        enriched_candidates["sponsor_id"].astype(str).isin(unresolved_sponsor_ids)
    ].copy()

    summary_output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary.to_csv(
        summary_output_path,
        index=False,
    )

    enriched_candidates.to_csv(
        candidate_output_path,
        index=False,
    )

    unresolved.to_csv(
        unresolved_output_path,
        index=False,
    )

    unresolved_candidates.to_csv(
        unresolved_candidates_path,
        index=False,
    )

    report = {
        "step": "3.6-secondary-identifier-resolution",
        "input_sponsors": EXPECTED_SPONSORS,
        "input_candidate_rows": EXPECTED_CANDIDATES,
        "human_decisions_preserved": int(human_mask.sum()),
        "human_match_decisions": int((human_mask & summary["final_decision"].eq("MATCH")).sum()),
        "human_no_match_decisions": int(
            (human_mask & summary["final_decision"].eq("NO_MATCH")).sum()
        ),
        "machine_deterministic_decisions": int(machine_mask.sum()),
        "machine_exact_ein_matches": int(machine_match_mask.sum()),
        "machine_all_known_ein_no_matches": int(machine_no_match_mask.sum()),
        "unresolved_sponsors": int(unresolved_mask.sum()),
        "sec_unique_ciks": len(unique_ciks),
        "sec_fetched": fetched,
        "sec_cache_hits": cached,
        "sec_fetch_failures": failed,
        "fuzzy_score_auto_accept": False,
        "exact_name_auto_accept": False,
        "manual_adjudication_file_modified": False,
        "machine_decisions_labeled_as_human": False,
        "protocol_amendment_required": True,
        "step_3_7_executed": False,
        "input_evidence_sha256": sha256_file(evidence_path),
        "input_manual_adjudication_sha256": (sha256_file(adjudication_path)),
        "resolution_sha256": sha256_file(summary_output_path),
        "candidate_enrichment_sha256": sha256_file(candidate_output_path),
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

    print()
    print(f"TOTAL_SPONSORS={len(summary)}")
    print(f"HUMAN_DECISIONS_PRESERVED={int(human_mask.sum())}")
    print(f"MACHINE_DETERMINISTIC_DECISIONS={int(machine_mask.sum())}")
    print(f"MACHINE_EXACT_EIN_MATCHES={int(machine_match_mask.sum())}")
    print(f"MACHINE_ALL_KNOWN_EIN_NO_MATCHES={int(machine_no_match_mask.sum())}")
    print(f"UNRESOLVED_SPONSORS={int(unresolved_mask.sum())}")
    print(f"SEC_FETCH_FAILURES={failed}")
    print("FUZZY_SCORE_AUTO_ACCEPT=NO")
    print("EXACT_NAME_AUTO_ACCEPT=NO")
    print("MANUAL_ADJUDICATION_FILE_MODIFIED=NO")
    print("MACHINE_DECISIONS_LABELED_AS_HUMAN=NO")
    print("PROTOCOL_AMENDMENT_REQUIRED=YES")
    print("STEP_3_7_EXECUTED=NO")

    if failed > 0:
        print("SECONDARY_IDENTIFIER_GATE=PARTIAL_SEC_FETCH")
        print("NEXT_ACTION=RERUN_TO_RETRY_FAILED_SEC_FETCHES")
    elif int(unresolved_mask.sum()) > 0:
        print("SECONDARY_IDENTIFIER_GATE=PASS")
        print("NEXT_ACTION=REVIEW_ONLY_UNRESOLVED_SPONSORS")
    else:
        print("SECONDARY_IDENTIFIER_GATE=PASS")
        print("HYBRID_RESOLUTION_COMPLETE=YES")
        print("NEXT_ACTION=FORMALIZE_STEP_3_6_PROTOCOL_AMENDMENT")


if __name__ == "__main__":
    main()
