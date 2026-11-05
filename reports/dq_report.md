# Data Quality Report

> ALL DATA IS SYNTHETIC. Dirt was injected on purpose by src/generate_data.py.

Generated: 2026-10-14T11:35:19  |  Overall: **PASS**

## dbt build

`pass=115, warn=4, error=0, skip=0, no_op=0, reused=0, total=119, models=27, tests=92`

## 1. Row-count reconciliation (raw -> staging -> mart)

| table | raw | staging | mart | dups removed (expected) | mart excluded (expected) | ok |
|---|---|---|---|---|---|---|
| clinics | 12 | 12 | 12 | 0 (0) | 0 (0) | yes |
| providers | 60 | 60 | 60 | 0 (0) | 0 (0) | yes |
| patients | 15,150 | 15,000 | 15,000 | 150 (150) | 0 (0) | yes |
| intake | 15,000 | 15,000 | - | 0 (0) | - | yes |
| eligibility_checks | 16,613 | 16,449 | - | 164 (164) | - | yes |
| prior_authorizations | 5,244 | 5,244 | 5,227 | 0 (0) | 17 (17) | yes |
| appointments | 127,984 | 126,717 | 125,803 | 1,267 (1,267) | 914 (914) | yes |
| claims | 86,540 | 85,683 | 84,639 | 857 (857) | 1,044 (1,044) | yes |
| experiment_assignments | 13,059 | 13,059 | - | 0 (0) | - | yes |

Every row dropped between layers is explained: duplicates (raw -> staging) and quarantined invalid rows (staging -> mart). 'Expected' is computed independently from staging.

## 2. Issues found and how they were handled

| issue | table | rows | handling | category |
|---|---|---|---|---|
| Duplicate rows | patients | 150 | Deduplicated in staging (keep first) | fixed |
| Duplicate rows | eligibility_checks | 164 | Deduplicated in staging | fixed |
| Duplicate rows | appointments | 1,267 | Deduplicated in staging | fixed |
| Duplicate rows | claims | 857 | Deduplicated in staging | fixed |
| Payer spelling variants | patients | 1,508 | Mapped to 4 canonical payer values | fixed |
| Missing payer | patients | 329 | Set to 'Unknown' (kept, flagged) | flagged |
| UTC-format timestamps | appointments | 19,103 | Converted to clinic-local time | fixed |
| Orphan patient_id | appointments | 393 | Excluded from fact_appointment | quarantined |
| Orphan provider_id | appointments | 248 | Excluded from fact_appointment | quarantined |
| Appointment before patient exists | appointments | 274 | Excluded from fact_appointment | quarantined |
| Orphan patient_id | prior_authorizations | 17 | Excluded from fact_prior_auth | quarantined |
| Orphan appointment_id | claims | 246 | Excluded from fact_claim | quarantined |
| paid_amount > allowed_amount | claims | 83 | Excluded from fact_claim | quarantined |
| allowed_amount > billed_amount | claims | 92 | Excluded from fact_claim | quarantined |
| Missing PHQ-9 total | intake | 455 | Left NULL (model handles missingness) | flagged |
| Missing GAD-7 total | intake | 446 | Left NULL (model handles missingness) | flagged |

Issue types found: 16 (fixed or quarantined: 13, flagged only: 3). Row counts can overlap across categories; do not sum them as unique rows.

## 3. Mart integrity checks (all must be 0)

| check | violations | status |
|---|---|---|
| fact_appointment duplicate keys | 0 | PASS |
| fact_claim duplicate keys | 0 | PASS |
| fact_prior_auth duplicate keys | 0 | PASS |
| dim_patient duplicate keys | 0 | PASS |
| fact_appointment -> dim_patient orphans | 0 | PASS |
| fact_appointment -> dim_provider orphans | 0 | PASS |
| fact_appointment -> dim_date orphans | 0 | PASS |
| fact_claim -> fact_appointment orphans | 0 | PASS |
| fact_claim -> dim_patient orphans | 0 | PASS |
| fact_prior_auth -> dim_patient orphans | 0 | PASS |
| appointments before patient created | 0 | PASS |
| claims violating paid <= allowed <= billed | 0 | PASS |
| prior auth decided before submitted | 0 | PASS |
| negative lead_days | 0 | PASS |

Appointment date range in fact_appointment: 2025-01-06 to 2026-06-30
