# Temporal Integrity

For every forecast:

InformationDate <= ForecastCutoff

The temporal filter must execute before semantic retrieval.

Future filings, future financial values, future pension values, retrospective
event narratives unavailable at forecast time, and transformations fitted using
future observations are prohibited.

A temporal-integrity violation invalidates the corresponding model result.