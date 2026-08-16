# Milestone 4 - Structured X Panel

## Status

Step 4.0 establishes the input and governance contract for the structured
sponsor-year information set `X(i,t)`.

Target release:

`v0.5.0-structured-panel`

Target local analytical artifact:

`data/processed/sponsor_year_X.parquet`

The Parquet artifact remains local and is not committed to Git.

## Frozen Upstream Handoff

Milestone 4 starts from:

`v0.4.0-entity-linkage`

The frozen final sponsor-to-SEC crosswalk contains 729 linked public-company
sponsors and 729 unique SEC CIKs.

Frozen crosswalk SHA-256:

`264FF2DCD22223B654C122B7EE6F69B23CEA71A8885937D976C1BBCF8203D55A`

The linked pension population contains:

- 729 linked sponsors;
- 1,294 linked pension plans;
- 8,950 linked plan-year observations;
- plan years 2015 through 2024.

## Target Observation

The final structured panel grain is:

`sponsor_id x plan_year`

Multiple pension plans belonging to the same sponsor-year therefore require
explicit aggregation before sponsor financial, market, and macro variables are
joined.

## Structured Information Families

### Pension

Candidate information includes:

- funded ratio;
- assets;
- liabilities;
- contributions;
- benefit payments;
- participants;
- pension size.

The provisional funded-ratio aggregation is the ratio of aggregate sponsor-year
assets to aggregate sponsor-year liabilities, rather than an unweighted mean of
plan-level funded ratios.

### Sponsor Financials

SEC/EDGAR/XBRL information will include prespecified variables from the
financial statements and related pension disclosures, subject to historical
availability and temporal controls.

Candidate classes include:

- assets;
- liabilities;
- debt;
- cash;
- revenue;
- operating income;
- profitability;
- cash flow;
- leverage;
- liquidity;
- relevant pension statement items.

### Market

Candidate market information includes:

- equity return;
- volatility;
- drawdown;
- market capitalization.

### Macro

Candidate macroeconomic controls include:

- interest rates;
- inflation;
- credit conditions;
- unemployment.

The final variable set must be frozen before final modeling and must not be
selected using future holdout outcomes.

## Temporal Integrity

Every final sponsor-year observation must retain:

`information_date`

and:

`forecast_cutoff`

The governing rule is:

`information_date <= forecast_cutoff`

No future filing, future financial value, revised future pension value,
post-cutoff market observation, or retrospectively available macro observation
may enter `X(i,t)`.

Step 4.0 intentionally does not invent the forecast-cutoff calendar convention.
That policy must be frozen after examining the actual historical filing and
data-availability structure, before structured sources are integrated.

## Missingness

Step 4.0 prohibits:

- silent zero filling;
- future-value backfilling;
- future-informed imputation.

Missingness and coverage will be reported separately for each data family.

## Step 4.0 Acceptance Gate

Step 4.0 passes only if:

1. `develop` equals the Milestone-3 release commit;
2. local and remote `v0.4.0-entity-linkage` resolve to that commit;
3. the frozen crosswalk hash is unchanged;
4. the 729 linked sponsors reconcile to the frozen pension universe;
5. the linked pension population contains 8,950 plan-year rows and
   1,294 unique plans;
6. the four structured-data families are explicitly defined;
7. `information_date` and `forecast_cutoff` are mandatory;
8. Ruff passes;
9. Pytest passes;
10. no Parquet data are staged or committed.

## Step 4.1

Step 4.1 will freeze the forecast-cutoff semantics and construct the audited
pension sponsor-year base before external sponsor-financial, market, or macro
data are joined.

No final `sponsor_year_X.parquet` is claimed at Step 4.0.