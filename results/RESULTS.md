# RESULTS (every number comes from the script named in its Source column)

> ALL DATA IS SYNTHETIC. Effect sizes, noise rates and the no-show structure are my assumptions (docs/assumptions.md). Nothing here is a claim about real clinical or operational impact.

## Data and pipeline

| Metric | Value | Source |
|---|---|---|
| Raw rows (appointments / claims / patients) | 127,984 / 86,540 / 15,150 | `src/generate_data.py -> results/pipeline_run.json` |
| Mart rows (fact_appointment / fact_claim) | 125,803 / 84,639 | `src/dq_checks.py` |
| Date range | 2025-01-01 to 2026-06-30 | `src/config.py` |
| dbt models / tests | 27 / 92 | `src/pipeline.py -> dbt build` |
| dbt tests passed / warned / failed | 88 / 4 / 0 | `src/pipeline.py` |
| Pipeline runtime (last run) | 6.21 s (full) | `src/pipeline.py` |
| DQ issue types found / fixed or quarantined | 16 / 13 | `src/dq_checks.py` |
| Mart integrity checks failed | 0 of 14 | `src/dq_checks.py` |

## KPIs (SQL views verified against independent pandas)

| Metric | Value | Source |
|---|---|---|
| KPI checks passing | 21 / 21 | `src/kpis.py` |
| No-show rate | 21.3% | `src/kpis.py` |
| Late-cancel rate | 4.1% | `src/kpis.py` |
| Median days intake to first visit | 18 | `src/kpis.py` |
| PA SLA-breach rate (assumed 72h/7d thresholds) | 21.2% | `src/kpis.py` |
| Clean-claim rate | 90.9% | `src/kpis.py` |
| Mean days in A/R | 35.0 | `src/kpis.py` |
| Revenue leakage (mature months) | 5.5% | `src/kpis.py` |

## Reminder experiment (planted effects; method demonstration)

| Metric | Value | Source |
|---|---|---|
| Arm A vs control, risk difference (95% CI) | -3.35 pp (-4.32 to -2.37); Holm p 0.0000 | `src/experiment.py` |
| Arm B vs control, risk difference (95% CI) | -1.92 pp (-2.91 to -0.94); Holm p 0.0003 | `src/experiment.py` |
| Decisions (pre-specified rule) | A: SHIP, B: ITERATE | `src/experiment.py` |
| Planted effects | A -3.0 pp, B -1.5 pp | `src/generate_data.py` |
| Sample-ratio p / omnibus randomization p | 0.1141 / 0.032 (flagged, see A39) | `src/experiment.py` |

## No-show model

| Metric | Value | Source |
|---|---|---|
| Final model (promotion rule) | M1; val PR-AUC gain of M2 over M1 +0.0071, 95% CI [-0.0001, 0.0134] | `src/model.py` |
| Test PR-AUC (95% CI) vs base-rate PR-AUC | 0.387 (0.374 to 0.401) vs 0.223 | `src/model.py` |
| Test ROC-AUC / Brier | 0.671 / 0.1603 | `src/model.py` |
| Precision / recall / lift at top 20% | 40.0% / 36.0% / 1.80 | `src/model.py` |

## Outreach simulation (assumptions A49; prevented no-shows in the test period, 95% CI)

| Metric | Value | Source |
|---|---|---|
| A: uniform absolute reduction, model top 20% | 209 (148 to 270); 29.9 calls per prevented | `src/model.py` |
| A: uniform absolute reduction, random 20% | 209 (148 to 270); 29.9 calls per prevented | `src/model.py` |
| B: relative reduction, model top 20% | 381 (276 to 480); 16.4 calls per prevented | `src/model.py` |
| B: relative reduction, random 20% | 212 (154 to 267); 29.5 calls per prevented | `src/model.py` |

## Tests

| Metric | Value | Source |
|---|---|---|
| pytest passed / failed / skipped | 29 / 0 / 0 | `pytest` |
