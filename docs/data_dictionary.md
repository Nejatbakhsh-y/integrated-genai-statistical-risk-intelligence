# Data Dictionary

## Sponsor Plan Universe

Primary local artifact: `data/processed/sponsor_plan_universe.parquet`

Frozen Milestone-2 plan-year window: **2015-2024**.

Candidate rows before plan-year freezing: 80045

Final rows: 79782

Final unique sponsors: 11520

Final unique plans: 13527

Plan year 2025 is preserved locally as provisional evidence and excluded from v0.3.0.

Milestone 2 is not yet restricted to publicly traded corporations; that filter is applied in Milestone 3 through SEC entity resolution.

| Field | Definition | Unit |
|---|---|---|
| sponsor_id | Stable standardized sponsor identifier. | identifier |
| plan_id | Stable EIN-plan-number identifier. | identifier |
| ein | Nine-digit sponsor EIN. | identifier |
| plan_number | Three-digit Form 5500 plan number. | identifier |
| sponsor_name | Standardized sponsor name. | text |
| plan_year | Reported plan year. | year |
| assets | Best available mapped plan asset measure. | USD, nearest dollar |
| liabilities | Best available funding-target/liability measure. | USD, nearest dollar |
| contributions | Best available annual contribution measure. | USD, nearest dollar |
| benefit_payments | Best available annual benefit/distribution amount. | USD, nearest dollar |
| participants | Reported participant count. | count |
| source_file | Source artifact provenance. | provenance |
| information_date | Filing/receipt date retained for temporal controls. | date |
| ack_id | EFAST acknowledgement identifier. | identifier |
| db_identification_method | Defined-benefit inclusion rule. | categorical |
