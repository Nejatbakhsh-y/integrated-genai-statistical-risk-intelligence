import runpy
from pathlib import Path

MODULE = runpy.run_path(str(Path("scripts/generate_sec_fuzzy_candidates.py")))


def test_fuzzy_configuration_is_frozen() -> None:
    assert MODULE["EXPECTED_INPUT_POPULATION"] == 10_665
    assert MODULE["MAX_CANDIDATES_PER_SPONSOR"] == 5
    assert MODULE["MINIMUM_CANDIDATE_SCORE"] == 90.0
    assert MODULE["STRONG_CANDIDATE_SCORE"] == 95.0
    assert MODULE["MINIMUM_BEST_VS_SECOND_MARGIN"] == 5.0
    assert MODULE["FUZZY_METHOD"] == "RapidFuzz WRatio"


def test_fuzzy_candidate_never_auto_accepts() -> None:
    disposition = MODULE["manual_review_disposition"]

    assert disposition(1) == "MANUAL_REVIEW"
    assert disposition(5) == "MANUAL_REVIEW"
    assert disposition(0) == "UNMATCHED"

    assert disposition(1) != "HIGH_CONFIDENCE_MATCH"
    assert disposition(5) != "HIGH_CONFIDENCE_MATCH"


def test_name_normalization_is_deterministic() -> None:
    normalize = MODULE["normalize_name"]

    assert normalize("ABC, Inc.") == "ABC INC"
    assert normalize("ABC & Co.") == "ABC AND CO"
    assert normalize("  ABC   CORPORATION ") == "ABC CORPORATION"


def test_cik_normalization_is_ten_digits() -> None:
    normalize_cik = MODULE["normalize_cik"]

    assert normalize_cik("320193") == "0000320193"
    assert normalize_cik("0000320193") == "0000320193"
