# Milestone 4 - Structured X Panel

## Status

Milestone 4 remains in progress. Step 4.3 ingests and aligns point-in-time market variables to the same frozen sponsor-year forecast cutoff. The final multi-family structured panel is not yet complete, and the release tag `v0.5.0-structured-panel` must not be created at this step.

Target final local analytical artifact:

`data/processed/sponsor_year_X.parquet`

Frozen Step-4.1 pension artifact:

`data/interim/structured_x/step_4_1/pension_sponsor_year_base.parquet`

Step-4.2 local artifacts:

- `data/interim/structured_x/step_4_2/sec_sponsor_year_financials.parquet`
- `data/interim/structured_x/step_4_2/pension_sec_sponsor_year_base.parquet`

All Parquet artifacts and raw SEC Company Facts JSON files are local-only and must not be tracked in Git.

## Frozen Upstream Handoff

The Step-4.2 analytical skeleton remains exactly:

- 729 linked sponsors;
- 729 unique SEC CIKs;
- 5,934 sponsor-year observations;
- plan years 2015 through 2024;
- grain `sponsor_id x plan_year`.

The Step-4.1 forecast cutoff remains:

`forecast_cutoff(i,t) = October 15 of calendar year t+1`

Step 4.2 does not alter that policy.

## SEC Company Facts Source

Step 4.2 uses the SEC EDGAR Company Facts endpoint:

`https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`

The automation attempts all 729 frozen CIKs, writes the returned JSON to `data/raw/sec_xbrl/companyfacts/`, and records a tracked source manifest containing endpoint, HTTP status, byte count, SHA-256, entity name, taxonomy count, and concept count. Raw JSON is never committed.

A 404 Company Facts response is treated as legitimate source unavailability and therefore produces analytical missingness. Other unrecoverable HTTP failures stop the step rather than being reinterpreted as missing financial data.

## Point-in-Time SEC Eligibility

A standardized SEC fact can enter sponsor-year `t` only when all of the following hold:

1. the filing is an annual form in the frozen allowlist (`10-K`, `10-K/A`, `10-KT`, `10-KT/A`, `20-F`, `20-F/A`, `40-F`, or `40-F/A`);
2. the XBRL fiscal-year field satisfies `fy == plan_year`;
3. the filing date is on or before the frozen sponsor-year forecast cutoff;
4. the fact period end is on or before the forecast cutoff;
5. duration facts use an annual context spanning 250 through 450 days;
6. the fact is reported in USD.

No filing submitted after the cutoff may revise an earlier sponsor-year value. No future observation is backfilled. A missing eligible fact remains missing.

## Deterministic Concept Selection

Step 4.2 freezes ordered US-GAAP and IFRS synonym hierarchies for total assets, total liabilities, debt, cash, revenue, operating income, operating cash flow, and selected pension-statement items.

For a metric with multiple eligible candidate facts, selection is deterministic:

1. latest eligible period end;
2. latest eligible filing date;
3. lowest frozen concept-priority rank;
4. accession number as the final deterministic tie-breaker.

Selected concept, taxonomy, period start/end, filing date, form, accession number, unit, and concept-priority rank are retained in the local sponsor-year artifact.

## Sponsor-Financial Variables

The Step-4.2 sponsor-financial family contains:

- `sec_total_assets`
- `sec_total_liabilities`
- `sec_debt`
- `sec_cash`
- `sec_revenue`
- `sec_operating_income`
- `sec_operating_cash_flow`
- `sec_profitability = sec_operating_income / sec_revenue`
- `sec_leverage = sec_total_liabilities / sec_total_assets`
- `sec_liquidity = sec_cash / sec_total_assets`
- `sec_pension_plan_assets`
- `sec_pension_projected_benefit_obligation`
- `sec_pension_employer_contributions`

The debt field is a frozen hierarchy-based reported debt proxy: preferred total debt/finance-lease obligation concepts are used first, followed by long-term debt concepts when the preferred concepts are absent.

## Pension Size Denominator

Step 4.2 resolves the Step-4.1 pending sponsor-financial denominator by defining:

`pension_size = Form5500 pension liabilities / SEC total assets`

Additional scale variables are retained:

- `pension_assets_to_sponsor_assets`
- `pension_liabilities_to_sponsor_assets`
- `pension_contributions_to_revenue`

Ratios remain missing when their required numerator or denominator is missing or when a required asset denominator is not strictly positive.

## Grain Preservation

The SEC sponsor-year frame is joined one-to-one to the frozen Step-4.1 pension skeleton on:

- `sponsor_id`
- `sec_cik`
- `plan_year`
- `forecast_cutoff`

