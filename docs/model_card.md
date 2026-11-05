# Model Card: no-show risk model

> ALL DATA IS SYNTHETIC. This documents a method demonstration, not a deployable clinical or operational model.

**Task:** predict no-show for an appointment at scheduling time, to rank appointments for outreach (top 20% by risk).
**Final model:** chosen by the pre-specified promotion rule (docs/leakage_audit.md): regularized logistic regression (M1) unless XGBoost (M2) beat it by >= 0.02 validation PR-AUC with a bootstrap CI above 0. See results/model_metrics.json for the decision and numbers.
**Data:** resolved appointments, standard and control reminder arms. Time split: train 2025, validation Jan-Mar 2026, test Apr-Jun 2026 (touched once).
**Features:** scheduling-time only (lead time, prior no-shows, modality, payer, age band, weekday/hour, PHQ-9/GAD-7, SDOH flags, provider type, language). Every excluded field is listed in docs/leakage_audit.md.

## Performance
See results/RESULTS.md (PR-AUC vs base rate, ROC-AUC, Brier, lift at top 20%) and reports/figures/model_eval.png (calibration, gain, precision-recall).

## Known limitations
- **Planted structure.** Several drivers, including a three-way interaction (Medicaid x in-person x lead > 21 days), were put in by the generator. A plain logistic model under-predicts that cell, and the gap between models is small overall.
- **Hidden trait.** A latent patient trait drives no-show and several features, so discrimination is moderate by construction.
- **Payer as a feature.** Payer is the top SHAP feature. Using it affects who gets flagged (Medicaid patients are flagged far more often). Whether payer should be a feature at all is a policy decision, not a modeling one.
- **Fairness slices** (results/fairness_slices.csv) show large gaps in flag rate and false-negative rate by payer and age band. Base rates differ by group, and chi-square p-values are optimistic because appointments cluster within patients.
- **Odds ratios.** The M1 coefficient table lists every one-hot level with no single reference; only differences within a feature are meaningful. Do not quote the raw table.
- **Cancelled appointments** are excluded from training; a deployed model would still score them.
- **Outreach simulation** (assumption A49) assumes the experiment effect transfers and ignores call cost. The two scenarios (uniform vs relative effect) differ by about 1.8x; the data cannot choose between them.
- **Not for real use.** No real patients, no external validation.
