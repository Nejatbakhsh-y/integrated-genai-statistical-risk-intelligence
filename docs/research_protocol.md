# Research Protocol

## Primary Question

Do evidence-grounded GenAI-derived risk signals improve temporally valid
out-of-sample prediction of future corporate defined-benefit pension funding
deterioration?

## X

Structured pension, financial, market, and macro variables.

## Z

Validated evidence-grounded GenAI risk indicators.

## I

Prespecified interconnected-risk interactions.

## Primary Outcome

FR(i,t) = A(i,t) / L(i,t)

DeltaFR(i,t+1) = FR(i,t+1) - FR(i,t)

D(i,t+1) = 1 when DeltaFR(i,t+1) <= -c

The material deterioration threshold c must be prespecified before final
holdout evaluation.

## Risk Domains

1. Climate / catastrophe
2. Cyber / digital
3. Financial crime / KYC
4. Sustainability / reputation
5. Operational / AI / workforce transformation
6. Regulatory / legal
7. Financial stress

## Temporal Rule

InformationDate <= ForecastCutoff

Date filtering must occur before semantic retrieval.

## Final Holdout Restrictions

The final holdout may not be used for:

- prompt tuning
- taxonomy revision
- threshold selection
- feature selection
- preprocessing fitting
- calibration fitting
- hyperparameter tuning

## Scope

The first empirical study focuses on pension funding deterioration.

Credit, collateral, fixed-income, insurance, and macro applications are later
transferability extensions.