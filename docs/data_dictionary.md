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

## Milestone 4 Step 4.3 Market Variables

Local market artifact: `data/interim/structured_x/step_4_3/market_sponsor_year_features.parquet`

Joined local artifact:

`data/interim/structured_x/step_4_3/pension_sec_market_sponsor_year_base.parquet`

The grain remains `sponsor_id x plan_year`. Price observations and SEC shares-outstanding
facts are eligible only when their relevant information dates are on or before the frozen
October-15-of-t+1 forecast cutoff.

| Field | Definition | Unit |
|---|---|---|
| market_sec_ticker | SEC ticker association used only for source resolution. | identifier |
| market_sec_exchange | SEC exchange association used only for source resolution. | identifier |
| market_source_symbol | Yahoo Finance symbol selected for the CIK. | identifier |
| market_price_provider | Historical price provider retained as provenance. | provenance |
| market_price_currency | Provider currency; Step 4.3 requires USD. | currency |
| market_ticker_candidate_count | Number of current SEC ticker associations for the CIK. | count |
| market_price_information_date | Last trading date on or before forecast cutoff. | date |
| market_information_date | Latest feature-source information date used by Step 4.3. | date |
| market_close | Last positive regular close on or before forecast cutoff. | USD/share |
| market_adjusted_close | Corporate-action-adjusted close on the same trading date. | USD/share |
| market_window_start_date | First date in the trailing price window. | date |
| market_window_price_observations | Trailing price count, capped at 253. | count |
| market_equity_return | Adjusted-close return over 252 intervals when 253 prices exist. | ratio |
| market_equity_volatility | Annualized adjusted-close log-return volatility. | ratio |
| market_equity_drawdown | Minimum close/running-peak minus one over the trailing window. | ratio |
| market_shares_outstanding | Latest eligible SEC common shares outstanding. | shares |
| market_shares_split_basis_factor | Split-only unit conversion after shares period end. | factor |
| market_shares_split_adjusted | SEC shares on the provider's split-normalized basis. | shares |
| market_shares_filed_date | SEC filing date for selected shares-outstanding fact. | date |
| market_shares_period_end | Period end for selected shares-outstanding fact. | date |
| market_shares_taxonomy | Taxonomy of selected shares-outstanding fact. | provenance |
| market_shares_concept | Concept of selected shares-outstanding fact. | provenance |
| market_shares_form | SEC form of selected shares-outstanding fact. | provenance |
| market_shares_accession | SEC accession number of selected shares-outstanding fact. | provenance |
| market_capitalization | Close times split-normalized shares for unique-ticker CIKs. | USD |
| market_transformation_version | Frozen Step-4.3 transformation version. | version |

## Milestone 4 Step 4.4 Macro Variables

Local macro artifact: `data/interim/structured_x/step_4_4/macro_sponsor_year_features.parquet`

Joined local artifact:

`data/interim/structured_x/step_4_4/pension_sec_market_macro_sponsor_year_base.parquet`

The macro values are common across sponsors within a plan year because the forecast cutoff is
common within plan year. Each value is selected from an ALFRED historical vintage equal to the
frozen October-15-of-t+1 cutoff.

| Field | Definition | Unit |
|---|---|---|
| macro_vintage_date | ALFRED vintage date, exactly equal to forecast cutoff. | date |
| macro_interest_rate_10y | Latest DGS10 value available in the cutoff vintage. | percent |
| macro_interest_rate_10y_observation_date | DGS10 observation date selected. | date |
| macro_inflation_yoy | CPIAUCNS year-over-year change within cutoff vintage. | percent |
| macro_inflation_observation_date | Latest CPI observation used in inflation. | date |
| macro_inflation_prior_year_observation_date | Same-month prior-year CPI observation. | date |
| macro_credit_conditions_nfci | Latest NFCI available in the cutoff vintage. | index |
| macro_credit_conditions_nfci_observation_date | NFCI observation date selected. | date |
| macro_unemployment_rate | Latest UNRATE available in the cutoff vintage. | percent |
| macro_unemployment_rate_observation_date | UNRATE observation date selected. | date |
| macro_transformation_version | Frozen Step-4.4 transformation version. | version |

## Milestone 4 Step 4.5 Final Structured-X Panel

Final local artifact: `data/processed/sponsor_year_X.parquet`

Grain: `sponsor_id x plan_year`; rows: 5,934; sponsors: 729; SEC CIKs: 729; plan years:
2015-2024. The final artifact is a byte-identical promotion of the frozen Step-4.4 joined
pension/SEC/market/macro artifact. SHA-256: `6E7C3954CE1F23110B4A88E7A83E5CEC5C6B759825670DB9A90682CE5AA56ACF`.

The frozen model-feature contract contains 31 fields across four families:
pension, sponsor financials, market, and macro. Missing values are preserved exactly as they
exist after the point-in-time family-specific construction steps; Step 4.5 performs no global
imputation or zero fill. Control and provenance columns are retained in the final Parquet but
are not automatically model features.
