"""Tests for deterministic Step 3.6 secondary-identifier resolution."""

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "resolve_sec_secondary_identifiers.py"
)

SPEC = importlib.util.spec_from_file_location(
    "resolve_sec_secondary_identifiers",
    MODULE_PATH,
)

if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load secondary-identifier resolver.")

MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_sponsor_ein_from_id() -> None:
    assert MODULE.sponsor_ein_from_id("SP-010263198") == "010263198"

    assert MODULE.sponsor_ein_from_id("BAD") == ""


def test_exact_ein_match() -> None:
    result = MODULE.classify_secondary_identifier(
        sponsor_ein="010263198",
        candidate_ranks=[1, 2],
        candidate_eins=[
            "731283193",
            "010263198",
        ],
        fetch_statuses=[
            "FETCHED",
            "FETCHED",
        ],
    )

    assert result[0] == "MATCH"
    assert result[1] == "2"
    assert result[2] == "DETERMINISTIC_EXACT_EIN"


def test_all_known_eins_different() -> None:
    result = MODULE.classify_secondary_identifier(
        sponsor_ein="010263198",
        candidate_ranks=[1],
        candidate_eins=[
            "731283193",
        ],
        fetch_statuses=[
            "CACHE",
        ],
    )

    assert result[0] == "NO_MATCH"
    assert result[1] == ""
    assert result[2] == "DETERMINISTIC_ALL_SEC_EINS_DIFFER"


def test_missing_ein_remains_unresolved() -> None:
    result = MODULE.classify_secondary_identifier(
        sponsor_ein="010263198",
        candidate_ranks=[1],
        candidate_eins=[""],
        fetch_statuses=["FETCHED"],
    )

    assert result[0] == ""
    assert result[2] == "UNRESOLVED"


def test_failed_fetch_remains_unresolved() -> None:
    result = MODULE.classify_secondary_identifier(
        sponsor_ein="010263198",
        candidate_ranks=[1],
        candidate_eins=["731283193"],
        fetch_statuses=["FETCH_FAILED"],
    )

    assert result[0] == ""
    assert result[2] == "UNRESOLVED"


def test_duplicate_exact_ein_is_not_auto_resolved() -> None:
    result = MODULE.classify_secondary_identifier(
        sponsor_ein="010263198",
        candidate_ranks=[1, 2],
        candidate_eins=[
            "010263198",
            "010263198",
        ],
        fetch_statuses=[
            "FETCHED",
            "FETCHED",
        ],
    )

    assert result[0] == ""
    assert result[2] == "UNRESOLVED"
