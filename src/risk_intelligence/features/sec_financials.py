"""Point-in-time SEC/XBRL sponsor financials for Milestone 4 Step 4.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

TRANSFORMATION_VERSION = "4.2.0"
ANNUAL_FORMS = frozenset(
    {
        "10-K",
        "10-K/A",
        "10-KT",
        "10-KT/A",
        "20-F",
        "20-F/A",
        "40-F",
        "40-F/A",
    }
)
MONETARY_UNIT = "USD"


@dataclass(frozen=True)
class FactCandidate:
    taxonomy: str
    concept: str
    period_type: str


METRIC_CANDIDATES: dict[str, tuple[FactCandidate, ...]] = {
    "total_assets": (
        FactCandidate("us-gaap", "Assets", "instant"),
        FactCandidate("ifrs-full", "Assets", "instant"),
    ),
    "total_liabilities": (
        FactCandidate("us-gaap", "Liabilities", "instant"),
        FactCandidate("ifrs-full", "Liabilities", "instant"),
    ),
    "debt": (
        FactCandidate("us-gaap", "LongTermDebtAndFinanceLeaseObligations", "instant"),
        FactCandidate("us-gaap", "LongTermDebt", "instant"),
        FactCandidate("us-gaap", "LongTermDebtAndFinanceLeaseObligationsNoncurrent", "instant"),
        FactCandidate("us-gaap", "LongTermDebtNoncurrent", "instant"),
        FactCandidate("ifrs-full", "Borrowings", "instant"),
        FactCandidate("ifrs-full", "NoncurrentBorrowings", "instant"),
    ),
    "cash": (
        FactCandidate("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "instant"),
        FactCandidate(
            "us-gaap",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "instant",
        ),
        FactCandidate("ifrs-full", "CashAndCashEquivalents", "instant"),
    ),
    "revenue": (
        FactCandidate(
            "us-gaap",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "duration",
        ),
        FactCandidate("us-gaap", "SalesRevenueNet", "duration"),
        FactCandidate("us-gaap", "Revenues", "duration"),
        FactCandidate("ifrs-full", "Revenue", "duration"),
    ),
    "operating_income": (
        FactCandidate("us-gaap", "OperatingIncomeLoss", "duration"),
        FactCandidate("ifrs-full", "ProfitLossFromOperatingActivities", "duration"),
    ),
    "operating_cash_flow": (
        FactCandidate(
            "us-gaap",
            "NetCashProvidedByUsedInOperatingActivities",
            "duration",
        ),
        FactCandidate(
            "ifrs-full",
            "CashFlowsFromUsedInOperatingActivities",
            "duration",
        ),
    ),
    "pension_plan_assets": (
        FactCandidate("us-gaap", "DefinedBenefitPlanFairValueOfPlanAssets", "instant"),
        FactCandidate("ifrs-full", "FairValueOfPlanAssets", "instant"),
    ),
    "pension_projected_benefit_obligation": (
        FactCandidate(
            "us-gaap",
            "DefinedBenefitPlanProjectedBenefitObligation",
            "instant",
        ),
        FactCandidate("ifrs-full", "PresentValueOfDefinedBenefitObligation", "instant"),
    ),
    "pension_employer_contributions": (
        FactCandidate("us-gaap", "DefinedBenefitPlanContributionsByEmployer", "duration"),
        FactCandidate("ifrs-full", "ContributionsByEmployer", "duration"),
    ),
}

CORE_METRICS = (
    "total_assets",
    "total_liabilities",
    "debt",
    "cash",
    "revenue",
    "operating_income",
    "operating_cash_flow",
)
PENSION_STATEMENT_METRICS = (
    "pension_plan_assets",
    "pension_projected_benefit_obligation",
    "pension_employer_contributions",
)
ALL_BASE_METRICS = CORE_METRICS + PENSION_STATEMENT_METRICS


def normalize_cik(value: object) -> str:
    """Return a 10-digit numeric SEC CIK."""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    digits = "".join(character for character in text if character.isdigit())
    if not digits or len(digits) > 10:
        raise ValueError(f"Invalid SEC CIK: {value!r}")
    return digits.zfill(10)


def _to_timestamp(value: object) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _to_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _to_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(result):
        return None
    return result


def _duration_is_annual(fact: dict[str, Any]) -> bool:
    start = _to_timestamp(fact.get("start"))
    end = _to_timestamp(fact.get("end"))
    if start is None or end is None or end < start:
        return False
    span_days = int((end - start).days) + 1
    return 250 <= span_days <= 450


def eligible_candidate_facts(
    payload: dict[str, Any],
    candidate: FactCandidate,
    *,
    plan_year: int,
    forecast_cutoff: pd.Timestamp,
) -> list[dict[str, Any]]:
    """Return annual USD facts eligible under the frozen point-in-time cutoff."""
    concept = payload.get("facts", {}).get(candidate.taxonomy, {}).get(candidate.concept, {})
    unit_facts = concept.get("units", {}).get(MONETARY_UNIT, [])
    if not isinstance(unit_facts, list):
        return []

    cutoff = pd.Timestamp(forecast_cutoff).normalize()
    eligible: list[dict[str, Any]] = []
    for raw in unit_facts:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("form", "")).strip() not in ANNUAL_FORMS:
            continue

        fy = _to_int(raw.get("fy"))
        if fy != int(plan_year):
            continue

        filed = _to_timestamp(raw.get("filed"))
        end = _to_timestamp(raw.get("end"))
        value = _to_float(raw.get("val"))
        if filed is None or end is None or value is None:
            continue
        if filed > cutoff or end > cutoff:
            continue
        if candidate.period_type == "duration" and not _duration_is_annual(raw):
            continue

        eligible.append(
            {
                "value": value,
                "filed_date": filed,
                "period_end": end,
                "period_start": _to_timestamp(raw.get("start")),
                "accession": str(raw.get("accn", "")).strip(),
                "form": str(raw.get("form", "")).strip(),
                "fy": fy,
                "fp": str(raw.get("fp", "")).strip(),
                "frame": str(raw.get("frame", "")).strip(),
                "unit": MONETARY_UNIT,
                "taxonomy": candidate.taxonomy,
                "concept": candidate.concept,
            }
        )
    return eligible


def select_metric_fact(
    payload: dict[str, Any],
    metric: str,
    *,
    plan_year: int,
    forecast_cutoff: pd.Timestamp,
) -> dict[str, Any] | None:
    """Select one point-in-time annual fact using period recency then concept priority."""
    if metric not in METRIC_CANDIDATES:
        raise KeyError(f"Unsupported SEC metric: {metric}")

    ranked: list[dict[str, Any]] = []
    for priority, candidate in enumerate(METRIC_CANDIDATES[metric]):
        facts = eligible_candidate_facts(
            payload,
            candidate,
            plan_year=plan_year,
            forecast_cutoff=forecast_cutoff,
        )
        for fact in facts:
            ranked.append({**fact, "candidate_priority": priority})

    if not ranked:
        return None

    ranked.sort(
        key=lambda fact: (
            -pd.Timestamp(fact["period_end"]).value,
            -pd.Timestamp(fact["filed_date"]).value,
            int(fact["candidate_priority"]),
            str(fact["accession"]),
        )
    )
    return ranked[0]


def safe_ratio(numerator: object, denominator: object, *, positive_denominator: bool) -> float:
    num = _to_float(numerator)
    den = _to_float(denominator)
    if num is None or den is None:
        return float("nan")
    if positive_denominator and den <= 0:
        return float("nan")
    if not positive_denominator and den == 0:
        return float("nan")
    return float(num / den)


def _clean_skeleton(skeleton: pd.DataFrame) -> pd.DataFrame:
    required = {"sponsor_id", "sec_cik", "plan_year", "forecast_cutoff"}
    missing = sorted(required - set(skeleton.columns))
    if missing:
        raise ValueError(f"Step-4.1 skeleton missing columns: {missing}")

    work = skeleton[list(required)].copy()
    work["sponsor_id"] = work["sponsor_id"].astype("string").str.strip()
    work["sec_cik"] = work["sec_cik"].map(normalize_cik).astype("string")
    work["plan_year"] = pd.to_numeric(work["plan_year"], errors="raise").astype(int)
    work["forecast_cutoff"] = pd.to_datetime(work["forecast_cutoff"], errors="raise").dt.normalize()

    if work["sponsor_id"].isna().any() or work["sponsor_id"].eq("").any():
        raise ValueError("Blank sponsor_id in Step-4.1 skeleton.")
    if work.duplicated(["sponsor_id", "plan_year"], keep=False).any():
        raise ValueError("Duplicate sponsor-year rows in Step-4.1 skeleton.")
    return work.sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)


def build_sec_sponsor_year_financials(
    skeleton: pd.DataFrame,
    payload_by_cik: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    """Build a sponsor-year SEC financial frame without future information."""
    work = _clean_skeleton(skeleton)
    missing_payloads = sorted(set(work["sec_cik"]) - set(payload_by_cik))
    if missing_payloads:
        raise ValueError(f"Missing companyfacts payloads for {len(missing_payloads)} CIKs.")

    rows: list[dict[str, Any]] = []
    for record in work.itertuples(index=False):
        sponsor_id = str(record.sponsor_id)
        cik = str(record.sec_cik)
        plan_year = int(record.plan_year)
        cutoff = pd.Timestamp(record.forecast_cutoff).normalize()
        payload = payload_by_cik[cik]

        row: dict[str, Any] = {
            "sponsor_id": sponsor_id,
            "sec_cik": cik,
            "plan_year": plan_year,
            "forecast_cutoff": cutoff,
            "sec_entity_name": str(payload.get("entityName", "")).strip() or pd.NA,
            "sec_transformation_version": TRANSFORMATION_VERSION,
        }
        selected_dates: list[pd.Timestamp] = []

        for metric in ALL_BASE_METRICS:
            selected = select_metric_fact(
                payload,
                metric,
                plan_year=plan_year,
                forecast_cutoff=cutoff,
            )
            prefix = f"sec_{metric}"
            if selected is None:
                row[prefix] = float("nan")
                row[f"{prefix}_taxonomy"] = pd.NA
                row[f"{prefix}_concept"] = pd.NA
                row[f"{prefix}_period_start"] = pd.NaT
                row[f"{prefix}_period_end"] = pd.NaT
                row[f"{prefix}_filed_date"] = pd.NaT
                row[f"{prefix}_form"] = pd.NA
                row[f"{prefix}_accession"] = pd.NA
                row[f"{prefix}_unit"] = pd.NA
                row[f"{prefix}_candidate_priority"] = pd.NA
                continue

            filed_date = pd.Timestamp(selected["filed_date"]).normalize()
            if filed_date > cutoff:
                raise ValueError(f"Temporal violation for {sponsor_id=} {plan_year=} {metric=}")
            selected_dates.append(filed_date)
            row[prefix] = float(selected["value"])
            row[f"{prefix}_taxonomy"] = selected["taxonomy"]
            row[f"{prefix}_concept"] = selected["concept"]
            row[f"{prefix}_period_start"] = selected["period_start"]
            row[f"{prefix}_period_end"] = selected["period_end"]
            row[f"{prefix}_filed_date"] = filed_date
            row[f"{prefix}_form"] = selected["form"]
            row[f"{prefix}_accession"] = selected["accession"]
            row[f"{prefix}_unit"] = selected["unit"]
            row[f"{prefix}_candidate_priority"] = int(selected["candidate_priority"])

        row["sec_profitability"] = safe_ratio(
            row["sec_operating_income"],
            row["sec_revenue"],
            positive_denominator=False,
        )
        row["sec_leverage"] = safe_ratio(
            row["sec_total_liabilities"],
            row["sec_total_assets"],
            positive_denominator=True,
        )
        row["sec_liquidity"] = safe_ratio(
            row["sec_cash"],
            row["sec_total_assets"],
            positive_denominator=True,
        )
        row["sec_information_date"] = max(selected_dates) if selected_dates else pd.NaT
        row["sec_selected_metric_count"] = len(selected_dates)
        row["sec_core_metric_count"] = sum(
            pd.notna(row[f"sec_{metric}"]) for metric in CORE_METRICS
        )
        rows.append(row)

    result = pd.DataFrame(rows).sort_values(["sponsor_id", "plan_year"]).reset_index(drop=True)
    if len(result) != len(work):
        raise ValueError("SEC sponsor-year frame changed skeleton row count.")
    if result.duplicated(["sponsor_id", "plan_year"], keep=False).any():
        raise ValueError("SEC sponsor-year frame contains duplicate sponsor-years.")
    violations = result["sec_information_date"].notna() & result["sec_information_date"].gt(
        result["forecast_cutoff"]
    )
    if violations.any():
        raise ValueError("SEC sponsor-year frame contains future information.")
    return result


def metric_metadata_columns(metric: str) -> tuple[str, ...]:
    prefix = f"sec_{metric}"
    return (
        f"{prefix}_taxonomy",
        f"{prefix}_concept",
        f"{prefix}_period_start",
        f"{prefix}_period_end",
        f"{prefix}_filed_date",
        f"{prefix}_form",
        f"{prefix}_accession",
        f"{prefix}_unit",
        f"{prefix}_candidate_priority",
    )
