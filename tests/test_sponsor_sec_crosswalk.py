"""Tests for Step 3.7 sponsor-SEC crosswalk builder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_sponsor_sec_crosswalk.py"

SPEC = importlib.util.spec_from_file_location(
    "build_sponsor_sec_crosswalk",
    MODULE_PATH,
)

if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load Step 3.7 crosswalk builder.")

MODULE = importlib.util.module_from_spec(SPEC)

SPEC.loader.exec_module(MODULE)


def test_normalize_cik() -> None:
    assert MODULE.normalize_cik("1000275") == "0001000275"

    assert MODULE.normalize_cik("0001114446") == "0001114446"


def test_normalize_blank_cik() -> None:
    assert MODULE.normalize_cik("") == ""


def test_sponsor_ein() -> None:
    assert MODULE.sponsor_ein("SP-010263198") == "010263198"


def test_invalid_sponsor_ein() -> None:
    assert MODULE.sponsor_ein("INVALID") == ""


def test_expected_crosswalk_arithmetic() -> None:
    assert MODULE.STEP34_HIGH_CONFIDENCE + MODULE.STEP36_LINKED == MODULE.EXPECTED_FINAL_LINKED


def test_expected_full_population_arithmetic() -> None:
    assert (
        MODULE.EXPECTED_FINAL_LINKED
        + MODULE.STEP34_MANUAL_REVIEW
        + MODULE.STEP36_SUPPORTED_NO_MATCH
        + MODULE.STEP36_UNRESOLVED
        + MODULE.STEP36_NO_CANDIDATE
        == MODULE.TOTAL_SPONSORS
    )
