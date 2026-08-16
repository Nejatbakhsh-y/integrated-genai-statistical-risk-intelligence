"""Tests for Step 3.6 fuzzy-linkage manual review."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "manage_sec_fuzzy_manual_review.py"

SPEC = importlib.util.spec_from_file_location(
    "manage_sec_fuzzy_manual_review",
    MODULE_PATH,
)

if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load Step 3.6 review module.")

MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sponsor_id": [
                "S1",
                "S1",
                "S2",
            ],
            "sponsor_name": [
                "ALPHA HOLDINGS",
                "ALPHA HOLDINGS",
                "BETA CORP",
            ],
            "sec_cik": [
                "0000000001",
                "0000000002",
                "0000000003",
            ],
            "sec_name_norm": [
                "ALPHA HOLDINGS INC",
                "ALPHA INDUSTRIES INC",
                "BETA CORPORATION",
            ],
            "fuzzy_score": [
                100.0,
                94.0,
                96.0,
            ],
        }
    )


def test_detect_score_column() -> None:
    frame = sample_candidates()

    assert MODULE.detect_score_column(frame) == "fuzzy_score"


def test_evidence_ranking_is_manual_only() -> None:
    old_rows = MODULE.EXPECTED_CANDIDATE_ROWS
    old_sponsors = MODULE.EXPECTED_REVIEW_SPONSORS
    old_score_100 = MODULE.EXPECTED_SCORE_100_ROWS

    try:
        MODULE.EXPECTED_CANDIDATE_ROWS = 3
        MODULE.EXPECTED_REVIEW_SPONSORS = 2
        MODULE.EXPECTED_SCORE_100_ROWS = 1

        evidence, score_column = MODULE.build_evidence(sample_candidates())

        assert score_column == "fuzzy_score"

        sponsor_one = evidence.loc[evidence["sponsor_id"].eq("S1")]

        assert sponsor_one["manual_candidate_rank"].tolist() == [1, 2]

        assert evidence["fuzzy_auto_accept"].eq(False).all()

        score_100 = evidence.loc[pd.to_numeric(evidence["fuzzy_score"]).eq(100.0)]

        assert len(score_100) == 1

        assert score_100["score_100_requires_manual_review"].eq(True).all()
    finally:
        MODULE.EXPECTED_CANDIDATE_ROWS = old_rows
        MODULE.EXPECTED_REVIEW_SPONSORS = old_sponsors
        MODULE.EXPECTED_SCORE_100_ROWS = old_score_100


def test_adjudication_has_one_row_per_sponsor() -> None:
    old_rows = MODULE.EXPECTED_CANDIDATE_ROWS
    old_sponsors = MODULE.EXPECTED_REVIEW_SPONSORS
    old_score_100 = MODULE.EXPECTED_SCORE_100_ROWS

    try:
        MODULE.EXPECTED_CANDIDATE_ROWS = 3
        MODULE.EXPECTED_REVIEW_SPONSORS = 2
        MODULE.EXPECTED_SCORE_100_ROWS = 1

        evidence, score_column = MODULE.build_evidence(sample_candidates())

        adjudication = MODULE.build_adjudication(
            evidence,
            score_column,
        )

        assert len(adjudication) == 2
        assert adjudication["sponsor_id"].nunique() == 2

        assert adjudication["manual_decision"].eq("").all()

        assert adjudication["auto_accept_permitted"].eq(False).all()

        score_100_sponsor = adjudication.loc[adjudication["sponsor_id"].eq("S1")].iloc[0]

        assert bool(score_100_sponsor["contains_score_100_candidate"])

        assert not bool(score_100_sponsor["score_100_bypass_permitted"])
    finally:
        MODULE.EXPECTED_CANDIDATE_ROWS = old_rows
        MODULE.EXPECTED_REVIEW_SPONSORS = old_sponsors
        MODULE.EXPECTED_SCORE_100_ROWS = old_score_100
