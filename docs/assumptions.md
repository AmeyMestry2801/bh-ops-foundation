# Assumptions Register

All values below are my assumptions, not measurements. Data is synthetic.

| ID | Assumption | Value | Where used |
|---|---|---|---|
| A1 | Random seed | 42 | all scripts |
| A2 | Data window | 2025-01-01 to 2026-06-30 | generate_data.py |
| A3 | Experiment window | 2025-10-01 to 2026-03-31 | generate_data.py, experiment.py |
| A4 | Baseline no-show rate | ~22% | generate_data.py |
| A5 | Arm A effect (AI voice 48h + SMS) | -3.0 pp | generate_data.py |
| A6 | Arm B effect (two-way SMS + reschedule link) | -1.5 pp | generate_data.py |
| A7 | PA SLA thresholds | 72h urgent / 7 calendar days standard (borrowed from CMS-0057-F; not a behavioral-health payer claim) | kpis.py |

(Rows for dirt-injection rates, non-linear no-show structure, and outreach capacity get added as each phase is built.)

## Phase 1 additions (generate_data.py)

| ID | Assumption | Value |
|---|---|---|
| A8 | Patients / clinics / providers | 15,000 / 12 (one in Buffalo NY) / 60 (12 psychiatrist, 18 NP, 30 therapist) |
| A9 | No-show definition | no_show / (completed + no_show + late_cancel); cancelled excluded from the denominator |
| A10 | Baseline no-show | intercept calibrated so the mean planted probability is 0.22 across all appointments |
| A11 | No-show drivers (logit) | +0.03/day of lead (cap 40), -0.40 if lead <= 1 day, payer (Medicaid +0.35, Medicare -0.10, Commercial -0.25, Self-pay +0.20), in-person +0.30, +0.18 per prior no-show (cap 6), age band, +0.015 per PHQ-9 point above 10, Mon +0.15, Thu +0.05, Fri +0.20, early/late hours, provider type, unobserved patient trait (SD 0.5) |
| A12 | Planted non-linear interaction | +0.90 logit when lead > 21 days AND Medicaid AND in-person |
| A13 | Experiment assignment | simple randomization at patient level, 1/3 per arm; appointments outside 2025-10-01..2026-03-31 are labelled `standard` |
| A14 | Reminder effects | arm A -3.0 pp, arm B -1.5 pp on average; per-appointment effect multiplier 1 + 0.6*Medicaid + 0.5*(lead >= 14), rescaled so the arm mean equals the planted effect |
| A15 | Arm B guardrail side effects | +2.0 pp cancellation, +1.5 pp late-cancel (reschedule link) |
| A16 | Funnel drop-off | P(never scheduled) = 0.05 + 0.10*eligibility blocked + 0.25*PA denied + 0.04*Medicaid + 0.05*transport barrier + 0.02*housing barrier |
| A17 | Prior-auth | required for ~40% Medicaid / 20% Medicare / 45% Commercial; urgent median 40h, standard median 96h (lognormal), Medicaid x1.2; denial 12% (+5 pp Medicaid) |
| A18 | Claims | one per completed appointment submitted within 7 days; first-pass denial 4-11% by payer, +20 pp if the patient's PA was denied (CO-197); 40% of denied claims recovered on resubmission; payment lag median 22-45 days by payer |
| A19 | Provider slot capacity (for fill rate) | psychiatrist 30, NP 28, therapist 25 slots/week |
| A20 | Dirt rates | duplicates 1% (patients, eligibility, appointments, claims); payer missing 2%, payer spelling variants 10%; UTC "Z" timestamps 15% of appointment rows (others clinic-local, no offset); orphan FKs 0.3% (appointments, prior auth, claims) + 0.2% provider; appointments before patient exists 0.2%; claim amount-rule violations 0.2%; missing PHQ-9 / GAD-7 3% each |

## Phase 3 additions (KPI layer)

| ID | Assumption | Value |
|---|---|---|
| A21 | Slot-capacity multiplier for fill rate | 1.7 x the Phase 1 provider weekly capacities (set in dbt_project.yml var capacity_multiplier). REVISED after seeing the generator's appointment volume, which would have exceeded the original capacities in late months. Fill rate therefore demonstrates the method; it is not a finding |
| A22 | Booked slot | an appointment whose status is not 'cancelled' (cancelled in advance frees the slot; late cancels and no-shows still consume it) |
| A23 | Clean claim | no first-pass denial code (independent of payment timing) |
| A24 | Days in A/R grouping | by month the claim was paid |
| A25 | Leakage cohort | claims submitted through 2026-03 (var leakage_max_month); 'pending' in that window = unpaid > 90 days |
| A26 | PA SLA / denial rates | decided requests only; pending requests excluded, which biases the most recent months slightly |

## Phase 3 caveats (found after first KPI run)

| ID | Caveat |
|---|---|
| A27 | Fill rate ramps from ~5% (Jan 2025) to ~93% (Jun 2026) because the generator onboards patients gradually over 15 months while slot capacity is constant. Early months are a synthetic ramp-up artifact. Dashboard and README report fill rate for 2026 months only |
| A28 | Mean days intake -> first visit (31.5) is skewed by a long right tail; the median (18) is the headline. Recent intake cohorts are right-censored |
| A29 | Gate conversion is descriptive. Planted weights make PA denial matter more than a blocked eligibility check |

## Phase 5 pre-specification (written BEFORE running src/experiment.py)

