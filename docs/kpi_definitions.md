# KPI Definitions (final, Phase 3)

All values are computed on SYNTHETIC data by dbt views `marts.kpi_*` and re-verified in pandas by src/kpis.py.

| KPI | Definition | Notes |
|---|---|---|
| No-show rate | no_show / (completed + no_show + late_cancel), by appointment month | cancelled (advance) excluded |
| Late-cancel rate | late_cancel / same denominator | |
| Fill rate | appointments not cancelled / assumed capacity | capacity = provider weekly slots x capacity_multiplier x days/7. ASSUMPTION (A21) |
| Days intake -> first visit | first COMPLETED appointment date - intake date, per patient | patients with no completed visit excluded from the mean; reported separately as first_visit_rate. Recent intake cohorts are right-censored |
| Prior-auth turnaround | (decided_ts - submitted_ts) in hours | pending requests excluded |
| PA SLA-breach rate | decided requests slower than 72h (urgent) or 168h = 7 calendar days (standard) / decided requests | thresholds are an ASSUMPTION borrowed from CMS-0057-F, not a claim about behavioral-health payers |
| Clean-claim rate | claims with no first-pass denial code / claims submitted | refined from the Phase 0 draft to avoid penalizing recent unpaid claims |
| Denial rate by reason | first-pass denied claims with that code / claims submitted (by payer) | code labels are paraphrased |
| Days in A/R | mean(paid_date - submit_date), paid claims, grouped by month PAID | grouping by paid month avoids censoring bias |
| Revenue leakage | allowed amount on claims that are denied (unrecovered) or unpaid > 90 days / total allowed | only claims submitted through 2026-03 (all at least 90 days old at data end) |
| Patient funnel | intake -> scheduled -> first visit completed -> claim submitted -> claim paid (nested) | |
| Gate conversion | share of patients ever scheduled, by eligibility status (latest check) and prior-auth outcome | descriptive, not causal |
