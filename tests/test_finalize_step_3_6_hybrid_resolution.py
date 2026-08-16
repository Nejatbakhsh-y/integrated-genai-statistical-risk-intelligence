"""Tests for Step 3.6 conservative finalization."""

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "finalize_step_3_6_hybrid_resolution.py"
)

SPEC = importlib.util.spec_from_file_location(
    "finalize_step_3_6_hybrid_resolution",
    MODULE_PATH,
)

if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load Step 3.6 finalizer.")

MODULE = importlib.util.module_from_spec(SPEC)

SPEC.loader.exec_module(MODULE)


def test_manual_match() -> None:
    disposition, accepted = MODULE.classify_final_disposition(
        "HUMAN",
        "MATCH",
        "MANUAL_ADJUDICATION",
    )

    assert disposition == "LINKED_MANUAL"
    assert accepted is True


def test_manual_no_match() -> None:
    disposition, accepted = MODULE.classify_final_disposition(
        "HUMAN",
        "NO_MATCH",
        "MANUAL_ADJUDICATION",
    )

    assert disposition == "REJECTED_MANUAL"
    assert accepted is False


def test_exact_ein_match() -> None:
    disposition, accepted = MODULE.classify_final_disposition(
        "MACHINE_DETERMINISTIC",
        "MATCH",
        "DETERMINISTIC_EXACT_EIN",
    )

    assert disposition == "LINKED_DETERMINISTIC_EXACT_EIN"

    assert accepted is True


def test_ein_mismatch_no_match() -> None:
    disposition, accepted = MODULE.classify_final_disposition(
        "MACHINE_DETERMINISTIC",
        "NO_MATCH",
        "DETERMINISTIC_ALL_SEC_EINS_DIFFER",
    )

    assert disposition == "REJECTED_DETERMINISTIC_EIN_MISMATCH"

    assert accepted is False


def test_exact_legal_name_match() -> None:
    disposition, accepted = MODULE.classify_final_disposition(
        "MACHINE_DETERMINISTIC",
        "MATCH",
        "DETERMINISTIC_UNIQUE_EXACT_LEGAL_NAME",
    )

    assert disposition == "LINKED_DETERMINISTIC_EXACT_LEGAL_NAME"

    assert accepted is True


def test_unresolved_retention() -> None:
    disposition, accepted = MODULE.classify_final_disposition(
        "UNRESOLVED",
        "",
        "UNRESOLVED",
    )

    assert disposition == "RETAIN_UNMATCHED_UNRESOLVED"

    assert accepted is False
