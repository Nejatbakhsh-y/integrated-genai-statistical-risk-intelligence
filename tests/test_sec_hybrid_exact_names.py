"""Tests for Step 3.6 second-pass exact legal-name resolution."""

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "resolve_sec_hybrid_exact_names.py"

SPEC = importlib.util.spec_from_file_location(
    "resolve_sec_hybrid_exact_names",
    MODULE_PATH,
)

if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load exact-name resolver.")

MODULE = importlib.util.module_from_spec(SPEC)

SPEC.loader.exec_module(MODULE)


def test_unique_exact_name_with_missing_sec_ein_matches() -> None:
    result = MODULE.exact_name_decision(
        sponsor_name="ACME CORPORATION",
        sponsor_ein="123456789",
        candidate_rows=[
            {
                "manual_candidate_rank": "1",
                "sec_api_name": "Acme Corporation",
                "sec_api_ein": "",
            },
        ],
    )

    assert result[0] == "MATCH"
    assert result[1] == "1"
    assert result[2] == "DETERMINISTIC_UNIQUE_EXACT_LEGAL_NAME"


def test_exact_name_with_conflicting_ein_is_unresolved() -> None:
    result = MODULE.exact_name_decision(
        sponsor_name="ACME CORPORATION",
        sponsor_ein="123456789",
        candidate_rows=[
            {
                "manual_candidate_rank": "1",
                "sec_api_name": "ACME CORPORATION",
                "sec_api_ein": "987654321",
            },
        ],
    )

    assert result[0] == ""
    assert result[2] == "UNRESOLVED"


def test_no_exact_name_is_unresolved() -> None:
    result = MODULE.exact_name_decision(
        sponsor_name="ACME CORPORATION",
        sponsor_ein="123456789",
        candidate_rows=[
            {
                "manual_candidate_rank": "1",
                "sec_api_name": "ACME HOLDINGS INC",
                "sec_api_ein": "",
            },
        ],
    )

    assert result[0] == ""
    assert result[2] == "UNRESOLVED"


def test_multiple_exact_names_are_unresolved() -> None:
    result = MODULE.exact_name_decision(
        sponsor_name="ACME CORPORATION",
        sponsor_ein="123456789",
        candidate_rows=[
            {
                "manual_candidate_rank": "1",
                "sec_api_name": "ACME CORPORATION",
                "sec_api_ein": "",
            },
            {
                "manual_candidate_rank": "2",
                "sec_api_name": "ACME CORPORATION",
                "sec_api_ein": "",
            },
        ],
    )

    assert result[0] == ""
    assert result[2] == "UNRESOLVED"


def test_normalization_is_exact_not_fuzzy() -> None:
    assert MODULE.normalize_name("A & B, Inc.") == "A AND B INC"

    assert MODULE.normalize_name("A B Holdings") != MODULE.normalize_name("A B Holding")
