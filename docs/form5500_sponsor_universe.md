# Form 5500 Sponsor Universe

Release target: `v0.3.0-sponsor-universe`

The controlled raw-data manifest contains 44 Form 5500/Schedule source artifacts for source form years 2015-2025.

Defined-benefit inclusion uses Schedule SB linked to Form 5500 through `ACK_ID`.

Candidate rows: 80045
Candidate unique sponsors: 11535
Candidate unique plans: 13545

The complete candidate artifact is preserved locally at `data/interim/sponsor_plan_universe_all_available.parquet`.

The frozen Milestone-2 primary plan-year window is **2015-2024**.

Final rows: 79782
Final unique sponsors: 11520
Final unique plans: 13527
Rows excluded before 2015: 44
Rows excluded after 2024: 219
2025 provisional rows: 219

No outcome construction, model fitting, prompt engineering, or final-holdout analysis was used to make this data-completeness decision.

Milestone 2 does not claim that all retained sponsors are publicly traded.
Milestone 3 performs Form 5500 sponsor <-> public corporation <-> SEC CIK entity resolution.

Primary local artifact: `data/processed/sponsor_plan_universe.parquet`.

Next release: `v0.4.0-entity-linkage`.
