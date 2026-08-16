# Milestone 4 - Structured X Panel

## Status

Milestone 4 remains in progress. Step 4.1 freezes the pension point-in-time
forecast cutoff and constructs the audited sponsor-year pension base. The final
multi-family structured panel is not yet complete and the release tag
`v0.5.0-structured-panel` must not be created at this step.

Target final local analytical artifact:

`data/processed/sponsor_year_X.parquet`

Step-4.1 local interim artifact:

`data/interim/structured_x/step_4_1/pension_sponsor_year_base.parquet`

Both Parquet artifacts are local-only and must not be tracked in Git.

## Frozen Upstream Handoff

Milestone 4 starts from `v0.4.0-entity-linkage` and the frozen sponsor-to-SEC
crosswalk.

Crosswalk SHA-256:

`264FF2DCD22223B654C122B7EE6F69B23CEA71A8885937D976C1BBCF8203D55A`

Sponsor-plan universe SHA-256 used by Step 4.1:

`ED22F81E6F6E407F0494CDBB94AB6D8FA84B9CF576C637D02E20A013735E6255`

Frozen linked pension population:

- 729 linked sponsors;
- 1,294 linked pension plans;
- 8,950 linked plan-year observations;
- 5,934 sponsor-year observations;
- plan years 2015 through 2024.

## Step-4.1 Forecast Cutoff

The Step-4.1 point-in-time policy is frozen as:

`forecast_cutoff(i,t) = October 15 of calendar year t+1`

The policy is common across sponsors for a given plan year and is fixed before
model fitting or holdout evaluation. It is not selected using outcomes.

For pension inputs, a plan filing is analytically available only when:

`information_date <= forecast_cutoff`

A filing with a missing information date or an information date after the
cutoff does not enter the point-in-time pension aggregation. The sponsor-year
skeleton remains present even when no plan filing is available by the cutoff.

Step 4.1 records July 31, September 30, October 15, and December 31 candidate
availability diagnostics for audit purposes. The frozen policy remains October
15 of t+1; the diagnostics do not select a policy using model outcomes.

## Deterministic Pension Aggregation

The sponsor-year grain is:

`sponsor_id x plan_year`

For each sponsor-year, aggregation uses only filings available by the frozen
cutoff.

Rules:

1. assets, liabilities, contributions, benefit payments, and participants are
   summed across available plans only when the field is nonmissing for every
   available plan;
2. partial field sums are not created when an available plan is missing the
   field;
3. funded ratio equals aggregate assets divided by aggregate liabilities;
4. funded ratio is missing when aggregate liabilities are unavailable or not
   strictly positive;
5. the unweighted mean of plan-level funded ratios is prohibited;
6. participant counts are summed under the provisional Step-4.0 rule and a
   `participants_overlap_risk` flag identifies sponsor-years with more than one
   available plan;
7. source-file provenance for available filings is retained;
8. pension size remains pending until a sponsor-financial denominator is
   defined in a later Milestone-4 step.

## Step-4.1 Audit Artifacts

Tracked audit artifacts include:

- forecast-cutoff diagnostics;
- sponsor-year temporal-detail audit;
- pension missingness audit;
- aggregation-identity audit;
- pension coverage by plan year;
- Step-4.1 summary audit JSON.

The interim pension Parquet is explicitly excluded from Git.

## Step-4.1 Acceptance Gate

Step 4.1 passes only if:

1. the feature branch starts from the frozen Step-4.0 commit;
2. the sponsor-universe and crosswalk hashes match the frozen inputs;
3. the linked population reconciles to 8,950 plan-year rows, 1,294 plans, 729
   sponsors, and 5,934 sponsor-years;
4. the October-15-of-t+1 cutoff is frozen in configuration;
5. the interim base contains exactly 5,934 unique sponsor-year rows;
6. `information_date <= forecast_cutoff` has zero violations;
7. deterministic aggregation identities pass;
8. duplicate and missingness audits pass;
9. Ruff and Pytest pass;
10. no Parquet file is staged or committed;
11. only Step-4.1 code, configuration, tests, documentation, and audit artifacts
    are committed.

## Next Step

Step 4.2 will ingest and align point-in-time SEC/EDGAR XBRL sponsor-financial
variables to the frozen sponsor-year cutoff policy.