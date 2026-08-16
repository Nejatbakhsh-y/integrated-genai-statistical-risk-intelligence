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

## Milestone 4 Step 4.2 SEC Sponsor Financials

Local artifact: `data/interim/structured_x/step_4_2/sec_sponsor_year_financials.parquet`

Joined local artifact: `data/interim/structured_x/step_4_2/pension_sec_sponsor_year_base.parquet`

The grain remains `sponsor_id x plan_year`. SEC facts are eligible only when they belong to the same XBRL fiscal year as `plan_year` and were filed on or before the frozen October-15-of-t+1 forecast cutoff.

| Field | Definition | Unit |
|---|---|---|
| sec_cik | Ten-digit zero-padded SEC Central Index Key. | identifier |
| forecast_cutoff | Frozen analytical cutoff, October 15 of calendar year t+1. | date |
| sec_information_date | Latest filing date among selected Step-4.2 SEC metrics for the sponsor-year. | date |
| sec_total_assets | Selected standardized SEC total-assets fact. | USD |
| sec_total_liabilities | Selected standardized SEC total-liabilities fact. | USD |
| sec_debt | Frozen hierarchy-based reported debt proxy, preferring total debt/finance-lease concepts and then long-term debt concepts. | USD |
| sec_cash | Selected cash and cash-equivalents fact. | USD |
| sec_revenue | Selected annual revenue fact. | USD/year |
| sec_operating_income | Selected annual operating-income fact. | USD/year |
| sec_operating_cash_flow | Selected annual net cash provided by/used in operating activities. | USD/year |
| sec_profitability | `sec_operating_income / sec_revenue`; missing when required inputs are missing or revenue is zero. | ratio |
| sec_leverage | `sec_total_liabilities / sec_total_assets`; missing when required inputs are missing or total assets are nonpositive. | ratio |
| sec_liquidity | `sec_cash / sec_total_assets`; missing when required inputs are missing or total assets are nonpositive. | ratio |
| sec_pension_plan_assets | Selected standardized sponsor financial-statement defined-benefit plan-assets fact. | USD |
| sec_pension_projected_benefit_obligation | Selected standardized sponsor financial-statement projected-benefit-obligation fact. | USD |
| sec_pension_employer_contributions | Selected standardized annual sponsor financial-statement employer-contribution fact. | USD/year |
| pension_size | Form 5500 aggregate pension liabilities divided by SEC total assets. | ratio |
| pension_assets_to_sponsor_assets | Form 5500 aggregate pension assets divided by SEC total assets. | ratio |
| pension_liabilities_to_sponsor_assets | Alias of the Step-4.2 `pension_size` definition. | ratio |
| pension_contributions_to_revenue | Form 5500 aggregate contributions divided by SEC revenue. | ratio |
| sec_selected_metric_count | Number of Step-4.2 base SEC metrics selected for the sponsor-year. | count |
| sec_core_metric_count | Number of seven core sponsor-financial metrics observed for the sponsor-year. | count |
| sec_transformation_version | Frozen transformation version for Step 4.2. | version |

For each base SEC metric, provenance columns retain the selected taxonomy, concept, period start, period end, filing date, annual form, accession number, reporting unit, and deterministic candidate-priority rank.