| ID | Item | Specification |
|---|---|---|
| A30 | Population | Patients in experiment_assignments (patients with >=1 appointment in the window; assigned-but-never-booked patients are not in the table). Arm does not affect whether an appointment exists in the generator, so no arm-dependent selection; a real trial defines the population at assignment |
| A31 | Primary metric | Appointment-level no-show among resolved appointments (completed + no_show + late_cancel), standard errors clustered by patient. Primary estimand: risk difference vs control |
| A32 | Multiplicity | Holm across the 3 pairwise comparisons (A vs control, B vs control, A vs B), applied within each method; power planned at alpha 0.05/3 |
| A33 | Power inputs | Baseline 22%, MDE 2 pp absolute, power 0.80, ICC estimated from pre-experiment standard-arm data (Jan-Sep 2025), design effect = 1 + (m_eff - 1) * ICC with m_eff = sum(m^2)/sum(m) of resolved appointments per patient in the window |
| A34 | Validity checks | SRM chi-square vs equal 1/3 split (alarm if p < 0.001); covariate SMD flagged if abs > 0.10; omnibus multinomial-logit likelihood-ratio test of arm on baseline covariates |
| A35 | Guardrails | Cancellation rate (all scheduled), late-cancel rate (resolved), non-completion rate (all scheduled). Breach = Holm p < 0.05 across the 6 tests AND harmful increase >= 1.0 pp vs control |
| A36 | Decision rule | SHIP an arm if Holm-adjusted primary p < 0.05, estimated reduction >= 2 pp (the MDE), and no guardrail breach. ITERATE if the reduction is significant but smaller than 2 pp or a guardrail is breached. STOP if there is no significant reduction |
| A37 | Heterogeneity | Subgroup RDs by payer and lead-time bucket (exploratory, unadjusted). Interaction model (linear probability, RD scale) with Medicaid and long lead (> 14 days); joint Wald tests per modifier, Holm across the 2. NOT blind: the author wrote the generator and knows the planted modifiers |
| A38 | Sensitivity | (a) all scheduled appointments as denominator, (b) covariate-adjusted logistic regression (pre-treatment covariates only), (c) patient-level analyses: any no-show (z-test) and mean patient no-show rate (Welch t) |

## Phase 5 post-run notes (added after seeing results)

| ID | Note |
|---|---|
| A39 | Omnibus randomization LR test gave p = 0.032 (below 0.05). A34 set no alarm threshold, so it is reported as a flag, not a failure: max SMD 0.057, adjusted and unadjusted ORs agree, and arms were assigned by simple random draws in the generator. The first version of the memo template claimed such a p-value was typical of working randomization; that wording was wrong and was corrected. No re-seeding was done |
| A40 | Heterogeneity tests are underpowered for the planted modifier sizes (about 1 to 1.5 pp difference vs SE about 2 pp). No heterogeneity is claimed. The long-lead cutoff in the analysis (> 14 days) differs slightly from the generator's multiplier (>= 14 days) |
| A41 | Holm families: 3 comparisons for the primary and sensitivity analyses on resolved or all scheduled appointments; only 2 (arm A, arm B vs control) for the covariate-adjusted logit |
| A42 | Arm A vs arm B is significant on resolved appointments (Holm p 0.0035) but not on all scheduled (0.0548); the claim "A beats B" is not robust |

## Phase 6 pre-specification (written BEFORE running src/model.py; details in docs/leakage_audit.md)

| ID | Item | Specification |
|---|---|---|
| A43 | Population and label | resolved appointments, reminder arms standard + control; label = no-show |
| A44 | Split | by appointment date: train 2025-01-01..2025-12-31, validation 2026-01-01..2026-03-31, test 2026-04-01..2026-06-30 (all standard reminders) |
| A45 | Tuning | logistic C and XGBoost hyperparameters chosen on validation PR-AUC; XGBoost budget = 25 random draws |
| A46 | Promotion rule | M2 replaces M1 only if validation PR-AUC gain >= 0.02 AND the 95% patient-cluster bootstrap CI of the difference excludes 0 on the positive side |
| A47 | Test discipline | chosen hyperparameters refit on train+val; test evaluated once |
| A48 | Outreach capacity | 20% of appointments, selected by highest predicted risk |
| A49 | Business simulation | arm A effect taken from results/experiment_effects.csv (primary, cluster-robust). Scenario A: uniform absolute reduction. Scenario B: relative reduction (RR) applied to observed no-shows of flagged appointments. Assumes the effect transfers to the test period and population, no call cost, no capacity limits other than 20%. Prevented counts are among resolved appointments. It is a simulation, not an impact claim |
| A50 | Fairness | flagged = top 20%; per payer and age band: flag rate, precision, false-negative rate, false-positive rate; chi-square on FNR and FPR by group, Holm over the 4 tests; descriptive (appointment clustering makes p-values optimistic; base rates differ by group, so unequal flag rates are expected) |

## Phase 7 additions (BI export)

| ID | Note |
|---|---|
| A51 | Days in A/R by paid month is biased low in the earliest months (claims only exist from 2025-01, so only quickly paid claims can appear). kpi_monthly.csv marks months before 2025-06 as reportable = 0. The cutoff is a back-of-envelope choice from the generator's payment-lag distribution (median 22-45 days, plus 30 days for recovered claims) |
| A52 | model_scores.csv: validation rows come from train-only fits, test rows from the train+val refits, so scores are not comparable across the split column |
