
# Milestone 5 - Outcome Construction

## Step 5.0 Status

Step 5.0 freezes the Milestone-5 outcome-construction contract.

It does not construct outcomes, choose the material-deterioration threshold,
inspect the final holdout, or fit any predictive model.

Base release:

`v0.5.0-structured-panel`

Target release:

`v0.6.0-outcomes`

Feature branch:

`feature/05-outcome-construction`

## Frozen Analytical Handoff

Released develop commit:

`23733f807a8293f79ae2cc50c87b3d3fc3853c11`

Structured-X SHA-256:

`6E7C3954CE1F23110B4A88E7A83E5CEC5C6B759825670DB9A90682CE5AA56ACF`

Pension sponsor-year base SHA-256:

`2140DCC58293583A5E4877E6E03FBF919C1BAB1022BD6752F5F33C7AA2B84529`

## Primary Outcome

For sponsor `i` and predictor plan year `t`:

`FR(i,t) = A(i,t) / L(i,t)`

Continuous one-year-ahead outcome:

`DeltaFR(i,t+1) = FR(i,t+1) - FR(i,t)`

Negative values denote funding deterioration.

Binary material-deterioration outcome:

`D(i,t+1) = 1{DeltaFR(i,t+1) <= -c}`

The primary value of `c` is not chosen in Step 5.0.

## Temporal Alignment

A target requires an actual consecutive sponsor-year pair:

`target_plan_year = predictor_plan_year + 1`

Same-year targets are prohibited.

Nonconsecutive years cannot be relabeled as one-year outcomes.

Future funded status is the dependent variable only and cannot enter the
predictor information set.

Targets cannot be forward-filled, backfilled, silently zero-filled, or
otherwise imputed.

## Denominator Validity

Funded ratio requires strictly positive liabilities.

Invalid or missing funded ratios remain missing rather than receiving an
artificial target.

## Historical Release-Test Compatibility

Milestone-4 release tests continue to require every frozen Milestone-4 release
invariant.

Lifecycle-only assertions may advance after the release:

- `PROJECT_STAGE` may move to Milestone 5.
- `NEXT_STEP` may appear after a later milestone is formally started.

This does not alter the Milestone-4 release commit, tag, final-panel hash,
merge record, or scientific acceptance status.

## Repository Quality Baseline

The immutable `v0.5.0-structured-panel` release passes Ruff lint and Pytest but contains
eight historical Python files that are not Ruff-format-normalized.

Step 5.0 freezes that formatter debt and does not modify those eight files.

All other Python files must remain Ruff-format clean.

## Step 5.1

Construct the continuous one-year-ahead outcome panel and audit:

- exact consecutive-year alignment;
- missing current funded ratio;
- missing future funded ratio;
- denominator validity;
- duplicate sponsor-years;
- sponsor-year sequence gaps;
- continuous-outcome coverage by predictor year.

Step 5.1 does not select the binary threshold.

## Step 5.2

Prespecify the primary material-deterioration threshold `c` and construct the
binary target.

The final holdout cannot be used to select or tune `c`.

## Step 5.3

Perform the final outcome-integrity audit and freeze:

`data/processed/outcomes.parquet`

## Step 5.4

Merge the frozen Milestone-5 branch into `develop` and create:

`v0.6.0-outcomes`

only after all Milestone-5 acceptance gates pass.
