# Temporal Integrity

For every sponsor-year forecast:

`information_date <= forecast_cutoff`

Step 4.1 freezes the annual pension cutoff as:

`forecast_cutoff(i,t) = October 15 of calendar year t+1`

This cutoff is fixed before model fitting and final holdout evaluation and is
common across sponsors within plan year t.

For the pension base, only plan filings whose `information_date` is known and
on or before the cutoff may contribute analytical values. Missing-date and
post-cutoff filings are excluded from the point-in-time aggregation. The full
5,934-row sponsor-year skeleton is retained so that availability and missingness
are represented without future-value substitution.

Late-filing and retrospective completeness diagnostics may be stored in audit
artifacts, but they must not be used as analytical features unless they were
observable by the forecast cutoff.

The same cutoff must govern later sponsor-financial, market, macro, retrieval,
and GenAI information. Temporal filtering must occur before semantic retrieval.

Future filings, future financial values, future pension values, retrospective
event narratives unavailable at forecast time, and transformations fitted using
future observations are prohibited.

A temporal-integrity violation invalidates the corresponding model result.