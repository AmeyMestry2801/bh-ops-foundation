# Leakage Audit and Model Pre-Specification (written BEFORE src/model.py was run)

> ALL DATA IS SYNTHETIC. Several no-show drivers were planted by src/generate_data.py.

**Prediction moment:** the time an appointment is scheduled (scheduled_ts). Only information available then may be a feature.
**Target:** is_no_show among resolved appointments (completed, no_show, late_cancel), reminder arms `standard` and `control` only.

## Features used (all known at scheduling)
| Feature | Why it is available at scheduling |
|---|---|
| lead_days | scheduled_ts and appt_ts are both set when booking |
| appt_dow, appt_hour | derived from the booked appointment time |
| modality, provider_type | chosen at booking |
| payer_type, age_band, language | patient attributes recorded at registration (payer 'Unknown' kept as its own level) |
| prior_no_show_count | patient attribute. In this synthetic data it is a static column; in production it must be computed as-of the scheduling timestamp |
| phq9_total, gad7_total, sdoh_housing, sdoh_transport, sdoh_food, sdoh_employment | collected at intake, which precedes scheduling in the generator (scheduled date is always after the intake date) |

## Fields excluded and why
| Field(s) | Reason |
|---|---|
| status, is_no_show, is_late_cancel, is_cancelled, is_completed, is_resolved | the outcome itself |
| reminder_arm, experiment_arm | treatment. The model estimates untreated baseline risk, so arms A and B are removed from training and evaluation |
| claim fields (billed/allowed/paid, claim_status, denial_code, submit/paid dates) | created after the visit |
| acuity | deterministic function of PHQ-9 and GAD-7, so redundant |
| eligibility and prior-auth tables | not leakage, but outside the brief's feature list and not used, to keep scope simple |
| clinic_id, provider_id | scope: provider_type is used instead of the 60-level id; no planted clinic effect |
| patient_id, appointment_id | identifiers |
| appt_ts, scheduled_ts, appt_date, created_date, intake_ts | raw calendar time would let the model memorize periods; only derived day-of-week and hour are used |
| generator internals (_frailty, _p0, _effect, _tele_prop) | never loaded into the warehouse |

## Known limitations
- Cancelled appointments are excluded (outcome unknown at scheduling). A deployed model would score them too.
- The latent patient trait in the generator drives both no-show and prior_no_show_count/PHQ-9/GAD-7, so those features proxy it. That is planted structure, not a real-world claim.

## Model ladder and promotion rule (fixed before running)
- M0: training base rate. M1: L2 logistic regression, C chosen from {0.001, 0.01, 0.1, 1, 10} by validation PR-AUC. M2: XGBoost, RandomizedSearchCV with 25 draws, scored by validation PR-AUC.
- **Promotion:** M2 replaces M1 only if (a) the validation PR-AUC gain M2 - M1 is >= 0.02 AND (b) the 95% percentile bootstrap CI of that difference (1,000 patient-cluster resamples) has a lower bound above 0. Otherwise M1 is kept.
- Both models are trained on train only for the decision. The chosen hyperparameters are then refit on train+val and all models are evaluated ONCE on test.
- Outreach capacity: top 20% of appointments by predicted risk.