The join must return exactly 5,934 rows and zero duplicate sponsor-years. Sponsor-years with no eligible SEC financial facts remain in the panel with missing sponsor-financial fields.

## Step-4.2 Audit Artifacts

Tracked audit artifacts include:

- raw Company Facts source manifest;
- sponsor-year temporal-integrity audit;
- deterministic concept-selection summary;
- sponsor-financial and derived-variable missingness audit;
- financial coverage by plan year;
- Step-4.2 summary audit JSON.

The local SEC and joined Parquet outputs are explicitly excluded from Git.

## Step-4.2 Acceptance Gate

Step 4.2 passes only if:

1. execution starts on `feature/04-structured-x-panel` at the frozen Step-4.1 commit;
2. the frozen Step-4.1 local artifact is present and its current SHA-256 is recorded;
3. all 729 CIKs are attempted through the SEC Company Facts source;
4. SEC annual facts satisfy the frozen fiscal-year and point-in-time filters;
5. deterministic concept selection is applied exactly as configured;
6. every selected SEC filing date is on or before `forecast_cutoff`;
7. the sponsor-year SEC frame contains exactly 5,934 unique sponsor-year rows;
8. the pension-plus-SEC join contains exactly 5,934 unique sponsor-year rows;
9. missing SEC facts remain missing rather than being zero-filled or future-filled;
10. Ruff, Pytest, and Git diff checks pass;
11. no raw SEC JSON or Parquet file is staged or committed;
12. only Step-4.2 code, configuration, tests, documentation, and tracked audit artifacts are committed.

## Step-4.3 Point-in-Time Market Variables

Step 4.3 preserves the 5,934-row `sponsor_id x plan_year` skeleton and the frozen
October-15-of-t+1 cutoff. It uses SEC ticker/exchange associations only as entity-resolution
metadata and does not expose ticker or exchange status as a model feature. The SEC notes that
its ticker-association files are periodically updated and are not guaranteed for accuracy or
scope; unresolved sponsors therefore remain missing rather than receiving inferred historical
tickers.

Daily USD equity history is retrieved from the Yahoo Finance chart feed and cached locally
under `data/raw/market/yahoo_finance/`. Raw market files are not committed. For each
sponsor-year, the last trading close on or before `forecast_cutoff` is the as-of price. A
trailing window requires 253 observations, yielding exactly 252 daily return intervals.
Regular close is retained for market capitalization; adjusted close is used for return,
volatility, and drawdown. Because the provider presents historical prices on a split-normalized
basis, SEC shares are multiplied by cumulative split ratios after the selected shares period
end before market capitalization is computed. Split metadata is retained only as unit
normalization provenance, not as a predictive feature.

Frozen Step-4.3 features are:

- `market_equity_return`: adjusted close at the cutoff divided by adjusted close 252 trading
  intervals earlier, minus one;
- `market_equity_volatility`: annualized standard deviation of the 252 adjusted-close daily
  log returns, using `sqrt(252)` annualization;
- `market_equity_drawdown`: minimum adjusted-close/running-peak minus one over the same
  window;
- `market_capitalization`: regular cutoff close multiplied by the latest eligible SEC shares
  normalized to the provider split basis, only when the CIK has one ticker association.

The shares-outstanding hierarchy is `dei:EntityCommonStockSharesOutstanding` followed by
`us-gaap:CommonStockSharesOutstanding`. No post-cutoff price or filing may enter an earlier
sponsor-year. Missing ticker associations, price histories, short price windows, or eligible
share facts remain missing; there is no zero fill, future backfill, or manual ticker inference.

Step-4.3 audit results:

- target CIKs: 729;
- CIKs with SEC ticker association: 450;
- CIKs with usable USD Yahoo Finance history: 450;
- sponsor-year rows: 5934;
- temporal violations: 0;
- equity-return nonmissing: 3862;
- equity-volatility nonmissing: 3862;
- equity-drawdown nonmissing: 3862;
- market-capitalization nonmissing: 3211.

Local Step-4.3 artifacts:

- `data/interim/structured_x/step_4_3/market_sponsor_year_features.parquet`;
- `data/interim/structured_x/step_4_3/pension_sec_market_sponsor_year_base.parquet`.

Both Parquet files are local-only and excluded from Git.

## Step-4.3 Acceptance Gate

Step 4.3 passes only if the frozen Step-4.2 artifact hash is unchanged; the SEC ticker
reference and Yahoo Finance histories are provenance-audited; market features use only observations
available by each cutoff; the 5,934-row sponsor-year grain is preserved; temporal violations
are zero; missingness is retained; Ruff, Pytest, and Git diff gates pass; and neither raw
market files nor Parquet artifacts enter Git.

## Step-4.4 Point-in-Time Macro Variables

