# Behavioral-Health Operations Data Foundation

Pipeline, KPI layer, reminder experiment and no-show model.

> **ALL DATA IS SYNTHETIC** (IDs only, no names). Every number below is "on synthetic data". Effect sizes, noise rates and
> the no-show structure are my assumptions (docs/assumptions.md). Nothing here is a claim about real clinical or operational impact.

## Questions answered
1. Where do patients drop out of the intake -> visit -> payment flow? (KPI layer, funnel and gate tables)
2. Did an AI reminder reduce no-shows? (randomized experiment; the effects were planted, so this shows the *method*)
3. Who should get outreach? (time-split model ladder with a pre-specified promotion rule)

All numbers are in **results/RESULTS.md**, each with the script that produced it. Key decisions are in:
docs/problem_framing.md, docs/assumptions.md, docs/leakage_audit.md, docs/experiment_readout.md, docs/model_card.md, reports/dq_report.md.

## Architecture src/generate_data.py synthetic, deliberately dirty CSVs
|
data/raw/.csv
| src/load_raw.py (full or --since incremental)
v
DuckDB raw (all text)
| dbt staging: cast, dedupe, payer standardization, UTC -> clinic-local
v
DuckDB staging --dbt tests--> warnings on known orphan keys
| dbt marts: star schema + kpi_ views, strict tests
v
DuckDB marts (dim_, fact_, kpi_) ----> src/dq_checks.py -> reports/dq_report.md
| row-count reconciliation raw -> staging -> mart
+--> src/kpis.py SQL KPIs re-verified in pandas
+--> src/eda.py association tests (Holm)
+--> src/experiment.py power, SRM, balance, cluster-robust effects, guardrails, memo
+--> src/model.py M0/M1/M2 ladder, SHAP, fairness, outreach simulation
+--> src/export_bi.py bi/.csv -> Tableau Public or Excel  
## Limitations
- Synthetic data: findings reflect what I built in, not the world. The model and experiment sections demonstrate method.
- The experiment's heterogeneity tests are underpowered; arm A vs B ordering is not robust to the all-scheduled denominator.
- Fill rate depends on an assumed capacity multiplier (A21) and 2025 is a ramp-up artifact; only 2026 is reportable.
- SLA thresholds are borrowed from CMS-0057-F as a reference, not a claim about behavioral-health payers.
- dbt models are full-refresh tables; only the raw load is incremental.
- Dashboard: see results/resume_facts.json for the tool actually used and pages built.

## Reproduce
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make all            # data, pipeline, test, analysis, bi
python -m src.make_notebooks && jupyter nbconvert --to notebook --execute --inplace notebooks/*.ipynb
python -m src.make_results --dashboard-tool "<what you built>" --dashboard-pages <n>
python -m pytest -q
```
Runtime is a few minutes on a laptop. Seed is fixed at 42, so reruns reproduce the same numbers.