Step 4.4 preserves the frozen 5,934-row `sponsor_id x plan_year` skeleton and uses an
ALFRED vintage exactly equal to each sponsor-year `forecast_cutoff`. This prevents a later
revision from replacing the value that was actually knowable at the historical cutoff.
ALFRED raw CSV snapshots are cached locally under `data/raw/macro/alfred/` and are excluded
from Git.

The frozen macro registry is:

- `DGS10` -> `macro_interest_rate_10y`, the 10-year U.S. Treasury constant-maturity yield;
- `CPIAUCNS` -> `macro_inflation_yoy`, the year-over-year percent change in CPI-U All Items
  computed from levels inside the same cutoff vintage;
- `NFCI` -> `macro_credit_conditions_nfci`, the Chicago Fed National Financial Conditions
  Index, where positive values indicate tighter-than-average financial conditions;
- `UNRATE` -> `macro_unemployment_rate`, the U-3 unemployment rate.

For each series and each of the ten frozen forecast cutoffs, the automation downloads a
historical ALFRED graph snapshot with `vintage_date == forecast_cutoff`. The selected
observation must be on or before the cutoff. Inflation uses the latest available CPI level and
the same calendar month one year earlier from that same vintage. No later vintage, later
observation, zero fill, or future backfill is allowed.

Step-4.4 audit results:

- unique forecast cutoffs: 10;
- raw ALFRED snapshot requests: 40;
- macro year rows: 10;
- sponsor-year macro rows: 5934;
- joined sponsor-year rows: 5934;
- temporal violations: 0;
- interest-rate nonmissing: 5934;
- inflation nonmissing: 5934;
- credit-conditions nonmissing: 5934;
- unemployment nonmissing: 5934.

Local Step-4.4 artifacts:

- `data/interim/structured_x/step_4_4/macro_sponsor_year_features.parquet`;
- `data/interim/structured_x/step_4_4/pension_sec_market_macro_sponsor_year_base.parquet`.

Both Parquet files are local-only and excluded from Git. Step 4.4 completes the ingestion of
all four structured-X information families, but it does not yet create the final release
artifact or the `v0.5.0-structured-panel` tag.

## Step-4.4 Acceptance Gate

Step 4.4 passes only if the frozen Step-4.3 joined-artifact hash is unchanged; all four macro
series are retrieved from cutoff-specific ALFRED vintages; every selected observation is on
or before its forecast cutoff; the 5,934-row sponsor-year grain is preserved; temporal
violations are zero; missingness is retained; Ruff, Pytest, and Git diff gates pass; and no
raw macro snapshot or Parquet artifact enters Git.

## Next Step

Step 4.5 will finalize and freeze the complete structured-X panel, perform the final
multi-family completeness and provenance gates, materialize the local final analytical
artifact, and only then determine whether the Milestone-4 release can be merged and tagged.

## Step-4.5 Final Structured-X Freeze

Step 4.5 promotes the frozen Step-4.4 pension/SEC/market/macro joined artifact to the final
local analytical artifact:

`data/processed/sponsor_year_X.parquet`

The promotion is byte-for-byte. Step 4.5 performs no value transformation and no imputation.
The final artifact therefore has the same SHA-256 as the frozen Step-4.4 joined artifact:

`6E7C3954CE1F23110B4A88E7A83E5CEC5C6B759825670DB9A90682CE5AA56ACF`

Final gates verify 5,934 sponsor-year rows, 729 sponsors, 729 SEC CIKs, plan years 2015-2024,
zero duplicate sponsor-years, the frozen October-15-of-t+1 cutoff, zero detected temporal
violations across retained provenance dates, and the presence of all four structured-X families.
The final feature contract contains 31 prespecified model features.

Raw, interim, and final Parquet data remain local-only and are excluded from Git. Tracked
Step-4.5 evidence consists only of code, configuration, tests, documentation, and audit reports.

Step 4.5 authorizes but does not execute the Milestone-4 release. The feature branch is not
merged into `develop` and `v0.5.0-structured-panel` is not created until the separate controlled
Step-4.6 release operation.

## Step-4.5 Acceptance Gate

Step 4.5 passes only if the Step-4.4 joined-artifact hash is unchanged; all upstream Step-4.1
through Step-4.4 audits remain PASS; the final artifact is byte-identical to the Step-4.4
joined artifact; grain, temporal-integrity, feature-family, missingness, Ruff, Pytest, Git diff,
and Git data-safety gates pass; and the release remains unexecuted.

## Next Step

Step 4.6 will merge the fully frozen Milestone-4 feature branch into `develop`, verify the
post-merge repository state, and create/push `v0.5.0-structured-panel` only if every release
gate remains satisfied.
